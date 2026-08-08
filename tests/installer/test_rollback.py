from pathlib import Path
import json
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
