import pathlib
import tempfile
import tomllib
import unittest
import subprocess
import os
import json
import threading
from unittest.mock import patch

from selfworkflow import wiki_module


class WikiHostTests(unittest.TestCase):
    def test_registration_accepts_equivalent_quoted_wiki_headers(self):
        headers = (
            '[mcp_servers."self-openwiki"]',
            '["mcp_servers".\'self-openwiki\']',
            '[ mcp_servers . "self-openwiki" ] # existing header',
        )
        for header in headers:
            with self.subTest(header=header), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                config = root / "config.toml"
                prefix = b'\xef\xbb\xbfmodel = "keep"\r\ninstructions = \'\'\'\r\n[bad%header]\r\n\'\'\'\r\n[mcp_servers.other]\r\ncommand = "other"\r\n'
                suffix = b'[mcp_servers.later]\r\ncommand = "later"\r\n'
                before = prefix + (header + '\r\ncommand = "old"\r\nargs = ["old.js"]\r\ntool_timeout_sec = 72000\r\n').encode() + suffix
                config.write_bytes(before)
                ready = {"status": "source-ready", "moduleRoot": str(root / "extensions/knowledge/selfopenwiki")}
                with patch.object(wiki_module, "inspect_wiki_module", return_value=ready):
                    plan = wiki_module.register_wiki_mcp(str(root), str(config))
                    self.assertEqual(config.read_bytes(), before)
                    result = wiki_module.register_wiki_mcp(str(root), str(config), confirm_plan_hash=plan["planHash"])
                after = config.read_bytes()
                parsed = tomllib.loads(after.decode("utf-8-sig"))
                self.assertEqual(result["status"], "host-registered")
                self.assertTrue(after.startswith(prefix))
                self.assertTrue(after.endswith(suffix))
                self.assertEqual(parsed["model"], "keep")
                self.assertEqual(parsed["mcp_servers"]["other"], {"command": "other"})
                self.assertEqual(parsed["mcp_servers"]["later"], {"command": "later"})
                self.assertEqual(parsed["mcp_servers"]["self-openwiki"], plan["server"])
                self.assertEqual(plan["server"]["tool_timeout_sec"], 72000)
                self.assertEqual(pathlib.Path(result["backupPath"]).read_bytes(), before)

    def test_registration_rejects_quoted_custom_and_disguised_table_layouts(self):
        examples = (
            '[mcp_servers."self-openwiki".env]\nSECRET = "preserve"\n',
            '[[mcp_servers."self-openwiki"]]\ncommand = "old"\n',
            'mcp_servers = {self-openwiki = {command = "old", args = ["old.js"]}}\n',
            'mcp_servers.self-openwiki.command = "old"\nmcp_servers.self-openwiki.args = ["old.js"]\n',
            "mcp_servers.self-openwiki.command = '''\n[mcp_servers.\"self-openwiki\"]\n[placeholder]\n'''\nmcp_servers.self-openwiki.args = [\"old.js\"]\n",
        )
        for index, content in enumerate(examples):
            with self.subTest(example=index), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                config = root / "config.toml"
                before = content.encode()
                config.write_bytes(before)
                ready = {"status": "source-ready", "moduleRoot": str(root / "extensions/knowledge/selfopenwiki")}
                with patch.object(wiki_module, "inspect_wiki_module", return_value=ready):
                    with self.assertRaises(wiki_module.WikiModuleError):
                        wiki_module.register_wiki_mcp(str(root), str(config))
                self.assertEqual(config.read_bytes(), before)
                self.assertFalse((root / "selfworkflow-wiki-backups").exists())

    def test_registration_shares_the_installers_named_mutex(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config = root / "config.toml"
            config.write_bytes(b'model = "before"\n')
            held = threading.Event()
            release = threading.Event()
            def holder():
                with wiki_module._host_mutex(config):
                    held.set()
                    release.wait(30)
            thread = threading.Thread(target=holder)
            thread.start()
            ready = {"status": "source-ready", "moduleRoot": str(root / "extensions/knowledge/selfopenwiki")}
            try:
                self.assertTrue(held.wait(10))
                with patch.object(wiki_module, "inspect_wiki_module", return_value=ready):
                    plan = wiki_module.register_wiki_mcp(str(root), str(config))
                    with self.assertRaisesRegex(wiki_module.WikiModuleError, "wiki-host-config-busy"):
                        wiki_module.register_wiki_mcp(str(root), str(config), confirm_plan_hash=plan["planHash"])
                self.assertEqual(config.read_bytes(), b'model = "before"\n')
            finally:
                release.set()
                thread.join(10)

    def test_registration_does_not_restore_over_a_later_observed_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config = root / "config.toml"
            config.write_bytes(b'model = "before"\n')
            concurrent = b'model = "later-user-change"\n'
            ready = {"status": "source-ready", "moduleRoot": str(root / "extensions/knowledge/selfopenwiki")}
            original_replace = wiki_module._replace_config
            def later_write(source, target, captured):
                result = original_replace(source, target, captured)
                config.write_bytes(concurrent)
                return result
            with patch.object(wiki_module, "inspect_wiki_module", return_value=ready):
                plan = wiki_module.register_wiki_mcp(str(root), str(config))
                with patch.object(wiki_module, "_replace_config", side_effect=later_write):
                    with self.assertRaisesRegex(wiki_module.WikiModuleError, "postcondition-conflict"):
                        wiki_module.register_wiki_mcp(str(root), str(config), confirm_plan_hash=plan["planHash"])
            self.assertEqual(config.read_bytes(), concurrent)

    @unittest.skipUnless(os.name == "nt", "Windows configuration DACL")
    def test_registration_preserves_config_dacl_and_keeps_backups_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config = root / "config.toml"
            config.write_bytes(b'model = "private-fixture"\n')
            setup = r'''
$p = [Console]::In.ReadToEnd() | ConvertFrom-Json
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
foreach ($target in @($p.root, $p.config)) {
    $acl = if ([IO.Directory]::Exists($target)) { [IO.Directory]::GetAccessControl($target) } else { [IO.File]::GetAccessControl($target) }
    $rules = if ($target -eq $p.root) { "D:P(A;OICI;FA;;;$sid)(A;OICI;FA;;;SY)(A;OICI;GR;;;BU)" } else { "D:P(A;;FA;;;$sid)(A;;FA;;;SY)" }
    $acl.SetSecurityDescriptorSddlForm($rules, [Security.AccessControl.AccessControlSections]::Access)
    if ([IO.Directory]::Exists($target)) { [IO.Directory]::SetAccessControl($target, $acl) } else { [IO.File]::SetAccessControl($target, $acl) }
}
'''
            result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", setup],
                                    input=json.dumps({"root": str(root), "config": str(config)}),
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            def permissions(path):
                code = r'''
$p = [Console]::In.ReadToEnd() | ConvertFrom-Json
$acl = if ([IO.Directory]::Exists($p.path)) { [IO.Directory]::GetAccessControl($p.path) } else { [IO.File]::GetAccessControl($p.path) }
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$allowed = @($acl.Access | Where-Object { $_.AccessControlType -eq 'Allow' } | ForEach-Object { $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value })
@{dacl=$acl.GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access);private=(@($allowed | Where-Object { $_ -ne $sid -and $_ -ne 'S-1-5-18' }).Count -eq 0)} | ConvertTo-Json -Compress
'''
                result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", code],
                                        input=json.dumps({"path": str(path)}), capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)
            before = permissions(config)
            ready = {"status": "source-ready", "moduleRoot": str(root / "extensions/knowledge/selfopenwiki")}
            with patch.object(wiki_module, "inspect_wiki_module", return_value=ready):
                plan = wiki_module.register_wiki_mcp(str(root), str(config))
                result = wiki_module.register_wiki_mcp(str(root), str(config), confirm_plan_hash=plan["planHash"])
            self.assertEqual(permissions(config)["dacl"], before["dacl"])
            self.assertTrue(permissions(pathlib.Path(result["backupPath"]))["private"])
            self.assertTrue(permissions(pathlib.Path(result["backupPath"]).parent)["private"])

    def test_registration_preserves_a_write_in_the_last_replace_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config = root / "config.toml"
            config.write_bytes(b'model = "before"\n')
            concurrent = b'model = "concurrent-user-change"\n'
            ready = {"status": "source-ready", "moduleRoot": str(root / "extensions/knowledge/selfopenwiki")}
            original_replace = wiki_module._replace_config
            calls = 0
            def race(source, target, captured):
                nonlocal calls
                calls += 1
                if calls == 1:
                    config.write_bytes(concurrent)
                return original_replace(source, target, captured)
            with patch.object(wiki_module, "inspect_wiki_module", return_value=ready):
                plan = wiki_module.register_wiki_mcp(str(root), str(config))
                with patch.object(wiki_module, "_replace_config", side_effect=race):
                    with self.assertRaisesRegex(wiki_module.WikiModuleError, "wiki-host-config-changed"):
                        wiki_module.register_wiki_mcp(str(root), str(config), confirm_plan_hash=plan["planHash"])
            self.assertEqual(config.read_bytes(), concurrent)

    def test_doctor_returns_a_bounded_error_when_the_probe_times_out(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config = root / "config.toml"
            ready = {"status": "source-ready", "moduleRoot": str(root / "extensions/knowledge/selfopenwiki")}
            with patch.object(wiki_module, "inspect_wiki_module", return_value=ready):
                plan = wiki_module.register_wiki_mcp(str(root), str(config))
                wiki_module.register_wiki_mcp(str(root), str(config), confirm_plan_hash=plan["planHash"])
                before = config.read_bytes()
                with patch.object(wiki_module.subprocess, "run", side_effect=subprocess.TimeoutExpired("probe", 120)):
                    with self.assertRaisesRegex(wiki_module.WikiModuleError, "wiki-live-probe-failed"):
                        wiki_module.doctor_wiki_module(str(root), str(config))
                self.assertEqual(config.read_bytes(), before)

    def test_registration_rejects_custom_wiki_environment_and_invalid_toml(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config = root / "config.toml"
            ready = {"status": "source-ready", "moduleRoot": str(root / "extensions/knowledge/selfopenwiki")}
            with patch.object(wiki_module, "inspect_wiki_module", return_value=ready):
                for content in ('[mcp_servers.self-openwiki.env]\nSECRET = "preserve"\n', 'broken = ['):
                    config.write_bytes(content.encode())
                    with self.assertRaises(wiki_module.WikiModuleError):
                        wiki_module.register_wiki_mcp(str(root), str(config))
                    self.assertEqual(config.read_bytes(), content.encode())

    def test_registration_preserves_other_servers_and_requires_current_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config = root / "config.toml"
            before = 'model = "keep-me"\n[mcp_servers.other]\ncommand = "keep"\n[mcp_servers.self-openwiki]\ncommand = "old"\nargs = ["old.js"]\n'
            config.write_text(before, encoding="utf-8")
            before_bytes = config.read_bytes()
            ready = {"status": "source-ready", "moduleRoot": str(root / "extensions/knowledge/selfopenwiki")}
            with patch.object(wiki_module, "inspect_wiki_module", return_value=ready):
                plan = wiki_module.register_wiki_mcp(str(root), str(config))
                self.assertEqual(plan["status"], "registration-plan")
                self.assertEqual(config.read_text(), before)
                applied = wiki_module.register_wiki_mcp(str(root), str(config), confirm_plan_hash=plan["planHash"])
                self.assertEqual(applied["status"], "host-registered")
                parsed = tomllib.loads(config.read_text())
                self.assertEqual(parsed["model"], "keep-me")
                self.assertEqual(parsed["mcp_servers"]["other"], {"command": "keep"})
                self.assertTrue(parsed["mcp_servers"]["self-openwiki"]["args"][0].endswith("mcp-server\\dist\\index.js"))
                self.assertEqual(pathlib.Path(applied["backupPath"]).read_bytes(), before_bytes)
                with self.assertRaises(wiki_module.WikiModuleError):
                    wiki_module.register_wiki_mcp(str(root), str(config), confirm_plan_hash=plan["planHash"])

    def test_registration_does_not_remove_someone_elses_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config = root / "config.toml"
            config.write_text('model = "keep"\n')
            lock = pathlib.Path(str(config) + ".selfworkflow-wiki.lock")
            lock.write_text("owner")
            ready = {"status": "source-ready", "moduleRoot": str(root / "extensions/knowledge/selfopenwiki")}
            with patch.object(wiki_module, "inspect_wiki_module", return_value=ready):
                plan = wiki_module.register_wiki_mcp(str(root), str(config))
                with self.assertRaises(wiki_module.WikiModuleError):
                    wiki_module.register_wiki_mcp(str(root), str(config), confirm_plan_hash=plan["planHash"])
            self.assertEqual(lock.read_text(), "owner")
