from pathlib import Path
import tempfile
import unittest

from selfworkflow.installer import (
    InstallerError,
    apply_install_plan,
    create_install_plan,
    verify_install,
)
from tests.installer.support import create_artifact


class InstallApplyTests(unittest.TestCase):
    def test_apply_preserves_unmanaged_content_and_verify_is_idempotent(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            existing = agents / "skills" / "existing" / "SKILL.md"
            existing.parent.mkdir(parents=True)
            existing.write_text("existing\n", encoding="utf-8")
            codex.mkdir()
            (codex / "AGENTS.md").write_text("user content\n", encoding="utf-8")
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0")

            result = apply_install_plan(plan, plan["planHash"])

            self.assertEqual(result["status"], "applied")
            self.assertEqual(existing.read_text(encoding="utf-8"), "existing\n")
            agents_text = (codex / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("user content", agents_text)
            self.assertEqual(agents_text.count("<!-- selfworkflow:begin -->"), 1)
            self.assertTrue(
                (agents / "skills/sample-skill/SKILL.md").is_file()
            )
            self.assertEqual(verify_install(Path(result["manifestPath"]))["status"], "verified")
            second = create_install_plan(artifact, agents, codex, state, "0.1.0")
            self.assertEqual(second["status"], "already-installed")

    def test_apply_rejects_wrong_confirmation_and_target_or_artifact_drift(self):
        for drift in ("target", "artifact"):
            with self.subTest(drift=drift):
                with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
                    root = Path(temporary)
                    artifact = create_artifact(root)
                    agents, codex, state = root / "agents", root / "codex", root / "state"
                    plan = create_install_plan(artifact, agents, codex, state, "0.1.0")
                    with self.assertRaises(InstallerError):
                        apply_install_plan(plan, "sha256:" + "0" * 64)
                    if drift == "target":
                        agents.mkdir()
                        (agents / "drift.txt").write_text("drift\n", encoding="utf-8")
                    else:
                        (artifact / "WORKFLOW.md").write_text("drift\n", encoding="utf-8")
                    with self.assertRaises(InstallerError):
                        apply_install_plan(plan, plan["planHash"])


if __name__ == "__main__":
    unittest.main()
