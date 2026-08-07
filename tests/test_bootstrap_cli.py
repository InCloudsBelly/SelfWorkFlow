import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_SCRIPT = REPOSITORY_ROOT / "scripts" / "bootstrap-codex-cli.ps1"
MANIFEST_LIBRARY = REPOSITORY_ROOT / "scripts" / "lib" / "bootstrap-manifest.ps1"
FAKE_NPM = REPOSITORY_ROOT / "tests" / "fixtures" / "bootstrap" / "fake-npm.cmd"
MANIFEST_SCHEMA = REPOSITORY_ROOT / "schemas" / "bootstrap-tool-manifest.schema.json"


def _run_bootstrap(
    local_app_data, *arguments, environment=None, script=BOOTSTRAP_SCRIPT
):
    Path(local_app_data).mkdir(parents=True, exist_ok=True)
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
            str(script),
            *arguments,
        ],
        cwd=REPOSITORY_ROOT,
        env=child_environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _discover_plan(local_app_data, *, npm_command=FAKE_NPM, environment=None, arguments=()):
    result = _run_bootstrap(
        local_app_data,
        "-Mode",
        "Discover",
        "-NpmCommand",
        str(npm_command),
        *arguments,
        environment=environment,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr + result.stdout)
    return result, json.loads(result.stdout)


def _apply_plan(
    local_app_data,
    plan,
    *,
    npm_command=FAKE_NPM,
    environment=None,
    arguments=(),
):
    return _run_bootstrap(
        local_app_data,
        "-Mode",
        "Apply",
        "-ConfirmPlanHash",
        plan["planHash"],
        "-NpmCommand",
        str(npm_command),
        *arguments,
        environment=environment,
    )


def _validate_manifest_candidate(
    local_app_data, plan, manifest, *, expected_sddl=None
):
    temporary_root = Path(local_app_data).parent
    plan_path = temporary_root / "validation-plan.json"
    manifest_path = temporary_root / "validation-manifest.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "SELFWORKFLOW_MANIFEST_LIBRARY": str(MANIFEST_LIBRARY),
            "SELFWORKFLOW_PLAN_PATH": str(plan_path),
            "SELFWORKFLOW_MANIFEST_PATH": str(manifest_path),
            "SELFWORKFLOW_ALLOWED_BOUNDARY": str(
                Path(local_app_data) / "SelfWorkFlow" / "bootstrap" / "codex-cli"
            ),
            "SELFWORKFLOW_PACKAGE_ROOT": str(
                Path(plan["bootstrapRoot"])
                / "node_modules"
                / "@openai"
                / "codex"
            ),
            "SELFWORKFLOW_EXPECTED_SDDL": expected_sddl or manifest["daclSddl"],
        }
    )
    command = r"""
try {
    . $env:SELFWORKFLOW_MANIFEST_LIBRARY
    $Plan = Get-Content -Raw -LiteralPath $env:SELFWORKFLOW_PLAN_PATH | ConvertFrom-Json
    $Manifest = Get-Content -Raw -LiteralPath $env:SELFWORKFLOW_MANIFEST_PATH | ConvertFrom-Json
    Assert-SelfWorkflowBootstrapManifest `
        -Manifest $Manifest `
        -Plan $Plan `
        -AllowedBoundary $env:SELFWORKFLOW_ALLOWED_BOUNDARY `
        -PackageRoot $env:SELFWORKFLOW_PACKAGE_ROOT `
        -ExpectedSddl $env:SELFWORKFLOW_EXPECTED_SDDL
} catch {
    [Console]::Error.WriteLine("SelfWorkFlow: manifest semantic validation failed.")
    exit 58
}
"""
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        env=environment,
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


def _compute_plan_hash(plan):
    plan_data = {
        key: plan[key]
        for key in (
            "schemaVersion",
            "bootstrapRoot",
            "package",
            "execution",
            "security",
            "sideEffects",
        )
    }
    serialized = json.dumps(
        plan_data, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


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


def _write_reparse_swapping_npm(path):
    fake_npm_path = str(FAKE_NPM).replace("%", "%%")
    path.write_text(
        f"""@echo off
if /I not "%~1"=="view" goto delegate
if defined FAKE_NPM_CREATE_JUNCTION (
  mklink /J "%FAKE_NPM_SWAP_ROOT%" "%FAKE_NPM_SWAP_TARGET%" >nul 2>&1
  if errorlevel 1 goto create-failed
)
if defined FAKE_NPM_REPLACE_DIRECTORY (
  move "%FAKE_NPM_SWAP_ROOT%" "%FAKE_NPM_SWAP_BACKUP%" >nul 2>&1
  if exist "%FAKE_NPM_SWAP_ROOT%" goto replace-failed
  if not exist "%FAKE_NPM_SWAP_BACKUP%" goto replace-failed
  mklink /J "%FAKE_NPM_SWAP_ROOT%" "%FAKE_NPM_SWAP_TARGET%" >nul 2>&1
  if errorlevel 1 goto junction-failed
)
:delegate
call "{fake_npm_path}" %*
exit /b %errorlevel%
:create-failed
exit /b 73
:replace-failed
exit /b 74
:junction-failed
exit /b 75
""".replace("\n", "\r\n"),
        encoding="utf-8",
    )


def _remove_junction_if_present(path):
    if not path.exists():
        return
    attributes = path.stat().st_file_attributes
    if attributes & 0x400:
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "rmdir", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr)


def _write_reparse_swapping_icacls(path):
    path.write_text(
        """@echo off
move "%~1" "%FAKE_ICACLS_BACKUP%" >nul 2>&1
if exist "%~1" goto replace-failed
if not exist "%FAKE_ICACLS_BACKUP%" goto replace-failed
mklink /J "%~1" "%FAKE_ICACLS_TARGET%" >nul 2>&1
if errorlevel 1 goto junction-failed
echo %~1
exit /b 0
:replace-failed
exit /b 74
:junction-failed
exit /b 75
""".replace("\n", "\r\n"),
        encoding="utf-8",
    )


def _write_self_mutating_npm(path):
    fake_npm_path = str(FAKE_NPM).replace("%", "%%")
    path.write_text(
        f"""@echo off
setlocal EnableDelayedExpansion
if /I "%~1"=="view" if defined FAKE_NPM_MUTATE_SELF (
  for %%A in ("%~f0") do set "SIZE_BEFORE=%%~zA"
  >> "%~f0" echo rem executable identity drift
  for %%A in ("%~f0") do set "SIZE_AFTER=%%~zA"
  if "!SIZE_BEFORE!"=="!SIZE_AFTER!" goto mutation-blocked
)
call "{fake_npm_path}" %*
exit /b %errorlevel%
:mutation-blocked
exit /b 76
""".replace("\n", "\r\n"),
        encoding="utf-8",
    )


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

    def test_manifest_schema_rejects_unsafe_static_values(self):
        from jsonschema import Draft202012Validator

        schema = json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))
        manifest = {
            "schemaVersion": 1,
            "bootstrapRoot": r"C:\Users\Example\AppData\Local\SelfWorkFlow\bootstrap\codex-cli",
            "package": {
                "name": "@openai/codex",
                "version": "1.2.3",
                "integrity": "sha512-U2VsZldvcmtGbG93RmFrZUludGVncml0eQ==",
            },
            "packageTreeHash": f"sha256:{'0' * 64}",
            "daclSddl": "D:P(A;OICI;FA;;;S-1-5-18)",
            "cliVersion": "1.2.3",
            "planHash": "0" * 64,
        }
        validator = Draft202012Validator(schema)
        for field, unsafe_value in (
            ("bootstrapRoot", r"C:\..\Windows"),
            ("daclSddl", "D:P(A;;FA;;;WD)"),
            ("cliVersion", "1.2.3 extra-sensitive-text"),
        ):
            with self.subTest(field=field):
                unsafe_manifest = json.loads(json.dumps(manifest))
                unsafe_manifest[field] = unsafe_value
                self.assertTrue(list(validator.iter_errors(unsafe_manifest)))

        for field_path in (("package", "version"), ("cliVersion",)):
            with self.subTest(field_path=field_path, value="1.2.3-01"):
                unsafe_manifest = json.loads(json.dumps(manifest))
                target = unsafe_manifest
                for field in field_path[:-1]:
                    target = target[field]
                target[field_path[-1]] = "1.2.3-01"
                self.assertTrue(list(validator.iter_errors(unsafe_manifest)))

        legal_manifest = json.loads(json.dumps(manifest))
        legal_manifest["package"]["version"] = "1.2.3-alpha.1+build.01"
        legal_manifest["cliVersion"] = "1.2.3-alpha.1+build.01"
        self.assertFalse(list(validator.iter_errors(legal_manifest)))

    def test_manifest_schema_semver_pattern_matches_production_rule(self):
        schema = json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))
        environment = os.environ.copy()
        environment["SELFWORKFLOW_MANIFEST_LIBRARY"] = str(MANIFEST_LIBRARY)
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                ". $env:SELFWORKFLOW_MANIFEST_LIBRARY; "
                "'^' + (Get-SelfWorkflowCanonicalSemVerPattern) + '$'",
            ],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            schema["$defs"]["canonicalSemVer"]["pattern"],
            result.stdout.strip(),
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

    def test_discover_plan_binds_complete_execution_and_security_semantics(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
            )
            plan = json.loads(result.stdout)
            current_sid = _read_directory_acl(local_app_data)["currentSid"]

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("execution", plan)
        self.assertIn("security", plan)
        self.assertIn("sideEffects", plan)
        npm_identity = plan["execution"]["npm"]
        self.assertEqual(Path(npm_identity["path"]), FAKE_NPM.resolve())
        self.assertEqual(
            npm_identity["sha256"],
            f"sha256:{hashlib.sha256(FAKE_NPM.read_bytes()).hexdigest()}",
        )
        self.assertEqual(npm_identity["registry"], "https://registry.npmjs.org/")
        self.assertEqual(
            plan["execution"]["metadataArguments"],
            [
                "view",
                "@openai/codex@latest",
                "version",
                "dist.integrity",
                "--json",
                "--registry",
                "https://registry.npmjs.org/",
            ],
        )
        self.assertEqual(
            plan["execution"]["installArguments"],
            [
                "install",
                "--prefix",
                plan["bootstrapRoot"],
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
                "--package-lock=true",
                "--save-exact",
                "--registry",
                "https://registry.npmjs.org/",
                "@openai/codex@1.2.3",
            ],
        )
        self.assertEqual(
            plan["execution"]["environment"],
            {
                "npmConfig": "cleared",
                "authentication": "cleared",
                "userConfig": "NUL",
                "globalConfig": "NUL",
            },
        )
        self.assertEqual(
            plan["security"]["dacl"],
            {
                "protected": True,
                "principals": [current_sid, "S-1-5-18"],
                "rights": "FullControl",
                "inheritance": ["ContainerInherit", "ObjectInherit"],
            },
        )
        self.assertEqual(plan["security"]["path"]["status"], "constrained")
        self.assertEqual(
            plan["security"]["path"]["verified"],
            [
                "existing ancestors locked against delete and rename",
                "path identities and reparse attributes rechecked before side effects",
            ],
        )
        self.assertEqual(
            plan["security"]["path"]["unverified"],
            [
                "atomic create-and-open of new directory components against a same-SID attacker",
                "same-SID mutation of unlocked ACL or package files after final verification",
            ],
        )
        self.assertEqual(
            plan["sideEffects"],
            {
                "bootstrapRoot": plan["bootstrapRoot"],
                "manifestPath": str(
                    Path(plan["bootstrapRoot"]) / "bootstrap-tool-manifest.json"
                ),
                "uninstallBoundary": plan["bootstrapRoot"],
            },
        )
        serialized_plan = json.dumps(plan, sort_keys=True).lower()
        for forbidden_word in ("password", "credential", "token", "_auth", "npmrc"):
            self.assertNotIn(forbidden_word, serialized_plan)

    def test_npm_execution_isolates_user_configuration_and_authentication(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            local_app_data = temporary_root / "LocalAppData"
            argument_log = temporary_root / "npm-arguments.log"
            environment_log = temporary_root / "npm-environment.log"
            hostile_environment = {
                "FAKE_NPM_ARGUMENT_LOG": str(argument_log),
                "FAKE_NPM_ENVIRONMENT_LOG": str(environment_log),
                "NPM_CONFIG_REGISTRY": "https://attacker:registry-secret@evil.invalid/",
                "NPM_CONFIG_USERCONFIG": str(temporary_root / "secret-user.npmrc"),
                "NPM_CONFIG_GLOBALCONFIG": str(
                    temporary_root / "secret-global.npmrc"
                ),
                "NPM_CONFIG_ATTACKER": "attacker-config-secret",
                "NPM_TOKEN": "npm-token-secret",
                "NODE_AUTH_TOKEN": "node-token-secret",
            }
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
                environment=hostile_environment,
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
                environment=hostile_environment,
            )
            manifest_path = Path(plan["sideEffects"]["manifestPath"])
            persisted_text = plan.copy()
            persisted_text["manifest"] = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            environment_lines = environment_log.read_text(
                encoding="utf-8"
            ).splitlines()
            argument_lines = argument_log.read_text(encoding="utf-8").splitlines()

        self.assertEqual(discover.returncode, 0, discover.stderr)
        self.assertEqual(apply_result.returncode, 0, apply_result.stderr)
        self.assertEqual(
            [line for line in environment_lines if line.startswith("COMMAND=")],
            ["COMMAND=view", "COMMAND=view", "COMMAND=install"],
        )
        for line in environment_lines:
            if line.startswith("NPM_CONFIG_REGISTRY="):
                self.assertEqual(
                    line, "NPM_CONFIG_REGISTRY=https://registry.npmjs.org/"
                )
            elif line.startswith("NPM_CONFIG_USERCONFIG="):
                self.assertEqual(line, "NPM_CONFIG_USERCONFIG=NUL")
            elif line.startswith("NPM_CONFIG_GLOBALCONFIG="):
                self.assertEqual(line, "NPM_CONFIG_GLOBALCONFIG=NUL")
            elif line.startswith("NPM_CONFIG_ATTACKER="):
                self.assertEqual(line, "NPM_CONFIG_ATTACKER=")
            elif line.startswith("NPM_TOKEN="):
                self.assertEqual(line, "NPM_TOKEN=")
            elif line.startswith("NODE_AUTH_TOKEN="):
                self.assertEqual(line, "NODE_AUTH_TOKEN=")
        self.assertIn("--registry https://registry.npmjs.org/", argument_lines[0])
        self.assertIn("--registry https://registry.npmjs.org/", argument_lines[-1])
        combined_output = discover.stderr + apply_result.stderr
        persisted_json = json.dumps(persisted_text, sort_keys=True)
        for sensitive_value in (
            "registry-secret",
            "secret-user.npmrc",
            "secret-global.npmrc",
            "attacker-config-secret",
            "npm-token-secret",
            "node-token-secret",
        ):
            self.assertNotIn(sensitive_value, combined_output)
            self.assertNotIn(sensitive_value, persisted_json)

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

    def test_discover_rejects_registry_userinfo_without_echoing_credentials(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            sensitive_registry = "https://registry-user:super-secret@registry.example/"
            result = _run_bootstrap(
                Path(temporary_directory) / "LocalAppData",
                "-Mode",
                "Discover",
                "-Registry",
                sensitive_registry,
                "-NpmCommand",
                str(FAKE_NPM),
            )

        combined_output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 41, combined_output)
        self.assertEqual(
            result.stderr.strip(), "SelfWorkFlow: registry configuration is invalid."
        )
        self.assertNotIn(sensitive_registry, combined_output)
        self.assertNotIn("registry-user", combined_output)
        self.assertNotIn("super-secret", combined_output)

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

    def test_discover_rejects_missing_npm_command_with_stable_redacted_error(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            sensitive_command = (
                Path(temporary_directory) / "missing-npm-super-secret.cmd"
            )
            result = _run_bootstrap(
                Path(temporary_directory) / "LocalAppData",
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(sensitive_command),
            )

        combined_output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 39, combined_output)
        self.assertEqual(
            result.stderr.strip(), "SelfWorkFlow: npm command validation failed."
        )
        self.assertNotIn(str(sensitive_command), combined_output)
        self.assertNotIn("super-secret", combined_output)

    def test_discover_rejects_invalid_metadata_payload_with_stable_redacted_error(self):
        for metadata_case in ("malformed", "array", "missing-field", "wrong-type"):
            with self.subTest(metadata_case=metadata_case):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    result = _run_bootstrap(
                        Path(temporary_directory) / "LocalAppData",
                        "-Mode",
                        "Discover",
                        "-NpmCommand",
                        str(FAKE_NPM),
                        environment={"FAKE_NPM_METADATA_CASE": metadata_case},
                    )

                combined_output = result.stdout + result.stderr
                self.assertEqual(result.returncode, 47, combined_output)
                self.assertEqual(
                    result.stderr.strip(),
                    "SelfWorkFlow: npm metadata response is invalid.",
                )
                self.assertNotIn("metadata-super-secret", combined_output)

    def test_discover_and_apply_reject_numeric_prerelease_leading_zero(self):
        invalid_version = "1.2.3-01"

        with self.subTest(mode="Discover"):
            with tempfile.TemporaryDirectory() as temporary_directory:
                result = _run_bootstrap(
                    Path(temporary_directory) / "LocalAppData",
                    "-Mode",
                    "Discover",
                    "-NpmCommand",
                    str(FAKE_NPM),
                    environment={"FAKE_NPM_VERSION": invalid_version},
                )

            self.assertEqual(result.returncode, 47, result.stderr + result.stdout)
            self.assertEqual(
                result.stderr.strip(),
                "SelfWorkFlow: npm metadata response is invalid.",
            )

        with self.subTest(mode="Apply"):
            with tempfile.TemporaryDirectory() as temporary_directory:
                temporary_root = Path(temporary_directory)
                local_app_data = temporary_root / "LocalAppData"
                install_marker = temporary_root / "npm-install-called"
                _, plan = _discover_plan(local_app_data)
                result = _apply_plan(
                    local_app_data,
                    plan,
                    environment={
                        "FAKE_NPM_VERSION": invalid_version,
                        "FAKE_NPM_INSTALL_MARKER": str(install_marker),
                    },
                )

                self.assertFalse(install_marker.exists())

            self.assertEqual(result.returncode, 47, result.stderr + result.stdout)
            self.assertEqual(
                result.stderr.strip(),
                "SelfWorkFlow: npm metadata response is invalid.",
            )

    def test_discover_and_apply_accept_canonical_prerelease_and_build(self):
        version = "1.2.3-alpha.1+build.01"
        environment = {"FAKE_NPM_VERSION": version}
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            discover, plan = _discover_plan(
                local_app_data,
                environment=environment,
            )
            apply_result = _apply_plan(
                local_app_data,
                plan,
                environment=environment,
            )
            manifest = json.loads(
                Path(plan["sideEffects"]["manifestPath"]).read_text(encoding="utf-8")
            )

        self.assertEqual(discover.returncode, 0, discover.stderr)
        self.assertEqual(apply_result.returncode, 0, apply_result.stderr)
        self.assertEqual(plan["package"]["version"], version)
        self.assertEqual(manifest["package"]["version"], version)
        self.assertEqual(manifest["cliVersion"], version)

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

    def test_apply_rechecks_reparse_ancestor_after_metadata_before_install(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            local_app_data = temporary_root / "LocalAppData"
            local_app_data.mkdir()
            junction = local_app_data / "SelfWorkFlow"
            junction_target = temporary_root / "junction-target"
            junction_target.mkdir()
            swapping_npm = temporary_root / "swap-npm.cmd"
            _write_reparse_swapping_npm(swapping_npm)
            install_marker = temporary_root / "npm-install-called"
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(swapping_npm),
            )
            plan_hash = json.loads(discover.stdout)["planHash"]

            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmPlanHash",
                plan_hash,
                "-NpmCommand",
                str(swapping_npm),
                environment={
                    "FAKE_NPM_CREATE_JUNCTION": "1",
                    "FAKE_NPM_SWAP_ROOT": str(junction),
                    "FAKE_NPM_SWAP_TARGET": str(junction_target),
                    "FAKE_NPM_INSTALL_MARKER": str(install_marker),
                },
            )

            install_was_called = install_marker.exists()
            junction_target_entries = list(junction_target.rglob("*"))
            _remove_junction_if_present(junction)

            self.assertFalse(install_was_called)
            self.assertEqual(junction_target_entries, [])

        self.assertEqual(result.returncode, 43, result.stderr)
        self.assertIn("bootstrap path security verification failed", result.stderr)

    def test_apply_locks_existing_ancestor_against_metadata_replacement(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            local_app_data = temporary_root / "LocalAppData"
            protected_ancestor = local_app_data / "SelfWorkFlow"
            protected_ancestor.mkdir(parents=True)
            backup_ancestor = local_app_data / "SelfWorkFlow-backup"
            junction_target = temporary_root / "junction-target"
            junction_target.mkdir()
            swapping_npm = temporary_root / "swap-npm.cmd"
            _write_reparse_swapping_npm(swapping_npm)
            install_marker = temporary_root / "npm-install-called"
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(swapping_npm),
            )
            plan_hash = json.loads(discover.stdout)["planHash"]

            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmPlanHash",
                plan_hash,
                "-NpmCommand",
                str(swapping_npm),
                environment={
                    "FAKE_NPM_REPLACE_DIRECTORY": "1",
                    "FAKE_NPM_SWAP_ROOT": str(protected_ancestor),
                    "FAKE_NPM_SWAP_BACKUP": str(backup_ancestor),
                    "FAKE_NPM_SWAP_TARGET": str(junction_target),
                    "FAKE_NPM_INSTALL_MARKER": str(install_marker),
                },
            )

            replacement_succeeded = backup_ancestor.exists()
            install_was_called = install_marker.exists()
            _remove_junction_if_present(protected_ancestor)
            if backup_ancestor.exists() and not protected_ancestor.exists():
                backup_ancestor.rename(protected_ancestor)

            self.assertFalse(replacement_succeeded)
            self.assertFalse(install_was_called)

        self.assertEqual(result.returncode, 40, result.stderr + result.stdout)
        self.assertIn("npm metadata query failed", result.stderr)

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

    def test_apply_rejects_npm_command_content_drift_since_discovery(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            local_app_data = temporary_root / "LocalAppData"
            mutable_npm = temporary_root / "mutable-npm.cmd"
            mutable_npm.write_bytes(FAKE_NPM.read_bytes())
            install_marker = temporary_root / "npm-install-called"
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(mutable_npm),
            )
            plan_hash = json.loads(discover.stdout)["planHash"]
            with mutable_npm.open("ab") as npm_file:
                npm_file.write(b"\r\nrem executable identity drift\r\n")

            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmPlanHash",
                plan_hash,
                "-NpmCommand",
                str(mutable_npm),
                environment={"FAKE_NPM_INSTALL_MARKER": str(install_marker)},
            )

            self.assertFalse(install_marker.exists())

        self.assertEqual(result.returncode, 46, result.stderr)
        self.assertIn("does not match the regenerated plan hash", result.stderr)

    def test_apply_locks_npm_command_identity_through_install(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            local_app_data = temporary_root / "LocalAppData"
            mutating_npm = temporary_root / "mutating-npm.cmd"
            _write_self_mutating_npm(mutating_npm)
            install_marker = temporary_root / "npm-install-called"
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(mutating_npm),
            )
            plan_hash = json.loads(discover.stdout)["planHash"]
            identity_before_apply = hashlib.sha256(mutating_npm.read_bytes()).hexdigest()

            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmPlanHash",
                plan_hash,
                "-NpmCommand",
                str(mutating_npm),
                environment={
                    "FAKE_NPM_MUTATE_SELF": "1",
                    "FAKE_NPM_INSTALL_MARKER": str(install_marker),
                },
            )
            identity_after_apply = hashlib.sha256(mutating_npm.read_bytes()).hexdigest()

            self.assertFalse(install_marker.exists())

        self.assertEqual(identity_after_apply, identity_before_apply)
        self.assertEqual(result.returncode, 40, result.stderr)
        self.assertIn("npm metadata query failed", result.stderr)

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
        self.assertEqual(
            result.stderr.strip(),
            "SelfWorkFlow: ACL security verification failed.",
        )

    def test_apply_redacts_missing_sensitive_icacls_path(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            local_app_data = temporary_root / "LocalAppData"
            sensitive_name = "super-secret"
            missing_icacls = temporary_root / f"{sensitive_name}-icacls.cmd"
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
                str(missing_icacls),
                environment={"FAKE_NPM_INSTALL_MARKER": str(install_marker)},
            )
            manifest_path = (
                Path(json.loads(discover.stdout)["bootstrapRoot"])
                / "bootstrap-tool-manifest.json"
            )
            persisted_bytes = b"".join(
                path.read_bytes()
                for path in temporary_root.rglob("*")
                if path.is_file()
            )

            self.assertFalse(install_marker.exists())
            self.assertFalse(manifest_path.exists())

        self.assertEqual(result.returncode, 48)
        self.assertEqual(
            result.stderr.strip(),
            "SelfWorkFlow: ACL security verification failed.",
        )
        self.assertNotIn(sensitive_name, result.stdout)
        self.assertNotIn(sensitive_name, result.stderr)
        self.assertNotIn(sensitive_name.encode("utf-8"), persisted_bytes)

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
        self.assertEqual(
            result.stderr.strip(),
            "SelfWorkFlow: ACL security verification failed.",
        )

    def test_apply_locks_new_bootstrap_root_before_icacls_command(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            local_app_data = temporary_root / "LocalAppData"
            swapping_icacls = temporary_root / "swap-icacls.cmd"
            _write_reparse_swapping_icacls(swapping_icacls)
            backup_root = temporary_root / "bootstrap-root-backup"
            junction_target = temporary_root / "junction-target"
            junction_target.mkdir()
            install_marker = temporary_root / "npm-install-called"
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
            )
            plan = json.loads(discover.stdout)
            bootstrap_root = Path(plan["bootstrapRoot"])

            result = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmPlanHash",
                plan["planHash"],
                "-NpmCommand",
                str(FAKE_NPM),
                "-IcaclsCommand",
                str(swapping_icacls),
                environment={
                    "FAKE_ICACLS_BACKUP": str(backup_root),
                    "FAKE_ICACLS_TARGET": str(junction_target),
                    "FAKE_NPM_INSTALL_MARKER": str(install_marker),
                },
            )

            replacement_succeeded = backup_root.exists()
            install_was_called = install_marker.exists()
            _remove_junction_if_present(bootstrap_root)
            if backup_root.exists() and not bootstrap_root.exists():
                backup_root.rename(bootstrap_root)

            self.assertFalse(replacement_succeeded)
            self.assertFalse(install_was_called)

        self.assertEqual(result.returncode, 48, result.stderr)
        self.assertIn("ACL security verification failed", result.stderr)

    def test_apply_stops_when_npm_install_fails(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            local_app_data = temporary_root / "LocalAppData"
            install_marker = temporary_root / "npm-install-called"
            _, plan = _discover_plan(local_app_data)
            result = _apply_plan(
                local_app_data,
                plan,
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
            _, plan = _discover_plan(local_app_data)
            result = _apply_plan(
                local_app_data,
                plan,
                environment={"FAKE_NPM_SKIP_ARTIFACTS": "1"},
            )

        self.assertEqual(result.returncode, 50)
        self.assertIn("installed package metadata is missing", result.stderr)

    def test_apply_rejects_invalid_installed_json_with_stable_redacted_error(self):
        cases = (
            ("FAKE_NPM_PACKAGE_CASE", "malformed", 56, "package-super-secret"),
            ("FAKE_NPM_PACKAGE_CASE", "wrong-type", 56, None),
            ("FAKE_NPM_LOCK_CASE", "malformed", 57, "lock-super-secret"),
            ("FAKE_NPM_LOCK_CASE", "missing-entry", 57, None),
            ("FAKE_NPM_LOCK_CASE", "wrong-type", 57, None),
        )
        for variable, value, expected_code, sensitive_text in cases:
            with self.subTest(variable=variable, value=value):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    local_app_data = Path(temporary_directory) / "LocalAppData"
                    _, plan = _discover_plan(local_app_data)
                    result = _apply_plan(
                        local_app_data,
                        plan,
                        environment={variable: value},
                    )
                    manifest_path = Path(plan["sideEffects"]["manifestPath"])

                    self.assertFalse(manifest_path.exists())

                combined_output = result.stdout + result.stderr
                self.assertEqual(result.returncode, expected_code, combined_output)
                expected_message = (
                    "SelfWorkFlow: installed package metadata is invalid."
                    if expected_code == 56
                    else "SelfWorkFlow: package-lock metadata is invalid."
                )
                self.assertEqual(result.stderr.strip(), expected_message)
                if sensitive_text:
                    self.assertNotIn(sensitive_text, combined_output)

    def test_apply_rejects_installed_version_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            _, plan = _discover_plan(local_app_data)
            result = _apply_plan(
                local_app_data,
                plan,
                environment={"FAKE_NPM_INSTALLED_VERSION": "9.9.9"},
            )

        self.assertEqual(result.returncode, 51)
        self.assertIn("installed package version does not match", result.stderr)

    def test_apply_rejects_installed_integrity_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            _, plan = _discover_plan(local_app_data)
            result = _apply_plan(
                local_app_data,
                plan,
                environment={"FAKE_NPM_INSTALLED_INTEGRITY": "sha512-drifted"},
            )

        self.assertEqual(result.returncode, 52)
        self.assertIn("installed package integrity does not match", result.stderr)

    def test_apply_rejects_missing_codex_cli_shim(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            _, plan = _discover_plan(local_app_data)
            result = _apply_plan(
                local_app_data,
                plan,
                environment={"FAKE_NPM_SKIP_CLI": "1"},
            )

        self.assertEqual(result.returncode, 53)
        self.assertIn("installed Codex CLI shim is missing", result.stderr)

    def test_apply_stops_when_codex_cli_version_command_fails(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            _, plan = _discover_plan(local_app_data)
            result = _apply_plan(
                local_app_data,
                plan,
                environment={"FAKE_NPM_CLI_EXIT_CODE": "7"},
            )

        self.assertEqual(result.returncode, 54)
        self.assertIn("Codex CLI version command failed with exit code 7", result.stderr)

    def test_apply_rejects_noncanonical_codex_cli_version_output(self):
        cases = (
            ({"FAKE_NPM_CLI_EMPTY": "1"}, None),
            ({"FAKE_NPM_CLI_SECOND_LINE": "stdout-sensitive-extra"}, "stdout-sensitive-extra"),
            ({"FAKE_NPM_CLI_STDERR": "stderr-sensitive-extra"}, "stderr-sensitive-extra"),
            ({"FAKE_NPM_CLI_VERSION_OUTPUT": "codex-cli version 1.2.3"}, None),
            ({"FAKE_NPM_CLI_VERSION_OUTPUT": "codex-cli 1.2.3-01"}, None),
            ({"FAKE_NPM_CLI_VERSION_OUTPUT": "codex-cli 9.9.9"}, None),
        )
        for cli_environment, sensitive_text in cases:
            with self.subTest(environment=cli_environment):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    local_app_data = Path(temporary_directory) / "LocalAppData"
                    _, plan = _discover_plan(local_app_data)
                    result = _apply_plan(
                        local_app_data,
                        plan,
                        environment=cli_environment,
                    )
                    manifest_path = Path(plan["sideEffects"]["manifestPath"])

                    self.assertFalse(manifest_path.exists())

                combined_output = result.stdout + result.stderr
                self.assertEqual(result.returncode, 55, combined_output)
                self.assertEqual(
                    result.stderr.strip(),
                    "SelfWorkFlow: Codex CLI version verification failed.",
                )
                if sensitive_text:
                    self.assertNotIn(sensitive_text, combined_output)

    def test_manifest_semantics_rejects_noncanonical_or_outside_root(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            local_app_data = temporary_root / "LocalAppData"
            _, plan = _discover_plan(local_app_data)
            apply_result = _apply_plan(local_app_data, plan)
            manifest_path = Path(plan["sideEffects"]["manifestPath"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            valid_result = _validate_manifest_candidate(
                local_app_data, plan, manifest
            )
            invalid_results = []
            for unsafe_root in (
                r"C:\..\Windows",
                str(temporary_root / "outside-bootstrap-boundary"),
                str(Path(plan["bootstrapRoot"]) / "inside-boundary-drift"),
            ):
                candidate = json.loads(json.dumps(manifest))
                candidate["bootstrapRoot"] = unsafe_root
                invalid_results.append(
                    _validate_manifest_candidate(local_app_data, plan, candidate)
                )

        self.assertEqual(apply_result.returncode, 0, apply_result.stderr)
        self.assertEqual(valid_result.returncode, 0, valid_result.stderr)
        for result in invalid_results:
            self.assertEqual(result.returncode, 58, result.stderr)
            self.assertEqual(
                result.stderr.strip(),
                "SelfWorkFlow: manifest semantic validation failed.",
            )

    def test_manifest_semantics_rejects_everyone_dacl(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            _, plan = _discover_plan(local_app_data)
            apply_result = _apply_plan(local_app_data, plan)
            manifest = json.loads(
                Path(plan["sideEffects"]["manifestPath"]).read_text(encoding="utf-8")
            )
            candidate = json.loads(json.dumps(manifest))
            candidate["daclSddl"] = "D:P(A;;FA;;;WD)"
            result = _validate_manifest_candidate(
                local_app_data,
                plan,
                candidate,
                expected_sddl=manifest["daclSddl"],
            )

        self.assertEqual(apply_result.returncode, 0, apply_result.stderr)
        self.assertEqual(result.returncode, 58, result.stderr)
        self.assertEqual(
            result.stderr.strip(),
            "SelfWorkFlow: manifest semantic validation failed.",
        )

    def test_manifest_semantics_rejects_version_drift(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            _, plan = _discover_plan(local_app_data)
            apply_result = _apply_plan(local_app_data, plan)
            manifest = json.loads(
                Path(plan["sideEffects"]["manifestPath"]).read_text(encoding="utf-8")
            )
            invalid_results = []
            for field_path, unsafe_value in (
                (("cliVersion",), "1.2.3 extra-sensitive-text"),
                (("package", "version"), "9.9.9"),
            ):
                candidate = json.loads(json.dumps(manifest))
                target = candidate
                for field in field_path[:-1]:
                    target = target[field]
                target[field_path[-1]] = unsafe_value
                invalid_results.append(
                    _validate_manifest_candidate(
                        local_app_data,
                        plan,
                        candidate,
                        expected_sddl=manifest["daclSddl"],
                    )
                )

        self.assertEqual(apply_result.returncode, 0, apply_result.stderr)
        for result in invalid_results:
            self.assertEqual(result.returncode, 58, result.stderr)
            self.assertNotIn("extra-sensitive-text", result.stderr)

    def test_manifest_semantics_rejects_numeric_prerelease_leading_zero(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            _, plan = _discover_plan(local_app_data)
            apply_result = _apply_plan(local_app_data, plan)
            manifest = json.loads(
                Path(plan["sideEffects"]["manifestPath"]).read_text(encoding="utf-8")
            )
            invalid_plan = json.loads(json.dumps(plan))
            invalid_plan["package"]["version"] = "1.2.3-01"
            invalid_plan["execution"]["installArguments"][-1] = (
                "@openai/codex@1.2.3-01"
            )
            invalid_plan["planHash"] = _compute_plan_hash(invalid_plan)
            candidate = json.loads(json.dumps(manifest))
            candidate["package"]["version"] = "1.2.3-01"
            candidate["cliVersion"] = "1.2.3-01"
            candidate["planHash"] = invalid_plan["planHash"]
            result = _validate_manifest_candidate(
                local_app_data,
                invalid_plan,
                candidate,
                expected_sddl=manifest["daclSddl"],
            )

        self.assertEqual(apply_result.returncode, 0, apply_result.stderr)
        self.assertEqual(result.returncode, 58, result.stderr)
        self.assertEqual(
            result.stderr.strip(),
            "SelfWorkFlow: manifest semantic validation failed.",
        )

    def test_manifest_semantics_rejects_hash_drift(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            _, plan = _discover_plan(local_app_data)
            apply_result = _apply_plan(local_app_data, plan)
            manifest = json.loads(
                Path(plan["sideEffects"]["manifestPath"]).read_text(encoding="utf-8")
            )
            invalid_results = []
            for field in ("packageTreeHash", "planHash"):
                candidate = json.loads(json.dumps(manifest))
                candidate[field] = (
                    "sha256:" + "f" * 64 if field == "packageTreeHash" else "f" * 64
                )
                invalid_results.append(
                    _validate_manifest_candidate(
                        local_app_data,
                        plan,
                        candidate,
                        expected_sddl=manifest["daclSddl"],
                    )
                )

        self.assertEqual(apply_result.returncode, 0, apply_result.stderr)
        for result in invalid_results:
            self.assertEqual(result.returncode, 58, result.stderr)
            self.assertEqual(
                result.stderr.strip(),
                "SelfWorkFlow: manifest semantic validation failed.",
            )

    def test_apply_validates_manifest_before_write(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            local_app_data = temporary_root / "LocalAppData"
            copied_script = temporary_root / "scripts" / BOOTSTRAP_SCRIPT.name
            copied_library = copied_script.parent / "lib" / MANIFEST_LIBRARY.name
            copied_library.parent.mkdir(parents=True)
            shutil.copy2(BOOTSTRAP_SCRIPT, copied_script)
            copied_library.write_text(
                MANIFEST_LIBRARY.read_text(encoding="utf-8")
                + "\nfunction Assert-SelfWorkflowBootstrapManifest {\n"
                + "    throw 'forced semantic validation failure'\n"
                + "}\n",
                encoding="utf-8",
            )
            discover = _run_bootstrap(
                local_app_data,
                "-Mode",
                "Discover",
                "-NpmCommand",
                str(FAKE_NPM),
                script=copied_script,
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
                script=copied_script,
            )
            manifest_path = Path(plan["sideEffects"]["manifestPath"])

            self.assertFalse(manifest_path.exists())

        self.assertEqual(discover.returncode, 0, discover.stderr)
        self.assertEqual(result.returncode, 58, result.stderr)
        self.assertEqual(
            result.stderr.strip(),
            "SelfWorkFlow: manifest semantic validation failed.",
        )

    def test_apply_writes_bound_credential_free_manifest(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            _, plan = _discover_plan(local_app_data)
            result = _apply_plan(local_app_data, plan)
            bootstrap_root = Path(plan["bootstrapRoot"])
            manifest_path = bootstrap_root / "bootstrap-tool-manifest.json"

            self.assertTrue(
                manifest_path.is_file(), result.stderr + result.stdout
            )
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
        self.assertEqual(manifest["cliVersion"], "1.2.3")
        self.assertEqual(manifest["planHash"], plan["planHash"])
        serialized_manifest = json.dumps(manifest, sort_keys=True).lower()
        for forbidden_word in ("password", "credential", "token", "_auth", "npmrc"):
            self.assertNotIn(forbidden_word, serialized_manifest)

    def test_generated_manifest_conforms_to_json_schema(self):
        from jsonschema import Draft202012Validator

        with tempfile.TemporaryDirectory() as temporary_directory:
            local_app_data = Path(temporary_directory) / "LocalAppData"
            _, plan = _discover_plan(local_app_data)
            apply_result = _apply_plan(local_app_data, plan)
            manifest_path = Path(plan["bootstrapRoot"]) / "bootstrap-tool-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            schema = json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))

        self.assertEqual(apply_result.returncode, 0, apply_result.stderr)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(manifest)


if __name__ == "__main__":
    unittest.main()
