import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_SCRIPT = REPOSITORY_ROOT / "scripts" / "bootstrap-codex-cli.ps1"
FAKE_NPM = REPOSITORY_ROOT / "tests" / "fixtures" / "bootstrap" / "fake-npm.cmd"
MANIFEST_SCHEMA = REPOSITORY_ROOT / "schemas" / "bootstrap-tool-manifest.schema.json"


def _run_bootstrap(local_app_data, *arguments, environment=None):
    child_environment = os.environ.copy()
    child_environment["LOCALAPPDATA"] = str(local_app_data)
    if environment:
        child_environment.update(environment)
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(BOOTSTRAP_SCRIPT),
            *arguments,
        ],
        cwd=REPOSITORY_ROOT,
        env=child_environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _read_directory_acl(directory):
    environment = os.environ.copy()
    environment["SELFWORKFLOW_ACL_TEST_PATH"] = str(directory)
    command = r"""
$Acl = Get-Acl -LiteralPath $env:SELFWORKFLOW_ACL_TEST_PATH
$Rules = @($Acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
[ordered]@{
    protected = $Acl.AreAccessRulesProtected
    currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    sddl = $Acl.GetSecurityDescriptorSddlForm([System.Security.AccessControl.AccessControlSections]::Access)
    rules = @($Rules | ForEach-Object {
        [ordered]@{
            sid = $_.IdentityReference.Value
            inherited = $_.IsInherited
            type = $_.AccessControlType.ToString()
            rights = $_.FileSystemRights.ToString()
            inheritance = $_.InheritanceFlags.ToString()
            propagation = $_.PropagationFlags.ToString()
        }
    })
} | ConvertTo-Json -Depth 4 -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


def _compute_package_tree_hash(package_root):
    digest = hashlib.sha256()
    files = sorted(
        (path for path in package_root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(package_root).as_posix(),
    )
    for path in files:
        relative_path = path.relative_to(package_root).as_posix().encode("utf-8")
        digest.update(relative_path)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _snapshot_tree(root):
    snapshot = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative_path = path.relative_to(root).as_posix()
        stat = path.stat()
        snapshot[relative_path] = {
            "isDirectory": path.is_dir(),
            "size": stat.st_size,
            "modifiedNanoseconds": stat.st_mtime_ns,
            "contentHash": (
                None if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
            ),
        }
    return snapshot


class BootstrapCodexCliTests(unittest.TestCase):
    def test_manifest_schema_requires_strict_security_bindings(self):
        self.assertTrue(MANIFEST_SCHEMA.is_file(), "manifest schema must exist")
        schema = json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))

        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            set(schema["required"]),
            {
                "schemaVersion",
                "bootstrapRoot",
                "package",
                "packageTreeHash",
                "daclSddl",
                "cliVersion",
                "planHash",
            },
        )
        package_schema = schema["properties"]["package"]
        self.assertFalse(package_schema["additionalProperties"])
        self.assertEqual(
            set(package_schema["required"]), {"name", "version", "integrity"}
        )

    def test_discover_returns_version_and_integrity_plan(self):
        self.assertTrue(BOOTSTRAP_SCRIPT.is_file(), "bootstrap script must exist")

        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["mode"], "Discover")
        self.assertEqual(plan["package"]["name"], "@openai/codex")
        self.assertEqual(plan["package"]["version"], "1.2.3")
        self.assertEqual(
            plan["package"]["integrity"],
            "sha512-U2VsZldvcmtGbG93RmFrZUludGVncml0eQ==",
        )
        self.assertRegex(plan["planHash"], re.compile(r"^[0-9a-f]{64}$"))

    def test_discover_rejects_non_codex_package_name(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = _run_bootstrap(
                Path(temporary_directory) / "LocalAppData",
                "-Mode",
                "Discover",
                "-PackageName",
                "left-pad",
                "-NpmCommand",
                str(FAKE_NPM),
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ValidateSet", result.stderr)
        self.assertIn("@openai/codex", result.stderr)

    def test_discover_does_not_mutate_local_file_tree(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            bootstrap_root = (
                local_app_data / "SelfWorkFlow" / "bootstrap" / "codex-cli"
            )
            bootstrap_root.mkdir(parents=True)
            marker = bootstrap_root / "existing-marker.txt"
            marker.write_text("must remain unchanged", encoding="utf-8")
            before = _snapshot_tree(local_app_data)

            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
            )
            after = _snapshot_tree(local_app_data)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(after, before)

    def test_discover_stops_on_npm_metadata_failure(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = _run_bootstrap(
                Path(temporary_directory) / "LocalAppData",
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
                environment={"FAKE_NPM_FAIL_COMMAND": "view"},
            )

        self.assertEqual(result.returncode, 40)
        self.assertIn("npm metadata query failed with exit code 41", result.stderr)

    def test_discover_rejects_bootstrap_root_outside_allowed_boundary(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            local_app_data = temporary_root / "LocalAppData"
            outside_root = temporary_root / "escape"
            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-BootstrapRoot",
                str(outside_root),
                "-NpmCommand",
                str(FAKE_NPM),
            )

        self.assertEqual(result.returncode, 42)
        self.assertIn("outside the allowed bootstrap boundary", result.stderr)

    def test_discover_rejects_reparse_point_ancestor(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            local_app_data = temporary_root / "LocalAppData"
            local_app_data.mkdir()
            junction_target = temporary_root / "junction-target"
            junction_target.mkdir()
            junction = local_app_data / "SelfWorkFlow"
            junction_result = subprocess.run(
                f'cmd.exe /d /c mklink /J "{junction}" "{junction_target}"',
                capture_output=True,
                text=True,
                check=False,
            )
            if junction_result.returncode != 0:
                self.skipTest(f"cannot create test junction: {junction_result.stderr}")

            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
            )

            junction.rmdir()

        self.assertEqual(result.returncode, 43)
        self.assertIn("reparse point ancestor", result.stderr)

    def test_apply_rejects_nonempty_existing_target(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
            )
            plan_hash = json.loads(discover.stdout)["planHash"]
            bootstrap_root = (
                local_app_data / "SelfWorkFlow" / "bootstrap" / "codex-cli"
            )
            bootstrap_root.mkdir(parents=True)
            (bootstrap_root / "untrusted.txt").write_text("data", encoding="utf-8")

            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmPlanHash",
                plan_hash,
                "-NpmCommand",
                str(FAKE_NPM),
            )

        self.assertEqual(result.returncode, 44)
        self.assertIn("does not satisfy safe recovery conditions", result.stderr)

    def test_apply_rejects_existing_file_target(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
            )
            plan_hash = json.loads(discover.stdout)["planHash"]
            bootstrap_root = (
                local_app_data / "SelfWorkFlow" / "bootstrap" / "codex-cli"
            )
            bootstrap_root.parent.mkdir(parents=True)
            bootstrap_root.write_text("not-a-directory", encoding="utf-8")

            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmPlanHash",
                plan_hash,
                "-NpmCommand",
                str(FAKE_NPM),
            )

        self.assertEqual(result.returncode, 44)
        self.assertIn("does not satisfy safe recovery conditions", result.stderr)

    def test_apply_requires_confirm_plan_hash(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-NpmCommand",
                str(FAKE_NPM),
            )
            bootstrap_root = (
                local_app_data / "SelfWorkFlow" / "bootstrap" / "codex-cli"
            )

            self.assertFalse(bootstrap_root.exists())

        self.assertEqual(result.returncode, 45)
        self.assertIn("ConfirmPlanHash is required", result.stderr)

    def test_apply_rejects_wrong_confirm_plan_hash(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmPlanHash",
                "0" * 64,
                "-NpmCommand",
                str(FAKE_NPM),
            )
            bootstrap_root = (
                local_app_data / "SelfWorkFlow" / "bootstrap" / "codex-cli"
            )

            self.assertFalse(bootstrap_root.exists())

        self.assertEqual(result.returncode, 46, result.stderr)
        self.assertIn("does not match the regenerated plan hash", result.stderr)

    def test_apply_rejects_metadata_drift_since_discovery(self):
        drift_cases = (
            {"FAKE_NPM_VERSION": "1.2.4"},
            {"FAKE_NPM_INTEGRITY": "sha512-RHJpZnRlZA=="},
        )
        for drift_environment in drift_cases:
            with self.subTest(drift=drift_environment):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    local_app_data = Path(temporary_directory) / "LocalAppData"
                    discover = _run_bootstrap(
                        local_app_data,
                        "-Mode",
                        "Discover",
                        "-NpmCommand",
                        str(FAKE_NPM),
                    )
                    plan_hash = json.loads(discover.stdout)["planHash"]
                    result = _run_bootstrap(
                        local_app_data,
                        "-Mode",
                        "Apply",
                        "-ConfirmPlanHash",
                        plan_hash,
                        "-NpmCommand",
                        str(FAKE_NPM),
                        environment=drift_environment,
                    )
                    bootstrap_root = (
                        local_app_data / "SelfWorkFlow" / "bootstrap" / "codex-cli"
                    )

                    self.assertFalse(bootstrap_root.exists())

                self.assertEqual(result.returncode, 46)
                self.assertIn("does not match the regenerated plan hash", result.stderr)

    def test_apply_creates_root_with_protected_current_user_and_system_dacl(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
            )
            plan = json.loads(discover.stdout)
            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmPlanHash",
                plan["planHash"],
                "-NpmCommand",
                str(FAKE_NPM),
            )
            bootstrap_root = Path(plan["bootstrapRoot"])

            self.assertTrue(bootstrap_root.is_dir())
            acl = _read_directory_acl(bootstrap_root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(acl["protected"])
        self.assertIn("D:P", acl["sddl"])
        self.assertEqual(
            {rule["sid"] for rule in acl["rules"]},
            {acl["currentSid"], "S-1-5-18"},
        )
        self.assertEqual(len(acl["rules"]), 2)
        for rule in acl["rules"]:
            self.assertFalse(rule["inherited"])
            self.assertEqual(rule["type"], "Allow")
            self.assertEqual(rule["rights"], "FullControl")
            self.assertIn("ContainerInherit", rule["inheritance"])
            self.assertIn("ObjectInherit", rule["inheritance"])
            self.assertEqual(rule["propagation"], "None")

    def test_apply_stops_when_icacls_verification_fails(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            local_app_data = temporary_root / "LocalAppData"
            failing_icacls = temporary_root / "fail-icacls.cmd"
            failing_icacls.write_bytes(b"@echo off\r\nexit /b 9\r\n")
            install_marker = temporary_root / "npm-install-called"
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
            )
            plan_hash = json.loads(discover.stdout)["planHash"]

            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmPlanHash",
                plan_hash,
                "-NpmCommand",
                str(FAKE_NPM),
                "-IcaclsCommand",
                str(failing_icacls),
                environment={"FAKE_NPM_INSTALL_MARKER": str(install_marker)},
            )

            self.assertFalse(install_marker.exists())

        self.assertEqual(result.returncode, 48)
        self.assertIn("icacls verification failed", result.stderr)

    def test_apply_fails_closed_when_acl_reread_detects_inheritance(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            local_app_data = temporary_root / "LocalAppData"
            corrupting_icacls = temporary_root / "corrupt-acl.ps1"
            corrupting_icacls.write_text(
                """param([string]$Path)
$ErrorActionPreference = "Stop"
$Acl = Get-Acl -LiteralPath $Path
$Acl.SetAccessRuleProtection($false, $true)
Set-Acl -LiteralPath $Path -AclObject $Acl
Write-Output $Path
exit 0
""",
                encoding="utf-8",
            )
            install_marker = temporary_root / "npm-install-called"
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
            )
            plan_hash = json.loads(discover.stdout)["planHash"]

            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmPlanHash",
                plan_hash,
                "-NpmCommand",
                str(FAKE_NPM),
                "-IcaclsCommand",
                str(corrupting_icacls),
                environment={"FAKE_NPM_INSTALL_MARKER": str(install_marker)},
            )

            self.assertFalse(install_marker.exists())

        self.assertEqual(result.returncode, 48, result.stderr)
        self.assertIn("ACL security verification failed", result.stderr)
        self.assertIn("DACL inheritance is not protected", result.stderr)

    def test_apply_stops_when_npm_install_fails(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            local_app_data = temporary_root / "LocalAppData"
            install_marker = temporary_root / "npm-install-called"
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
            )
            plan_hash = json.loads(discover.stdout)["planHash"]

            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmPlanHash",
                plan_hash,
                "-NpmCommand",
                str(FAKE_NPM),
                environment={
                    "FAKE_NPM_FAIL_COMMAND": "install",
                    "FAKE_NPM_INSTALL_MARKER": str(install_marker),
                },
            )

            self.assertTrue(install_marker.is_file())

        self.assertEqual(result.returncode, 49)
        self.assertIn("npm install failed with exit code 42", result.stderr)

    def test_apply_rejects_missing_installed_package_metadata(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
            )
            plan_hash = json.loads(discover.stdout)["planHash"]

            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmPlanHash",
                plan_hash,
                "-NpmCommand",
                str(FAKE_NPM),
                environment={"FAKE_NPM_SKIP_ARTIFACTS": "1"},
            )

        self.assertEqual(result.returncode, 50)
        self.assertIn("installed package metadata is missing", result.stderr)

    def test_apply_rejects_installed_version_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
            )
            plan_hash = json.loads(discover.stdout)["planHash"]

            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmPlanHash",
                plan_hash,
                "-NpmCommand",
                str(FAKE_NPM),
                environment={"FAKE_NPM_INSTALLED_VERSION": "9.9.9"},
            )

        self.assertEqual(result.returncode, 51)
        self.assertIn("installed package version does not match", result.stderr)

    def test_apply_rejects_installed_integrity_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
            )
            plan_hash = json.loads(discover.stdout)["planHash"]

            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmPlanHash",
                plan_hash,
                "-NpmCommand",
                str(FAKE_NPM),
                environment={"FAKE_NPM_INSTALLED_INTEGRITY": "sha512-drifted"},
            )

        self.assertEqual(result.returncode, 52)
        self.assertIn("installed package integrity does not match", result.stderr)

    def test_apply_rejects_missing_codex_cli_shim(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
            )
            plan_hash = json.loads(discover.stdout)["planHash"]

            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmPlanHash",
                plan_hash,
                "-NpmCommand",
                str(FAKE_NPM),
                environment={"FAKE_NPM_SKIP_CLI": "1"},
            )

        self.assertEqual(result.returncode, 53)
        self.assertIn("installed Codex CLI shim is missing", result.stderr)

    def test_apply_stops_when_codex_cli_version_command_fails(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
            )
            plan_hash = json.loads(discover.stdout)["planHash"]

            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmPlanHash",
                plan_hash,
                "-NpmCommand",
                str(FAKE_NPM),
                environment={"FAKE_NPM_CLI_EXIT_CODE": "7"},
            )

        self.assertEqual(result.returncode, 54)
        self.assertIn("Codex CLI version command failed with exit code 7", result.stderr)

    def test_apply_writes_bound_credential_free_manifest(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
            )
            plan = json.loads(discover.stdout)
            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmPlanHash",
                plan["planHash"],
                "-NpmCommand",
                str(FAKE_NPM),
            )
            bootstrap_root = Path(plan["bootstrapRoot"])
            manifest_path = bootstrap_root / "bootstrap-tool-manifest.json"

            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            acl = _read_directory_acl(bootstrap_root)
            expected_tree_hash = _compute_package_tree_hash(
                bootstrap_root / "node_modules" / "@openai" / "codex"
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["bootstrapRoot"], plan["bootstrapRoot"])
        self.assertEqual(
            manifest["package"],
            {
                "name": "@openai/codex",
                "version": "1.2.3",
                "integrity": "sha512-U2VsZldvcmtGbG93RmFrZUludGVncml0eQ==",
            },
        )
        self.assertEqual(manifest["packageTreeHash"], expected_tree_hash)
        self.assertEqual(manifest["daclSddl"], acl["sddl"])
        self.assertEqual(manifest["cliVersion"], "codex-cli 1.2.3")
        self.assertEqual(manifest["planHash"], plan["planHash"])
        serialized_manifest = json.dumps(manifest, sort_keys=True).lower()
        for forbidden_word in ("password", "credential", "token", "_auth", "npmrc"):
            self.assertNotIn(forbidden_word, serialized_manifest)

    def test_generated_manifest_conforms_to_json_schema(self):
        from jsonschema import Draft202012Validator

        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
            )
            plan = json.loads(discover.stdout)
            apply_result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmPlanHash",
                plan["planHash"],
                "-NpmCommand",
                str(FAKE_NPM),
            )
            manifest_path = Path(plan["bootstrapRoot"]) / "bootstrap-tool-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            schema = json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))

        self.assertEqual(apply_result.returncode, 0, apply_result.stderr)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(manifest)


if __name__ == "__main__":
    unittest.main()
