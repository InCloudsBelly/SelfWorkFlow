import copy
import json
import unittest

from tests.unit.v3.artifact_fixtures import load_test_artifacts


def _module(module_id, *, requested=False):
    return {
        "schemaVersion": 3,
        "id": module_id,
        "sourceHash": "sha256:" + ("a" if not requested else "b") * 64,
        "stage": "reviewed",
        "slot": "review.primary",
        "selectionMode": "static",
        "invocation": {"kind": "agent-native", "ref": module_id},
        "dependencies": [],
        "conflicts": [],
        "contextCost": {"estimatedContextCost": 1, "estimatedExecutionCost": 1},
        "supportEvidence": {
            "sourceIntegrity": "supported",
            "adapterSupport": "supported",
            "runtimeCapability": "supported",
            "behaviorEvidence": "supported",
        },
    }


REQUEST = {
    "schemaVersion": 3,
    "operationType": "review",
    "complexity": "C1",
    "risk": "R1",
    "writeTask": False,
    "ambiguity": False,
    "explicitModuleIds": [],
    "projectDefaultModuleIds": [],
    "projectMinimums": {"strength": "Light"},
    "capabilityEvidenceSnapshot": {
        "schemaVersion": 1,
        "capturedAt": "2026-08-09T00:00:00Z",
        "evidence": [],
    },
    "taskArchetype": "bounded-feature",
    "requirementsMaturity": "approved",
    "scopeShape": "single-module",
    "durableSpec": True,
    "classificationConfidence": 1.0,
    "classificationEvidence": [{
        "evidenceRef": "classification-1",
        "evidenceHash": "sha256:" + "c" * 64,
        "classifierVersion": "classifier-v1",
        "classifierHash": "sha256:" + "d" * 64,
    }],
    "testLevelFloor": "T1",
}


class HostLedgerTests(unittest.TestCase):
    def setUp(self):
        from selfworkflow.v3.host import Host
        from selfworkflow.v3.plan_graph import build_plan_graph

        self.catalog, self.pipeline = load_test_artifacts(
            [_module("review-a")], mode="static"
        )
        self.plan = build_plan_graph(REQUEST, self.catalog, self.pipeline)
        self.host = Host(self.plan, REQUEST, self.catalog, self.pipeline)
        self.ledger = self.host.new_ledger()

    def _start_review(self):
        return self.host.start_stage(
            self.ledger, "discovered", "attempt-discovered", "2026-08-09T00:00:00Z"
        )

    def _pass_stage(self, ledger, stage_id, attempt_ref):
        return self.host.apply_stage_result(
            ledger,
            {
                "schemaVersion": 3,
                "planHash": self.plan.plan_hash,
                "stageId": stage_id,
                "attemptRef": attempt_ref,
                "capabilitySnapshotHash": self.plan["capabilitySnapshotHash"],
                "inputArtifactHashes": [],
                "outputArtifactHashes": ["sha256:" + "e" * 64],
                "slotResults": [],
                "gateResults": [],
                "runtimeSkips": [],
                "artifactHashes": ["sha256:" + "e" * 64],
                "status": "passed",
                "completedAt": "2026-08-09T00:20:00Z",
            },
        )

    def test_real_loader_artifacts_create_schema_valid_v3_result_and_ledger(self):
        from selfworkflow.v3.contracts import validate_run_ledger, validate_resolve_result
        from selfworkflow.v3.resolver import resolve_request

        result = resolve_request(REQUEST, catalog_source=self.catalog, pipeline_source=self.pipeline)
        self.assertEqual(result["schemaVersion"], 3)
        self.assertEqual(result["planGraph"]["schemaVersion"], 3)
        self.assertEqual(result["runLedger"]["schemaVersion"], 3)
        validate_resolve_result(result)
        validate_run_ledger(result["runLedger"], result["planGraph"])
        validate_resolve_result(json.loads(json.dumps(result)))

    def test_selection_receipt_and_slot_artifact_bind_to_same_attempt(self):
        from selfworkflow.v3.contracts import validate_run_ledger
        from selfworkflow.v3.selector import SelectionInput, select_modules

        ledger = self.ledger
        for ordinal, stage_id in enumerate((
            "discovered", "capability-checked", "classified", "designed",
            "planned", "implemented",
        ), start=1):
            attempt = f"attempt-{ordinal}"
            ledger = self.host.start_stage(
                ledger, stage_id, attempt, f"2026-08-09T00:1{ordinal}:00Z"
            )
            ledger = self._pass_stage(ledger, stage_id, attempt)
        ledger = self.host.start_stage(
            ledger, "reviewed", "attempt-reviewed", "2026-08-09T01:00:00Z"
        )
        selection = select_modules(
            self.plan, "reviewed", "review.primary", "attempt-reviewed",
            SelectionInput(
                artifact_id="review-signal",
                artifact_hash="sha256:" + "1" * 64,
            ),
        )
        receipt = selection.receipt.as_dict()
        ledger = self.host.apply_stage_result(
            ledger,
            {
                "schemaVersion": 3,
                "planHash": self.plan.plan_hash,
                "stageId": "reviewed",
                "attemptRef": "attempt-reviewed",
                "capabilitySnapshotHash": self.plan["capabilitySnapshotHash"],
                "inputArtifactHashes": ["sha256:" + "1" * 64],
                "outputArtifactHashes": ["sha256:" + "2" * 64],
                "slotResults": [{
                    "slotId": "review.primary",
                    "moduleId": "review-a",
                    "artifactHash": "sha256:" + "2" * 64,
                }],
                "gateResults": [],
                "runtimeSkips": [],
                "artifactHashes": ["sha256:" + "1" * 64, "sha256:" + "2" * 64],
                "selectionReceipts": [receipt],
                "status": "passed",
                "completedAt": "2026-08-09T01:01:00Z",
            },
        )
        validate_run_ledger(ledger, self.plan.document, (receipt,))
        self.assertEqual(
            ledger["stages"][6]["selectionReceiptRefs"],
            [{"attemptRef": "attempt-reviewed", "receiptHash": receipt["receiptHash"]}],
        )

    def test_normal_stage_progression_preserves_plan_and_requires_predecessor(self):
        from selfworkflow.v3.host import HostError

        active = self._start_review()
        self.assertEqual(active["planHash"], self.plan.plan_hash)
        with self.assertRaisesRegex(HostError, "stage-predecessor"):
            self.host.start_stage(
                active, "capability-checked", "attempt-cap", "2026-08-09T00:00:00Z"
            )
        passed = self._pass_stage(active, "discovered", "attempt-discovered")
        self.assertEqual(passed["planHash"], active["planHash"])
        self.assertEqual(passed["status"], "pending")
        next_ledger = self.host.start_stage(
            passed, "capability-checked", "attempt-cap", "2026-08-09T00:02:00Z"
        )
        self.assertEqual(next_ledger["planHash"], self.plan.plan_hash)

    def test_stage_result_rejects_old_attempt_and_hash_drift(self):
        from selfworkflow.v3.host import HostError

        active = self._start_review()
        bad = {
            "schemaVersion": 3,
            "planHash": "sha256:" + "f" * 64,
            "stageId": "discovered",
            "attemptRef": "attempt-discovered",
            "capabilitySnapshotHash": self.plan["capabilitySnapshotHash"],
            "inputArtifactHashes": [], "outputArtifactHashes": [],
            "slotResults": [], "gateResults": [], "runtimeSkips": [],
            "artifactHashes": [], "status": "passed",
            "completedAt": "2026-08-09T00:01:00Z",
        }
        with self.assertRaisesRegex(HostError, "plan-binding"):
            self.host.apply_stage_result(active, bad)
        bad["planHash"] = self.plan.plan_hash
        bad["attemptRef"] = "old-attempt"
        with self.assertRaisesRegex(HostError, "attempt"):
            self.host.apply_stage_result(active, bad)

    def test_typed_outside_eligible_request_creates_new_plan_and_supersedes_old_ledger(self):
        from selfworkflow.v3.selector import SelectionInput, select_modules

        runtime_catalog, runtime_pipeline = load_test_artifacts([
            {**_module("review-a"), "selectionMode": "bounded-runtime"},
            {
                **_module("review-extra", requested=True),
                "stage": "planned",
                "slot": "plan.primary",
                "selectionMode": "static",
            },
        ], mode="bounded-runtime")
        from selfworkflow.v3.plan_graph import build_plan_graph
        plan = build_plan_graph(REQUEST, runtime_catalog, runtime_pipeline)
        host = __import__("selfworkflow.v3.host", fromlist=["Host"]).Host(
            plan, REQUEST, runtime_catalog, runtime_pipeline
        )
        ledger = host.new_ledger()
        for ordinal, stage_id in enumerate((
            "discovered", "capability-checked", "classified", "designed",
            "planned", "implemented",
        ), start=1):
            attempt = f"attempt-{ordinal}"
            ledger = host.start_stage(
                ledger, stage_id, attempt, f"2026-08-09T00:0{ordinal}:00Z"
            )
            ledger = host.apply_stage_result(
                ledger,
                {
                    "schemaVersion": 3,
                    "planHash": plan.plan_hash,
                    "stageId": stage_id,
                    "attemptRef": attempt,
                    "capabilitySnapshotHash": plan["capabilitySnapshotHash"],
                    "inputArtifactHashes": [], "outputArtifactHashes": [],
                    "slotResults": [], "gateResults": [], "runtimeSkips": [],
                    "artifactHashes": [], "status": "passed",
                    "completedAt": f"2026-08-09T00:0{ordinal}:30Z",
                },
            )
        ledger = host.start_stage(ledger, "reviewed", "attempt-review", "2026-08-09T00:00:00Z")
        outcome = select_modules(
            plan, "reviewed", "review.primary", "attempt-review",
            SelectionInput(
                artifact_id="signal", artifact_hash="sha256:" + "1" * 64,
                requested_module_ids=("review-extra",),
            ),
        )
        self.assertEqual(outcome.status, "next-stage-request")
        extension = host.extend_from_next_stage_request(ledger, outcome)
        self.assertEqual(extension.old_ledger["status"], "superseded")
        self.assertNotEqual(extension.plan.plan_hash, plan.plan_hash)
        self.assertEqual(extension.old_ledger["supersededByPlanHash"], extension.plan.plan_hash)
        self.assertEqual(extension.plan["requestHash"], extension.new_request_hash)
        self.assertEqual(extension.new_request["explicitModuleIds"], ["review-extra"])
        self.assertEqual(ledger["status"], "active")

    def test_raw_next_stage_mapping_is_not_accepted(self):
        from selfworkflow.v3.host import HostError

        with self.assertRaisesRegex(HostError, "typed"):
            self.host.extend_from_next_stage_request(self.ledger, {"status": "next-stage-request"})


if __name__ == "__main__":
    unittest.main()
