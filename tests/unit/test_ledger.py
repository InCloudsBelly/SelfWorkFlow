from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest


HASHES = ["sha256:" + str(index) * 64 for index in range(1, 6)]


def _plan():
    return {
        "schemaVersion": 2, "requestHash": HASHES[0], "capabilitySnapshotHash": HASHES[1],
        "pipelineHash": HASHES[2], "policyHash": HASHES[3], "catalogHash": HASHES[4],
        "planHash": "sha256:" + "a" * 64, "strength": "Light",
        "stages": [
            {"stageId": "designed", "failureOwner": "designed", "applicability": "applicable", "slots": [
                {"slotId": "design.primary", "cardinality": "exactly-one", "applicability": "applicable", "selectedModules": ["design-light"], "gates": []},
                {"slotId": "design.specialists", "cardinality": "zero-or-many", "applicability": "applicable", "selectedModules": [], "gates": []},
            ]},
            {"stageId": "planned", "failureOwner": "designed", "applicability": "applicable", "slots": [
                {"slotId": "plan.gate", "cardinality": "gate", "applicability": "applicable", "selectedModules": ["plan-gate"], "gates": ["plan-gate"]},
            ]},
        ],
    }


class LedgerTests(unittest.TestCase):
    def test_ledger_binds_plan_and_permits_only_pending_active_terminal(self):
        from selfworkflow.ledger import new_ledger, transition_stage, validate_ledger

        plan = _plan()
        initial = new_ledger(plan)
        active = transition_stage(initial, plan, "designed", "active", capability_snapshot_hash=plan["capabilitySnapshotHash"], attempt_ref="attempt-1")
        passed = transition_stage(active, plan, "designed", "passed", capability_snapshot_hash=plan["capabilitySnapshotHash"])

        self.assertEqual(initial["stages"][0]["status"], "pending")
        self.assertEqual(active["stages"][0]["attempts"], ["attempt-1"])
        self.assertEqual(passed["stages"][0]["status"], "passed")
        self.assertTrue(validate_ledger(passed, plan, plan["capabilitySnapshotHash"])["valid"])

    def test_rejects_two_active_stages_invalid_transition_and_changed_snapshot(self):
        from selfworkflow.ledger import LedgerError, new_ledger, transition_stage, validate_ledger

        plan = _plan()
        ledger = new_ledger(plan)
        with self.assertRaises(LedgerError):
            transition_stage(ledger, plan, "planned", "passed", capability_snapshot_hash=plan["capabilitySnapshotHash"])
        changed = validate_ledger(ledger, plan, "sha256:" + "f" * 64)
        self.assertFalse(changed["valid"])
        self.assertIn("capability-snapshot-changed", changed["reasonCodes"])
        attack = deepcopy(ledger)
        attack["stages"][0]["status"] = "active"
        attack["stages"][1]["status"] = "active"
        self.assertFalse(validate_ledger(attack, plan, plan["capabilitySnapshotHash"])["valid"])

    def test_optional_skip_gate_binding_failure_owner_and_supersede(self):
        from selfworkflow.ledger import (
            LedgerError, failure_owner_for, new_ledger, record_gate_result,
            record_runtime_skip, supersede_ledger,
        )

        plan = _plan()
        ledger = new_ledger(plan)
        skipped = record_runtime_skip(ledger, plan, "designed", "design.specialists", "evidence-1")
        self.assertEqual(skipped["stages"][0]["runtimeSkips"], ["design.specialists:evidence-1"])
        with self.assertRaises(LedgerError):
            record_runtime_skip(ledger, plan, "designed", "design.primary", "evidence-1")
        gated = record_gate_result(ledger, plan, "planned", "plan-gate", "gate-result-1")
        self.assertEqual(gated["stages"][1]["gateResults"], ["plan-gate:gate-result-1"])
        self.assertEqual(failure_owner_for(plan, "planned"), "designed")
        superseded = supersede_ledger(ledger, "sha256:" + "b" * 64)
        self.assertEqual(superseded["status"], "superseded")
        self.assertEqual(superseded["supersededByPlanHash"], "sha256:" + "b" * 64)

    def test_cli_validation_is_read_only(self):
        from selfworkflow.cli import main
        from selfworkflow.ledger import new_ledger

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            plan, ledger = _plan(), new_ledger(_plan())
            plan_path, ledger_path = root / "plan.json", root / "ledger.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
            before = ledger_path.read_bytes()
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["ledger", "validate", "--ledger", str(ledger_path), "--plan", str(plan_path)])
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(output.getvalue())["valid"])
            self.assertEqual(ledger_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
