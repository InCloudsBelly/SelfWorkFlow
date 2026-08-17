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
    apply_rollback_plan,
    create_install_plan,
    create_rollback_plan,
)
from tests.installer.support import create_artifact


class RollbackTests(unittest.TestCase):
    def test_rollback_restores_only_transaction_changes_and_rejects_drift(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            codex.mkdir()
            original = codex / "AGENTS.md"
            original.write_text("user content\n", encoding="utf-8")
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0")
            applied = apply_install_plan(plan, plan["planHash"])
            rollback = create_rollback_plan(
                Path(applied["transactionPath"]), state / "rollback.json"
            )
            schema = json.loads(
                (Path(__file__).resolve().parents[2] / "schemas/rollback-plan.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(rollback)
            self.assertEqual(
                schema["properties"]["operations"]["items"]["type"], "object"
            )
            pending = [schema]
            while pending:
                value = pending.pop()
                if isinstance(value, dict):
                    if value.get("type") == "object":
                        self.assertFalse(value.get("additionalProperties", True))
                    pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)
            installed_bytes = original.read_bytes()

            original.write_text("later user edit\n", encoding="utf-8")
            with self.assertRaises(InstallerError):
                apply_rollback_plan(rollback, rollback["planHash"])
            original.write_bytes(installed_bytes)
            result = apply_rollback_plan(rollback, rollback["planHash"])
            self.assertEqual(result["status"], "rolled-back")
            self.assertEqual(original.read_text(encoding="utf-8"), "user content\n")
            self.assertFalse((state / "current-manifest.json").exists())

    def test_rollback_plan_is_invalidated_when_transaction_record_changes(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0")
            applied = apply_install_plan(plan, plan["planHash"])
            transaction_path = Path(applied["transactionPath"])
            rollback = create_rollback_plan(transaction_path)
            transaction_path.write_text(
                transaction_path.read_text(encoding="utf-8") + " ", encoding="utf-8"
            )
            with self.assertRaises(InstallerError):
                apply_rollback_plan(rollback, rollback["planHash"])

    def test_rollback_rechecks_target_after_lock_and_preserves_concurrent_edit(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            codex.mkdir()
            target = codex / "AGENTS.md"
            target.write_text("user content\n", encoding="utf-8")
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0")
            applied = apply_install_plan(plan, plan["planHash"])
            rollback = create_rollback_plan(applied["transactionPath"])

            @contextmanager
            def edit_before_lock_yields(_state):
                target.write_text("concurrent user edit\n", encoding="utf-8")
                yield

            with mock.patch(
                "selfworkflow.installer.exclusive_install_lock",
                side_effect=edit_before_lock_yields,
            ):
                with self.assertRaisesRegex(InstallerError, "rollback-target-drift"):
                    apply_rollback_plan(rollback, rollback["planHash"])

            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "concurrent user edit\n",
            )

    def test_interrupted_rollback_persists_progress_and_resumes_remaining_operations(self):
        from selfworkflow import installer

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = create_artifact(root)
            agents, codex, state = root / "agents", root / "codex", root / "state"
            codex.mkdir()
            original = codex / "AGENTS.md"
            original.write_text("user content\n", encoding="utf-8")
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0")
            applied = apply_install_plan(plan, plan["planHash"])
            transaction_path = Path(applied["transactionPath"])
            rollback = create_rollback_plan(transaction_path)
            real_write = installer.write_json_atomic
            interrupted = False

            def persist_then_interrupt(path, value):
                nonlocal interrupted
                real_write(path, value)
                if (
                    not interrupted
                    and path == transaction_path
                    and value.get("state") == "rolling-back"
                    and any(
                        item.get("phase") == "rolled-back"
                        for item in value.get("operations", [])
                    )
                ):
                    interrupted = True
                    raise SystemExit("injected rollback interruption")

            with mock.patch(
                "selfworkflow.installer.write_json_atomic",
                side_effect=persist_then_interrupt,
            ):
                with self.assertRaises(SystemExit):
                    apply_rollback_plan(rollback, rollback["planHash"])

            interrupted_state = json.loads(transaction_path.read_text(encoding="utf-8"))
            self.assertEqual(interrupted_state["state"], "rolling-back")
            self.assertTrue(any(
                item.get("phase") == "rolled-back"
                for item in interrupted_state["operations"]
            ))
            resumed = create_rollback_plan(transaction_path)
            self.assertLess(len(resumed["operations"]), len(rollback["operations"]))
            result = apply_rollback_plan(resumed, resumed["planHash"])
            self.assertEqual(result["status"], "rolled-back")
            self.assertEqual(original.read_text(encoding="utf-8"), "user content\n")


if __name__ == "__main__":
    unittest.main()
