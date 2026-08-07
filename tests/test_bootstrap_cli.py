import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_SCRIPT = REPOSITORY_ROOT / "scripts" / "bootstrap-codex-cli.ps1"
MANIFEST_LIBRARY = REPOSITORY_ROOT / "scripts" / "lib" / "bootstrap-manifest.ps1"
EXECUTION_LIBRARY = REPOSITORY_ROOT / "scripts" / "lib" / "bootstrap-execution.ps1"
FAKE_NPM_CLI = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "bootstrap" / "fake-npm-cli.js"
)
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
            "SELFWORKFLOW_EXECUTION_LIBRARY": str(EXECUTION_LIBRARY),
            "SELFWORKFLOW_BOOTSTRAP_SCRIPT": str(BOOTSTRAP_SCRIPT),
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
    $Tokens = $null
    $Errors = $null
    $Ast = [Management.Automation.Language.Parser]::ParseFile(
        $env:SELFWORKFLOW_BOOTSTRAP_SCRIPT, [ref]$Tokens, [ref]$Errors
    )
    $Needed = @(
        "Assert-SelfWorkflowExactProperties", "Assert-SelfWorkflowPlanV2Shape",
        "ConvertTo-SelfWorkflowCanonicalValue", "ConvertTo-SelfWorkflowCanonicalJson",
        "Get-SelfWorkflowSha256Text", "Get-SelfWorkflowPlanHash"
    )
    foreach ($Definition in @($Ast.FindAll({
        param($Node)
        $Node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $Node.Name -in $Needed
    }, $true))) {
        . ([scriptblock]::Create($Definition.Extent.Text))
    }
    . $env:SELFWORKFLOW_EXECUTION_LIBRARY
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
    owner = $Acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
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


def _compute_v2_plan_hash(plan):
    plan_data = {key: value for key, value in plan.items() if key != "planHash"}
    serialized = json.dumps(
        plan_data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _compute_package_tree_hash(root):
    inventory = []
    paths = [root, *sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())]
    for path in paths:
        inventory.append(
            {
                "path": "." if path == root else path.relative_to(root).as_posix(),
                "type": "directory" if path.is_dir() else "file",
                "sha256": (
                    None
                    if path.is_dir()
                    else "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
                ),
            }
        )
    canonical = json.dumps(inventory, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


def _set_protected_current_user_acl(root):
    environment = os.environ.copy()
    environment["SELFWORKFLOW_ACL_ROOT"] = str(root)
    command = r"""
$ErrorActionPreference = "Stop"
$Root = [IO.Path]::GetFullPath($env:SELFWORKFLOW_ACL_ROOT)
$CurrentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$SystemSid = [Security.Principal.SecurityIdentifier]::new("S-1-5-18")
$Items = @((Get-Item -LiteralPath $Root)) + @(Get-ChildItem -LiteralPath $Root -Force -Recurse)
foreach ($Item in @($Items | Sort-Object { $_.FullName.Length } -Descending)) {
    if ($Item.PSIsContainer) {
        $Security = [Security.AccessControl.DirectorySecurity]::new()
        $Inheritance = (
            [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [Security.AccessControl.InheritanceFlags]::ObjectInherit
        )
    } else {
        $Security = [Security.AccessControl.FileSecurity]::new()
        $Inheritance = [Security.AccessControl.InheritanceFlags]::None
    }
    $Security.SetOwner($CurrentSid)
    $Security.SetAccessRuleProtection($true, $false)
    foreach ($Sid in @($CurrentSid, $SystemSid)) {
        [void]$Security.AddAccessRule(
            [Security.AccessControl.FileSystemAccessRule]::new(
                $Sid,
                [Security.AccessControl.FileSystemRights]::FullControl,
                $Inheritance,
                [Security.AccessControl.PropagationFlags]::None,
                [Security.AccessControl.AccessControlType]::Allow
            )
        )
    }
    if ($Item.PSIsContainer) {
        [IO.Directory]::SetAccessControl($Item.FullName, $Security)
    } else {
        [IO.File]::SetAccessControl($Item.FullName, $Security)
    }
}
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


def _enable_acl_inheritance(path):
    environment = os.environ.copy()
    environment["SELFWORKFLOW_ACL_PATH"] = str(path)
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "$Acl=Get-Acl -LiteralPath $env:SELFWORKFLOW_ACL_PATH; "
            "$Acl.SetAccessRuleProtection($false,$true); "
            "Set-Acl -LiteralPath $env:SELFWORKFLOW_ACL_PATH -AclObject $Acl",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)


def _add_allow_acl(path, sid, rights):
    environment = os.environ.copy()
    environment.update(
        {
            "SELFWORKFLOW_ACL_PATH": str(path),
            "SELFWORKFLOW_ACL_SID": sid,
            "SELFWORKFLOW_ACL_RIGHTS": rights,
        }
    )
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "$Acl=Get-Acl -LiteralPath $env:SELFWORKFLOW_ACL_PATH; "
            "$Rule=[Security.AccessControl.FileSystemAccessRule]::new("
            "[Security.Principal.SecurityIdentifier]::new($env:SELFWORKFLOW_ACL_SID),"
            "$env:SELFWORKFLOW_ACL_RIGHTS,'ContainerInherit, ObjectInherit','None','Allow'); "
            "[void]$Acl.AddAccessRule($Rule); "
            "Set-Acl -LiteralPath $env:SELFWORKFLOW_ACL_PATH -AclObject $Acl",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)


def _remove_junction_if_present(path):
    if not os.path.lexists(path):
        return
    attributes = path.lstat().st_file_attributes
    if attributes & 0x400:
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "rmdir", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr)


def _run_with_rename_probes(
    command,
    environment,
    barrier,
    release,
    probes,
    *,
    stop_marker=None,
    child_barrier_stage=None,
):
    target_process = probe_process = None
    try:
        target_process = subprocess.Popen(
            command,
            cwd=REPOSITORY_ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        probe_environment = os.environ.copy()
        probe_environment.update(
            {
                "SELFWORKFLOW_TARGET_PID": str(target_process.pid),
                "SELFWORKFLOW_LOCK_BARRIER": str(barrier),
                "SELFWORKFLOW_LOCK_RELEASE": str(release),
                "SELFWORKFLOW_PROBE_COUNT": str(len(probes)),
                "SELFWORKFLOW_STOP_MARKER": str(stop_marker or ""),
                "SELFWORKFLOW_CHILD_BARRIER_STAGE": str(child_barrier_stage or ""),
            }
        )
        for index, probe in enumerate(probes):
            for field in ("target", "backup", "attempt", "success", "junction", "log"):
                probe_environment[f"SELFWORKFLOW_{field.upper()}_{index}"] = str(
                    probe.get(field, "")
                )
        probe_command = r"""
$ErrorActionPreference = "SilentlyContinue"
$TargetProcess = [Diagnostics.Process]::GetProcessById([int]$env:SELFWORKFLOW_TARGET_PID)
function Test-TargetRunning { return -not $TargetProcess.HasExited }
function Get-ProbeValue($Name, $Index) {
    return [Environment]::GetEnvironmentVariable("SELFWORKFLOW_${Name}_$Index")
}
while (-not [IO.File]::Exists($env:SELFWORKFLOW_LOCK_BARRIER)) {
    if (-not (Test-TargetRunning)) { exit 71 }
    Start-Sleep -Milliseconds 1
}
$ChildProcess = $null
$BarrierState = $null
if ($env:SELFWORKFLOW_CHILD_BARRIER_STAGE) {
    try {
        $BarrierState = Get-Content -LiteralPath $env:SELFWORKFLOW_LOCK_BARRIER -Raw | ConvertFrom-Json
        if ($BarrierState.stage -cne $env:SELFWORKFLOW_CHILD_BARRIER_STAGE) { exit 72 }
        $ChildProcess = [Diagnostics.Process]::GetProcessById([int]$BarrierState.pid)
    } catch { exit 72 }
}
function Test-ProbeWindowOpen {
    if ($null -ne $ChildProcess) {
        return (-not [IO.File]::Exists($env:SELFWORKFLOW_LOCK_RELEASE)) -and (-not $ChildProcess.HasExited)
    }
    return Test-TargetRunning
}
function Write-ProbeLog($Path, $Index, $Outcome) {
    if (-not $Path) { return }
    [pscustomobject]@{
        timestampUtc = [DateTime]::UtcNow.ToString("o")
        index = $Index
        stage = if ($null -ne $BarrierState) { $BarrierState.stage } else { "parent" }
        childPid = if ($null -ne $BarrierState) { [int]$BarrierState.pid } else { $null }
        releaseExists = [IO.File]::Exists($env:SELFWORKFLOW_LOCK_RELEASE)
        childRunning = if ($null -ne $ChildProcess) { -not $ChildProcess.HasExited } else { $null }
        outcome = $Outcome
    } | ConvertTo-Json -Compress | Add-Content -LiteralPath $Path
}
$Released = $false
while (Test-ProbeWindowOpen) {
    if ($env:SELFWORKFLOW_STOP_MARKER -and [IO.File]::Exists($env:SELFWORKFLOW_STOP_MARKER)) { break }
    for ($Index = 0; $Index -lt [int]$env:SELFWORKFLOW_PROBE_COUNT; $Index++) {
        $Target = Get-ProbeValue "TARGET" $Index
        $Backup = Get-ProbeValue "BACKUP" $Index
        $Attempt = Get-ProbeValue "ATTEMPT" $Index
        $Success = Get-ProbeValue "SUCCESS" $Index
        $Junction = Get-ProbeValue "JUNCTION" $Index
        $Log = Get-ProbeValue "LOG" $Index
        [IO.File]::WriteAllText($Attempt, "attempted")
        try {
            [IO.Directory]::Move($Target, $Backup)
            if ($Junction) {
                & cmd.exe /d /c mklink /J $Target $Junction *> $null
                if ($LASTEXITCODE -ne 0) { throw "junction failed" }
            } else {
                [IO.Directory]::Move($Backup, $Target)
            }
            if (Test-ProbeWindowOpen) {
                [IO.File]::WriteAllText($Success, "renamed")
                Write-ProbeLog $Log $Index "renamed"
            } else {
                Write-ProbeLog $Log $Index "renamed-after-window"
            }
        } catch {
            Write-ProbeLog $Log $Index "locked"
            if ([IO.Directory]::Exists($Backup) -and -not [IO.Directory]::Exists($Target)) {
                [IO.Directory]::Move($Backup, $Target)
            }
        }
    }
    if (-not $Released -and $env:SELFWORKFLOW_LOCK_RELEASE) {
        [IO.File]::WriteAllText($env:SELFWORKFLOW_LOCK_RELEASE, "release")
        $Released = $true
    }
    Start-Sleep -Milliseconds 1
}
"""
        probe_process = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-Command", probe_command],
            env=probe_environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = target_process.communicate(timeout=60)
        probe_stdout, probe_stderr = probe_process.communicate(timeout=10)
        return (
            subprocess.CompletedProcess(
                target_process.args, target_process.returncode, stdout, stderr
            ),
            subprocess.CompletedProcess(
                probe_process.args,
                probe_process.returncode,
                probe_stdout,
                probe_stderr,
            ),
        )
    finally:
        Path(release).write_text("release", encoding="utf-8")
        for process in (target_process, probe_process):
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=10)


class BootstrapConfirmedPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node_path = shutil.which("node.exe")
        if not node_path:
            raise AssertionError("node.exe is required for bootstrap fixture tests")
        cls._temporary_directory = tempfile.TemporaryDirectory()
        cls.temporary_root = Path(cls._temporary_directory.name)
        cls.local_app_data = cls.temporary_root / "LocalAppData"
        cls.toolchain_anchor = (
            cls.local_app_data / "SelfWorkFlow" / "bootstrap" / "toolchains"
        )
        cls.toolchain_root = cls.toolchain_anchor / "fake-node"
        cls.npm_cli = cls.toolchain_root / "node_modules" / "npm" / "bin" / "npm-cli.js"
        cls.npm_cli.parent.mkdir(parents=True)
        shutil.copy2(node_path, cls.toolchain_root / "node.exe")
        shutil.copy2(FAKE_NPM_CLI, cls.npm_cli)
        _set_protected_current_user_acl(cls.local_app_data)

    @classmethod
    def tearDownClass(cls):
        cls._temporary_directory.cleanup()

    def tearDown(self):
        default_root = self.local_app_data / "SelfWorkFlow" / "bootstrap" / "codex-cli"
        if default_root.is_dir() and not any(default_root.iterdir()):
            default_root.rmdir()

    def _discover_v2(self, *arguments):
        result = _run_bootstrap(
            self.local_app_data,
            "-Mode",
            "Discover",
            "-ToolchainRoot",
            str(self.toolchain_root),
            *arguments,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def _write_plan(self, plan, name="confirmed-plan.json"):
        plan_path = self.temporary_root / name
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        return plan_path

    def _run_with_shadowed_add_type(self, marker, *arguments):
        wrapper = self.temporary_root / "shadow-add-type.ps1"
        wrapper.write_text(
            r"""
function Add-Type {
    param([string]$TypeDefinition)
    [IO.File]::WriteAllText($env:SELFWORKFLOW_ADD_TYPE_MARKER, "called")
    throw "shadow Add-Type reached"
}
& $env:SELFWORKFLOW_BOOTSTRAP_TARGET @args
exit $LASTEXITCODE
""",
            encoding="utf-8",
        )
        return _run_bootstrap(
            self.local_app_data,
            *arguments,
            script=wrapper,
            environment={
                "SELFWORKFLOW_ADD_TYPE_MARKER": str(marker),
                "SELFWORKFLOW_BOOTSTRAP_TARGET": str(BOOTSTRAP_SCRIPT),
            },
        )

    def _assert_final_apply(self, plan, result):
        from jsonschema import Draft202012Validator

        self.assertEqual(result.returncode, 0, result.stderr)
        bootstrap_root = Path(plan["bootstrapRoot"])
        manifest_path = Path(plan["sideEffects"]["manifestPath"])
        response = json.loads(result.stdout)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        schema = json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(manifest)
        semantic = _validate_manifest_candidate(self.local_app_data, plan, manifest)
        self.assertEqual(semantic.returncode, 0, semantic.stderr)
        self.assertEqual(response, {"manifestPath": str(manifest_path), "manifest": manifest})
        self.assertEqual(manifest["cliVersionVerification"], "not-run")

        invocation_log = Path(plan["sideEffects"]["cachePath"]) / "fake-npm-invocations.jsonl"
        invocations = [
            json.loads(line)
            for line in invocation_log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual([entry["command"] for entry in invocations], ["install"])
        self.assertFalse(list(bootstrap_root.rglob("*.executed")))

        acl = _read_directory_acl(bootstrap_root)
        self.assertTrue(acl["protected"])
        self.assertEqual(
            {rule["sid"] for rule in acl["rules"]},
            {acl["currentSid"], "S-1-5-18"},
        )
        self.assertEqual(len(acl["rules"]), 2)
        return {"manifest": manifest, "invocations": invocations, "acl": acl}

    def _apply_install_control(self, control, name):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        control_path.write_text(json.dumps(control), encoding="utf-8")
        _set_protected_current_user_acl(self.local_app_data)
        bootstrap_root = None
        try:
            plan = self._discover_v2()
            plan_path = self._write_plan(plan, f"{name}-plan.json")
            bootstrap_root = Path(plan["bootstrapRoot"])
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmedPlanPath",
                str(plan_path),
                "-ConfirmPlanHash",
                plan["planHash"],
            )
            return result, {
                "codexMarkers": list(bootstrap_root.rglob("*.executed")),
                "formalManifestExists": Path(
                    plan["sideEffects"]["manifestPath"]
                ).exists(),
                "temporaryManifests": list(bootstrap_root.glob("*.tmp")),
            }
        finally:
            control_path.unlink(missing_ok=True)
            if bootstrap_root and bootstrap_root.exists():
                shutil.rmtree(bootstrap_root)

    def _apply_with_acl_corruptor(self, mode, name, bootstrap_root=None):
        bootstrap_root = bootstrap_root or (
            self.local_app_data / "SelfWorkFlow" / "bootstrap" / "codex-cli"
        )
        plan = self._discover_v2("-BootstrapRoot", str(bootstrap_root))
        plan_path = self._write_plan(plan, f"{name}-plan.json")
        marker = self.temporary_root / f"{name}-acl-changed"
        stop = self.temporary_root / f"{name}-stop"
        backup_root = Path(str(bootstrap_root) + "-moved")
        environment = os.environ.copy()
        environment.update(
            {
                "SELFWORKFLOW_ACL_TARGET": str(bootstrap_root),
                "SELFWORKFLOW_ACL_MODE": mode,
                "SELFWORKFLOW_ACL_MARKER": str(marker),
                "SELFWORKFLOW_ACL_STOP": str(stop),
                "SELFWORKFLOW_ACL_BACKUP": str(backup_root),
            }
        )
        command = r"""
$ErrorActionPreference = "SilentlyContinue"
$Target = $env:SELFWORKFLOW_ACL_TARGET
while (-not (Test-Path -LiteralPath $Target) -and -not (Test-Path -LiteralPath $env:SELFWORKFLOW_ACL_STOP)) { Start-Sleep -Milliseconds 1 }
while (-not (Test-Path -LiteralPath $env:SELFWORKFLOW_ACL_STOP)) {
    $Acl = Get-Acl -LiteralPath $Target
    if ($env:SELFWORKFLOW_ACL_MODE -in @("reread", "rename")) {
        $Rules = @($Acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
        if (-not $Acl.AreAccessRulesProtected -or $Rules.Count -ne 2) { continue }
    }
    if ($env:SELFWORKFLOW_ACL_MODE -eq "rename") {
        [IO.Directory]::Move($Target, $env:SELFWORKFLOW_ACL_BACKUP)
        [IO.File]::WriteAllText($env:SELFWORKFLOW_ACL_MARKER, "changed")
        break
    }
    if ($env:SELFWORKFLOW_ACL_MODE -eq "inheritance") {
        $Acl.SetAccessRuleProtection($false, $true)
    } else {
        $Sid = if ($env:SELFWORKFLOW_ACL_MODE -eq "everyone") { "S-1-1-0" } else { "S-1-5-32-545" }
        $Rights = if ($env:SELFWORKFLOW_ACL_MODE -eq "everyone") { "FullControl" } else { "ReadAndExecute" }
        $Rule = [Security.AccessControl.FileSystemAccessRule]::new(
            [Security.Principal.SecurityIdentifier]::new($Sid), $Rights,
            "ContainerInherit, ObjectInherit", "None", "Allow")
        [void]$Acl.AddAccessRule($Rule)
    }
    Set-Acl -LiteralPath $Target -AclObject $Acl
    [IO.File]::WriteAllText($env:SELFWORKFLOW_ACL_MARKER, "changed")
}
"""
        corruptor = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-Command", command],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmedPlanPath",
                str(plan_path),
                "-ConfirmPlanHash",
                plan["planHash"],
            )
            changed = marker.exists()
            manifest_exists = Path(plan["sideEffects"]["manifestPath"]).exists()
        finally:
            stop.write_text("stop", encoding="utf-8")
            corruptor.wait(timeout=10)
            if bootstrap_root.exists():
                shutil.rmtree(bootstrap_root)
            if backup_root.exists():
                shutil.rmtree(backup_root)
            marker.unlink(missing_ok=True)
            stop.unlink(missing_ok=True)
        return result, changed, manifest_exists

    def _assert_removed_parameter_fails_without_side_effects(self, parameter, mode):
        secret = f"{parameter}-super-secret"
        bootstrap_root = (
            self.local_app_data
            / "SelfWorkFlow"
            / "bootstrap"
            / f"removed-{parameter.lower()}"
        )
        node_marker = self.temporary_root / f"removed-{parameter.lower()}-node-marker"
        before = _snapshot_tree(self.local_app_data)
        result = _run_bootstrap(
            self.local_app_data,
            "-Mode",
            mode,
            f"-{parameter}",
            secret,
            "-BootstrapRoot",
            str(bootstrap_root),
        )

        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, combined)
        self.assertIn("NamedParameterNotFound", combined)
        self.assertIn(parameter, combined)
        self.assertNotIn(secret, combined)
        self.assertFalse(node_marker.exists())
        self.assertFalse(bootstrap_root.exists())
        self.assertFalse((bootstrap_root / "npm-cache").exists())
        self.assertFalse((bootstrap_root / "bootstrap-tool-manifest.json").exists())
        self.assertEqual(_snapshot_tree(self.local_app_data), before)

    def test_npm_command_parameter_is_removed_without_side_effects(self):
        self._assert_removed_parameter_fails_without_side_effects("NpmCommand", "Discover")

    def test_icacls_command_parameter_is_removed_without_side_effects(self):
        self._assert_removed_parameter_fails_without_side_effects("IcaclsCommand", "Apply")

    def test_discover_rejects_non_codex_package_before_metadata_or_side_effects(self):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        metadata_marker = self.temporary_root / "non-codex-metadata.marker"
        bootstrap_root = (
            self.local_app_data
            / "SelfWorkFlow"
            / "bootstrap"
            / "codex-cli"
            / "non-codex"
        )
        control_path.write_text(
            json.dumps({"metadataMarker": str(metadata_marker)}), encoding="utf-8"
        )
        try:
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Discover",
                "-ToolchainRoot",
                str(self.toolchain_root),
                "-BootstrapRoot",
                str(bootstrap_root),
                "-PackageName",
                "left-pad",
            )
        finally:
            control_path.unlink(missing_ok=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ValidateSet", result.stderr)
        self.assertIn("@openai/codex", result.stderr)
        self.assertFalse(metadata_marker.exists())
        self.assertFalse(bootstrap_root.exists())
        self.assertFalse((bootstrap_root / "npm-cache").exists())
        self.assertFalse((bootstrap_root / "bootstrap-tool-manifest.json").exists())

    def test_discover_rejects_toolchain_outside_anchor(self):
        outside_toolchain = self.temporary_root / "outside-toolchain"
        result = _run_bootstrap(
            self.local_app_data,
            "-Mode",
            "Discover",
            "-ToolchainRoot",
            str(outside_toolchain),
        )

        self.assertEqual(result.returncode, 59, result.stderr)
        self.assertEqual(
            result.stderr.strip(),
            "SelfWorkFlow: toolchain security verification failed.",
        )

    def test_discover_emits_complete_plan_v2_from_toolchain(self):
        secret = "batch1-plan-super-secret"
        environment = {
            "NODE_OPTIONS": secret,
            "NPM_TOKEN": secret,
            "HTTPS_PROXY": f"https://{secret}.invalid/",
        }
        result = _run_bootstrap(
            self.local_app_data,
            "-Mode",
            "Discover",
            "-ToolchainRoot",
            str(self.toolchain_root),
            environment=environment,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        bootstrap_root = plan["bootstrapRoot"]
        registry = "https://registry.npmjs.org/"
        trusted_cwd = str(Path(os.environ["SystemRoot"]) / "System32")
        node_path = plan["execution"]["node"]["path"]
        npm_cli_path = plan["execution"]["npmCli"]["path"]
        metadata_arguments = [
            npm_cli_path, "view", "@openai/codex@latest", "version",
            "dist.integrity", "--json", "--registry", registry,
            "--userconfig", "NUL", "--globalconfig", "NUL", "--cache", "NUL",
            "--ignore-scripts", "--no-audit", "--no-fund",
        ]
        install_cache = str(Path(bootstrap_root) / "npm-cache")
        install_arguments = [
            npm_cli_path, "install", "--prefix", bootstrap_root,
            "--package-lock=true", "--save-exact", "--registry", registry,
            "--userconfig", "NUL", "--globalconfig", "NUL", "--cache",
            install_cache, "--ignore-scripts", "--no-audit", "--no-fund",
            "@openai/codex@1.2.3",
        ]

        self.assertEqual(
            set(plan),
            {
                "planSchemaVersion", "bootstrapRoot", "package", "execution",
                "security", "sideEffects", "unverified", "planHash",
            },
        )
        self.assertEqual(plan["planSchemaVersion"], 2)
        self.assertTrue(
            os.path.samefile(Path(bootstrap_root).parents[2], self.local_app_data)
        )
        self.assertEqual(
            plan["package"],
            {
                "name": "@openai/codex",
                "requestedVersion": "latest",
                "version": "1.2.3",
                "integrity": "sha512-U2VsZldvcmtGbG93RmFrZUludGVncml0eQ==",
            },
        )
        execution = plan["execution"]
        self.assertEqual(
            set(execution),
            {
                "registry", "trustedCwd", "node", "npmCli", "toolchain",
                "metadataArguments", "installArguments", "metadataEnvironment",
                "installEnvironment",
            },
        )
        self.assertEqual(execution["registry"], registry)
        self.assertEqual(execution["trustedCwd"], trusted_cwd)
        for field, path in (
            ("node", self.toolchain_root / "node.exe"),
            ("npmCli", self.npm_cli),
        ):
            self.assertTrue(os.path.samefile(execution[field]["path"], path))
            self.assertEqual(
                execution[field]["sha256"],
                f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
            )
        self.assertTrue(
            os.path.samefile(execution["toolchain"]["root"], self.toolchain_root)
        )
        inventory_json = json.dumps(
            execution["toolchain"]["inventory"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(
            execution["toolchain"]["treeHash"],
            f"sha256:{hashlib.sha256(inventory_json.encode('utf-8')).hexdigest()}",
        )
        self.assertEqual(execution["metadataArguments"], metadata_arguments)
        self.assertEqual(execution["installArguments"], install_arguments)
        common_environment = {
            "SystemRoot": os.environ["SystemRoot"],
            "WINDIR": os.environ["WINDIR"],
            "TEMP": os.environ["TEMP"],
            "TMP": os.environ["TMP"],
            "NPM_CONFIG_REGISTRY": registry,
            "NPM_CONFIG_USERCONFIG": "NUL",
            "NPM_CONFIG_GLOBALCONFIG": "NUL",
            "NPM_CONFIG_IGNORE_SCRIPTS": "true",
            "NPM_CONFIG_AUDIT": "false",
            "NPM_CONFIG_FUND": "false",
            "NPM_CONFIG_UPDATE_NOTIFIER": "false",
        }
        self.assertEqual(
            execution["metadataEnvironment"],
            {**common_environment, "NPM_CONFIG_CACHE": "NUL"},
        )
        self.assertEqual(
            execution["installEnvironment"],
            {**common_environment, "NPM_CONFIG_CACHE": install_cache},
        )
        acl = _read_directory_acl(self.local_app_data)
        self.assertTrue(
            os.path.samefile(plan["security"]["toolchainAnchor"], self.toolchain_anchor)
        )
        self.assertEqual(
            plan["security"],
            {
                "toolchainAnchor": plan["security"]["toolchainAnchor"],
                "expectedBootstrapDacl": {
                    "protected": True,
                    "principals": [acl["currentSid"], "S-1-5-18"],
                    "rights": "FullControl",
                },
            },
        )
        self.assertEqual(
            plan["sideEffects"],
            {
                "bootstrapRoot": bootstrap_root,
                "cachePath": install_cache,
                "manifestPath": str(Path(bootstrap_root) / "bootstrap-tool-manifest.json"),
                "uninstallBoundary": bootstrap_root,
            },
        )
        self.assertEqual(
            plan["unverified"],
            [
                "same-SID, SYSTEM, or OS-privileged mutation after final verification",
                "real npm, network, and Codex execution",
            ],
        )
        self.assertEqual(plan["planHash"], _compute_v2_plan_hash(plan))
        self.assertNotIn(secret, result.stdout + result.stderr)

    def test_discover_metadata_uses_bound_cwd_and_environment_without_secrets(self):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        metadata_log = self.temporary_root / "discover-metadata-invocation.json"
        control_path.write_text(
            json.dumps({"metadataLog": str(metadata_log)}), encoding="utf-8"
        )
        _set_protected_current_user_acl(self.local_app_data)
        secret = "discover-child-super-secret"
        hostile_environment = {
            "NODE_OPTIONS": "--require=must-not-run",
            "NODE_PATH": secret,
            "NODE_EXTRA_CA_CERTS": secret,
            "NPM_CONFIG_REGISTRY": f"https://{secret}.invalid/",
            "NPM_CONFIG_USERCONFIG": secret,
            "NPM_CONFIG_GLOBALCONFIG": secret,
            "HTTP_PROXY": f"http://{secret}.invalid/",
            "HTTPS_PROXY": f"http://{secret}.invalid/",
            "ALL_PROXY": f"http://{secret}.invalid/",
            "NO_PROXY": secret,
            "NODE_TLS_REJECT_UNAUTHORIZED": "0",
            "NPM_TOKEN": secret,
            "NODE_AUTH_TOKEN": secret,
            "USERPROFILE": str(self.temporary_root / "hostile-profile"),
        }
        try:
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Discover",
                "-ToolchainRoot",
                str(self.toolchain_root),
                environment=hostile_environment,
            )
            plan = json.loads(result.stdout)
            invocation = json.loads(metadata_log.read_text(encoding="utf-8"))
        finally:
            control_path.unlink(missing_ok=True)
            metadata_log.unlink(missing_ok=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(invocation["command"], "view")
        self.assertEqual(invocation["args"], plan["execution"]["metadataArguments"][1:])
        self.assertEqual(invocation["cwd"].casefold(), plan["execution"]["trustedCwd"].casefold())
        self.assertEqual(
            {key.upper(): value for key, value in invocation["environment"].items()},
            {
                key.upper(): value
                for key, value in plan["execution"]["metadataEnvironment"].items()
            },
        )
        persisted = result.stdout + result.stderr + json.dumps(invocation, sort_keys=True)
        self.assertNotIn(secret, persisted)
        self.assertFalse(Path(plan["sideEffects"]["cachePath"]).exists())
        self.assertFalse(Path(plan["sideEffects"]["manifestPath"]).exists())

    def test_discover_rejects_registry_userinfo_without_disclosure_or_side_effects(self):
        secret = "registry-userinfo-super-secret"
        bootstrap_root = (
            self.local_app_data / "SelfWorkFlow" / "bootstrap" / "codex-cli"
        )
        before = _snapshot_tree(self.local_app_data)
        result = _run_bootstrap(
            self.local_app_data,
            "-Mode",
            "Discover",
            "-ToolchainRoot",
            str(self.toolchain_root),
            "-Registry",
            f"https://user:{secret}@registry.npmjs.org/",
        )

        persisted = result.stdout + result.stderr
        self.assertEqual(result.returncode, 59, persisted)
        self.assertEqual(
            result.stderr.strip(),
            "SelfWorkFlow: toolchain security verification failed.",
        )
        self.assertNotIn(secret, persisted)
        self.assertFalse(bootstrap_root.exists())
        self.assertEqual(_snapshot_tree(self.local_app_data), before)

    def test_discover_preserves_existing_bootstrap_root_snapshot(self):
        bootstrap_root = (
            self.local_app_data
            / "SelfWorkFlow"
            / "bootstrap"
            / "codex-cli"
        )
        bootstrap_root.mkdir(parents=True)
        marker = bootstrap_root / "existing-marker.txt"
        marker.write_text("must remain unchanged", encoding="utf-8")
        _set_protected_current_user_acl(self.local_app_data)
        before = _snapshot_tree(bootstrap_root)
        try:
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Discover",
                "-ToolchainRoot",
                str(self.toolchain_root),
                "-BootstrapRoot",
                str(bootstrap_root),
            )
            after = _snapshot_tree(bootstrap_root)
        finally:
            shutil.rmtree(bootstrap_root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(after, before)

    def test_discover_metadata_failures_are_stable_and_redacted(self):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        secret = "metadata-super-secret"
        cases = (
            ("malformed", {"metadataRaw": "{" + secret}, 47,
             "SelfWorkFlow: npm metadata response is invalid."),
            ("array", {"metadataRaw": json.dumps([secret])}, 47,
             "SelfWorkFlow: npm metadata response is invalid."),
            ("missing", {"metadataRaw": json.dumps({"version": "1.2.3", "extra": secret})}, 47,
             "SelfWorkFlow: npm metadata response is invalid."),
            ("wrong-type", {"metadataRaw": json.dumps({"version": 123, "dist.integrity": secret})}, 47,
             "SelfWorkFlow: npm metadata response is invalid."),
            ("exit", {"metadataExitCode": 41, "stderr": secret}, 40,
             "SelfWorkFlow: npm metadata query failed with exit code 41."),
        )
        for name, control, expected_code, expected_error in cases:
            with self.subTest(name=name):
                control_path.write_text(json.dumps(control), encoding="utf-8")
                _set_protected_current_user_acl(self.local_app_data)
                try:
                    result = _run_bootstrap(
                        self.local_app_data,
                        "-Mode",
                        "Discover",
                        "-ToolchainRoot",
                        str(self.toolchain_root),
                    )
                finally:
                    control_path.unlink(missing_ok=True)

                combined = result.stdout + result.stderr
                self.assertEqual(result.returncode, expected_code, combined)
                self.assertEqual(result.stderr.strip(), expected_error)
                self.assertNotIn(secret, combined)
                bootstrap_root = (
                    self.local_app_data / "SelfWorkFlow" / "bootstrap" / "codex-cli"
                )
                self.assertFalse(bootstrap_root.exists())

    def test_discover_rejects_numeric_prerelease_leading_zero(self):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        control_path.write_text(
            json.dumps({"metadataVersion": "1.2.3-01"}), encoding="utf-8"
        )
        _set_protected_current_user_acl(self.local_app_data)
        try:
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Discover",
                "-ToolchainRoot",
                str(self.toolchain_root),
            )
        finally:
            control_path.unlink(missing_ok=True)

        self.assertEqual(result.returncode, 47, result.stdout + result.stderr)
        self.assertEqual(
            result.stderr.strip(), "SelfWorkFlow: npm metadata response is invalid."
        )

    def test_canonical_prerelease_build_survives_discover_apply_and_manifest(self):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        version = "1.2.3-alpha.1+build.01"
        control_path.write_text(
            json.dumps({"metadataVersion": version}), encoding="utf-8"
        )
        _set_protected_current_user_acl(self.local_app_data)
        bootstrap_root = None
        try:
            plan = self._discover_v2()
            plan_path = self._write_plan(plan, "canonical-semver-plan.json")
            bootstrap_root = Path(plan["bootstrapRoot"])
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmedPlanPath",
                str(plan_path),
                "-ConfirmPlanHash",
                plan["planHash"],
            )
            manifest = self._assert_final_apply(plan, result)["manifest"]
        finally:
            control_path.unlink(missing_ok=True)
            if bootstrap_root and bootstrap_root.exists():
                shutil.rmtree(bootstrap_root)

        self.assertEqual(plan["package"]["version"], version)
        self.assertEqual(manifest["package"]["version"], version)
        self.assertEqual(manifest["expectedCliVersion"], version)

    def test_manifest_semantics_rejects_internally_consistent_illegal_semver(self):
        plan = self._discover_v2()
        plan_path = self._write_plan(plan, "semantic-semver-plan.json")
        bootstrap_root = Path(plan["bootstrapRoot"])
        try:
            apply_result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmedPlanPath",
                str(plan_path),
                "-ConfirmPlanHash",
                plan["planHash"],
            )
            manifest = self._assert_final_apply(plan, apply_result)["manifest"]
            invalid_version = "1.2.3-01"
            invalid_plan = json.loads(json.dumps(plan))
            invalid_plan["package"]["version"] = invalid_version
            invalid_plan["execution"]["installArguments"][-1] = (
                f"@openai/codex@{invalid_version}"
            )
            invalid_plan["planHash"] = _compute_v2_plan_hash(invalid_plan)
            candidate = json.loads(json.dumps(manifest))
            candidate["package"]["version"] = invalid_version
            candidate["expectedCliVersion"] = invalid_version
            candidate["planHash"] = invalid_plan["planHash"]
            semantic = _validate_manifest_candidate(
                self.local_app_data,
                invalid_plan,
                candidate,
                expected_sddl=manifest["daclSddl"],
            )
        finally:
            if bootstrap_root.exists():
                shutil.rmtree(bootstrap_root)

        self.assertEqual(semantic.returncode, 58, semantic.stdout + semantic.stderr)
        self.assertEqual(
            semantic.stderr.strip(),
            "SelfWorkFlow: manifest semantic validation failed.",
        )

    def test_discover_rejects_bootstrap_root_outside_boundary_before_metadata(self):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        metadata_log = self.temporary_root / "outside-root-metadata.json"
        outside_root = self.temporary_root / "outside-bootstrap-boundary"
        control_path.write_text(
            json.dumps({"metadataLog": str(metadata_log)}), encoding="utf-8"
        )
        _set_protected_current_user_acl(self.local_app_data)
        try:
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Discover",
                "-ToolchainRoot",
                str(self.toolchain_root),
                "-BootstrapRoot",
                str(outside_root),
            )
            metadata_started = metadata_log.exists()
        finally:
            control_path.unlink(missing_ok=True)
            metadata_log.unlink(missing_ok=True)

        self.assertEqual(result.returncode, 43, result.stdout + result.stderr)
        self.assertEqual(
            result.stderr.strip(),
            "SelfWorkFlow: bootstrap path security verification failed.",
        )
        self.assertFalse(metadata_started)
        self.assertFalse(outside_root.exists())

    def test_discover_rejects_reparse_in_toolchain_anchor_chain(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            local_app_data = temporary_root / "LocalAppData"
            local_app_data.mkdir()
            junction_target = temporary_root / "junction-target"
            toolchain_root = junction_target / "bootstrap" / "toolchains" / "fake-node"
            npm_cli = toolchain_root / "node_modules" / "npm" / "bin" / "npm-cli.js"
            npm_cli.parent.mkdir(parents=True)
            shutil.copy2(self.toolchain_root / "node.exe", toolchain_root / "node.exe")
            shutil.copy2(FAKE_NPM_CLI, npm_cli)
            _set_protected_current_user_acl(local_app_data)
            _set_protected_current_user_acl(junction_target)
            junction = local_app_data / "SelfWorkFlow"
            link = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(junction_target)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(link.returncode, 0, link.stderr + link.stdout)
            try:
                result = _run_bootstrap(
                    local_app_data,
                    "-Mode",
                    "Discover",
                    "-ToolchainRoot",
                    str(local_app_data / "SelfWorkFlow" / "bootstrap" / "toolchains" / "fake-node"),
                )
            finally:
                _remove_junction_if_present(junction)

        self.assertEqual(result.returncode, 59, result.stdout + result.stderr)
        self.assertEqual(
            result.stderr.strip(),
            "SelfWorkFlow: toolchain security verification failed.",
        )

    def test_discover_rejects_unprotected_toolchain_anchor_before_metadata(self):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        metadata_marker = self.temporary_root / "unprotected-anchor-metadata.marker"
        control_path.write_text(
            json.dumps({"metadataMarker": str(metadata_marker)}), encoding="utf-8"
        )
        _set_protected_current_user_acl(self.local_app_data)
        _enable_acl_inheritance(self.toolchain_anchor)
        try:
            acl = _read_directory_acl(self.toolchain_anchor)
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Discover",
                "-ToolchainRoot",
                str(self.toolchain_root),
            )
        finally:
            _set_protected_current_user_acl(self.local_app_data)
            control_path.unlink(missing_ok=True)
            metadata_called = metadata_marker.exists()
            metadata_marker.unlink(missing_ok=True)

        self.assertFalse(acl["protected"])
        self.assertEqual(
            {rule["sid"] for rule in acl["rules"]},
            {acl["currentSid"], "S-1-5-18"},
        )
        self.assertEqual(result.returncode, 59, result.stderr)
        self.assertFalse(metadata_called)
        self.assertEqual(
            result.stderr.strip(),
            "SelfWorkFlow: toolchain security verification failed.",
        )

    def test_discover_holds_toolchain_and_ancestor_locks_through_metadata_child(self):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        barrier = self.temporary_root / "metadata-lock-barrier"
        release = self.temporary_root / "metadata-lock-release"
        probes = [
            {
                "target": self.toolchain_root,
                "backup": Path(str(self.toolchain_root) + "-probe"),
                "attempt": self.temporary_root / "toolchain-rename-attempt",
                "success": self.temporary_root / "toolchain-rename-success",
                "log": self.temporary_root / "toolchain-rename.jsonl",
            },
            {
                "target": self.toolchain_anchor.parent,
                "backup": Path(str(self.toolchain_anchor.parent) + "-probe"),
                "attempt": self.temporary_root / "toolchain-ancestor-rename-attempt",
                "success": self.temporary_root / "toolchain-ancestor-rename-success",
                "log": self.temporary_root / "toolchain-ancestor-rename.jsonl",
            },
        ]
        control_path.write_text(
            json.dumps(
                {"metadataBarrier": str(barrier), "metadataRelease": str(release)}
            ),
            encoding="utf-8",
        )
        _set_protected_current_user_acl(self.local_app_data)
        environment = os.environ.copy()
        environment["LOCALAPPDATA"] = str(self.local_app_data)
        try:
            result, probe_result = _run_with_rename_probes(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(BOOTSTRAP_SCRIPT),
                    "-Mode",
                    "Discover",
                    "-ToolchainRoot",
                    str(self.toolchain_root),
                ],
                environment,
                barrier,
                release,
                probes,
                child_barrier_stage="metadata",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                probe_result.returncode, 0, probe_result.stdout + probe_result.stderr
            )
            json.loads(result.stdout)
            barrier_state = json.loads(barrier.read_text(encoding="utf-8"))
            self.assertEqual(barrier_state["stage"], "metadata")
            self.assertIsInstance(barrier_state["pid"], int)
            for probe in probes:
                self.assertTrue(probe["attempt"].exists())
                self.assertFalse(probe["success"].exists())
                events = [
                    json.loads(line)
                    for line in probe["log"].read_text(encoding="utf-8").splitlines()
                ]
                self.assertTrue(events)
                self.assertEqual({event["stage"] for event in events}, {"metadata"})
                self.assertEqual(
                    {event["childPid"] for event in events}, {barrier_state["pid"]}
                )
                self.assertTrue(all(event["childRunning"] for event in events))
                self.assertTrue(all(not event["releaseExists"] for event in events))
                after_exit = Path(str(probe["target"]) + "-after-exit")
                probe["target"].rename(after_exit)
                after_exit.rename(probe["target"])
        finally:
            control_path.unlink(missing_ok=True)
            for path in (barrier, release):
                path.unlink(missing_ok=True)
            for probe in probes:
                probe["attempt"].unlink(missing_ok=True)
                probe["success"].unlink(missing_ok=True)
                probe["log"].unlink(missing_ok=True)
                if probe["backup"].exists() and not probe["target"].exists():
                    probe["backup"].rename(probe["target"])

    def test_discover_locks_npm_entry_through_metadata_child(self):
        original_entry = self.npm_cli.read_bytes()
        try:
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Discover",
                "-ToolchainRoot",
                str(self.toolchain_root),
                "-PackageVersion",
                "mutate-entry",
            )
            entry_after = self.npm_cli.read_bytes()
        finally:
            self.npm_cli.write_bytes(original_entry)

        self.assertEqual(result.returncode, 40, result.stderr)
        self.assertEqual(entry_after, original_entry)
        self.assertIn("npm metadata query failed with exit code 76", result.stderr)

    def test_metadata_and_install_children_cannot_modify_locked_node(self):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        node_path = self.toolchain_root / "node.exe"
        original_node = node_path.read_bytes()
        for stage, control_field, expected_code, expected_error in (
            ("metadata", "mutateNodeOnMetadata", 40, "npm metadata query failed with exit code 76"),
            ("install", "mutateNodeOnInstall", 49, "npm install failed with exit code 76"),
        ):
            with self.subTest(stage=stage):
                control_path.write_text(
                    json.dumps({control_field: True}), encoding="utf-8"
                )
                _set_protected_current_user_acl(self.local_app_data)
                bootstrap_root = None
                try:
                    if stage == "metadata":
                        result = _run_bootstrap(
                            self.local_app_data,
                            "-Mode",
                            "Discover",
                            "-ToolchainRoot",
                            str(self.toolchain_root),
                        )
                    else:
                        plan = self._discover_v2()
                        plan_path = self._write_plan(plan, "node-install-lock-plan.json")
                        bootstrap_root = Path(plan["bootstrapRoot"])
                        result = _run_bootstrap(
                            self.local_app_data,
                            "-Mode",
                            "Apply",
                            "-ConfirmedPlanPath",
                            str(plan_path),
                            "-ConfirmPlanHash",
                            plan["planHash"],
                        )
                    node_after = node_path.read_bytes()
                finally:
                    node_path.write_bytes(original_node)
                    control_path.unlink(missing_ok=True)
                    if bootstrap_root and bootstrap_root.exists():
                        shutil.rmtree(bootstrap_root)

                self.assertEqual(result.returncode, expected_code, result.stderr)
                self.assertEqual(node_after, original_node)
                self.assertIn(expected_error, result.stderr)
                if bootstrap_root:
                    self.assertFalse(
                        (bootstrap_root / "bootstrap-tool-manifest.json").exists()
                    )

    def test_apply_plan_v2_six_state_gate_has_no_prevalidation_side_effects(self):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        cases = (
            ("missing-path", 45),
            ("missing-hash", 45),
            ("wrong-parameter-hash", 60),
            ("stale-content-hash", 60),
            ("rehashed-semantic-drift", 60),
            ("success", 0),
        )
        for name, expected_code in cases:
            with self.subTest(name=name):
                metadata_marker = self.temporary_root / f"{name}-metadata.marker"
                install_marker = self.temporary_root / f"{name}-install.marker"
                control_path.write_text(
                    json.dumps(
                        {
                            "metadataMarker": str(metadata_marker),
                            "installMarker": str(install_marker),
                        }
                    ),
                    encoding="utf-8",
                )
                _set_protected_current_user_acl(self.local_app_data)
                bootstrap_root = None
                try:
                    plan = self._discover_v2()
                    bootstrap_root = Path(plan["bootstrapRoot"])
                    self.assertTrue(metadata_marker.exists(), "Discover must run metadata")
                    metadata_marker.unlink()

                    candidate = json.loads(json.dumps(plan))
                    confirmed_hash = plan["planHash"]
                    if name == "stale-content-hash":
                        candidate["package"]["version"] = "9.9.9"
                    elif name == "rehashed-semantic-drift":
                        candidate["execution"]["installArguments"].append("--unsafe-drift")
                        candidate["planHash"] = _compute_v2_plan_hash(candidate)
                        confirmed_hash = candidate["planHash"]
                    plan_path = self._write_plan(candidate, f"{name}-plan.json")
                    arguments = ["-Mode", "Apply"]
                    if name != "missing-path":
                        arguments += ["-ConfirmedPlanPath", str(plan_path)]
                    if name != "missing-hash":
                        arguments += [
                            "-ConfirmPlanHash",
                            "0" * 64 if name == "wrong-parameter-hash" else confirmed_hash,
                        ]
                    result = _run_bootstrap(self.local_app_data, *arguments)

                    self.assertEqual(result.returncode, expected_code, result.stderr)
                    self.assertFalse(metadata_marker.exists(), "Apply must never run view")
                    if name == "success":
                        self.assertTrue(install_marker.exists())
                        self._assert_final_apply(plan, result)
                    else:
                        self.assertFalse(install_marker.exists())
                        self.assertFalse(bootstrap_root.exists())
                        self.assertFalse(Path(plan["sideEffects"]["cachePath"]).exists())
                        self.assertFalse(Path(plan["sideEffects"]["manifestPath"]).exists())
                finally:
                    control_path.unlink(missing_ok=True)
                    metadata_marker.unlink(missing_ok=True)
                    install_marker.unlink(missing_ok=True)
                    if bootstrap_root and bootstrap_root.exists():
                        shutil.rmtree(bootstrap_root)

    def test_apply_rejects_rehashed_unverified_semantic_drift_before_side_effects(self):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        install_marker = self.temporary_root / "unverified-drift-install.marker"
        control_path.write_text(
            json.dumps({"installMarker": str(install_marker)}), encoding="utf-8"
        )
        _set_protected_current_user_acl(self.local_app_data)
        bootstrap_root = None
        try:
            plan = self._discover_v2()
            candidate = json.loads(json.dumps(plan))
            candidate["unverified"] = [
                "all mutation races are verified safe",
                "real npm, network, and Codex execution is verified",
            ]
            candidate["planHash"] = _compute_v2_plan_hash(candidate)
            plan_path = self._write_plan(candidate, "unverified-drift-plan.json")
            bootstrap_root = Path(plan["bootstrapRoot"])

            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmedPlanPath",
                str(plan_path),
                "-ConfirmPlanHash",
                candidate["planHash"],
            )
            install_called = install_marker.exists()
            root_exists = bootstrap_root.exists()
            cache_exists = Path(plan["sideEffects"]["cachePath"]).exists()
            manifest_exists = Path(plan["sideEffects"]["manifestPath"]).exists()
        finally:
            control_path.unlink(missing_ok=True)
            install_marker.unlink(missing_ok=True)
            if bootstrap_root and bootstrap_root.exists():
                shutil.rmtree(bootstrap_root)

        self.assertEqual(result.returncode, 60, result.stderr)
        self.assertFalse(install_called)
        self.assertFalse(root_exists)
        self.assertFalse(cache_exists)
        self.assertFalse(manifest_exists)
        self.assertEqual(
            result.stderr.strip(),
            "SelfWorkFlow: confirmed plan validation failed.",
        )

    def test_apply_rejects_relative_confirmed_plan_before_external_process(self):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        metadata_marker = self.temporary_root / "relative-plan-metadata.marker"
        install_marker = self.temporary_root / "relative-plan-install.marker"
        control_path.write_text(
            json.dumps(
                {
                    "metadataMarker": str(metadata_marker),
                    "installMarker": str(install_marker),
                }
            ),
            encoding="utf-8",
        )
        _set_protected_current_user_acl(self.local_app_data)
        try:
            plan = self._discover_v2()
            metadata_marker.unlink()
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmedPlanPath",
                "relative-plan.json",
                "-ConfirmPlanHash",
                plan["planHash"],
            )
        finally:
            control_path.unlink(missing_ok=True)

        self.assertEqual(result.returncode, 60, result.stderr)
        self.assertFalse(metadata_marker.exists())
        self.assertFalse(install_marker.exists())
        self.assertEqual(
            result.stderr.strip(),
            "SelfWorkFlow: confirmed plan validation failed.",
        )

    def test_apply_rejects_wrong_typed_plan_with_recomputed_hash(self):
        plan = self._discover_v2()
        plan["execution"]["metadataArguments"] = "not-an-array"
        plan["planHash"] = _compute_v2_plan_hash(plan)
        plan_path = self._write_plan(plan, "wrong-type-plan.json")

        result = _run_bootstrap(
            self.local_app_data,
            "-Mode",
            "Apply",
            "-ConfirmedPlanPath",
            str(plan_path),
            "-ConfirmPlanHash",
            plan["planHash"],
        )

        self.assertEqual(result.returncode, 60, result.stderr)
        self.assertEqual(
            result.stderr.strip(),
            "SelfWorkFlow: confirmed plan validation failed.",
        )

    def test_apply_rejects_node_or_npm_identity_drift_without_side_effects(self):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        for identity, target in (
            ("node", self.toolchain_root / "node.exe"),
            ("npm", self.npm_cli),
        ):
            with self.subTest(identity=identity):
                metadata_marker = self.temporary_root / f"{identity}-drift-metadata.marker"
                install_marker = self.temporary_root / f"{identity}-drift-install.marker"
                control_path.write_text(
                    json.dumps(
                        {
                            "metadataMarker": str(metadata_marker),
                            "installMarker": str(install_marker),
                        }
                    ),
                    encoding="utf-8",
                )
                _set_protected_current_user_acl(self.local_app_data)
                original = target.read_bytes()
                try:
                    plan = self._discover_v2()
                    plan_path = self._write_plan(plan, f"{identity}-drift-plan.json")
                    metadata_marker.unlink()
                    target.write_bytes(original + b"identity-drift")
                    result = _run_bootstrap(
                        self.local_app_data,
                        "-Mode",
                        "Apply",
                        "-ConfirmedPlanPath",
                        str(plan_path),
                        "-ConfirmPlanHash",
                        plan["planHash"],
                    )
                    metadata_called = metadata_marker.exists()
                    install_called = install_marker.exists()
                finally:
                    target.write_bytes(original)
                    control_path.unlink(missing_ok=True)
                    metadata_marker.unlink(missing_ok=True)
                    install_marker.unlink(missing_ok=True)

                self.assertEqual(result.returncode, 59, result.stderr)
                self.assertFalse(metadata_called, "Apply must never run view")
                self.assertFalse(install_called)
                self.assertFalse(Path(plan["bootstrapRoot"]).exists())
                self.assertFalse(Path(plan["sideEffects"]["cachePath"]).exists())
                self.assertFalse(Path(plan["sideEffects"]["manifestPath"]).exists())
                self.assertEqual(
                    result.stderr.strip(),
                    "SelfWorkFlow: toolchain security verification failed.",
                )

    def test_plan_identity_gate_precedes_add_type(self):
        _set_protected_current_user_acl(self.local_app_data)
        plan = self._discover_v2()
        plan_path = self._write_plan(plan, "pre-add-type-plan.json")
        marker = self.temporary_root / "add-type.marker"
        valid_result = self._run_with_shadowed_add_type(
            marker,
            "-Mode",
            "Apply",
            "-ConfirmedPlanPath",
            str(plan_path),
            "-ConfirmPlanHash",
            plan["planHash"],
        )
        self.assertEqual(valid_result.returncode, 59, valid_result.stderr)
        self.assertTrue(marker.exists(), "oracle must observe a valid plan reaching Add-Type")

        mutations = (
            ("node", self.toolchain_root / "node.exe", b"identity-drift"),
            ("npm", self.npm_cli, b"identity-drift"),
            ("tree", self.toolchain_root / "tree-drift.txt", b"tree-drift"),
        )
        for identity, target, payload in mutations:
            with self.subTest(identity=identity):
                marker.unlink(missing_ok=True)
                original = target.read_bytes() if target.exists() else None
                try:
                    if original is None:
                        target.write_bytes(payload)
                    else:
                        target.write_bytes(original + payload)
                    _set_protected_current_user_acl(self.local_app_data)
                    result = self._run_with_shadowed_add_type(
                        marker,
                        "-Mode",
                        "Apply",
                        "-ConfirmedPlanPath",
                        str(plan_path),
                        "-ConfirmPlanHash",
                        plan["planHash"],
                    )
                finally:
                    if original is None:
                        target.unlink(missing_ok=True)
                    else:
                        target.write_bytes(original)
                    _set_protected_current_user_acl(self.local_app_data)

                self.assertEqual(result.returncode, 59, result.stderr)
                self.assertFalse(marker.exists(), "identity drift must fail before Add-Type")

    def test_apply_enforces_bootstrap_root_states_before_install(self):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        allowed_root = (
            self.local_app_data / "SelfWorkFlow" / "bootstrap" / "codex-cli"
        )
        cases = (
            ("file", 44, False),
            ("nonempty", 44, False),
            ("empty", 0, True),
            ("missing", 0, True),
        )
        for state, expected_code, expect_install in cases:
            with self.subTest(state=state):
                bootstrap_root = allowed_root / f"root-state-{state}"
                install_marker = self.temporary_root / f"root-state-{state}.install"
                control_path.write_text(
                    json.dumps({"installMarker": str(install_marker)}),
                    encoding="utf-8",
                )
                _set_protected_current_user_acl(self.local_app_data)
                try:
                    plan = self._discover_v2("-BootstrapRoot", str(bootstrap_root))
                    plan_path = self._write_plan(plan, f"root-state-{state}-plan.json")
                    if state == "file":
                        bootstrap_root.parent.mkdir(parents=True, exist_ok=True)
                        bootstrap_root.write_text("sentinel", encoding="utf-8")
                    elif state in {"nonempty", "empty"}:
                        bootstrap_root.mkdir(parents=True)
                        if state == "nonempty":
                            (bootstrap_root / "sentinel.txt").write_text(
                                "sentinel", encoding="utf-8"
                            )
                        else:
                            _set_protected_current_user_acl(bootstrap_root)

                    result = _run_bootstrap(
                        self.local_app_data,
                        "-Mode",
                        "Apply",
                        "-ConfirmedPlanPath",
                        str(plan_path),
                        "-ConfirmPlanHash",
                        plan["planHash"],
                    )

                    self.assertEqual(result.returncode, expected_code, result.stderr)
                    self.assertEqual(install_marker.exists(), expect_install)
                    if expect_install:
                        self._assert_final_apply(plan, result)
                    elif state == "file":
                        self.assertTrue(bootstrap_root.is_file())
                        self.assertEqual(
                            bootstrap_root.read_text(encoding="utf-8"), "sentinel"
                        )
                    else:
                        self.assertEqual(
                            [path.name for path in bootstrap_root.iterdir()],
                            ["sentinel.txt"],
                        )
                finally:
                    control_path.unlink(missing_ok=True)
                    install_marker.unlink(missing_ok=True)
                    if bootstrap_root.is_dir():
                        shutil.rmtree(bootstrap_root)
                    elif bootstrap_root.exists():
                        bootstrap_root.unlink()

    def test_apply_rejects_existing_empty_root_with_dangerous_acl_before_install(self):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        secret = "dangerous-root-super-secret"
        install_marker = self.temporary_root / f"{secret}.install"
        control_path.write_text(
            json.dumps({"installMarker": str(install_marker)}), encoding="utf-8"
        )
        _set_protected_current_user_acl(self.local_app_data)
        bootstrap_root = (
            self.local_app_data
            / "SelfWorkFlow"
            / "bootstrap"
            / "codex-cli"
            / "dangerous-empty-root"
        )
        try:
            plan = self._discover_v2("-BootstrapRoot", str(bootstrap_root))
            plan_path = self._write_plan(plan, "dangerous-empty-root-plan.json")
            bootstrap_root.mkdir(parents=True)
            _set_protected_current_user_acl(bootstrap_root)
            _add_allow_acl(bootstrap_root, "S-1-1-0", "FullControl")

            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmedPlanPath",
                str(plan_path),
                "-ConfirmPlanHash",
                plan["planHash"],
            )
            invocation_log = (
                Path(plan["sideEffects"]["cachePath"])
                / "fake-npm-invocations.jsonl"
            )
            manifest_path = Path(plan["sideEffects"]["manifestPath"])
            install_called = install_marker.exists()
            invocation_exists = invocation_log.exists()
            manifest_exists = manifest_path.exists()
            temporary_manifests = list(bootstrap_root.glob("*.tmp"))
        finally:
            control_path.unlink(missing_ok=True)
            install_marker.unlink(missing_ok=True)
            if bootstrap_root.exists():
                _set_protected_current_user_acl(bootstrap_root)
                shutil.rmtree(bootstrap_root)

        self.assertEqual(result.returncode, 44, result.stderr)
        self.assertFalse(install_called)
        self.assertFalse(invocation_exists)
        self.assertFalse(manifest_exists)
        self.assertFalse(temporary_manifests)
        self.assertNotIn(secret, result.stdout + result.stderr)
        self.assertEqual(
            result.stderr.strip(),
            "SelfWorkFlow: existing BootstrapRoot does not satisfy safe recovery conditions; only an empty directory is accepted.",
        )

    def test_apply_runs_only_install_with_bound_cwd_and_environment(self):
        plan = self._discover_v2()
        plan_path = self._write_plan(plan, "install-only-plan.json")
        bootstrap_root = Path(plan["bootstrapRoot"])
        invocation_log = Path(plan["sideEffects"]["cachePath"]) / "fake-npm-invocations.jsonl"
        secret = "super-secret-parent-value"
        injected_environment = {
            "NODE_OPTIONS": "--require=must-not-run",
            "NODE_PATH": secret,
            "NODE_EXTRA_CA_CERTS": secret,
            "NPM_CONFIG_REGISTRY": "https://attacker.invalid/",
            "NPM_CONFIG_USERCONFIG": secret,
            "HTTP_PROXY": f"http://{secret}@attacker.invalid/",
            "HTTPS_PROXY": f"http://{secret}@attacker.invalid/",
            "ALL_PROXY": f"http://{secret}@attacker.invalid/",
            "NO_PROXY": secret,
            "NODE_TLS_REJECT_UNAUTHORIZED": "0",
            "NPM_TOKEN": secret,
            "NODE_AUTH_TOKEN": secret,
            "USERPROFILE": str(self.temporary_root / "hostile-profile"),
        }
        try:
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmedPlanPath",
                str(plan_path),
                "-ConfirmPlanHash",
                plan["planHash"],
                environment=injected_environment,
            )
            inspection = self._assert_final_apply(plan, result)
            invocations = inspection["invocations"]
        finally:
            if bootstrap_root.exists():
                shutil.rmtree(bootstrap_root)

        self.assertEqual([entry["command"] for entry in invocations], ["install"])
        self.assertEqual(invocations[0]["cwd"], plan["execution"]["trustedCwd"])
        self.assertEqual(
            {key.upper(): value for key, value in invocations[0]["environment"].items()},
            {key.upper(): value for key, value in plan["execution"]["installEnvironment"].items()},
        )
        serialized_invocation = json.dumps(invocations, sort_keys=True)
        self.assertNotIn(secret, serialized_invocation)

    def test_apply_redacts_install_failure_output(self):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        secret = "install-super-secret"
        control_path.write_text(
            json.dumps({"installExitCode": 77, "stderr": secret}),
            encoding="utf-8",
        )
        _set_protected_current_user_acl(self.local_app_data)
        bootstrap_root = None
        try:
            plan = self._discover_v2()
            plan_path = self._write_plan(plan, "install-failure-plan.json")
            bootstrap_root = Path(plan["bootstrapRoot"])
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmedPlanPath",
                str(plan_path),
                "-ConfirmPlanHash",
                plan["planHash"],
            )
        finally:
            control_path.unlink(missing_ok=True)
            if bootstrap_root and bootstrap_root.exists():
                shutil.rmtree(bootstrap_root)

        self.assertEqual(result.returncode, 49)
        self.assertEqual(
            result.stderr.strip(),
            "SelfWorkFlow: npm install failed with exit code 77.",
        )
        self.assertNotIn(secret, result.stdout + result.stderr)

    def test_apply_holds_npm_entry_lock_until_install_child_exits(self):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        control_path.write_text(
            json.dumps({"mutateEntryOnInstall": True}),
            encoding="utf-8",
        )
        _set_protected_current_user_acl(self.local_app_data)
        original_entry = self.npm_cli.read_bytes()
        bootstrap_root = None
        try:
            plan = self._discover_v2()
            plan_path = self._write_plan(plan, "install-lock-plan.json")
            bootstrap_root = Path(plan["bootstrapRoot"])
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmedPlanPath",
                str(plan_path),
                "-ConfirmPlanHash",
                plan["planHash"],
            )
            entry_after = self.npm_cli.read_bytes()
        finally:
            self.npm_cli.write_bytes(original_entry)
            control_path.unlink(missing_ok=True)
            if bootstrap_root and bootstrap_root.exists():
                shutil.rmtree(bootstrap_root)

        self.assertEqual(result.returncode, 49, result.stderr)
        self.assertEqual(entry_after, original_entry)
        self.assertIn("npm install failed with exit code 76", result.stderr)

    def test_apply_rejects_invalid_install_artifacts_without_publication(self):
        integrity = "sha512-U2VsZldvcmtGbG93RmFrZUludGVncml0eQ=="
        valid_entry = {"name": "@openai/codex", "version": "1.2.3", "integrity": integrity}
        def lock(name="@openai/codex", version="1.2.3"):
            return json.dumps(
                {
                    "lockfileVersion": 3,
                    "packages": {
                        "node_modules/@openai/codex": {
                            "name": name,
                            "version": version,
                            "integrity": integrity,
                        }
                    },
                }
            )

        secrets = {
            "malformed-package": "package-json-super-secret",
            "malformed-lock": "package-lock-super-secret",
            "integrity": "integrity-super-secret",
        }
        cases = (
            ("missing-package", {"omitPackageJson": True}, None),
            ("missing-lock", {"omitPackageLock": True}, None),
            ("malformed-package", {"packageJsonRaw": "{" + secrets["malformed-package"]}, secrets["malformed-package"]),
            ("malformed-lock", {"packageLockRaw": "{" + secrets["malformed-lock"]}, secrets["malformed-lock"]),
            ("package-missing-version", {"packageJsonRaw": json.dumps({"name": "@openai/codex"})}, None),
            ("package-version-type", {"packageJsonRaw": json.dumps({"name": "@openai/codex", "version": 123})}, None),
            ("lock-missing-entry", {"packageLockRaw": json.dumps({"lockfileVersion": 3, "packages": {}})}, None),
            ("lock-packages-type", {"packageLockRaw": json.dumps({"lockfileVersion": 3, "packages": []})}, None),
            ("lock-version-type", {"packageLockRaw": json.dumps({"lockfileVersion": "3", "packages": {"node_modules/@openai/codex": valid_entry}})}, None),
            ("lock-entry-type", {"packageLockRaw": json.dumps({"lockfileVersion": 3, "packages": {"node_modules/@openai/codex": {**valid_entry, "version": 123}}})}, None),
            ("package-name-drift", {"packageJsonRaw": json.dumps({"name": "other", "version": "1.2.3"})}, None),
            ("package-version-drift", {"packageJsonRaw": json.dumps({"name": "@openai/codex", "version": "9.9.9"})}, None),
            ("lock-name-drift", {"packageLockRaw": lock(name="other")}, None),
            ("lock-version-drift", {"packageLockRaw": lock(version="9.9.9")}, None),
            ("integrity-drift", {"packageLockRaw": lock().replace(integrity, "sha512-" + secrets["integrity"])}, secrets["integrity"]),
            ("tree-reparse", {"createPackageReparse": True}, None),
        )
        for name, control, secret in cases:
            with self.subTest(name=name):
                result, observation = self._apply_install_control(control, name)
                self.assertEqual(result.returncode, 50, result.stderr)
                self.assertEqual(
                    result.stderr.strip(),
                    "SelfWorkFlow: installed package verification failed.",
                )
                self.assertFalse(observation["codexMarkers"])
                self.assertFalse(observation["formalManifestExists"])
                self.assertFalse(observation["temporaryManifests"])
                if secret:
                    self.assertNotIn(secret, result.stdout + result.stderr)

    def test_apply_rejects_package_tree_drift_during_verification(self):
        import ctypes

        control_path = self.npm_cli.parent / "fake-npm-control.json"
        control_path.write_text(
            json.dumps(
                {
                    "createTreeWindowFixture": True,
                    "packagePaddingBytes": 64 * 1024 * 1024,
                }
            ),
            encoding="utf-8",
        )
        _set_protected_current_user_acl(self.local_app_data)
        bootstrap_root = None
        mutation_observed = threading.Event()
        worker_errors = []

        def mutate_tree():
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            create_file = kernel32.CreateFileW
            create_file.argtypes = [
                ctypes.c_wchar_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_void_p,
            ]
            create_file.restype = ctypes.c_void_p
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [ctypes.c_void_p]
            invalid_handle = ctypes.c_void_p(-1).value
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if not package_json.exists() or not target.exists():
                    time.sleep(0.001)
                    continue
                handle = create_file(str(package_json), 0x40000000, 0, None, 3, 0x80, None)
                if handle == invalid_handle:
                    error = ctypes.get_last_error()
                    if error in {32, 33}:
                        with target.open("ab") as stream:
                            stream.write(b"-after")
                        mutation_observed.set()
                        return
                    worker_errors.append(f"CreateFileW failed: {error}")
                    return
                close_handle(handle)
                time.sleep(0.001)
            worker_errors.append("verification read lock was not observed")

        try:
            plan = self._discover_v2()
            plan_path = self._write_plan(plan, "package-tree-drift-plan.json")
            bootstrap_root = Path(plan["bootstrapRoot"])
            package_root = bootstrap_root / "node_modules" / "@openai" / "codex"
            package_json = package_root / "package.json"
            target = package_root / "zzz-drift.bin"
            worker = threading.Thread(target=mutate_tree)
            worker.start()
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmedPlanPath",
                str(plan_path),
                "-ConfirmPlanHash",
                plan["planHash"],
            )
            codex_markers = list(bootstrap_root.rglob("*.executed"))
            manifest_exists = Path(plan["sideEffects"]["manifestPath"]).exists()
            temporary_manifests = list(bootstrap_root.glob("*.tmp"))
        finally:
            if "worker" in locals():
                worker.join(timeout=10)
            control_path.unlink(missing_ok=True)
            if bootstrap_root.exists():
                shutil.rmtree(bootstrap_root)

        self.assertFalse(worker_errors)
        self.assertTrue(mutation_observed.is_set())
        self.assertEqual(result.returncode, 50, result.stderr)
        self.assertEqual(
            result.stderr.strip(),
            "SelfWorkFlow: installed package verification failed.",
        )
        self.assertFalse(codex_markers)
        self.assertFalse(manifest_exists)
        self.assertFalse(temporary_manifests)

    def test_apply_sets_and_rereads_exact_protected_bootstrap_acl(self):
        plan = self._discover_v2()
        plan_path = self._write_plan(plan, "bootstrap-acl-plan.json")
        bootstrap_root = Path(plan["bootstrapRoot"])
        try:
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmedPlanPath",
                str(plan_path),
                "-ConfirmPlanHash",
                plan["planHash"],
            )
            acl = self._assert_final_apply(plan, result)["acl"]
            manifest_exists = Path(plan["sideEffects"]["manifestPath"]).exists()
        finally:
            if bootstrap_root.exists():
                shutil.rmtree(bootstrap_root)

        self.assertTrue(acl["protected"])
        self.assertEqual({rule["sid"] for rule in acl["rules"]}, {acl["currentSid"], "S-1-5-18"})
        self.assertEqual(len(acl["rules"]), 2)
        for rule in acl["rules"]:
            self.assertFalse(rule["inherited"])
            self.assertEqual(rule["type"], "Allow")
            self.assertEqual(rule["rights"], "FullControl")
            self.assertEqual(rule["inheritance"], "ContainerInherit, ObjectInherit")
            self.assertEqual(rule["propagation"], "None")
        self.assertTrue(manifest_exists)

    def test_apply_rejects_inherited_acl_written_by_concurrent_helper(self):
        result, changed, manifest_exists = self._apply_with_acl_corruptor(
            "inheritance", "inherited-acl"
        )

        self.assertTrue(changed, "concurrent helper must change the filesystem ACL")
        self.assertEqual(result.returncode, 48, result.stderr)
        self.assertEqual(
            result.stderr.strip(), "SelfWorkFlow: ACL security verification failed."
        )
        self.assertFalse(manifest_exists)

    def test_apply_rejects_everyone_acl_written_by_concurrent_helper(self):
        result, changed, manifest_exists = self._apply_with_acl_corruptor(
            "everyone", "everyone-acl"
        )

        self.assertTrue(changed, "concurrent helper must change the filesystem ACL")
        self.assertEqual(result.returncode, 48, result.stderr)
        self.assertEqual(
            result.stderr.strip(), "SelfWorkFlow: ACL security verification failed."
        )
        self.assertFalse(manifest_exists)

    def test_apply_rejects_extra_acl_written_by_concurrent_helper(self):
        result, changed, manifest_exists = self._apply_with_acl_corruptor(
            "extra", "extra-acl"
        )

        self.assertTrue(changed, "concurrent helper must change the filesystem ACL")
        self.assertEqual(result.returncode, 48, result.stderr)
        self.assertEqual(
            result.stderr.strip(), "SelfWorkFlow: ACL security verification failed."
        )
        self.assertFalse(manifest_exists)

    def test_apply_rejects_acl_drift_after_strict_state_is_observed(self):
        result, changed, manifest_exists = self._apply_with_acl_corruptor(
            "reread", "acl-reread-drift"
        )

        self.assertTrue(changed, "helper must observe strict ACL before changing it")
        self.assertEqual(result.returncode, 48, result.stderr)
        self.assertEqual(
            result.stderr.strip(), "SelfWorkFlow: ACL security verification failed."
        )
        self.assertFalse(manifest_exists)

    def test_apply_holds_root_and_ancestor_locks_until_process_exit(self):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        ancestor = self.local_app_data / "SelfWorkFlow" / "bootstrap" / "codex-cli"
        bootstrap_root = ancestor / "root-lock-lifecycle"
        barrier = self.temporary_root / "root-lock-barrier"
        release = self.temporary_root / "root-lock-release"
        probes = [
            {
                "target": bootstrap_root,
                "backup": Path(str(bootstrap_root) + "-probe"),
                "attempt": self.temporary_root / "root-lock-attempt",
                "success": self.temporary_root / "root-lock-success",
            },
            {
                "target": ancestor,
                "backup": Path(str(ancestor) + "-probe"),
                "attempt": self.temporary_root / "ancestor-lock-attempt",
                "success": self.temporary_root / "ancestor-lock-success",
            },
        ]
        control_path.write_text(
            json.dumps(
                {"installBarrier": str(barrier), "installRelease": str(release)}
            ),
            encoding="utf-8",
        )
        _set_protected_current_user_acl(self.local_app_data)
        try:
            plan = self._discover_v2("-BootstrapRoot", str(bootstrap_root))
            plan_path = self._write_plan(plan, "root-lock-lifecycle-plan.json")
            environment = os.environ.copy()
            environment["LOCALAPPDATA"] = str(self.local_app_data)
            result, probe_result = _run_with_rename_probes(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(BOOTSTRAP_SCRIPT),
                    "-Mode",
                    "Apply",
                    "-ConfirmedPlanPath",
                    str(plan_path),
                    "-ConfirmPlanHash",
                    plan["planHash"],
                ],
                environment,
                barrier,
                release,
                probes,
            )
            self.assertEqual(
                probe_result.returncode, 0, probe_result.stdout + probe_result.stderr
            )
            for probe in probes:
                self.assertTrue(probe["attempt"].exists())
                self.assertFalse(probe["success"].exists())
            self._assert_final_apply(plan, result)
            for target in (bootstrap_root, ancestor):
                backup = Path(str(target) + "-after-exit")
                target.rename(backup)
                backup.rename(target)
        finally:
            control_path.unlink(missing_ok=True)
            for path in (barrier, release):
                path.unlink(missing_ok=True)
            for probe in probes:
                probe["attempt"].unlink(missing_ok=True)
                probe["success"].unlink(missing_ok=True)
                if probe["backup"].exists() and not probe["target"].exists():
                    probe["backup"].rename(probe["target"])
            if bootstrap_root.exists():
                shutil.rmtree(bootstrap_root)

    def test_apply_ancestor_junction_race_is_locked_or_fails_closed_before_install(self):
        control_path = self.npm_cli.parent / "fake-npm-control.json"
        ancestor = self.local_app_data / "SelfWorkFlow" / "bootstrap" / "codex-cli"
        bootstrap_root = ancestor / "ancestor-junction-race"
        ancestor.mkdir(parents=True, exist_ok=True)
        escape_target = self.temporary_root / "ancestor-junction-escape"
        escape_target.mkdir()
        barrier = self.temporary_root / "ancestor-junction-start"
        release = self.temporary_root / "ancestor-junction-release"
        install_marker = self.temporary_root / "ancestor-junction-install.marker"
        probe = {
            "target": ancestor,
            "backup": Path(str(ancestor) + "-probe"),
            "attempt": self.temporary_root / "ancestor-junction-attempt",
            "success": self.temporary_root / "ancestor-junction-success",
            "junction": escape_target,
        }
        control_path.write_text(
            json.dumps({"installMarker": str(install_marker)}), encoding="utf-8"
        )
        _set_protected_current_user_acl(self.local_app_data)
        barrier.write_text("start", encoding="utf-8")
        try:
            plan = self._discover_v2("-BootstrapRoot", str(bootstrap_root))
            plan_path = self._write_plan(plan, "ancestor-junction-race-plan.json")
            environment = os.environ.copy()
            environment["LOCALAPPDATA"] = str(self.local_app_data)
            result, probe_result = _run_with_rename_probes(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(BOOTSTRAP_SCRIPT),
                    "-Mode",
                    "Apply",
                    "-ConfirmedPlanPath",
                    str(plan_path),
                    "-ConfirmPlanHash",
                    plan["planHash"],
                ],
                environment,
                barrier,
                release,
                [probe],
                stop_marker=install_marker,
            )
            replacement_succeeded = probe["backup"].exists()
            install_started = install_marker.exists()
            manifest_exists = Path(plan["sideEffects"]["manifestPath"]).exists()
            self.assertEqual(
                probe_result.returncode, 0, probe_result.stdout + probe_result.stderr
            )
            self.assertTrue(probe["attempt"].exists())
            if replacement_succeeded:
                self.assertIn(result.returncode, (43, 59), result.stderr)
                self.assertFalse(install_started)
                self.assertFalse(manifest_exists)
                self.assertEqual(list(escape_target.rglob("*")), [])
            else:
                self.assertFalse(probe["success"].exists())
                self.assertTrue(install_started)
                self._assert_final_apply(plan, result)
        finally:
            control_path.unlink(missing_ok=True)
            for path in (
                barrier,
                release,
                install_marker,
                probe["attempt"],
                probe["success"],
            ):
                path.unlink(missing_ok=True)
            _remove_junction_if_present(ancestor)
            if probe["backup"].exists() and not ancestor.exists():
                probe["backup"].rename(ancestor)
            if bootstrap_root.exists():
                shutil.rmtree(bootstrap_root)
            if escape_target.exists():
                shutil.rmtree(escape_target)

    def test_apply_publishes_schema_valid_semantic_manifest_v2(self):
        from jsonschema import Draft202012Validator

        plan = self._discover_v2()
        plan_path = self._write_plan(plan, "manifest-success-plan.json")
        bootstrap_root = Path(plan["bootstrapRoot"])
        manifest_path = Path(plan["sideEffects"]["manifestPath"])
        secret = "manifest-oracle-super-secret-token"
        raw_output = "manifest-oracle-raw-output"
        try:
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmedPlanPath",
                str(plan_path),
                "-ConfirmPlanHash",
                plan["planHash"],
                environment={
                    "NPM_TOKEN": secret,
                    "SELFWORKFLOW_RAW_OUTPUT": raw_output,
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            response = json.loads(result.stdout)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            schema = json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))
            Draft202012Validator(schema).validate(manifest)
            independent_tree_hash = _compute_package_tree_hash(
                bootstrap_root / "node_modules" / "@openai" / "codex"
            )
            independent_acl = _read_directory_acl(bootstrap_root)
            codex_markers = list(bootstrap_root.rglob("*.executed"))
            temporary_manifests = list(bootstrap_root.glob("*.tmp"))
        finally:
            if bootstrap_root.exists():
                shutil.rmtree(bootstrap_root)

        self.assertEqual(response, {"manifestPath": str(manifest_path), "manifest": manifest})
        self.assertEqual(manifest["schemaVersion"], 2)
        self.assertEqual(manifest["bootstrapRoot"], plan["bootstrapRoot"])
        self.assertEqual(manifest["package"], {
            "name": plan["package"]["name"],
            "version": plan["package"]["version"],
            "integrity": plan["package"]["integrity"],
        })
        self.assertEqual(manifest["expectedCliVersion"], plan["package"]["version"])
        self.assertEqual(manifest["cliVersionVerification"], "not-run")
        self.assertEqual(manifest["packageTreeHash"], independent_tree_hash)
        self.assertEqual(manifest["daclSddl"], independent_acl["sddl"])
        self.assertEqual(manifest["planHash"], _compute_v2_plan_hash(plan))
        self.assertEqual(manifest["planHash"], plan["planHash"])
        self.assertTrue(independent_acl["protected"])
        self.assertIn(
            independent_acl["owner"],
            {independent_acl["currentSid"], "S-1-5-18"},
        )
        self.assertEqual(
            {rule["sid"] for rule in independent_acl["rules"]},
            {independent_acl["currentSid"], "S-1-5-18"},
        )
        self.assertEqual(len(independent_acl["rules"]), 2)
        for rule in independent_acl["rules"]:
            self.assertFalse(rule["inherited"])
            self.assertEqual(rule["type"], "Allow")
            self.assertEqual(rule["rights"], "FullControl")
        serialized = (
            json.dumps(manifest, sort_keys=True) + result.stdout + result.stderr
        ).lower()
        self.assertNotIn("cliVersion", manifest)
        self.assertNotIn("credential", serialized)
        self.assertNotIn("stdout", serialized)
        self.assertNotIn("stderr", serialized)
        self.assertNotIn(secret, serialized)
        self.assertNotIn(raw_output, serialized)
        self.assertFalse(codex_markers)
        self.assertFalse(temporary_manifests)

    def test_published_manifest_passes_production_semantic_validation(self):
        plan = self._discover_v2()
        plan_path = self._write_plan(plan, "manifest-semantic-plan.json")
        bootstrap_root = Path(plan["bootstrapRoot"])
        manifest_path = Path(plan["sideEffects"]["manifestPath"])
        try:
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmedPlanPath",
                str(plan_path),
                "-ConfirmPlanHash",
                plan["planHash"],
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            semantic = _validate_manifest_candidate(self.local_app_data, plan, manifest)
            self.assertEqual(semantic.returncode, 0, semantic.stderr)
        finally:
            if bootstrap_root.exists():
                shutil.rmtree(bootstrap_root)

    def test_manifest_semantics_rejects_string_schema_version(self):
        plan = self._discover_v2()
        plan_path = self._write_plan(plan, "manifest-schema-type-plan.json")
        bootstrap_root = Path(plan["bootstrapRoot"])
        manifest_path = Path(plan["sideEffects"]["manifestPath"])
        try:
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmedPlanPath",
                str(plan_path),
                "-ConfirmPlanHash",
                plan["planHash"],
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["schemaVersion"] = "2"
            semantic = _validate_manifest_candidate(self.local_app_data, plan, manifest)
            self.assertEqual(semantic.returncode, 58, semantic.stderr)
            self.assertEqual(
                semantic.stderr.strip(),
                "SelfWorkFlow: manifest semantic validation failed.",
            )
        finally:
            if bootstrap_root.exists():
                shutil.rmtree(bootstrap_root)

    def test_manifest_semantics_rejects_shape_and_binding_drift(self):
        plan = self._discover_v2()
        plan_path = self._write_plan(plan, "manifest-drift-plan.json")
        bootstrap_root = Path(plan["bootstrapRoot"])
        manifest_path = Path(plan["sideEffects"]["manifestPath"])
        try:
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmedPlanPath",
                str(plan_path),
                "-ConfirmPlanHash",
                plan["planHash"],
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected_version_secret = "expected-version-super-secret"
            mutations = {
                "missing-top-field": lambda value: value.pop("expectedCliVersion"),
                "extra-top-field": lambda value: value.update(extra="rejected"),
                "extra-package-field": lambda value: value["package"].update(extra="rejected"),
                "schema-version": lambda value: value.update(schemaVersion=1),
                "package-version": lambda value: value["package"].update(version="1.2.4"),
                "tree-hash": lambda value: value.update(packageTreeHash=f"sha256:{'1' * 64}"),
                "plan-hash": lambda value: value.update(planHash="1" * 64),
                "dacl": lambda value: value.update(daclSddl="D:P(A;OICI;FA;;;WD)"),
                "root-noncanonical": lambda value: value.update(bootstrapRoot=r"C:\..\Windows"),
                "root-outside-boundary": lambda value: value.update(
                    bootstrapRoot=str(self.temporary_root / "outside-manifest-root")
                ),
                "root-confirmed-plan-drift": lambda value: value.update(
                    bootstrapRoot=str(Path(plan["bootstrapRoot"]) / "inside-drift")
                ),
                "expected-version": lambda value: value.update(
                    expectedCliVersion=f"1.2.3+{expected_version_secret}"
                ),
            }
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    candidate = json.loads(json.dumps(manifest))
                    mutate(candidate)
                    semantic = _validate_manifest_candidate(
                        self.local_app_data, plan, candidate
                    )
                    self.assertEqual(semantic.returncode, 58, semantic.stderr)
                    self.assertEqual(
                        semantic.stderr.strip(),
                        "SelfWorkFlow: manifest semantic validation failed.",
                    )
                    self.assertNotIn(
                        expected_version_secret, semantic.stdout + semantic.stderr
                    )
        finally:
            if bootstrap_root.exists():
                shutil.rmtree(bootstrap_root)

    def test_nonempty_manifest_path_is_rejected_without_sensitive_content(self):
        secret = "super-secret-manifest-token"
        bootstrap_root = (
            self.local_app_data
            / "SelfWorkFlow"
            / "bootstrap"
            / "codex-cli"
            / "atomic-failure"
        )
        plan = self._discover_v2("-BootstrapRoot", str(bootstrap_root))
        plan_path = self._write_plan(plan, "manifest-atomic-failure-plan.json")
        manifest_path = Path(plan["sideEffects"]["manifestPath"])
        manifest_path.mkdir(parents=True)
        try:
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmedPlanPath",
                str(plan_path),
                "-ConfirmPlanHash",
                plan["planHash"],
                environment={"SELFWORKFLOW_SECRET_TOKEN": secret},
            )
            written_text = "".join(
                path.read_text(encoding="utf-8", errors="ignore")
                for path in bootstrap_root.rglob("*")
                if path.is_file()
            )
            codex_markers = list(bootstrap_root.rglob("*.executed"))
            temporary_manifests = list(bootstrap_root.glob("*.tmp"))
            formal_manifest_is_file = manifest_path.is_file()
        finally:
            if bootstrap_root.exists():
                shutil.rmtree(bootstrap_root)

        self.assertEqual(result.returncode, 44, result.stderr)
        self.assertEqual(
            result.stderr.strip(),
            "SelfWorkFlow: existing BootstrapRoot does not satisfy safe recovery conditions; only an empty directory is accepted.",
        )
        self.assertFalse(formal_manifest_is_file)
        self.assertFalse(temporary_manifests)
        self.assertNotIn(secret, result.stdout + result.stderr + written_text)
        self.assertFalse(codex_markers)

    def test_nonempty_root_rejection_preserves_existing_manifest(self):
        bootstrap_root = (
            self.local_app_data
            / "SelfWorkFlow"
            / "bootstrap"
            / "codex-cli"
            / "existing-manifest"
        )
        plan = self._discover_v2("-BootstrapRoot", str(bootstrap_root))
        plan_path = self._write_plan(plan, "existing-manifest-plan.json")
        manifest_path = Path(plan["sideEffects"]["manifestPath"])
        manifest_path.parent.mkdir(parents=True)
        sentinel = "existing-manifest-must-survive"
        manifest_path.write_text(sentinel, encoding="utf-8")
        try:
            result = _run_bootstrap(
                self.local_app_data,
                "-Mode",
                "Apply",
                "-ConfirmedPlanPath",
                str(plan_path),
                "-ConfirmPlanHash",
                plan["planHash"],
            )
            preserved = manifest_path.read_text(encoding="utf-8")
            temporary_manifests = list(bootstrap_root.glob("*.tmp"))
        finally:
            if bootstrap_root.exists():
                shutil.rmtree(bootstrap_root)

        self.assertEqual(result.returncode, 44, result.stderr)
        self.assertEqual(preserved, sentinel)
        self.assertFalse(temporary_manifests)

class BootstrapCodexCliTests(unittest.TestCase):
    def test_manifest_atomic_publish_cleans_published_file_after_postcheck_failure(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manifest_path = root / "bootstrap-tool-manifest.json"
            environment = os.environ.copy()
            environment.update(
                {
                    "SELFWORKFLOW_MANIFEST_LIBRARY": str(MANIFEST_LIBRARY),
                    "SELFWORKFLOW_MANIFEST_TARGET": str(manifest_path),
                    "SELFWORKFLOW_MANIFEST_ROOT": str(root),
                }
            )
            command = r"""
. $env:SELFWORKFLOW_MANIFEST_LIBRARY
$script:ValidationCalls = 0
$script:ObservedMovedFile = $false
function Assert-SelfWorkflowBootstrapManifest {
    param($Manifest, $Plan, $AllowedBoundary, $PackageRoot, $ExpectedSddl)
    $script:ValidationCalls++
    if ($script:ValidationCalls -eq 2) {
        $script:ObservedMovedFile = [IO.File]::Exists($env:SELFWORKFLOW_MANIFEST_TARGET)
        throw "deterministic post-move validation failure"
    }
}
$Failed = $false
try {
    [void](Publish-SelfWorkflowManifestAtomic `
        -Manifest ([pscustomobject]@{ schemaVersion = 2 }) `
        -ManifestPath $env:SELFWORKFLOW_MANIFEST_TARGET `
        -Plan ([pscustomobject]@{}) `
        -AllowedBoundary $env:SELFWORKFLOW_MANIFEST_ROOT `
        -PackageRoot $env:SELFWORKFLOW_MANIFEST_ROOT `
        -ExpectedSddl "ignored")
} catch {
    $Failed = $true
}
[ordered]@{
    failed = $Failed
    validationCalls = $script:ValidationCalls
    observedMovedFile = $script:ObservedMovedFile
    formalExists = [IO.File]::Exists($env:SELFWORKFLOW_MANIFEST_TARGET)
    temporaryCount = @(Get-ChildItem -LiteralPath $env:SELFWORKFLOW_MANIFEST_ROOT -Filter "*.tmp").Count
} | ConvertTo-Json -Compress
"""
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", command],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        observation = json.loads(result.stdout)
        self.assertTrue(observation["failed"])
        self.assertEqual(observation["validationCalls"], 2)
        self.assertTrue(observation["observedMovedFile"])
        self.assertFalse(observation["formalExists"])
        self.assertEqual(observation["temporaryCount"], 0)

    def test_manifest_atomic_publish_cleans_temp_after_move_conflict(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manifest_path = root / "bootstrap-tool-manifest.json"
            environment = os.environ.copy()
            environment.update(
                {
                    "SELFWORKFLOW_MANIFEST_LIBRARY": str(MANIFEST_LIBRARY),
                    "SELFWORKFLOW_MANIFEST_TARGET": str(manifest_path),
                    "SELFWORKFLOW_MANIFEST_ROOT": str(root),
                }
            )
            command = r"""
. $env:SELFWORKFLOW_MANIFEST_LIBRARY
$script:ValidationCalls = 0
function Assert-SelfWorkflowBootstrapManifest {
    param($Manifest, $Plan, $AllowedBoundary, $PackageRoot, $ExpectedSddl)
    $script:ValidationCalls++
    if ($script:ValidationCalls -eq 1) {
        [IO.Directory]::CreateDirectory($env:SELFWORKFLOW_MANIFEST_TARGET) | Out-Null
    }
}
$Failed = $false
try {
    [void](Publish-SelfWorkflowManifestAtomic `
        -Manifest ([pscustomobject]@{ schemaVersion = 2 }) `
        -ManifestPath $env:SELFWORKFLOW_MANIFEST_TARGET `
        -Plan ([pscustomobject]@{}) `
        -AllowedBoundary $env:SELFWORKFLOW_MANIFEST_ROOT `
        -PackageRoot $env:SELFWORKFLOW_MANIFEST_ROOT `
        -ExpectedSddl "ignored")
} catch { $Failed = $true }
[ordered]@{
    failed = $Failed
    validationCalls = $script:ValidationCalls
    conflictDirectoryExists = [IO.Directory]::Exists($env:SELFWORKFLOW_MANIFEST_TARGET)
    formalFileExists = [IO.File]::Exists($env:SELFWORKFLOW_MANIFEST_TARGET)
    temporaryCount = @(Get-ChildItem -LiteralPath $env:SELFWORKFLOW_MANIFEST_ROOT -Filter "*.tmp").Count
} | ConvertTo-Json -Compress
"""
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", command],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        observation = json.loads(result.stdout)
        self.assertTrue(observation["failed"])
        self.assertEqual(observation["validationCalls"], 1)
        self.assertTrue(observation["conflictDirectoryExists"])
        self.assertFalse(observation["formalFileExists"])
        self.assertEqual(observation["temporaryCount"], 0)

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
                "expectedCliVersion",
                "cliVersionVerification",
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
            "schemaVersion": 2,
            "bootstrapRoot": r"C:\Users\Example\AppData\Local\SelfWorkFlow\bootstrap\codex-cli",
            "package": {
                "name": "@openai/codex",
                "version": "1.2.3",
                "integrity": "sha512-U2VsZldvcmtGbG93RmFrZUludGVncml0eQ==",
            },
            "packageTreeHash": f"sha256:{'0' * 64}",
            "daclSddl": "D:P(A;OICI;FA;;;S-1-5-18)",
            "expectedCliVersion": "1.2.3",
            "cliVersionVerification": "not-run",
            "planHash": "0" * 64,
        }
        validator = Draft202012Validator(schema)
        for field, unsafe_value in (
            ("schemaVersion", 1),
            ("bootstrapRoot", r"C:\..\Windows"),
            ("daclSddl", "D:P(A;;FA;;;WD)"),
            ("expectedCliVersion", "1.2.3 extra-sensitive-text"),
            ("cliVersionVerification", "run"),
        ):
            with self.subTest(field=field):
                unsafe_manifest = json.loads(json.dumps(manifest))
                unsafe_manifest[field] = unsafe_value
                self.assertTrue(list(validator.iter_errors(unsafe_manifest)))

        for field_path in (("package", "version"), ("expectedCliVersion",)):
            with self.subTest(field_path=field_path, value="1.2.3-01"):
                unsafe_manifest = json.loads(json.dumps(manifest))
                target = unsafe_manifest
                for field in field_path[:-1]:
                    target = target[field]
                target[field_path[-1]] = "1.2.3-01"
                self.assertTrue(list(validator.iter_errors(unsafe_manifest)))

        legal_manifest = json.loads(json.dumps(manifest))
        legal_manifest["package"]["version"] = "1.2.3-alpha.1+build.01"
        legal_manifest["expectedCliVersion"] = "1.2.3-alpha.1+build.01"
        self.assertFalse(list(validator.iter_errors(legal_manifest)))

        extra_manifest = json.loads(json.dumps(manifest))
        extra_manifest["unexpected"] = "rejected"
        self.assertTrue(list(validator.iter_errors(extra_manifest)))

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

    def test_manifest_atomic_publish_validates_before_temp_or_move(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manifest_path = root / "bootstrap-tool-manifest.json"
            environment = os.environ.copy()
            environment.update(
                {
                    "SELFWORKFLOW_MANIFEST_LIBRARY": str(MANIFEST_LIBRARY),
                    "SELFWORKFLOW_MANIFEST_TARGET": str(manifest_path),
                    "SELFWORKFLOW_MANIFEST_ROOT": str(root),
                }
            )
            command = r"""
. $env:SELFWORKFLOW_MANIFEST_LIBRARY
$script:ValidationCalls = 0
function Assert-SelfWorkflowBootstrapManifest {
    param($Manifest, $Plan, $AllowedBoundary, $PackageRoot, $ExpectedSddl)
    $script:ValidationCalls++
    throw "deterministic pre-write validation failure"
}
$Failed = $false
try {
    [void](Publish-SelfWorkflowManifestAtomic `
        -Manifest ([pscustomobject]@{ schemaVersion = 2 }) `
        -ManifestPath $env:SELFWORKFLOW_MANIFEST_TARGET `
        -Plan ([pscustomobject]@{}) `
        -AllowedBoundary $env:SELFWORKFLOW_MANIFEST_ROOT `
        -PackageRoot $env:SELFWORKFLOW_MANIFEST_ROOT `
        -ExpectedSddl "ignored")
} catch { $Failed = $true }
[ordered]@{
    failed = $Failed
    validationCalls = $script:ValidationCalls
    formalExists = [IO.File]::Exists($env:SELFWORKFLOW_MANIFEST_TARGET)
    temporaryCount = @(Get-ChildItem -LiteralPath $env:SELFWORKFLOW_MANIFEST_ROOT -Filter "*.tmp").Count
} | ConvertTo-Json -Compress
"""
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", command],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        observation = json.loads(result.stdout)
        self.assertTrue(observation["failed"])
        self.assertEqual(observation["validationCalls"], 1)
        self.assertFalse(observation["formalExists"])
        self.assertEqual(observation["temporaryCount"], 0)

if __name__ == "__main__":
    unittest.main()
