from pathlib import Path
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from selfworkflow.installer import doctor
from selfworkflow import cli
from unittest.mock import patch


def _commit(root):
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "--local", "core.autocrlf", "false"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git", "-c", "user.name=SelfWorkFlow Tests",
            "-c", "user.email=selfworkflow@example.invalid",
            "commit", "-q", "-m", "fixture",
        ],
        cwd=root,
        check=True,
    )


class OneClickInstallerContractTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_post_apply_failure_preserves_pending_cleanup_and_failed_rollback(self):
        source = (self.ROOT / "scripts/install-selfworkflow.ps1").read_text(encoding="utf-8")
        # Exercise the real apply-to-catch orchestration with boundary failures;
        # do not run dependency installation or touch the user's live state.
        tail = source[source.index('    Set-InstallStage "apply" 60'):]
        harness = r'''
param([string]$LogDirectory)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$script:LogDirectory = $LogDirectory
$script:FailureExitCode = 60
$script:CurrentStage = "apply"
$applyResult = $null
$cleanupPending = @()
$codeGraphRollbackToken = $null
$planPath = "fixture-plan"
$plan = [pscustomobject]@{ planHash = "fixture-hash" }
$HostLauncherPath = "fixture-launcher"
function Set-InstallStage($Stage, $Code) { $script:CurrentStage = $Stage; $script:FailureExitCode = $Code }
function Write-InstallLog($Message) { }
function Write-JsonFile($Path, $Value) { $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding UTF8 }
function Ensure-HostLauncher($Path) { throw "injected-host-launcher-failure" }
function Restore-McpFiles { return "not-required" }
function Invoke-SelfWorkflow($Arguments, $OutputPath) {
    if ($Arguments[0] -eq "install" -and $Arguments[1] -eq "apply") {
        return [pscustomobject]@{status="applied";manifestPath="fixture-manifest";transactionPath="fixture-transaction";cleanupPending=@("installer-lock-release-failed")}
    }
    if ($Arguments[1] -eq "verify") { return [pscustomobject]@{status="verified"} }
    if ($Arguments[1] -eq "rollback-plan") {
        Write-JsonFile $Arguments[5] ([ordered]@{planHash="rollback-hash"})
        return
    }
    if ($Arguments[1] -eq "rollback") {
        [IO.File]::WriteAllText((Join-Path $script:LogDirectory "install-rollback-called"), "called")
        throw "installer-locked"
    }
    throw "unexpected-command"
}
try {
'''
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            script = root / "fault.ps1"
            script.write_text(harness + tail, encoding="utf-8")
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), str(root)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 80, result.stdout + result.stderr)
            summary = json.loads((root / "summary.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["stage"], "host-cli")
            self.assertEqual(summary["reason"], "injected-host-launcher-failure")
            self.assertEqual(summary["rollback"], "failed")
            self.assertEqual(summary["cleanupPending"], ["installer-lock-release-failed"])
            self.assertTrue((root / "install-rollback-called").is_file())

    def test_batch_entry_is_thin_forwards_arguments_and_preserves_exit_code(self):
        batch = self.ROOT / "Install_SelfWorkFlow.bat"
        self.assertTrue(batch.is_file())
        content = batch.read_text(encoding="utf-8").casefold()
        self.assertIn("scripts\\install-selfworkflow.ps1", content)
        self.assertIn("%*", content)
        self.assertIn("exit /b %errorlevel%", content)
        self.assertNotIn("pip install", content)
        self.assertNotIn("git clone", content)

    def test_provider_batch_is_thin_and_powershell_records_failure_logs(self):
        batch = (self.ROOT / "Manage_SelfWorkFlow_Providers.bat").read_text(
            encoding="utf-8"
        ).casefold()
        script = (self.ROOT / "scripts/manage-selfworkflow-providers.ps1").read_text(
            encoding="utf-8"
        ).casefold()
        self.assertIn("scripts\\manage-selfworkflow-providers.ps1", batch)
        self.assertIn("%*", batch)
        self.assertIn("exit /b %errorlevel%", batch)
        self.assertIn("selfworkflow.cli provider", script)
        self.assertIn("provider-manager-failed", script)
        self.assertIn("selfworkflow\\logs", script)
        self.assertNotIn("invoke-expression", script)

    def test_provider_batch_forwards_list_from_an_arbitrary_working_directory(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            environment = os.environ.copy()
            environment["LOCALAPPDATA"] = str(root / "localappdata")
            result = subprocess.run(
                [str(self.ROOT / "Manage_SelfWorkFlow_Providers.bat"), "list"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                env=environment,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {"providers": []})
        self.assertFalse((root / "list").exists())

    def test_install_publishes_machine_local_host_launcher_for_provider_calls(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            result = self._run_installer(
                root, "-SuperpowersChoice", "Skip", "-ConfirmApply"
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            launcher = root / "localappdata/SelfWorkFlow/bin/selfworkflow.cmd"
            self.assertTrue(launcher.is_file())
            launcher_text = launcher.read_text(encoding="utf-8").casefold()
            self.assertIn("managed", launcher_text)
            information = subprocess.run(
                [str(launcher), "--host-info"], cwd=root,
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(information.returncode, 0, information.stderr)
            host = json.loads(information.stdout)
            self.assertEqual(
                Path(host["cliPath"]), Path(host["snapshot"]) / "src/selfworkflow/cli.py"
            )
            self.assertNotEqual(Path(host["cliPath"]), self.ROOT / "src/selfworkflow/cli.py")
            codegraph_mcp = root / "localappdata/SelfWorkFlow/bin/codegraph-mcp.cmd"
            self.assertTrue(codegraph_mcp.is_file())
            codegraph_mcp_text = codegraph_mcp.read_text(encoding="utf-8").casefold()
            self.assertIn("codegraph", codegraph_mcp_text)
            self.assertIn("%*", codegraph_mcp_text)
            codex_config = (root / "codex/config.toml").read_text(encoding="utf-8")
            self.assertIn("# selfworkflow:codegraph-mcp:begin", codex_config)
            self.assertIn("[mcp_servers.codegraph]", codex_config)
            self.assertIn("codegraph-mcp.cmd", codex_config)

            (root / "arbitrary-working-directory").mkdir()
            environment = os.environ.copy()
            environment["LOCALAPPDATA"] = str(root / "localappdata")
            result = subprocess.run(
                [str(launcher), "provider", "list"],
                cwd=root / "arbitrary-working-directory",
                capture_output=True,
                text=True,
                check=False,
                env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            providers = json.loads(result.stdout)["providers"]
            self.assertEqual([item["providerId"] for item in providers], ["codegraph"])

    def test_launcher_only_repairs_codegraph_mcp_without_touching_runtime_roots(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            result = self._run_installer(
                root, "-CodeGraphMcpLauncherOnly", "-ConfirmApply"
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            launcher = root / "localappdata/SelfWorkFlow/bin/codegraph-mcp.cmd"
            self.assertTrue(launcher.is_file())
            launcher_text = launcher.read_text(encoding="utf-8").casefold()
            self.assertIn("codegraph", launcher_text)
            log_directory = self._single_log_directory(root)
            summary = json.loads((log_directory / "summary.json").read_text())
            self.assertEqual(summary["status"], "launcher-only")
            self.assertFalse((log_directory / "install-plan.json").exists())
            self.assertFalse((root / "agents").exists())
            self.assertFalse((root / "state").exists())

    def test_launcher_only_failure_restores_launcher_and_preserves_foreign_config(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary).resolve()
            launcher = root / "localappdata/SelfWorkFlow/bin/codegraph-mcp.cmd"
            launcher.parent.mkdir(parents=True)
            launcher.write_bytes(b"@echo original-launcher\r\n")
            config = root / "codex/config.toml"
            config.parent.mkdir()
            config.write_bytes(b'[mcp_servers.codegraph]\ncommand = "foreign-owner"\n')
            before = (launcher.read_bytes(), config.read_bytes())
            result = self._run_installer(root, "-CodeGraphMcpLauncherOnly", "-ConfirmApply")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((launcher.read_bytes(), config.read_bytes()), before)
            summary = json.loads((self._single_log_directory(root) / "summary.json").read_text())
            self.assertEqual(summary["rollback"], "rolled-back")

    def _mcp_fault_install(self, root, case, launcher_only):
        source = (self.ROOT / "scripts/install-selfworkflow.ps1").read_text(encoding="utf-8")
        functions = source[source.index("function Get-McpBytesHash"):source.index("function Remove-LegacyState")]
        catch = source[source.rindex("\ncatch {"):]
        if launcher_only:
            begin = source.index("    if ($CodeGraphMcpLauncherOnly) {")
            body = source[begin:source.index('    Set-InstallStage "submodules"', begin)]
        else:
            body = source[source.index('    Set-InstallStage "apply" 60'):source.rindex("\ncatch {")]
            body = body[:body.rindex("}")]
        harness = r'''
param([string]$Root, [string]$Case, [string]$Only, [string]$PythonPath)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$script:LogDirectory = $Root
$script:McpFileStates = @{}
$script:FailureExitCode = 75
$script:CurrentStage = "codegraph-mcp"
$codeGraphRollbackToken = $null
$applyResult = $null
$cleanupPending = @()
$CodeGraphMcpLauncherOnly = $Only -eq "yes"
$ConfirmApply = $true
$CodeGraphMcpLauncherPath = Join-Path $Root "launch.cmd"
$CodexCodeGraphMcpConfigPath = Join-Path $Root "config.toml"
$ProviderConfigFile = Join-Path $Root "providers.json"
if ($Case -in @("provider-race", "provider-preserve-race")) { $ProviderConfigFile = Join-Path $Root "localappdata/SelfWorkFlow/config/providers.local.yaml" }
$providerBeforeHash = "missing"
$preserveSource = $false
$runtimeRoot = $Root
$AgentsRoot = Join-Path $Root "agents"
$CodexRoot = Join-Path $Root "codex"
$DshRoot = ""
$DshArguments = @()
$StateRoot = Join-Path $Root "state"
$scriptPath = Join-Path $Root "runtime.js"
[IO.File]::WriteAllText($scriptPath, "fixture")
$runtimeReport = [pscustomobject]@{commandPrefix=@((Get-Command node.exe).Source,$scriptPath);sourceHash="fixture"}
$Profile = "knowledge"
$RepositoryRoot = $Root
$codeGraphVerification = [pscustomobject]@{status="fixture"}
$ponytailReport = [pscustomobject]@{status="fixture"}
$mattSkillsReport = [pscustomobject]@{status="fixture"}
$HostLauncherPath = Join-Path $Root "host.cmd"
$planPath = "fixture"
$plan = [pscustomobject]@{planHash="fixture"}
function Get-Sha256Hex($Path) { return Get-McpBytesHash ([IO.File]::ReadAllBytes($Path)) }
function Write-InstallLog($Message) { }
function Set-InstallStage($Stage,$Code) { $script:CurrentStage=$Stage; $script:FailureExitCode=$Code }
function Stop-Install($Stage,$Code,$Message) {
    Set-InstallStage $Stage $Code
    if ($Error.Count -gt 0) { throw ($Message + ":" + $Error[0].Exception.Message) }
    throw $Message
}
function Write-JsonFile($Path,$Value) {
if ($CodeGraphMcpLauncherOnly -and [IO.Path]::GetFileName($Path) -eq "summary.json" -and $Value.status -eq "launcher-only") {
        if ($Case -in @("success", "noop-drift", "provider-preserve-race")) { $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding UTF8; return }
        if ($Case -eq "rollback-conflict") { [IO.File]::WriteAllText($CodeGraphMcpLauncherPath,"concurrent-user-change") }
        throw "injected-post-mcp-failure"
    }
    $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding UTF8
}
function Ensure-HostLauncher($Path) { return [pscustomobject]@{status="fixture"} }
function Remove-LegacyState($Path) { }
function Invoke-SelfWorkflow($Arguments,$OutputPath) {
    if ($Arguments[0] -eq "wiki") {
        if ($Arguments[1] -eq "inspect") {
            $status = if ($Case -eq "wiki-post-failure") { "source-ready" } else { "setup-required" }
            return [pscustomobject]@{status=$status}
        }
        if ($Arguments[1] -eq "register") {
            $before = [IO.File]::ReadAllBytes($CodexCodeGraphMcpConfigPath)
            $after = [Text.Encoding]::UTF8.GetBytes([Text.Encoding]::UTF8.GetString($before) + "`n[mcp_servers.self-openwiki]`ncommand = `"new-wiki`"`n")
            if ($Arguments -contains "--confirm-plan-hash") {
                [IO.File]::WriteAllBytes($CodexCodeGraphMcpConfigPath, $after)
            }
            return [pscustomobject]@{planHash="wiki-plan";beforeConfigHash=("sha256:" + (Get-McpBytesHash $before));afterConfigHash=("sha256:" + (Get-McpBytesHash $after))}
        }
    }
    if ($Arguments[0] -eq "doctor") {
        if ($Case -eq "rollback-conflict") { [IO.File]::WriteAllText($CodeGraphMcpLauncherPath,"concurrent-user-change") }
        return [pscustomobject]@{status="fixture"}
    }
    if ($Arguments[0] -eq "provider") {
        if ($Case -in @("provider-race", "provider-preserve-race")) {
            if ($Arguments[1] -eq "list" -and -not $script:ProviderRaceInjected) {
                [IO.File]::WriteAllBytes($ProviderConfigFile,[IO.File]::ReadAllBytes((Join-Path $Root "concurrent-provider.json")))
                $script:ProviderRaceInjected = $true
            }
            $output = & $PythonPath -m selfworkflow.cli @Arguments
            if ($LASTEXITCODE -ne 0) { throw "provider-race-cli-failed" }
            $result = $output | Out-String | ConvertFrom-Json
            if ($OutputPath) { Write-JsonFile $OutputPath $result }
            return $result
        }
        if ($Arguments[1] -eq "list") { return [pscustomobject]@{providers=@()} }
        if ($Arguments[1] -eq "rollback-config") { return [pscustomobject]@{status="not-issued"} }
        if ($Case -in @("success", "noop-drift")) {
            if ($Arguments[1] -eq "configure") {
                $token = $Arguments[([array]::IndexOf($Arguments,"--rollback-token") + 1)]
                $directory = Join-Path (Split-Path -Parent $ProviderConfigFile) ".provider-transactions"
                [IO.Directory]::CreateDirectory($directory) | Out-Null
                Write-JsonFile (Join-Path $directory ($token + ".json")) ([ordered]@{rollbackToken=$token;state="applied";preimageHash="missing"})
            }
            return [pscustomobject]@{status="configured"}
        }
        throw "injected-post-mcp-failure"
    }
    if ($Arguments[1] -eq "apply") { return [pscustomobject]@{status="applied";manifestPath="fixture";transactionPath="fixture"} }
    if ($Arguments[1] -eq "verify" -or $Arguments[1] -eq "rollback") { return [pscustomobject]@{status="verified"} }
    if ($Arguments[1] -eq "rollback-plan") { Write-JsonFile $Arguments[5] ([ordered]@{planHash="fixture"}); return }
    throw "unexpected-fixture-command"
}
'''
        setup = r'''
Get-McpFileState $CodeGraphMcpLauncherPath | Out-Null
Get-McpFileState $CodexCodeGraphMcpConfigPath | Out-Null
if ($Case -eq "wiki-post-failure") {
    $storageDirectory = Join-Path $Root "localappdata/SelfOpenWiki"
    [IO.Directory]::CreateDirectory($storageDirectory) | Out-Null
    [IO.File]::WriteAllText((Join-Path $storageDirectory "config.json"), "fixture")
}
if ($Case -in @("provider-race", "provider-preserve-race")) {
    $script:ProviderRaceInjected = $false
    $runtimeRoot = Join-Path $Root "codegraph-runtime"
    $runtimeReport = [IO.File]::ReadAllText((Join-Path $Root "candidate-source.json"),[Text.Encoding]::UTF8) | ConvertFrom-Json
}
if ($Case -eq "provider-preserve-race") {
    $preserveSource = $true
    $runtimeRoot = Join-Path $Root "local-source"
    $providerBeforeHash = Get-Sha256Hex $ProviderConfigFile
    $sourceEntry = ([IO.File]::ReadAllText($ProviderConfigFile,[Text.Encoding]::UTF8) | ConvertFrom-Json).providers[0]
    if ($CodeGraphMcpLauncherOnly) {
        $script:OriginalEnsureCodex = ${function:Ensure-CodexCodeGraphMcp}
        function Ensure-CodexCodeGraphMcp($Path,$Launcher) {
            $result = & $script:OriginalEnsureCodex $Path $Launcher
            [IO.File]::WriteAllBytes($ProviderConfigFile,[IO.File]::ReadAllBytes((Join-Path $Root "concurrent-provider.json")))
            return $result
        }
    }
}
if ($Case -eq "before-write") { [IO.File]::WriteAllText($CodeGraphMcpLauncherPath,"concurrent-user-change") }
if ($Case -eq "noop-drift") { [IO.File]::WriteAllText($CodexCodeGraphMcpConfigPath,"concurrent-user-change") }
if ($Case -eq "late-before-commit") {
    $script:OriginalMcpHash = ${function:Get-McpFileHash}
    $script:McpHashReads = 0
    function Get-McpFileHash($Path) {
        $value = & $script:OriginalMcpHash $Path
        if ($Path -eq $CodeGraphMcpLauncherPath) {
            $script:McpHashReads++
            if ($script:McpHashReads -eq 2) { [IO.File]::WriteAllText($Path,"concurrent-user-change") }
        }
        return $value
    }
}
if ($Case -eq "stage-failure") {
    function Write-McpStage($Path,$Bytes) { [IO.File]::WriteAllBytes($Path,[byte[]]@(1,2,3)); throw "injected-partial-stage-write" }
}
if ($Case -eq "commit-failure") {
    $script:HeldFile = [IO.File]::Open($CodeGraphMcpLauncherPath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
}
try {
'''
        script = root / "mcp-fault.ps1"
        script.write_text(harness + functions + setup + body + "\n}\n" + catch, encoding="utf-8")
        environment = os.environ.copy()
        environment["LOCALAPPDATA"] = str(root / "localappdata")
        environment["PYTHONPATH"] = str(self.ROOT / "src")
        return subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                               str(root), case, "yes" if launcher_only else "no", sys.executable],
                              capture_output=True, text=True, env=environment)

    def test_mcp_atomic_writes_and_rollback_preserve_user_bytes_in_both_modes(self):
        for only in (False, True):
            for case in ("before-write", "late-before-commit", "stage-failure", "commit-failure", "post-failure", "rollback-conflict"):
                with self.subTest(launcher_only=only, case=case), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
                    root = Path(temporary).resolve()
                    launcher = root / "launch.cmd"
                    config = root / "config.toml"
                    launcher.write_bytes(b"@echo original\r\n")
                    config.write_bytes(b'model = "keep-user-setting"\n')
                    result = self._mcp_fault_install(root, case, only)
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    expected_launcher = b"concurrent-user-change" if case in {"before-write", "late-before-commit", "rollback-conflict"} else b"@echo original\r\n"
                    self.assertEqual(launcher.read_bytes(), expected_launcher, result.stdout + result.stderr)
                    self.assertEqual(config.read_bytes(), b'model = "keep-user-setting"\n')
                    summary = json.loads((root / "summary.json").read_text(encoding="utf-8-sig"))
                    if case in {"post-failure", "rollback-conflict"}:
                        self.assertIn("injected-post-mcp-failure", summary["reason"])
                    if case == "rollback-conflict":
                        self.assertEqual(summary["rollback"], "failed")
                        self.assertEqual(result.returncode, 80)
                    else:
                        self.assertNotEqual(summary["rollback"], "failed")

    def test_failure_after_wiki_registration_restores_the_whole_original_config(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary).resolve()
            config = root / "config.toml"
            original = b'model = "keep-user-setting"\n'
            config.write_bytes(original)
            (root / "launch.cmd").write_bytes(b"@echo original\r\n")
            result = self._mcp_fault_install(root, "wiki-post-failure", False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(config.read_bytes(), original, result.stdout + result.stderr)
            summary = json.loads((root / "summary.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(summary["rollback"], "rolled-back")

    def test_failed_mcp_install_restores_original_absence_in_both_modes(self):
        for only in (False, True):
            with self.subTest(launcher_only=only), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
                root = Path(temporary).resolve()
                result = self._mcp_fault_install(root, "post-failure", only)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / "launch.cmd").exists())
                self.assertFalse((root / "config.toml").exists())
                summary = json.loads((root / "summary.json").read_text(encoding="utf-8-sig"))
                self.assertIn("injected-post-mcp-failure", summary["reason"])
                self.assertEqual(summary["rollback"], "rolled-back")

    def test_existing_empty_mcp_files_install_and_restore_in_both_modes(self):
        for only in (False, True):
            for case in ("success", "post-failure"):
                with self.subTest(launcher_only=only, case=case), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
                    root = Path(temporary).resolve()
                    launcher = root / "launch.cmd"
                    config = root / "config.toml"
                    launcher.write_bytes(b"")
                    config.write_bytes(b"")
                    result = self._mcp_fault_install(root, case, only)
                    summary_path = root / "summary.json"
                    self.assertTrue(summary_path.is_file(), result.stdout + result.stderr)
                    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
                    if case == "success":
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr + str(summary))
                        self.assertIn(b"runtime.js", launcher.read_bytes())
                        self.assertIn(b"[mcp_servers.codegraph]", config.read_bytes())
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("injected-post-mcp-failure", summary["reason"])
                        self.assertEqual(summary["rollback"], "rolled-back")
                        self.assertEqual(launcher.read_bytes(), b"")
                        self.assertEqual(config.read_bytes(), b"")

    def test_correct_mcp_section_still_rejects_snapshot_drift_in_both_modes(self):
        for only in (False, True):
            with self.subTest(launcher_only=only), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
                root = Path(temporary).resolve()
                installed = self._mcp_fault_install(root, "success", only)
                self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
                launcher_before = (root / "launch.cmd").read_bytes()
                result = self._mcp_fault_install(root, "noop-drift", only)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                summary = json.loads((root / "summary.json").read_text(encoding="utf-8-sig"))
                self.assertIn("codex-codegraph-mcp-write-failed:mcp-file-precondition-conflict", summary["reason"])
                self.assertEqual((root / "config.toml").read_bytes(), b"concurrent-user-change")
                self.assertEqual((root / "launch.cmd").read_bytes(), launcher_before)

    def test_provider_configure_restores_override_added_after_final_precondition_check(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary).resolve()
            local = root / "local-source"
            (local / "dist/bin").mkdir(parents=True)
            (local / "dist/bin/codegraph.js").write_text("console.log('local');\n", encoding="utf-8")
            (local / "package.json").write_text('{"name":"@colbymchenry/codegraph","version":"1"}', encoding="utf-8")
            _commit(local)
            config = root / "localappdata/SelfWorkFlow/config/providers.local.yaml"
            with patch.dict(os.environ, {"LOCALAPPDATA": str(root / "localappdata")}), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["provider", "configure", "--config-file", str(config),
                                           "--codegraph-path", str(local)]), 0)
            concurrent = config.read_bytes()
            (root / "concurrent-provider.json").write_bytes(concurrent)
            config.unlink()
            candidate = self._fake_runtime(root)
            report = io.StringIO()
            with contextlib.redirect_stdout(report):
                self.assertEqual(cli.main(["provider", "inspect", "--codegraph-path", str(candidate)]), 0)
            (root / "candidate-source.json").write_text(report.getvalue(), encoding="utf-8")
            result = self._mcp_fault_install(root, "provider-race", False)
            self.assertEqual(config.read_bytes(), concurrent, "concurrent local override was replaced")
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = json.loads((root / "summary.json").read_text(encoding="utf-8-sig"))
            self.assertIn("provider-config-precondition-conflict", summary["reason"])
            self.assertEqual(summary["rollback"], "rolled-back")

    def test_preserved_source_rejects_concurrent_binding_change_in_both_modes(self):
        for only in (False, True):
            with self.subTest(launcher_only=only), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
                root = Path(temporary).resolve()
                config = root / "localappdata/SelfWorkFlow/config/providers.local.yaml"
                sources = []
                with patch.dict(os.environ, {"LOCALAPPDATA": str(root / "localappdata")}), contextlib.redirect_stdout(io.StringIO()):
                    for name in ("local-source", "concurrent-source"):
                        local = root / name
                        (local / "dist/bin").mkdir(parents=True)
                        (local / "dist/bin/codegraph.js").write_text("console.log('local');\n", encoding="utf-8")
                        (local / "package.json").write_text('{"name":"@colbymchenry/codegraph","version":"1"}', encoding="utf-8")
                        _commit(local)
                        self.assertEqual(cli.main(["provider", "configure", "--config-file", str(config),
                                                   "--codegraph-path", str(local), "--replace-existing"]), 0)
                        sources.append(config.read_bytes())
                (root / "concurrent-provider.json").write_bytes(sources[1])
                config.write_bytes(sources[0])
                report = io.StringIO()
                with contextlib.redirect_stdout(report):
                    self.assertEqual(cli.main(["provider", "inspect", "--codegraph-path", str(root / "local-source")]), 0)
                (root / "candidate-source.json").write_text(report.getvalue(), encoding="utf-8")
                (root / "launch.cmd").write_bytes(b"original-launcher")
                (root / "config.toml").write_bytes(b'original = "config"\n')
                result = self._mcp_fault_install(root, "provider-preserve-race", only)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                summary = json.loads((root / "summary.json").read_text(encoding="utf-8-sig"))
                self.assertIn("provider-config-precondition-conflict", summary["reason"])
                self.assertEqual(config.read_bytes(), sources[1])
                self.assertEqual((root / "launch.cmd").read_bytes(), b"original-launcher")
                self.assertEqual((root / "config.toml").read_bytes(), b'original = "config"\n')

    def test_unicode_mcp_launcher_runs_under_ansi_and_preserves_exit_and_codepage(self):
        for only in (False, True):
            with self.subTest(launcher_only=only), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
                parent = Path(temporary).resolve()
                root = parent / "本地 CodeGraph"
                root.mkdir()
                installed = self._mcp_fault_install(root, "success", only)
                self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
                (root / "runtime.js").write_text("console.log('unicode-started'); process.exit(7);\n", encoding="utf-8")
                driver = parent / "driver.cmd"
                driver.write_bytes(
                    b'@echo off\r\nchcp 1252 >nul\r\ncall "%SELFWORKFLOW_TEST_MCP_LAUNCHER%"\r\n'
                    b'set "SELFTEST_EXIT=%ERRORLEVEL%"\r\n'
                    b'for /f "tokens=2 delims=:" %%p in (\'chcp\') do echo restored-codepage:%%p\r\n'
                    b'exit /b %SELFTEST_EXIT%\r\n'
                )
                environment = os.environ.copy()
                environment["SELFWORKFLOW_TEST_MCP_LAUNCHER"] = str(root / "launch.cmd")
                result = subprocess.run(["cmd.exe", "/d", "/c", str(driver)], env=environment,
                                        capture_output=True, text=True, errors="replace")
                self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
                self.assertIn("unicode-started", result.stdout)
                self.assertRegex(result.stdout, r"restored-codepage:\s*1252")

    def test_powershell_help_documents_pinned_matt_logs_and_explicit_apply(self):
        script = self.ROOT / "scripts" / "install-selfworkflow.ps1"
        result = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(script), "-Help",
            ],
            cwd=self.ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = result.stdout.casefold()
        self.assertNotIn("grillmechoice", output)
        self.assertIn("pinned matt pocock", output)
        self.assertIn("grilling and tea are explicit-only", output)
        self.assertIn("one combined", output)
        self.assertIn("reviewer inheriting the parent model", output)
        self.assertIn("superpowers is external-only", output)
        self.assertIn("apply", output)
        self.assertIn("log", output)
        self.assertIn("codegraphpath", output)
        self.assertIn("profile", output)
        self.assertIn("knowledge", output)

    def test_codegraph_install_is_pinned_and_uses_the_official_mcp_entry(self):
        script = (self.ROOT / "scripts" / "install-selfworkflow.ps1").read_text(
            encoding="utf-8"
        ).casefold()
        self.assertIn("@colbymchenry/codegraph v1.6.2", script)
        self.assertIn("codegraph serve --mcp", script)
        self.assertIn("codegraph-runtime-install-failed", script)
        self.assertIn("windowsassetsha256", script)
        self.assertIn("download-andverifyfile", script)
        self.assertNotIn("raw.githubusercontent.com/colbymchenry/codegraph/main/install.ps1", script)
        self.assertNotIn("dependencies\\upstream\\graft", script)

    def test_codegraph_lock_pins_release_metadata_and_asset_hash(self):
        lock = (self.ROOT / "dependencies" / "locks" / "codegraph.lock.yaml").read_text(
            encoding="utf-8"
        ).casefold()
        self.assertIn("releasetag: v1.6.2", lock)
        self.assertIn(
            "windowsasseturl: https://github.com/colbymchenry/codegraph/releases/download/v1.6.2/codegraph-win32-x64.zip",
            lock,
        )
        self.assertRegex(lock, r"windowsassetsha256:\s*sha256:[0-9a-f]{64}")
        self.assertRegex(lock, r"entrysha256:\s*sha256:[0-9a-f]{64}")
        self.assertNotIn("/main/", lock)

    def _fake_runtime(self, root):
        codegraph = root / "codegraph-runtime"
        (codegraph / "bin").mkdir(parents=True, exist_ok=True)
        (codegraph / "lib/dist/bin").mkdir(parents=True, exist_ok=True)
        if not (codegraph / "node.exe").exists():
            shutil.copyfile(shutil.which("node.exe") or shutil.which("node"), codegraph / "node.exe")
        (codegraph / "lib/package.json").write_text('{"name":"@colbymchenry/codegraph","version":"1.6.2"}', encoding="utf-8")
        (codegraph / "lib/dist/bin/codegraph.js").write_text(
            "const a=process.argv.slice(2); console.log(a.includes('--version')?'1.6.2':"
            "a.includes('--help')?'codegraph':JSON.stringify({initialized:true,index:{state:'complete'}}));\n",
            encoding="utf-8")
        (codegraph / "bin" / "codegraph.cmd").write_text(
            "@echo off\r\nexit /b 0\r\n", encoding="utf-8"
        )
        return codegraph

    def _run_installer(self, root, *arguments, env=None):
        environment = (env or os.environ).copy()
        local_app_data = root / "localappdata"
        environment["LOCALAPPDATA"] = str(local_app_data)
        codegraph = self._fake_runtime(root)
        return subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(self.ROOT / "scripts/install-selfworkflow.ps1"),
                "-NonInteractive",
                "-AgentsRoot", str(root / "agents"),
                "-CodexRoot", str(root / "codex"),
                "-StateRoot", str(root / "state"),
                "-ProviderConfigFile",
                str(local_app_data / "SelfWorkFlow/config/providers.local.yaml"),
                "-DependencyRoot", str(root / "dependencies"),
                "-LogRoot", str(root / "logs"),
                "-CodeGraphPath", str(codegraph),
                *arguments,
            ],
            cwd=self.ROOT,
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )

    def _select_preserved_source_with_ansi_default(self, root, config, local, only):
        source = (self.ROOT / "scripts/install-selfworkflow.ps1").read_text(encoding="utf-8")
        start = source.index('    Set-InstallStage "codegraph-runtime" 27')
        body = source[start:source.index("    if ($CodeGraphMcpLauncherOnly) {", start)]
        harness = r'''
param([string]$Root, [string]$ProviderConfigFile, [string]$ExpectedRoot, [string]$Only, [string]$PythonPath)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$script:LogDirectory = $Root
$CodeGraphMcpLauncherOnly = $Only -eq "yes"
$ReplaceCodeGraphOverride = $false
$CodeGraphPath = ""
$codeGraphLock = $null
function Set-InstallStage($Stage,$Code) { }
function Stop-Install($Stage,$Code,$Reason) { throw $Reason }
function Get-Sha256Hex($Path) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($Path)))).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose() }
}
# Emulate Windows PowerShell's ANSI default on machines whose ACP is not UTF-8.
function Get-Content([string]$LiteralPath, [switch]$Raw, [string]$Encoding) {
    $decoder = [Text.Encoding]::GetEncoding(1252)
    if ($Encoding -eq "UTF8") { $decoder = [Text.Encoding]::UTF8 }
    return [IO.File]::ReadAllText($LiteralPath, $decoder)
}
function Invoke-SelfWorkflow($Arguments,$OutputPath) {
    $output = & $PythonPath -m selfworkflow.cli @Arguments
    if ($LASTEXITCODE -ne 0) { throw "fixture-cli-failed" }
    return ($output | Out-String | ConvertFrom-Json)
}
'''
        script = root / "ansi-selection.ps1"
        script.write_text(harness + body + '\nif ($runtimeRoot -ne $ExpectedRoot) { throw "source-path-mismatch" }\n', encoding="utf-8")
        environment = os.environ.copy()
        environment["LOCALAPPDATA"] = str(root / "localappdata")
        environment["PYTHONPATH"] = str(self.ROOT / "src")
        return subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                               str(root), str(config), str(local), "yes" if only else "no", sys.executable],
                              capture_output=True, text=True, env=environment)

    def test_preserved_local_override_keeps_provider_and_mcp_on_the_same_source(self):
        for only in (False, True):
            with self.subTest(launcher_only=only), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
                root = Path(temporary).resolve()
                local = root / "本地 CodeGraph"
                (local / "dist/bin").mkdir(parents=True)
                script = local / "dist/bin/codegraph.js"
                script.write_text("console.log('local fixture');\n", encoding="utf-8")
                (local / "package.json").write_text('{"name":"@colbymchenry/codegraph","version":"1"}', encoding="utf-8")
                _commit(local)
                config = root / "localappdata/SelfWorkFlow/config/providers.local.yaml"
                with patch.dict(os.environ, {"LOCALAPPDATA": str(root / "localappdata")}), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(["provider", "configure", "--config-file", str(config),
                                               "--codegraph-path", str(local)]), 0)
                before_bytes = config.read_bytes()
                self.assertIn("本地".encode("utf-8"), before_bytes)
                self.assertFalse(before_bytes.startswith(b"\xef\xbb\xbf"))
                ansi = self._select_preserved_source_with_ansi_default(root, config, local, only)
                self.assertEqual(ansi.returncode, 0, ansi.stdout + ansi.stderr)
                extra = ["-CodeGraphMcpLauncherOnly"] if only else ["-Profile", "knowledge"]
                result = self._run_installer(root, *extra, "-ConfirmApply")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(config.read_bytes(), before_bytes)
                launcher = root / "localappdata/SelfWorkFlow/bin/codegraph-mcp.cmd"
                self.assertIn(str(script), launcher.read_text(encoding="utf-8"))

    @staticmethod
    def _single_log_directory(root):
        directories = [path for path in (root / "logs").iterdir() if path.is_dir()]
        if len(directories) != 1:
            raise AssertionError(f"expected one log directory, got {directories}")
        return directories[0]

    def test_default_install_publishes_pinned_matt_grill_and_preserves_unmanaged_skill(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary) / "中文 path"
            root.mkdir()
            foreign = root / "agents/skills/grill-me/SKILL.md"
            foreign.parent.mkdir(parents=True)
            foreign.write_text("foreign\n", encoding="utf-8")

            result = self._run_installer(
                root, "-SuperpowersChoice", "Skip", "-ConfirmApply"
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = json.loads(
                (self._single_log_directory(root) / "summary.json").read_text()
            )
            self.assertEqual(summary["status"], "installed")
            self.assertEqual(summary["superpowers"], "external-only")
            self.assertEqual(summary["writeCapability"], "enabled")
            self.assertEqual(summary["cleanupPending"], [])
            self.assertEqual(
                summary["mattSkills"]["commit"],
                "49dd158d1076134a641b33efb035946536778336",
            )
            self.assertTrue(
                (root / "agents/skills/matt-pocock/grill-me/SKILL.md").is_file()
            )
            self.assertEqual(foreign.read_text(encoding="utf-8"), "foreign\n")

    def test_explicit_knowledge_profile_installs_generic_and_optional_backend_skills(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            result = self._run_installer(
                root,
                "-Profile", "knowledge",
                "-SuperpowersChoice", "Skip",
                "-ConfirmApply",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            log_directory = self._single_log_directory(root)
            summary = json.loads((log_directory / "summary.json").read_text())
            self.assertEqual(summary["profile"], "knowledge")
            self.assertTrue(
                (root / "agents/skills/knowledge-backend/SKILL.md").is_file()
            )
            self.assertTrue(
                (root / "agents/skills/kg-selfopenwiki/SKILL.md").is_file()
            )
            self.assertTrue((root / "codex/AGENTS.md").is_file())
            for name in (
                "doctor-before.json", "runtime-manifest.json", "install-plan.json",
                "apply-result.json", "verify-result.json", "doctor-after.json",
            ):
                self.assertTrue((log_directory / name).is_file(), name)

    def test_noninteractive_apply_requires_confirmation_before_any_publish(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            result = self._run_installer(root, "-SuperpowersChoice", "Skip")
            self.assertEqual(result.returncode, 50, result.stdout + result.stderr)
            summary = json.loads(
                (self._single_log_directory(root) / "summary.json").read_text()
            )
            self.assertEqual(summary["stage"], "confirmation")
            self.assertFalse((root / "codex/AGENTS.md").exists())

    def test_non_skip_superpowers_choices_fail_closed_before_publish(self):
        for choice in ("Ask", "Existing", "InstallOfficial"):
            with self.subTest(choice=choice):
                with tempfile.TemporaryDirectory(
                    ignore_cleanup_errors=True
                ) as temporary:
                    root = Path(temporary)
                    result = self._run_installer(
                        root,
                        "-SuperpowersChoice", choice,
                        "-ConfirmApply",
                    )
                    self.assertEqual(
                        result.returncode, 20, result.stdout + result.stderr
                    )
                    summary = json.loads(
                        (self._single_log_directory(root) / "summary.json").read_text()
                    )
                    self.assertEqual(summary["stage"], "preflight")
                    self.assertIn("superpowers-external-only", summary["reason"])
                    self.assertFalse((root / "codex/AGENTS.md").exists())

    def test_one_click_forwards_dsh_root_to_doctor_and_plan(self):
        source = (Path(__file__).resolve().parents[2] / "scripts/install-selfworkflow.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn('[string]$DshRoot = ""', source)
        self.assertIn('@("--dsh-root", $DshRoot)', source)
        self.assertIn('$doctorBeforeArguments = @("doctor"', source)
        self.assertIn('$planArguments = @("install", "plan"', source)
        self.assertIn('+ $DshArguments', source)
        self.assertIn("repeat it on upgrades", source)

    def test_default_install_is_idempotent_and_doctor_matches_published_tree(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            first = self._run_installer(
                root, "-SuperpowersChoice", "Skip", "-ConfirmApply"
            )
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            first_hash = doctor(
                root / "agents", root / "codex", root / "state"
            )["agentsRoot"]["treeHash"]

            second = self._run_installer(
                root, "-SuperpowersChoice", "Skip", "-ConfirmApply"
            )

            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            second_hash = doctor(
                root / "agents", root / "codex", root / "state"
            )["agentsRoot"]["treeHash"]
            self.assertEqual(second_hash, first_hash)
            codex_config = (root / "codex/config.toml").read_text(encoding="utf-8")
            self.assertEqual(codex_config.count("[mcp_servers.codegraph]"), 1)


if __name__ == "__main__":
    unittest.main()
