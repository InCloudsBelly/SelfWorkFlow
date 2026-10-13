from pathlib import Path
import json
import os
import re
import subprocess
import tempfile
import unittest

from selfworkflow.installer import doctor


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
function Invoke-SelfWorkflow($Arguments, $OutputPath) {
    if ($Arguments[0] -eq "install" -and $Arguments[1] -eq "apply") {
        return [pscustomobject]@{status="applied";manifestPath="fixture-manifest";transactionPath="fixture-transaction";cleanupPending=@("installer-lock-release-failed")}
    }
    if ($Arguments[1] -eq "verify") { return [pscustomobject]@{status="verified"} }
    if ($Arguments[1] -eq "rollback-plan") {
        Write-JsonFile $Arguments[5] ([ordered]@{planHash="rollback-hash"})
        return
    }
    if ($Arguments[1] -eq "rollback") { throw "installer-locked" }
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
        self.assertIn("strength-routed grilling", output)
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

    def _run_installer(self, root, *arguments, env=None):
        environment = (env or os.environ).copy()
        local_app_data = root / "localappdata"
        environment["LOCALAPPDATA"] = str(local_app_data)
        codegraph = root / "codegraph-runtime"
        (codegraph / "bin").mkdir(parents=True, exist_ok=True)
        (codegraph / "bin" / "codegraph.cmd").write_text(
            "@echo off\r\nexit /b 0\r\n", encoding="utf-8"
        )
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
