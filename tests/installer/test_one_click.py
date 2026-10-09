from pathlib import Path
import json
import os
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
            self.assertIn("selfworkflow.cli", launcher_text)
            self.assertIn("managed", launcher_text)
            graft_mcp = root / "localappdata/SelfWorkFlow/bin/graft-mcp.cmd"
            self.assertTrue(graft_mcp.is_file())
            graft_mcp_text = graft_mcp.read_text(encoding="utf-8").casefold()
            self.assertIn("official graft mcp launcher", graft_mcp_text)
            self.assertIn(" mcp ", graft_mcp_text)
            self.assertIn("%cd%", graft_mcp_text)
            codex_config = (root / "codex/config.toml").read_text(encoding="utf-8")
            self.assertIn("# selfworkflow:graft-mcp:begin", codex_config)
            self.assertIn("[mcp_servers.graft]", codex_config)
            self.assertIn("graft-mcp.cmd", codex_config)

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
            self.assertEqual([item["providerId"] for item in providers], ["graft"])

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
        self.assertNotIn("codegraphoverridechoice", output)
        self.assertNotIn("codegraphpath", output)
        self.assertIn("profile", output)
        self.assertIn("knowledge", output)

    def test_graft_install_rebuilds_native_packages_and_smoke_checks_runtime(self):
        script = (self.ROOT / "scripts" / "install-selfworkflow.ps1").read_text(
            encoding="utf-8"
        ).casefold()
        self.assertIn('"rebuild", "--foreground-scripts"', script)
        self.assertIn("graft-native-build-failed", script)
        self.assertIn("graft-runtime-check-failed", script)
        self.assertNotIn('"prune", "--omit=dev"', script)

    def _run_installer(self, root, *arguments, env=None):
        environment = (env or os.environ).copy()
        local_app_data = root / "localappdata"
        environment["LOCALAPPDATA"] = str(local_app_data)
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
            self.assertEqual(
                summary["mattSkills"]["commit"],
                "b0618bc436ad893b3c5e84e55fba86586d34a404",
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
            self.assertEqual(codex_config.count("[mcp_servers.graft]"), 1)


if __name__ == "__main__":
    unittest.main()
