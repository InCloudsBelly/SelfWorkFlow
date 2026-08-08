from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest


HASHES = ["sha256:" + str(index) * 64 for index in range(1, 6)]


def _plan():
    from selfworkflow.capability_snapshot import normalize_capability_snapshot
    from selfworkflow.pipeline import canonical_hash

    snapshot = _snapshot()
    snapshot_hash = normalize_capability_snapshot(snapshot)[1]
    plan = {
        "schemaVersion": 2, "requestHash": HASHES[0], "capabilitySnapshotHash": snapshot_hash,
        "pipelineHash": HASHES[2], "policyHash": HASHES[3], "catalogHash": HASHES[4],
        "strength": "Light",
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
    plan["planHash"] = canonical_hash(plan)
    return plan


def _snapshot():
    return {
        "schemaVersion": 1, "capturedAt": "2026-08-08T00:00:00Z",
        "evidence": [{
            "name": "filesystem-read", "provider": "test-host",
            "subject": {"kind": "host", "id": "fixture", "version": "1", "build": "1", "sourceLock": HASHES[0]},
            "state": "supported", "observedAt": "2020-01-01T00:00:00Z", "validUntil": "2099-01-01T00:00:00Z",
            "evidenceRef": "fixture", "evidenceHash": HASHES[1],
        }],
    }


class LedgerTests(unittest.TestCase):
    def test_ledger_binds_plan_and_permits_only_pending_active_terminal(self):
        from selfworkflow.ledger import new_ledger, record_slot_result, transition_stage, validate_ledger

        plan = _plan()
        initial = new_ledger(plan)
        active = transition_stage(initial, plan, "designed", "active", capability_snapshot=_snapshot(), attempt_ref="attempt-1")
        with_result = record_slot_result(active, plan, "designed", "design-light", "result-1")
        passed = transition_stage(with_result, plan, "designed", "passed", capability_snapshot=_snapshot())

        self.assertEqual(initial["stages"][0]["status"], "pending")
        self.assertEqual(active["stages"][0]["attempts"], [
            {"attemptRef": "attempt-1", "ordinal": 1, "previousAttemptRef": None}
        ])
        self.assertEqual(passed["stages"][0]["status"], "passed")
        self.assertTrue(validate_ledger(passed, plan, _snapshot())["valid"])

    def test_rejects_two_active_stages_invalid_transition_and_changed_snapshot(self):
        from selfworkflow.ledger import LedgerError, new_ledger, transition_stage, validate_ledger

        plan = _plan()
        ledger = new_ledger(plan)
        with self.assertRaises(LedgerError):
            transition_stage(ledger, plan, "planned", "passed", capability_snapshot=_snapshot())
        with self.assertRaises(LedgerError):
            transition_stage(ledger, plan, "planned", "active", capability_snapshot=_snapshot(), attempt_ref="attempt-1")
        changed_snapshot = deepcopy(_snapshot())
        changed_snapshot["evidence"][0]["subject"]["build"] = "2"
        changed = validate_ledger(ledger, plan, changed_snapshot)
        self.assertFalse(changed["valid"])
        self.assertIn("capability-snapshot-changed", changed["reasonCodes"])
        attack = deepcopy(ledger)
        attack["stages"][0]["status"] = "active"
        attack["stages"][1]["status"] = "active"
        self.assertFalse(validate_ledger(attack, plan, _snapshot())["valid"])

    def test_rejects_blocked_or_tampered_plan_and_missing_required_results(self):
        from selfworkflow.ledger import LedgerError, new_ledger, transition_stage, validate_ledger

        plan = _plan()
        blocked = deepcopy(plan)
        blocked["stages"][0]["applicability"] = "blocked"
        with self.assertRaises(LedgerError):
            new_ledger(blocked)
        tampered = deepcopy(plan)
        tampered["stages"][0]["failureOwner"] = "planned"
        self.assertFalse(validate_ledger(new_ledger(plan), tampered, _snapshot())["valid"])
        active = transition_stage(new_ledger(plan), plan, "designed", "active", capability_snapshot=_snapshot(), attempt_ref="attempt-1")
        with self.assertRaises(LedgerError):
            transition_stage(active, plan, "designed", "passed", capability_snapshot=_snapshot())

        forged = new_ledger(plan)
        forged["stages"][0]["status"] = "passed"
        forged["stages"][1]["status"] = "passed"
        forged["status"] = "completed"
        invalid = validate_ledger(forged, plan, _snapshot())
        self.assertFalse(invalid["valid"])
        self.assertIn("stage-results-incomplete", invalid["reasonCodes"])

    def test_optional_skip_gate_binding_failure_owner_and_supersede(self):
        from selfworkflow.ledger import (
            LedgerError, failure_owner_for, new_ledger, record_gate_result,
            record_runtime_skip, record_slot_result, supersede_ledger,
            transition_stage,
        )
        from selfworkflow.pipeline import canonical_hash

        plan = _plan()
        plan["stages"][0]["slots"][1]["selectedModules"] = ["design-grill-me"]
        plan.pop("planHash")
        plan["planHash"] = canonical_hash(plan)
        ledger = new_ledger(plan)
        active_design = transition_stage(ledger, plan, "designed", "active", capability_snapshot=_snapshot(), attempt_ref="attempt-1")
        skipped = record_runtime_skip(
            active_design, plan, "designed", "design.specialists", "fixture",
            capability_snapshot=_snapshot(),
        )
        self.assertEqual(skipped["stages"][0]["runtimeSkips"], [{
            "attemptRef": "attempt-1", "slotId": "design.specialists",
            "evidenceRef": "fixture",
        }])
        with self.assertRaises(LedgerError):
            record_runtime_skip(
                active_design, plan, "designed", "design.primary", "fixture",
                capability_snapshot=_snapshot(),
            )
        with self.assertRaises(LedgerError):
            record_runtime_skip(
                active_design, plan, "designed", "design.specialists", "missing",
                capability_snapshot=_snapshot(),
            )
        design_result = record_slot_result(skipped, plan, "designed", "design-light", "result-1")
        designed = transition_stage(design_result, plan, "designed", "passed", capability_snapshot=_snapshot())
        active_plan = transition_stage(designed, plan, "planned", "active", capability_snapshot=_snapshot(), attempt_ref="attempt-2")
        gated = record_gate_result(active_plan, plan, "planned", "plan-gate", "gate-result-1")
        self.assertEqual(gated["stages"][1]["gateResults"], [{
            "attemptRef": "attempt-2", "gateId": "plan-gate",
            "outcome": "passed", "resultRef": "gate-result-1",
        }])
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
            plan_path, ledger_path, snapshot_path = root / "plan.json", root / "ledger.json", root / "snapshot.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
            snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
            before = ledger_path.read_bytes()
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["ledger", "validate", "--ledger", str(ledger_path), "--plan", str(plan_path), "--capability-snapshot", str(snapshot_path)])
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(output.getvalue())["valid"])
            self.assertEqual(ledger_path.read_bytes(), before)

    def test_review_retry_requires_results_from_latest_attempt(self):
        from selfworkflow.ledger import (
            LedgerError, new_ledger, record_slot_result, record_stage_attempt,
            transition_stage, validate_ledger,
        )
        from selfworkflow.pipeline import canonical_hash

        plan = _plan()
        active = transition_stage(
            new_ledger(plan), plan, "designed", "active",
            capability_snapshot=_snapshot(), attempt_ref="attempt-1",
        )
        first = record_slot_result(active, plan, "designed", "design-light", "result-1")
        retry = record_stage_attempt(
            first, plan, "designed", "attempt-2", capability_snapshot=_snapshot()
        )
        self.assertEqual(len(retry["stages"][0]["slotResults"]), 1)
        with self.assertRaises(LedgerError):
            transition_stage(retry, plan, "designed", "passed", capability_snapshot=_snapshot())
        with self.assertRaises(LedgerError):
            record_slot_result(retry, plan, "designed", "design-light", "result-1")
        second = record_slot_result(retry, plan, "designed", "design-light", "result-2")
        passed = transition_stage(second, plan, "designed", "passed", capability_snapshot=_snapshot())
        self.assertTrue(validate_ledger(passed, plan, _snapshot())["valid"])
        self.assertEqual(
            passed["stages"][0]["attempts"][-1],
            {"attemptRef": "attempt-2", "ordinal": 2, "previousAttemptRef": "attempt-1"},
        )

        with self.assertRaises(LedgerError):
            record_stage_attempt(retry, plan, "planned", "attempt-3", capability_snapshot=_snapshot())
        with self.assertRaises(LedgerError):
            record_stage_attempt(retry, plan, "designed", "attempt-1", capability_snapshot=_snapshot())
        stale = deepcopy(_snapshot()); stale["evidence"][0]["validUntil"] = "2025-01-01T00:00:00Z"
        with self.assertRaises(LedgerError):
            record_stage_attempt(retry, plan, "designed", "attempt-3", capability_snapshot=stale)
        different_plan = deepcopy(plan)
        different_plan["requestHash"] = "sha256:" + "9" * 64
        different_plan.pop("planHash")
        different_plan["planHash"] = canonical_hash(different_plan)
        with self.assertRaises(LedgerError):
            record_stage_attempt(
                retry, different_plan, "designed", "attempt-3",
                capability_snapshot=_snapshot(),
            )

    def test_v2_rejects_legacy_unknown_cross_stage_and_broken_attempts(self):
        from selfworkflow.ledger import (
            new_ledger, record_slot_result, record_stage_attempt,
            transition_stage, validate_ledger,
        )

        plan = _plan()
        legacy = new_ledger(plan); legacy["schemaVersion"] = 1
        invalid = validate_ledger(legacy, plan, _snapshot())
        self.assertIn("ledger-schema-version-unsupported", invalid["reasonCodes"])

        active = transition_stage(
            new_ledger(plan), plan, "designed", "active",
            capability_snapshot=_snapshot(), attempt_ref="attempt-1",
        )
        result = record_slot_result(active, plan, "designed", "design-light", "result-1")
        unknown = deepcopy(result); unknown["stages"][0]["slotResults"][0]["attemptRef"] = "missing"
        self.assertFalse(validate_ledger(unknown, plan, _snapshot())["valid"])
        broken = deepcopy(result); broken["stages"][0]["attempts"][0]["ordinal"] = 2
        self.assertIn(
            "ledger-attempt-chain-invalid",
            validate_ledger(broken, plan, _snapshot())["reasonCodes"],
        )
        retry = record_stage_attempt(
            result, plan, "designed", "attempt-2", capability_snapshot=_snapshot()
        )
        broken_link = deepcopy(retry)
        broken_link["stages"][0]["attempts"][1]["previousAttemptRef"] = "missing"
        self.assertIn(
            "ledger-attempt-chain-invalid",
            validate_ledger(broken_link, plan, _snapshot())["reasonCodes"],
        )
        duplicate_global = deepcopy(result)
        duplicate_global["stages"][1]["attempts"] = [
            {"attemptRef": "attempt-1", "ordinal": 1, "previousAttemptRef": None}
        ]
        self.assertIn(
            "ledger-attempt-duplicate",
            validate_ledger(duplicate_global, plan, _snapshot())["reasonCodes"],
        )
        duplicate_result = deepcopy(result)
        duplicate_result["stages"][0]["slotResults"].append({
            "attemptRef": "attempt-1", "moduleId": "design-light",
            "resultRef": "result-2",
        })
        self.assertIn(
            "ledger-result-duplicate",
            validate_ledger(duplicate_result, plan, _snapshot())["reasonCodes"],
        )
        replayed = record_stage_attempt(
            result, plan, "designed", "attempt-2", capability_snapshot=_snapshot()
        )
        replayed["stages"][0]["slotResults"].append({
            "attemptRef": "attempt-2", "moduleId": "design-light",
            "resultRef": "result-1",
        })
        self.assertIn(
            "ledger-result-ref-duplicate",
            validate_ledger(replayed, plan, _snapshot())["reasonCodes"],
        )
        cross_stage = deepcopy(result)
        cross_stage["stages"][1]["gateResults"] = [{
            "attemptRef": "attempt-1", "gateId": "plan-gate",
            "outcome": "passed", "resultRef": "gate-result-1",
        }]
        self.assertFalse(validate_ledger(cross_stage, plan, _snapshot())["valid"])

    def test_cli_rejects_v1_ledger_without_echoing_content(self):
        from selfworkflow.cli import main
        from selfworkflow.ledger import new_ledger

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            plan, ledger = _plan(), new_ledger(_plan())
            ledger["schemaVersion"] = 1
            plan_path, ledger_path, snapshot_path = root / "plan.json", root / "ledger.json", root / "snapshot.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
            snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["ledger", "validate", "--ledger", str(ledger_path), "--plan", str(plan_path), "--capability-snapshot", str(snapshot_path)])
            result = json.loads(output.getvalue())
            self.assertEqual(code, 51)
            self.assertIn("ledger-schema-version-unsupported", result["reasonCodes"])

    def test_write_helpers_reject_schema_collection_limits_before_append(self):
        from selfworkflow.ledger import (
            LedgerError, new_ledger, record_slot_result, record_stage_attempt,
            transition_stage,
        )

        plan = _plan()
        active = transition_stage(
            new_ledger(plan), plan, "designed", "active",
            capability_snapshot=_snapshot(), attempt_ref="attempt-1",
        )
        attempt_limit = deepcopy(active)
        attempt_limit["stages"][0]["attempts"] = [
            {
                "attemptRef": f"attempt-{index}", "ordinal": index,
                "previousAttemptRef": f"attempt-{index - 1}" if index > 1 else None,
            }
            for index in range(1, 1025)
        ]
        with self.assertRaisesRegex(LedgerError, "ledger-attempt-invalid"):
            record_stage_attempt(
                attempt_limit, plan, "designed", "attempt-1025",
                capability_snapshot=_snapshot(),
            )

        result_limit = deepcopy(active)
        result_limit["stages"][0]["attempts"] = [
            {
                "attemptRef": f"attempt-{index}", "ordinal": index,
                "previousAttemptRef": f"attempt-{index - 1}" if index > 1 else None,
            }
            for index in range(1, 258)
        ]
        result_limit["stages"][0]["slotResults"] = [
            {
                "attemptRef": f"attempt-{index}", "moduleId": "design-light",
                "resultRef": f"result-{index}",
            }
            for index in range(1, 257)
        ]
        with self.assertRaisesRegex(LedgerError, "ledger-result-limit"):
            record_slot_result(
                result_limit, plan, "designed", "design-light", "result-257"
            )


if __name__ == "__main__":
    unittest.main()
