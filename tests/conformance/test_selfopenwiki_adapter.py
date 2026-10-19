from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest
import shutil

import yaml

from selfworkflow.adapters import build_runtime
from selfworkflow import selfopenwiki
from selfworkflow.selfopenwiki import (
    EXTERNAL_CAPABILITIES,
    SelfOpenWikiAdapter,
    SelfOpenWikiError,
    validate_external_status,
    validate_visualizer_status,
)


class _FakeClient:
    def __init__(self, response):
        self.responses = list(response) if isinstance(response, list) else [response]
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.responses.pop(0)


class SelfOpenWikiAdapterTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    @staticmethod
    def status(**overrides):
        value = {
            "ok": True,
            "executionMode": "external_agent",
            "authRequired": False,
            "version": {"contractSchema": 2},
            "externalAgent": {"ready": True, "activeTransaction": None},
            "paths": {
                "openWikiRoot": "D:/SelfOpenWiki/.work/openwiki",
                "runtimeRoot": "D:/wiki_zxh.selfopenwiki",
                "wikiRoot": "D:/wiki_zxh",
            },
            "visualizer": {
                "id": "selfopenwiki.zxh_wiki_viewer",
                "contractSchema": 1,
                "launcherPath": "D:/SelfOpenWiki/Visualize.bat",
                "loopbackOnly": True,
                "autoOpen": False,
                "wikiRootInput": {"kind": "argument", "flag": "--wiki-root"},
                "urlTemplate": "http://127.0.0.1:{port}/wiki/local",
            },
            "capabilities": [
                {"id": capability}
                for capability in sorted(EXTERNAL_CAPABILITIES)
            ],
        }
        value.update(overrides)
        return value

    def repo(self, root):
        (root / "Setup.bat").write_text("@echo off\n", encoding="utf-8")
        (root / "Install.bat").write_text("@echo off\n", encoding="utf-8")
        (root / "Visualize.bat").write_text("@echo off\n", encoding="utf-8")

    @staticmethod
    def personal_status():
        return SelfOpenWikiAdapterTests.status(
            capabilities=[
                {"id": capability}
                for capability in sorted(
                    EXTERNAL_CAPABILITIES | set(selfopenwiki.PERSONAL_CAPABILITIES)
                )
            ]
        )

    def test_status_is_first_call_and_requires_external_pair(self):
        client = _FakeClient(self.status())
        result = SelfOpenWikiAdapter(client).status()
        self.assertEqual(result["version"]["contractSchema"], 2)
        self.assertEqual(client.calls, [("openwiki_status", {})])

        for response in (
            self.status(executionMode="legacy_provider"),
            self.status(authRequired=True),
            self.status(capabilities=[{"id": "update.external-agent.begin"}]),
            self.status(externalAgent={"ready": False, "activeTransaction": None}),
        ):
            with self.assertRaises(SelfOpenWikiError):
                validate_external_status(response)

    def test_recovery_abort_remains_accessible_when_publishing_is_not_ready(self):
        status = self.status(externalAgent={"ready": False, "activeTransaction": None})
        result = {"ok": True, "status": "external_update_aborted", "executionMode": "external_agent",
                  "authRequired": False, "transactionId": "external-12345678", "generation": 1,
                  "bindingHash": "sha256:" + "a" * 64}
        client = _FakeClient([status, result])
        adapter = SelfOpenWikiAdapter(client)
        self.assertEqual(adapter.abort_external_update("external-12345678", 1, "sha256:" + "a" * 64,
                                                     confirmed_by_user=True), result)
        self.assertEqual(client.calls, [("openwiki_status", {}), ("openwiki_finalize_external_update", {
            "action": "abort", "transactionId": "external-12345678",
            "bindingHash": "sha256:" + "a" * 64, "confirmedByUser": True,
        })])
        with self.assertRaisesRegex(SelfOpenWikiError, "confirmation-required"):
            SelfOpenWikiAdapter(_FakeClient(status)).abort_external_update("external-12345678", 1,
                                                                         "sha256:" + "a" * 64)

    def test_safe_read_uses_its_own_capability_and_preserves_evidence(self):
        import hashlib
        content = "hello wiki\n"
        digest = "sha256:" + hashlib.sha256(content.encode()).hexdigest()
        revision = "sha256:" + "b" * 64
        status = self.status(externalAgent={"ready": False, "activeTransaction": None},
                             capabilities=[{"id": value} for value in sorted(EXTERNAL_CAPABILITIES | {"knowledge.read.safe"})])
        response = {"ok": True, "status": "wiki_read", "recovery": {"action": "none"}, "revision": revision,
                    "pages": [{"path": "intro.md", "size": 11, "contentHash": digest}],
                    "knowledge": [{"content": content, "sourceId": "selfopenwiki:intro.md", "revision": revision,
                                   "contentHash": digest, "verificationStatus": "unverified"}]}
        client = _FakeClient([status, response])
        self.assertEqual(SelfOpenWikiAdapter(client).read(["intro.md"], expected_revision=revision), response)
        self.assertEqual(client.calls, [("openwiki_status", {}), ("openwiki_read", {
            "paths": ["intro.md"], "expectedWikiRevision": revision,
        })])

    def test_safe_read_rejects_unbound_page_metadata(self):
        status = self.status(capabilities=[{"id": value} for value in sorted(EXTERNAL_CAPABILITIES | {"knowledge.read.safe"})])
        response = {"ok": True, "status": "wiki_read", "recovery": {"action": "none"},
                    "revision": "sha256:" + "a" * 64, "knowledge": []}
        for pages in ([{"path": "../private.md", "size": 0, "contentHash": "sha256:" + "b" * 64}],
                      [{"path": "intro.md", "size": -1, "contentHash": "sha256:" + "b" * 64}],
                      [{"path": "intro.md", "size": 0, "contentHash": "invalid"}]):
            with self.subTest(pages=pages):
                with self.assertRaisesRegex(SelfOpenWikiError, "wiki-read-result-invalid"):
                    SelfOpenWikiAdapter(_FakeClient([status, {**response, "pages": pages}])).read()

    def test_safe_read_index_accepts_large_unselected_pages(self):
        status = self.status(capabilities=[{"id": value} for value in sorted(EXTERNAL_CAPABILITIES | {"knowledge.read.safe"})])
        response = {"ok": True, "status": "wiki_read", "recovery": {"action": "none"},
                    "revision": "sha256:" + "a" * 64, "knowledge": [],
                    "pages": [{"path": "large.md", "size": 262145, "contentHash": "sha256:" + "b" * 64}]}
        self.assertEqual(SelfOpenWikiAdapter(_FakeClient([status, response])).read(), response)

    def test_recovery_abort_rejects_wrong_binding_and_missing_capabilities(self):
        status = self.status(externalAgent={"ready": False, "activeTransaction": None})
        result = {"ok": True, "status": "external_update_aborted", "executionMode": "external_agent",
                  "authRequired": False, "transactionId": "external-12345678", "generation": 1,
                  "bindingHash": "sha256:" + "b" * 64}
        with self.assertRaisesRegex(SelfOpenWikiError, "external-abort-result-invalid"):
            SelfOpenWikiAdapter(_FakeClient([status, result])).abort_external_update(
                "external-12345678", 1, "sha256:" + "a" * 64, confirmed_by_user=True)
        client = _FakeClient(self.status(capabilities=[]))
        with self.assertRaises(SelfOpenWikiError):
            SelfOpenWikiAdapter(client).abort_external_update(
                "external-12345678", 1, "sha256:" + "a" * 64, confirmed_by_user=True)
        self.assertEqual(client.calls, [("openwiki_status", {})])

    def test_recovery_abort_crosses_the_real_strict_mcp_transport(self):
        status = self.status(externalAgent={"ready": False, "activeTransaction": None})
        root = self.ROOT
        class StrictClient:
            def call_tool(self, name, arguments):
                if name == "openwiki_status":
                    return status
                completed = subprocess.run([shutil.which("node"), str(root / "tests/fixtures/wiki_strict_mcp.mjs")],
                                           input=json.dumps({"name": name, "arguments": arguments}),
                                           capture_output=True, text=True, encoding="utf-8", timeout=30)
                if completed.returncode:
                    raise RuntimeError(completed.stderr)
                return json.loads(completed.stdout)
        result = SelfOpenWikiAdapter(StrictClient()).abort_external_update(
            "external-12345678", 1, "sha256:" + "a" * 64, confirmed_by_user=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "external_update_aborted")
        self.assertEqual(result["generation"], 1)

    def test_personal_status_requires_v2_capabilities(self):
        self.assertTrue(hasattr(SelfOpenWikiAdapter, "personal_status"))
        required = set(selfopenwiki.PERSONAL_CAPABILITIES)
        ready = self.status(
            capabilities=[
                {"id": capability}
                for capability in sorted(EXTERNAL_CAPABILITIES | required)
            ]
        )
        client = _FakeClient(ready)
        result = SelfOpenWikiAdapter(client).personal_status()
        self.assertEqual(result["version"]["contractSchema"], 2)
        self.assertEqual(client.calls, [("openwiki_status", {})])
        self.assertEqual(
            SelfOpenWikiAdapter(_FakeClient(ready)).override_wiki_root(),
            "D:/wiki_zxh",
        )

        missing = self.status(
            capabilities=[
                {"id": capability}
                for capability in sorted(EXTERNAL_CAPABILITIES)
            ]
        )
        with self.assertRaisesRegex(SelfOpenWikiError, "personal-capability-missing"):
            selfopenwiki.validate_personal_status(missing)

    def test_personal_call_accepts_only_v2_protocol_and_tool_status(self):
        self.assertTrue(hasattr(SelfOpenWikiAdapter, "personal_call"))
        status = self.status(
            capabilities=[
                {"id": capability}
                for capability in sorted(EXTERNAL_CAPABILITIES | set(selfopenwiki.PERSONAL_CAPABILITIES))
            ]
        )
        result = {
            "ok": True,
            "protocol": "selfopenwiki:personal-openwiki-v1",
            "status": "planning",
        }
        client = _FakeClient([status, result])
        self.assertEqual(
            SelfOpenWikiAdapter(client).personal_call("openwiki_begin", {"mode": "update"}),
            result,
        )
        self.assertEqual(
            client.calls,
            [
                ("openwiki_status", {}),
                ("openwiki_begin", {"mode": "update", "wikiRoot": "D:/wiki_zxh"}),
            ],
        )
        mismatch_client = _FakeClient([status])
        with self.assertRaisesRegex(SelfOpenWikiError, "personal-wiki-root-mismatch"):
            SelfOpenWikiAdapter(mismatch_client).personal_call(
                "openwiki_begin", {"wikiRoot": "D:/other-wiki"}
            )
        with self.assertRaisesRegex(SelfOpenWikiError, "personal-result-invalid"):
            selfopenwiki.validate_personal_result(
                "openwiki_begin", {**result, "protocol": "wrong"}
            )
        with self.assertRaisesRegex(SelfOpenWikiError, "personal-result-invalid"):
            selfopenwiki.validate_personal_result(
                "openwiki_finish", result
            )
        self.assertEqual(
            selfopenwiki.validate_personal_result(
                "openwiki_finish",
                {
                    "ok": False,
                    "error": {
                        "code": "busy",
                        "message": "Busy.",
                        "retryable": True,
                    },
                    "recovery": {"action": "retry"},
                },
            )["ok"],
            False,
        )
        with self.assertRaisesRegex(SelfOpenWikiError, "personal-tool-invalid"):
            selfopenwiki.validate_personal_result("openwiki_status", result)

    def test_external_active_transaction_is_structurally_bound(self):
        active = {
            "transactionId": "tx-1",
            "generation": 1,
            "state": "review_ready",
            "nextAction": "retry_review",
        }
        result = validate_external_status(
            self.status(externalAgent={"ready": True, "activeTransaction": active})
        )
        self.assertEqual(result["externalAgent"]["activeTransaction"], active)
        with self.assertRaisesRegex(SelfOpenWikiError, "external-status-invalid"):
            validate_external_status(
                self.status(
                    externalAgent={
                        "ready": True,
                        "activeTransaction": {**active, "generation": True},
                    }
                )
            )

    def test_visualizer_status_requires_the_new_selfopenwiki_contract(self):
        ready = self.personal_status()
        self.assertEqual(
            validate_visualizer_status(ready)["visualizer"]["id"],
            "selfopenwiki.zxh_wiki_viewer",
        )
        for visualizer in (
            None,
            {**ready["visualizer"], "id": "openwiki.legacy"},
            {**ready["visualizer"], "loopbackOnly": False},
            {**ready["visualizer"], "wikiRootInput": {"kind": "argument", "flag": "--root"}},
        ):
            with self.subTest(visualizer=visualizer):
                value = {**ready, "visualizer": visualizer}
                with self.assertRaises(SelfOpenWikiError):
                    validate_visualizer_status(value)

    def test_install_requires_confirmations_and_does_not_create_or_mutate_wiki(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            repo = root / "SelfOpenWiki"
            wiki = root / "wiki"
            repo.mkdir()
            wiki.mkdir()
            self.repo(repo)
            before = sorted(path.relative_to(wiki).as_posix() for path in wiki.rglob("*"))
            adapter = SelfOpenWikiAdapter(_FakeClient(self.status()))

            with self.assertRaisesRegex(SelfOpenWikiError, "confirm-data-safety-required"):
                adapter.install_command(repo, wiki, confirmed_data_safety=False)
            self.assertEqual(
                before,
                sorted(path.relative_to(wiki).as_posix() for path in wiki.rglob("*")),
            )
            command = adapter.install_command(
                repo, wiki, confirmed_data_safety=True
            )
            self.assertEqual(
                command,
                [str((repo / "Install.bat").resolve()), "--wiki-root",
                 str(wiki.resolve()), "--confirm-data-safety"],
            )
            self.assertFalse((wiki / ".selfopenwiki").exists())

    def test_git_wiki_requires_explicit_git_authorization(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            repo = root / "SelfOpenWiki"
            wiki = root / "wiki"
            repo.mkdir()
            wiki.mkdir()
            (wiki / ".git").mkdir()
            self.repo(repo)
            adapter = SelfOpenWikiAdapter(_FakeClient(self.status()))
            with self.assertRaisesRegex(
                SelfOpenWikiError, "confirm-git-authorization-required"
            ):
                adapter.install_command(repo, wiki, confirmed_data_safety=True)
            command = adapter.install_command(
                repo,
                wiki,
                confirmed_data_safety=True,
                confirmed_git_authorization=True,
            )
            self.assertEqual(command[-1], "--confirm-git-authorization")

    def test_install_rejects_wiki_inside_backend_repository(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            repo = Path(temporary).resolve() / "backend"
            repo.mkdir()
            self.repo(repo)
            inside = repo / "upstream" / "wiki"
            inside.mkdir(parents=True)
            for wiki in (repo, inside):
                with self.subTest(wiki=wiki), self.assertRaisesRegex(SelfOpenWikiError, "wiki-root-inside-repository"):
                    SelfOpenWikiAdapter.install_command(repo, wiki, confirmed_data_safety=True,
                                                       confirmed_git_authorization=True)

    @unittest.skipUnless(os.name == "nt", "Windows junction boundary")
    def test_install_resolves_junctions_before_validating_wiki_boundary(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary).resolve()
            repo = root / "backend"
            repo.mkdir()
            self.repo(repo)
            inside = repo / "wiki"
            outside = root / "personal-wiki"
            inside.mkdir()
            outside.mkdir()
            for name, target, allowed in (("inside-link", inside, False), ("outside-link", outside, True)):
                link = root / name
                created = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                                         capture_output=True, text=True)
                self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
                if allowed:
                    command = SelfOpenWikiAdapter.install_command(repo, link, confirmed_data_safety=True)
                    self.assertEqual(command[2], str(outside))
                else:
                    with self.assertRaisesRegex(SelfOpenWikiError, "wiki-root-inside-repository"):
                        SelfOpenWikiAdapter.install_command(repo, link, confirmed_data_safety=True)
                self.assertFalse((target / ".selfopenwiki").exists())

    def test_setup_and_visualizer_commands_are_exact_and_nonexecuting(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            repo = root / "SelfOpenWiki"
            wiki = root / "wiki"
            repo.mkdir()
            wiki.mkdir()
            self.repo(repo)
            wiki.mkdir(exist_ok=True)
            status = self.personal_status()
            status["paths"]["wikiRoot"] = str(wiki.resolve()).replace("\\", "/")
            status["visualizer"]["launcherPath"] = str(
                (repo / "Visualize.bat").resolve()
            ).replace("\\", "/")
            adapter = SelfOpenWikiAdapter(
                _FakeClient([status, status, status])
            )
            self.assertEqual(
                adapter.setup_command(repo, with_mcp=True),
                [str((repo / "Setup.bat").resolve()), "--with-mcp"],
            )
            self.assertEqual(
                adapter.visualizer_command(repo, wiki, port=4321),
                [
                    "cmd.exe",
                    "/d",
                    "/s",
                    "/c",
                    f'"{(repo / "Visualize.bat").resolve()}" --wiki-root "{wiki.resolve()}" --port 4321',
                ],
            )
            spec = adapter.visualizer_spec(port=4321)
            self.assertEqual(spec["url"], "http://127.0.0.1:4321/wiki/local")
            with self.assertRaisesRegex(SelfOpenWikiError, "visualizer-port-invalid"):
                adapter.visualizer_command(repo, wiki, port=0)

            missing_launcher = {
                **status,
                "visualizer": {
                    **status["visualizer"],
                    "launcherPath": str((repo / "missing-Visualize.bat").resolve()),
                },
            }
            with self.assertRaisesRegex(SelfOpenWikiError, "visualizer-missing"):
                SelfOpenWikiAdapter(_FakeClient(missing_launcher)).visualizer_spec()

            other_wiki = root / "other-wiki"
            other_wiki.mkdir()
            with self.assertRaisesRegex(
                SelfOpenWikiError, "personal-wiki-root-mismatch"
            ):
                SelfOpenWikiAdapter(_FakeClient(status)).visualizer_spec(
                    wiki_root=other_wiki
                )

    def test_contract_and_knowledge_runtime_contain_no_machine_specific_evidence(self):
        adapter = yaml.safe_load(
            (self.ROOT / "extensions/knowledge/selfopenwiki/adapter.yaml")
            .read_text(encoding="utf-8")
        )
        contract = json.loads(
            (self.ROOT / "extensions/knowledge/selfopenwiki/tool-contract.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(adapter["personalWiki"]["requiredExternalRoot"], True)
        self.assertEqual(contract["status"]["required"]["version.contractSchema"], 2)
        self.assertEqual(contract["externalUpdate"]["legacyFallback"], False)
        self.assertEqual(
            adapter["mcp"]["personalLifecycle"]["protocol"],
            "selfopenwiki:personal-openwiki-v1",
        )
        self.assertEqual(
            adapter["mcp"]["personalLifecycle"]["tools"],
            list(selfopenwiki.PERSONAL_TOOL_NAMES),
        )
        self.assertEqual(
            set(adapter["mcp"]["personalLifecycle"]["requiredCapabilities"]),
            set(selfopenwiki.PERSONAL_CAPABILITIES),
        )
        self.assertEqual(
            adapter["personalWiki"]["overrideRouting"]["source"],
            "openwiki_status.paths.wikiRoot",
        )
        self.assertEqual(
            adapter["visualizer"],
            {
                "source": "openwiki_status.visualizer",
                "requiredForDefault": True,
                "id": "selfopenwiki.zxh_wiki_viewer",
                "contractSchema": 1,
                "launcherPath": "status.visualizer.launcherPath",
                "wikiRootInput": ["--wiki-root", "<wiki-root>"],
                "urlTemplate": "http://127.0.0.1:{port}/wiki/local",
                "loopbackOnly": True,
                "autoOpen": False,
            },
        )
        self.assertEqual(
            adapter["defaultRouting"],
            {
                "profile": "knowledge",
                "backend": "selfopenwiki",
                "intents": ["wiki-visualize", "wiki-summary", "wiki-organize", "wiki-update"],
                "fallback": "forbidden",
            },
        )
        self.assertEqual(
            adapter["hostBinding"],
            {
                "entrypoint": "selfworkflow.selfopenwiki:SelfOpenWikiAdapter",
                "callBoundary": "personal_call",
                "statusBoundary": "personal_status",
                "readBoundary": "read",
                "recoveryStatusBoundary": "recovery_status",
                "confirmedAbortBoundary": "abort_external_update",
            },
        )
        self.assertEqual(
            contract["personalLifecycle"]["tools"],
            list(selfopenwiki.PERSONAL_TOOL_NAMES),
        )
        self.assertEqual(
            set(contract["personalLifecycle"]["requiredCapabilities"]),
            set(selfopenwiki.PERSONAL_CAPABILITIES),
        )
        self.assertEqual(
            contract["personalLifecycle"]["overrideRouting"]["source"],
            "openwiki_status.paths.wikiRoot",
        )
        self.assertEqual(
            contract["visualizer"]["source"],
            "openwiki_status.visualizer",
        )
        self.assertEqual(
            contract["defaultRouting"]["fallback"],
            "forbidden",
        )
        self.assertIn("openwiki_finish", contract["personalLifecycle"]["sequence"])
        for path in (
            self.ROOT / "extensions/knowledge/selfopenwiki/adapter.yaml",
            self.ROOT / "extensions/knowledge/selfopenwiki/tool-contract.json",
            self.ROOT / "skills/kg-selfopenwiki/SKILL.md",
        ):
            content = path.read_text(encoding="utf-8").casefold()
            self.assertNotIn("credentials.json", content)
            self.assertNotIn("verified-capabilities", content)
            self.assertNotIn("c:\\users\\", content)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            runtime = build_runtime(
                self.ROOT, Path(temporary) / "knowledge", "0.1.0.dev0", profile="knowledge"
            )
            self.assertEqual(runtime["profile"], "knowledge")
            self.assertTrue(
                (Path(temporary) / "knowledge/extensions/knowledge/selfopenwiki/adapter.yaml").is_file()
            )
            self.assertTrue(
                (Path(temporary) / "knowledge/skills/kg-selfopenwiki/SKILL.md").is_file()
            )


if __name__ == "__main__":
    unittest.main()
