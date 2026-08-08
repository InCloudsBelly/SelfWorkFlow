from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest

from selfworkflow.installer import tree_hash


def _commit(root):
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
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

    def test_powershell_help_documents_grill_choices_logs_and_explicit_apply(self):
        script = self.ROOT / "scripts" / "install-selfworkflow.ps1"
        self.assertTrue(script.is_file())
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Help",
            ],
            cwd=self.ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = result.stdout.casefold()
        self.assertIn("grillmechoice", output)
        self.assertIn("install", output)
        self.assertIn("skip", output)
        self.assertIn("apply", output)
        self.assertIn("log", output)

    def _run_installer(self, root, *arguments, env=None):
        return subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.ROOT / "scripts/install-selfworkflow.ps1"),
                "-NonInteractive",
                "-AgentsRoot",
                str(root / "agents"),
                "-CodexRoot",
                str(root / "codex"),
                "-StateRoot",
                str(root / "state"),
                "-DependencyRoot",
                str(root / "dependencies"),
                "-LogRoot",
                str(root / "logs"),
                *arguments,
            ],
            cwd=self.ROOT,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    @staticmethod
    def _single_log_directory(root):
        directories = [path for path in (root / "logs").iterdir() if path.is_dir()]
        if len(directories) != 1:
            raise AssertionError(f"expected one log directory, got {directories}")
        return directories[0]

    def test_noninteractive_missing_grill_requires_an_explicit_choice_and_logs_failure(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            result = self._run_installer(
                root,
                "-SuperpowersChoice",
                "Skip",
                "-ConfirmApply",
            )
            self.assertEqual(result.returncode, 30, result.stdout + result.stderr)
            log_directory = self._single_log_directory(root)
            self.assertTrue((log_directory / "install.log").is_file())
            summary = json.loads((log_directory / "summary.json").read_text())
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["stage"], "grill-selection")
            self.assertFalse((root / "codex/AGENTS.md").exists())

    def test_skip_grill_installs_verified_core_without_grill_and_records_readonly_limit(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary) / "中文 path"
            root.mkdir()
            result = self._run_installer(
                root,
                "-GrillMeChoice",
                "Skip",
                "-SuperpowersChoice",
                "Skip",
                "-ConfirmApply",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            log_directory = self._single_log_directory(root)
            summary = json.loads((log_directory / "summary.json").read_text())
            self.assertEqual(summary["status"], "installed")
            self.assertEqual(summary["grillMe"], "skipped")
            self.assertEqual(summary["writeCapability"], "paused-superpowers-unavailable")
            self.assertFalse((root / "agents/skills/grill-me").exists())
            self.assertTrue((root / "codex/AGENTS.md").is_file())
            for name in (
                "doctor-before.json",
                "runtime-manifest.json",
                "install-plan.json",
                "apply-result.json",
                "verify-result.json",
                "doctor-after.json",
            ):
                self.assertTrue((log_directory / name).is_file(), name)

    def test_noninteractive_apply_requires_confirmation_before_any_publish(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            result = self._run_installer(
                root,
                "-GrillMeChoice",
                "Skip",
                "-SuperpowersChoice",
                "Skip",
            )
            self.assertEqual(result.returncode, 50, result.stdout + result.stderr)
            summary = json.loads(
                (self._single_log_directory(root) / "summary.json").read_text()
            )
            self.assertEqual(summary["stage"], "confirmation")
            self.assertFalse((root / "codex/AGENTS.md").exists())

    def test_unmanaged_grill_conflict_pauses_without_overwrite(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            foreign = root / "agents/skills/grill-me/SKILL.md"
            foreign.parent.mkdir(parents=True)
            foreign.write_text("foreign\n", encoding="utf-8")
            result = self._run_installer(
                root,
                "-GrillMeChoice",
                "Install",
                "-SuperpowersChoice",
                "Skip",
                "-ConfirmApply",
            )
            self.assertEqual(result.returncode, 40, result.stdout + result.stderr)
            self.assertEqual(foreign.read_text(encoding="utf-8"), "foreign\n")
            summary = json.loads(
                (self._single_log_directory(root) / "summary.json").read_text()
            )
            self.assertEqual(summary["stage"], "plan")

    def test_post_apply_superpowers_conflict_rolls_back_only_current_publication(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            superpowers = root / "source"
            for name in (
                "brainstorming",
                "writing-plans",
                "test-driven-development",
                "systematic-debugging",
                "requesting-code-review",
                "receiving-code-review",
                "verification-before-completion",
            ):
                skill = superpowers / "skills" / name / "SKILL.md"
                skill.parent.mkdir(parents=True, exist_ok=True)
                skill.write_text(name + "\n", encoding="utf-8")
            _commit(superpowers)
            foreign = root / "agents/skills/superpowers/foreign.txt"
            foreign.parent.mkdir(parents=True)
            foreign.write_text("preserve\n", encoding="utf-8")

            result = self._run_installer(
                root,
                "-GrillMeChoice",
                "Install",
                "-SuperpowersChoice",
                "Existing",
                "-SuperpowersSource",
                str(superpowers),
                "-ConfirmApply",
            )

            self.assertEqual(result.returncode, 70, result.stdout + result.stderr)
            summary = json.loads(
                (self._single_log_directory(root) / "summary.json").read_text()
            )
            self.assertEqual(summary["stage"], "verify")
            self.assertEqual(summary["rollback"], "rolled-back")
            self.assertEqual(foreign.read_text(encoding="utf-8"), "preserve\n")
            self.assertFalse((root / "agents/skills/grill-me/SKILL.md").exists())
            self.assertFalse((root / "codex/AGENTS.md").exists())

    def test_install_grill_and_existing_superpowers_source_are_really_discoverable(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            superpowers = root / "selected superpowers"
            for name in (
                "brainstorming",
                "writing-plans",
                "test-driven-development",
                "systematic-debugging",
                "requesting-code-review",
                "receiving-code-review",
                "verification-before-completion",
            ):
                skill = superpowers / "skills" / name / "SKILL.md"
                skill.parent.mkdir(parents=True, exist_ok=True)
                skill.write_text(name + "\n", encoding="utf-8")
            _commit(superpowers)

            result = self._run_installer(
                root,
                "-GrillMeChoice",
                "Install",
                "-SuperpowersChoice",
                "Existing",
                "-SuperpowersSource",
                str(superpowers),
                "-ConfirmApply",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((root / "agents/skills/grill-me/SKILL.md").is_file())
            staged = root / "agents/skills/superpowers"
            self.assertTrue(staged.is_dir())
            self.assertTrue((staged / "brainstorming/SKILL.md").is_file())
            self.assertTrue((staged / ".selfworkflow-source.json").is_file())
            log_directory = self._single_log_directory(root)
            install_log = (log_directory / "install.log").read_text(encoding="utf-8")
            stage_position = install_log.rfind("Running selfworkflow source stage")
            doctor_position = install_log.rfind("Running selfworkflow doctor")
            self.assertNotEqual(stage_position, -1)
            self.assertLess(stage_position, doctor_position)
            doctor_after = json.loads(
                (log_directory / "doctor-after.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                doctor_after["agentsRoot"]["treeHash"], tree_hash(root / "agents")
            )
            summary = json.loads(
                (log_directory / "summary.json").read_text()
            )
            self.assertEqual(summary["grillMe"], "installed")
            self.assertEqual(summary["superpowers"]["supportStatus"], "supported")
            self.assertEqual(summary["writeCapability"], "enabled")

            repeated = self._run_installer(
                root,
                "-GrillMeChoice",
                "Install",
                "-SuperpowersChoice",
                "Existing",
                "-SuperpowersSource",
                str(superpowers),
                "-ConfirmApply",
            )
            self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)

    def test_approved_official_clone_path_is_exercised_without_network(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            mirror = root / "official mirror"
            for name in (
                "brainstorming",
                "writing-plans",
                "test-driven-development",
                "systematic-debugging",
                "requesting-code-review",
                "receiving-code-review",
                "verification-before-completion",
            ):
                skill = mirror / "skills" / name / "SKILL.md"
                skill.parent.mkdir(parents=True, exist_ok=True)
                skill.write_text(name + "\n", encoding="utf-8")
            _commit(mirror)
            environment = os.environ.copy()
            environment.update(
                {
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": f"url.{mirror.resolve().as_uri()}.insteadOf",
                    "GIT_CONFIG_VALUE_0": "https://github.com/obra/superpowers.git",
                }
            )

            result = self._run_installer(
                root,
                "-GrillMeChoice",
                "Install",
                "-SuperpowersChoice",
                "InstallOfficial",
                "-ConfirmApply",
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertLess(
                result.stdout.index(
                    "Cloning the approved official Superpowers source."
                ),
                result.stdout.index("Plan status:"),
            )
            self.assertIn("Agents root:", result.stdout)
            self.assertIn("Artifact files:", result.stdout)
            self.assertIn("Superpowers commit:", result.stdout)
            self.assertIn("Superpowers inventoryHash:", result.stdout)
            self.assertTrue(
                (root / "dependencies/superpowers/.git").is_dir()
            )
            self.assertTrue(
                (root / "agents/skills/superpowers/brainstorming/SKILL.md").is_file()
            )


if __name__ == "__main__":
    unittest.main()
