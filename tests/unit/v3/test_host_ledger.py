import copy
import json
import unittest
from unittest.mock import Mock

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


INPUT_A = "sha256:" + "1" * 64
INPUT_B = "sha256:" + "2" * 64
OUTPUT_A = "sha256:" + "3" * 64


def _fresh_snapshots(capability=None):
    return {
        "capabilitySnapshot": copy.deepcopy(
            capability or REQUEST["capabilityEvidenceSnapshot"]
        ),
        "providerPreferenceSnapshot": {},
        "providerBindingSnapshot": {},
        "executionPolicySnapshot": {},
        "policySnapshot": {},
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
        return self._pass_with(self.host, self.plan, ledger, stage_id, attempt_ref)

    @staticmethod
    def _pass_with(host, plan, ledger, stage_id, attempt_ref):
        return host.apply_stage_result(
            ledger,
            {
                "schemaVersion": 3,
                "planHash": plan.plan_hash,
                "stageId": stage_id,
                "attemptRef": attempt_ref,
                "capabilitySnapshotHash": plan["capabilitySnapshotHash"],
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

    def _advance_to_review(self, host, plan, ledger, *, input_hash=INPUT_A):
        for ordinal, stage_id in enumerate((
            "discovered", "capability-checked", "classified", "designed",
            "planned", "implemented",
        ), start=1):
            attempt = f"attempt-{ordinal}"
            ledger = host.start_stage(
                ledger, stage_id, attempt, f"2026-08-09T00:0{ordinal}:00Z"
            )
            ledger = self._pass_with(host, plan, ledger, stage_id, attempt)
        return host.start_stage(
            ledger, "reviewed", "attempt-review", "2026-08-09T01:00:00Z",
            input_artifact_hashes=(input_hash,),
        )

    def test_real_loader_artifacts_create_schema_valid_v3_result_and_ledger(self):
        from selfworkflow.v3.contracts import validate_run_ledger, validate_resolve_result
        from selfworkflow.v3.resolver import resolve_request

        result = resolve_request(REQUEST, catalog_source=self.catalog, pipeline_source=self.pipeline)
        self.assertEqual(result["schemaVersion"], 3)
        self.assertEqual(result["planGraph"]["schemaVersion"], 3)
        validate_resolve_result(result)
        self.assertNotIn("runLedger", result)
        ledger = self.host.new_ledger()
        validate_run_ledger(ledger, result["planGraph"])
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
            ledger, "reviewed", "attempt-reviewed", "2026-08-09T01:00:00Z",
            input_artifact_hashes=(INPUT_A,),
        )
        selection = select_modules(
            self.plan, "reviewed", "review.primary", "attempt-reviewed",
            SelectionInput(
                artifact_id="review-signal",
                artifact_hash=INPUT_A,
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
                "inputArtifactHashes": [INPUT_A],
                "outputArtifactHashes": [OUTPUT_A],
                "slotResults": [{
                    "slotId": "review.primary",
                    "moduleId": "review-a",
                    "artifactHash": OUTPUT_A,
                }],
                "gateResults": [],
                "runtimeSkips": [],
                "artifactHashes": [INPUT_A, OUTPUT_A],
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
        snapshot_spy = Mock(return_value=_fresh_snapshots())
        host = __import__("selfworkflow.v3.host", fromlist=["Host"]).Host(
            plan, REQUEST, runtime_catalog, runtime_pipeline,
            snapshot_resolver=snapshot_spy,
        )
        ledger = self._advance_to_review(host, plan, host.new_ledger())
        outcome = select_modules(
            plan, "reviewed", "review.primary", "attempt-review",
            SelectionInput(
                artifact_id="signal", artifact_hash=INPUT_A,
                requested_module_ids=("review-extra",),
            ),
        )
        self.assertEqual(outcome.status, "next-stage-request")
        extension = host.extend_from_next_stage_request(
            ledger, outcome, superseded_at="2026-08-09T01:01:00Z"
        )
        snapshot_spy.assert_called_once()
        self.assertEqual(extension.old_ledger["status"], "superseded")
        self.assertNotEqual(extension.plan.plan_hash, plan.plan_hash)
        self.assertEqual(extension.old_ledger["supersededByPlanHash"], extension.plan.plan_hash)
        self.assertEqual(extension.plan["requestHash"], extension.new_request_hash)
        self.assertEqual(extension.new_request["explicitModuleIds"], ["review-extra"])
        self.assertEqual(ledger["status"], "active")

    def test_next_stage_request_can_promote_grill_module(self):
        from selfworkflow.v3.host import Host
        from selfworkflow.v3.plan_graph import build_plan_graph
        from selfworkflow.v3.selector import SelectionInput, select_modules

        catalog, pipeline = load_test_artifacts([
            {**_module("review-a"), "selectionMode": "bounded-runtime"},
            {
                **_module("design-grill-me", requested=True),
                "stage": "planned", "slot": "plan.primary",
                "selectionMode": "static",
            },
        ], mode="bounded-runtime")
        plan = build_plan_graph(REQUEST, catalog, pipeline)
        resolver = Mock(return_value=_fresh_snapshots())
        host = Host(plan, REQUEST, catalog, pipeline, snapshot_resolver=resolver)
        ledger = self._advance_to_review(host, plan, host.new_ledger())
        outcome = select_modules(
            plan, "reviewed", "review.primary", "attempt-review",
            SelectionInput(
                artifact_id="signal", artifact_hash=INPUT_A,
                requested_module_ids=("design-grill-me",),
            ),
        )

        self.assertEqual(outcome.status, "next-stage-request")
        extension = host.extend_from_next_stage_request(
            ledger, outcome, superseded_at="2026-08-09T01:01:00Z",
        )
        self.assertEqual(extension.new_request["explicitModuleIds"], ["design-grill-me"])
        resolver.assert_called_once()

    def test_next_stage_request_rejects_stale_attempt_and_unregistered_input(self):
        from selfworkflow.v3.host import Host, HostError
        from selfworkflow.v3.plan_graph import build_plan_graph
        from selfworkflow.v3.selector import SelectionInput, select_modules

        catalog, pipeline = load_test_artifacts([
            {**_module("review-a"), "selectionMode": "bounded-runtime"},
            {
                **_module("review-extra", requested=True),
                "stage": "planned", "slot": "plan.primary",
                "selectionMode": "static",
            },
        ], mode="bounded-runtime")
        plan = build_plan_graph(REQUEST, catalog, pipeline)
        resolver = Mock(return_value=_fresh_snapshots())
        host = Host(plan, REQUEST, catalog, pipeline, snapshot_resolver=resolver)
        ledger = self._advance_to_review(host, plan, host.new_ledger())

        stale = select_modules(
            plan, "reviewed", "review.primary", "stale-attempt",
            SelectionInput(
                artifact_id="signal", artifact_hash=INPUT_A,
                requested_module_ids=("review-extra",),
            ),
        )
        with self.assertRaisesRegex(HostError, "attempt"):
            host.extend_from_next_stage_request(ledger, stale)
        unknown_input = select_modules(
            plan, "reviewed", "review.primary", "attempt-review",
            SelectionInput(
                artifact_id="signal", artifact_hash=INPUT_B,
                requested_module_ids=("review-extra",),
            ),
        )
        with self.assertRaisesRegex(HostError, "input"):
            host.extend_from_next_stage_request(ledger, unknown_input)
        wrong_stage = select_modules(
            plan, "planned", "plan.primary", "attempt-review",
            SelectionInput(
                artifact_id="signal", artifact_hash=INPUT_A,
                requested_module_ids=("review-a",),
            ),
        )
        with self.assertRaisesRegex(HostError, "stage"):
            host.extend_from_next_stage_request(ledger, wrong_stage)
        resolver.assert_not_called()

        current = select_modules(
            plan, "reviewed", "review.primary", "attempt-review",
            SelectionInput(
                artifact_id="signal", artifact_hash=INPUT_A,
                requested_module_ids=("review-extra",),
            ),
        )
        host_without_resolver = Host(plan, REQUEST, catalog, pipeline)
        with self.assertRaisesRegex(HostError, "fresh-snapshots-required"):
            host_without_resolver.extend_from_next_stage_request(ledger, current)
        extension = host_without_resolver.extend_from_next_stage_request(
            ledger, current, fresh_snapshots=_fresh_snapshots(),
            superseded_at="2026-08-09T01:01:00Z",
        )
        self.assertEqual(extension.old_ledger["status"], "superseded")

        invalid = _fresh_snapshots()
        invalid["capabilitySnapshot"] = {
            "schemaVersion": 1,
            "capturedAt": "2026-08-09T00:00:00Z",
            "evidence": [{
                "name": "test-execution", "provider": "spy",
                "subject": {
                    "kind": "host", "id": "spy", "version": "1",
                    "build": "1", "sourceLock": "sha256:" + "a" * 64,
                },
                "state": "supported",
                "observedAt": "2026-08-10T00:00:00Z",
                "validUntil": "2026-08-11T00:00:00Z",
                "evidenceRef": "spy:test-execution",
                "evidenceHash": "sha256:" + "b" * 64,
            }],
        }
        invalid_resolver = Mock(return_value=invalid)
        invalid_host = Host(
            plan, REQUEST, catalog, pipeline,
            snapshot_resolver=invalid_resolver,
        )
        before = copy.deepcopy(ledger)
        with self.assertRaises(HostError):
            invalid_host.extend_from_next_stage_request(ledger, current)
        self.assertEqual(ledger, before)
        invalid_resolver.assert_called_once()

    def test_failed_and_paused_retry_append_attempt_chain_and_keep_old_results(self):
        from selfworkflow.v3.host import HostError

        active = self.host.start_stage(
            self.ledger, "discovered", "attempt-1", "2026-08-09T00:00:00Z",
            input_artifact_hashes=(INPUT_A,),
        )
        failed = self.host.apply_stage_result(active, {
            "schemaVersion": 3, "planHash": self.plan.plan_hash,
            "stageId": "discovered", "attemptRef": "attempt-1",
            "capabilitySnapshotHash": self.plan["capabilitySnapshotHash"],
            "inputArtifactHashes": [INPUT_A], "outputArtifactHashes": [OUTPUT_A],
            "slotResults": [], "gateResults": [], "runtimeSkips": [],
            "artifactHashes": [INPUT_A, OUTPUT_A], "status": "failed",
            "completedAt": "2026-08-09T00:01:00Z",
        })
        retry = self.host.start_stage(
            failed, "discovered", "attempt-2", "2026-08-09T00:02:00Z",
            input_artifact_hashes=(INPUT_B,),
        )
        stage = retry["stages"][0]
        self.assertEqual(retry["status"], "active")
        self.assertEqual(stage["status"], "active")
        self.assertEqual(stage["attempts"][1]["ordinal"], 2)
        self.assertEqual(stage["attempts"][1]["previousAttemptRef"], "attempt-1")
        self.assertIn(OUTPUT_A, stage["artifactHashes"])

        paused = self.host.apply_stage_result(retry, {
            "schemaVersion": 3, "planHash": self.plan.plan_hash,
            "stageId": "discovered", "attemptRef": "attempt-2",
            "capabilitySnapshotHash": self.plan["capabilitySnapshotHash"],
            "inputArtifactHashes": [INPUT_B], "outputArtifactHashes": [],
            "slotResults": [], "gateResults": [], "runtimeSkips": [],
            "artifactHashes": [INPUT_B], "status": "paused",
            "completedAt": "2026-08-09T00:03:00Z",
        })
        third = self.host.start_stage(
            paused, "discovered", "attempt-3", "2026-08-09T00:04:00Z"
        )
        self.assertEqual(third["stages"][0]["attempts"][-1]["ordinal"], 3)

        passed = self._pass_with(
            self.host, self.plan, third, "discovered", "attempt-3"
        )
        with self.assertRaisesRegex(HostError, "transition"):
            self.host.start_stage(
                passed, "discovered", "attempt-4", "2026-08-09T00:21:00Z"
            )

    def test_stage_result_rejects_unbound_artifact_and_duplicate_identities(self):
        from selfworkflow.v3.host import HostError

        active = self._advance_to_review(
            self.host, self.plan, self.ledger,
        )
        base = {
            "schemaVersion": 3, "planHash": self.plan.plan_hash,
            "stageId": "reviewed", "attemptRef": "attempt-review",
            "capabilitySnapshotHash": self.plan["capabilitySnapshotHash"],
            "inputArtifactHashes": [INPUT_A], "outputArtifactHashes": [OUTPUT_A],
            "slotResults": [], "gateResults": [], "runtimeSkips": [],
            "artifactHashes": [INPUT_A, OUTPUT_A], "status": "failed",
            "completedAt": "2026-08-09T00:01:00Z",
        }
        mismatch = copy.deepcopy(base)
        mismatch["slotResults"] = [{
            "slotId": "review.primary", "moduleId": "review-a",
            "artifactHash": INPUT_B,
        }]
        with self.assertRaisesRegex(HostError, "artifact"):
            self.host.apply_stage_result(active, mismatch)

        duplicate_slot = copy.deepcopy(base)
        duplicate_slot["slotResults"] = [
            {
                "slotId": "review.primary", "moduleId": "review-a",
                "artifactHash": OUTPUT_A,
            },
            {
                "slotId": "review.primary", "moduleId": "review-a",
                "artifactHash": OUTPUT_A,
            },
        ]
        with self.assertRaisesRegex(HostError, "duplicate"):
            self.host.apply_stage_result(active, duplicate_slot)

        duplicate = copy.deepcopy(base)
        duplicate["gateResults"] = [
            {"gateId": "gate-a", "outcome": "failed", "artifactHash": OUTPUT_A},
            {"gateId": "gate-a", "outcome": "paused", "artifactHash": OUTPUT_A},
        ]
        with self.assertRaisesRegex(HostError, "duplicate"):
            self.host.apply_stage_result(active, duplicate)

    def test_new_plan_failure_does_not_supersede_original_ledger(self):
        from selfworkflow.v3.host import Host, HostError
        from selfworkflow.v3.plan_graph import build_plan_graph
        from selfworkflow.v3.selector import SelectionInput, select_modules

        unsupported = _module("review-extra", requested=True)
        unsupported.update({
            "stage": "planned", "slot": "plan.primary", "selectionMode": "static",
        })
        unsupported["supportEvidence"] = {
            **unsupported["supportEvidence"], "adapterSupport": "unsupported",
        }
        catalog, pipeline = load_test_artifacts([
            {**_module("review-a"), "selectionMode": "bounded-runtime"},
            unsupported,
        ], mode="bounded-runtime")
        plan = build_plan_graph(REQUEST, catalog, pipeline)
        resolver = Mock(return_value=_fresh_snapshots())
        host = Host(plan, REQUEST, catalog, pipeline, snapshot_resolver=resolver)
        ledger = self._advance_to_review(host, plan, host.new_ledger())
        before = copy.deepcopy(ledger)
        outcome = select_modules(
            plan, "reviewed", "review.primary", "attempt-review",
            SelectionInput(
                artifact_id="signal", artifact_hash=INPUT_A,
                requested_module_ids=("review-extra",),
            ),
        )
        with self.assertRaises(HostError):
            host.extend_from_next_stage_request(
                ledger, outcome, superseded_at="2026-08-09T01:01:00Z"
            )
        self.assertEqual(ledger, before)
        resolver.assert_called_once()

    def test_raw_next_stage_mapping_is_not_accepted(self):
        from selfworkflow.v3.host import HostError

        with self.assertRaisesRegex(HostError, "typed"):
            self.host.extend_from_next_stage_request(self.ledger, {"status": "next-stage-request"})


if __name__ == "__main__":
    unittest.main()
