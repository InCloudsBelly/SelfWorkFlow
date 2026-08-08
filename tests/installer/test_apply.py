from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

from jsonschema import Draft202012Validator

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
            manifest = json.loads(Path(result["manifestPath"]).read_text(encoding="utf-8"))
            schema = json.loads(
                (Path(__file__).resolve().parents[2] / "schemas/install-manifest.schema.json")
                .read_text(encoding="utf-8")
            )
            Draft202012Validator(schema).validate(manifest)
            self.assertEqual(manifest["profile"], "custom-unverified")
            second = create_install_plan(artifact, agents, codex, state, "0.1.0")
            self.assertEqual(second["status"], "already-installed")

    def test_already_installed_is_bound_to_the_exact_target_roots(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            state = root / "state"
            first = create_install_plan(
                artifact, root / "agents-a", root / "codex-a", state, "0.1.0"
            )
            apply_install_plan(first, first["planHash"])

            second = create_install_plan(
                artifact, root / "agents-b", root / "codex-b", state, "0.1.0"
            )
            self.assertEqual(second["status"], "ready")
            applied = apply_install_plan(second, second["planHash"])
            self.assertEqual(applied["status"], "applied")
            self.assertTrue((root / "agents-b/skills/sample-skill/SKILL.md").is_file())

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

    def test_apply_failure_after_first_write_automatically_restores_targets(self):
        from selfworkflow import installer

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            codex.mkdir()
            agents_file = codex / "AGENTS.md"
            agents_file.write_text("user content\n", encoding="utf-8")
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0")
            real_operation = installer._operation
            calls = 0

            def fail_second_operation(*arguments, **keywords):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected-operation-failure")
                return real_operation(*arguments, **keywords)

            with mock.patch(
                "selfworkflow.installer._operation",
                side_effect=fail_second_operation,
            ):
                with self.assertRaises(InstallerError):
                    apply_install_plan(plan, plan["planHash"])

            self.assertEqual(
                agents_file.read_text(encoding="utf-8"), "user content\n"
            )
            self.assertFalse((agents / "skills/sample-skill/SKILL.md").exists())
            transactions = list((state / "transactions").glob("*.json"))
            self.assertEqual(len(transactions), 1)
            transaction = json.loads(transactions[0].read_text(encoding="utf-8"))
            self.assertEqual(transaction["state"], "rolled-back")


if __name__ == "__main__":
    unittest.main()
