from pathlib import Path
from contextlib import contextmanager
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
            self.assertIn("For ordinary tasks", agents_text)
            self.assertIn("do not create a PlanGraph or RunLedger", agents_text)
            self.assertIn("explicitly contract-managed", agents_text)
            self.assertNotIn("run `selfworkflow resolve", agents_text)
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

    def test_apply_rejects_wrong_confirmation_and_managed_target_or_artifact_drift(self):
        for drift in ("target", "state", "artifact"):
            with self.subTest(drift=drift):
                with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
                    root = Path(temporary)
                    artifact = create_artifact(root)
                    agents, codex, state = root / "agents", root / "codex", root / "state"
                    plan = create_install_plan(artifact, agents, codex, state, "0.1.0")
                    with self.assertRaises(InstallerError):
                        apply_install_plan(plan, "sha256:" + "0" * 64)
                    if drift == "target":
                        managed = agents / "skills/sample-skill/SKILL.md"
                        managed.parent.mkdir(parents=True)
                        managed.write_text("drift\n", encoding="utf-8")
                    elif drift == "state":
                        state.mkdir()
                        (state / "current-manifest.json").write_text(
                            "{}\n", encoding="utf-8"
                        )
                    else:
                        (artifact / "WORKFLOW.md").write_text("drift\n", encoding="utf-8")
                    with self.assertRaises(InstallerError):
                        apply_install_plan(plan, plan["planHash"])

    def test_apply_allows_unmanaged_target_drift(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0")
            codex.mkdir()
            (codex / "session.jsonl").write_bytes(b"x" * (8 * 1024 * 1024 + 1))

            result = apply_install_plan(plan, plan["planHash"])

            self.assertEqual(result["status"], "applied")
            self.assertTrue((codex / "session.jsonl").is_file())

    def test_apply_rechecks_artifact_and_target_after_lock_acquisition(self):
        from selfworkflow import installer

        for drift in ("target", "artifact"):
            with self.subTest(drift=drift):
                with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
                    root = Path(temporary)
                    artifact = create_artifact(root)
                    agents, codex, state = (
                        root / "agents", root / "codex", root / "state"
                    )
                    plan = create_install_plan(
                        artifact, agents, codex, state, "0.1.0"
                    )

                    @contextmanager
                    def drift_while_waiting(_state):
                        if drift == "target":
                            managed = agents / "skills/sample-skill/SKILL.md"
                            managed.parent.mkdir(parents=True, exist_ok=True)
                            managed.write_text(
                                "concurrent\n", encoding="utf-8"
                            )
                        else:
                            (artifact / "WORKFLOW.md").write_text(
                                "concurrent artifact\n", encoding="utf-8"
                            )
                        yield

                    with mock.patch(
                        "selfworkflow.installer.exclusive_install_lock",
                        side_effect=drift_while_waiting,
                    ):
                        with self.assertRaisesRegex(
                            InstallerError,
                            "target-drift" if drift == "target" else "artifact-drift",
                        ):
                            apply_install_plan(plan, plan["planHash"])

                    managed = agents / "skills/sample-skill/SKILL.md"
                    if drift == "target":
                        self.assertEqual(
                            managed.read_text(encoding="utf-8"), "concurrent\n"
                        )
                    else:
                        self.assertFalse(managed.exists())

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
            real_operation = installer._publish_operation
            calls = 0

            def fail_second_operation(*arguments, **keywords):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected-operation-failure")
                return real_operation(*arguments, **keywords)

            with mock.patch(
                "selfworkflow.installer._publish_operation",
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

    def test_interrupt_after_publish_has_a_persisted_intent_and_rolls_back(self):
        from selfworkflow import installer

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0")
            real_write = installer._atomic_write
            interrupted = False

            def publish_then_interrupt(path, content):
                nonlocal interrupted
                real_write(path, content)
                if not interrupted:
                    interrupted = True
                    raise SystemExit("injected-interrupt")

            with mock.patch(
                "selfworkflow.installer._atomic_write",
                side_effect=publish_then_interrupt,
            ):
                with self.assertRaises(SystemExit):
                    apply_install_plan(plan, plan["planHash"])

            transactions = list((state / "transactions").glob("*.json"))
            self.assertEqual(len(transactions), 1)
            transaction = json.loads(transactions[0].read_text(encoding="utf-8"))
            self.assertEqual(transaction["state"], "rolled-back")
            self.assertGreaterEqual(len(transaction["operations"]), 1)
            self.assertFalse((agents / "skills/sample-skill/SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
