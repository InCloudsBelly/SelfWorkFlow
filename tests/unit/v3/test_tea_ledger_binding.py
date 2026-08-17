import copy
from pathlib import Path
import tempfile
import unittest

from selfworkflow.adapters import build_runtime
from selfworkflow.v3.host import Host, HostError
from selfworkflow.v3.tea_adapter import build_packaged_invocation, validate_packaged_output
from tests.unit.v3.artifact_fixtures import load_test_artifacts


ROOT = Path(__file__).resolve().parents[3]
PLAN_HASH = "sha256:" + "a" * 64


def _request():
    return {
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
            "schemaVersion": 1, "capturedAt": "2026-08-09T00:00:00Z", "evidence": [],
        },
        "taskArchetype": "bounded-feature",
        "requirementsMaturity": "approved",
        "scopeShape": "single-module",
        "durableSpec": True,
        "classificationConfidence": 1.0,
        "classificationEvidence": [{
            "evidenceRef": "classification-1", "evidenceHash": "sha256:" + "c" * 64,
            "classifierVersion": "classifier-v1", "classifierHash": "sha256:" + "d" * 64,
        }],
        "testLevelFloor": "T1",
    }


def _tea_module():
    return {
        "schemaVersion": 3,
        "id": "tea-test-design",
        "sourceHash": "sha256:" + "b" * 64,
        "stage": "planned",
        "slot": "test.quality.plan",
        "selectionMode": "static",
        "invocation": {"kind": "agent-native", "ref": "selfworkflow:tea-quality"},
        "dependencies": [], "conflicts": [],
        "contextCost": {"estimatedContextCost": 1, "estimatedExecutionCost": 1},
        "supportEvidence": {
            "sourceIntegrity": "supported", "adapterSupport": "supported",
            "runtimeCapability": "supported", "behaviorEvidence": "supported",
        },
    }


class TeaLedgerBindingTests(unittest.TestCase):
    def setUp(self):
        from selfworkflow.v3.plan_graph import build_plan_graph

        self.catalog, self.pipeline = load_test_artifacts(
            [_tea_module()], mode="static", target_stage="planned", target_slot="test.quality.plan",
        )
        self.request = _request()
        self.plan = build_plan_graph(self.request, self.catalog, self.pipeline)
        self.host = Host(self.plan, self.request, self.catalog, self.pipeline)
        self.ledger = self.host.new_ledger()
        self._temporary = tempfile.TemporaryDirectory()
        root = Path(self._temporary.name)
        self.runtime = root / "runtime"
        self.project = root / "project"
        self.project.mkdir()
        build_runtime(ROOT, self.runtime, "test", profile="core")

    def tearDown(self):
        self._temporary.cleanup()

    @staticmethod
    def _pass(host, plan, ledger, stage_id, attempt_ref):
        return host.apply_stage_result(ledger, {
            "schemaVersion": 3, "planHash": plan.plan_hash, "stageId": stage_id,
            "attemptRef": attempt_ref, "capabilitySnapshotHash": plan["capabilitySnapshotHash"],
            "inputArtifactHashes": [], "outputArtifactHashes": [], "slotResults": [],
            "gateResults": [], "runtimeSkips": [], "artifactHashes": [],
            "status": "passed", "completedAt": "2026-08-09T00:20:00Z",
        })

    def _active_planned(self):
        ledger = self.ledger
        for ordinal, stage_id in enumerate(("discovered", "capability-checked", "classified", "designed"), 1):
            attempt = f"attempt-{ordinal}"
            ledger = self.host.start_stage(ledger, stage_id, attempt, f"2026-08-09T00:0{ordinal}:00Z")
            ledger = self._pass(self.host, self.plan, ledger, stage_id, attempt)
        return self.host.start_stage(ledger, "planned", "attempt-planned", "2026-08-09T01:00:00Z")

    def _stage_result(self, receipt=None):
        output_hash = receipt["outputHash"] if receipt is not None else "sha256:" + "e" * 64
        result = {
            "schemaVersion": 3, "planHash": self.plan.plan_hash, "stageId": "planned",
            "attemptRef": "attempt-planned", "capabilitySnapshotHash": self.plan["capabilitySnapshotHash"],
            "inputArtifactHashes": [], "outputArtifactHashes": [output_hash],
            "slotResults": [{
                "slotId": "test.quality.plan", "moduleId": "tea-test-design",
                "artifactHash": output_hash,
            }],
            "gateResults": [], "runtimeSkips": [], "artifactHashes": [output_hash],
            "status": "passed", "completedAt": "2026-08-09T01:01:00Z",
        }
        if receipt is not None:
            result["teaReceipts"] = [receipt]
        return result

    def _receipt(self):
        context = {"requirements": "r", "acceptanceCriteria": "a", "design": "d", "risk": "r"}
        invocation = build_packaged_invocation(self.runtime, "test-design", context, "test-design.md")
        (self.project / "test-design.md").write_text(
            "# Scope\n# Risks\n# Coverage\n# Cases\n", encoding="utf-8",
        )
        return validate_packaged_output(
            self.runtime, self.project, invocation,
            binding={
                "planHash": self.plan.plan_hash, "attemptRef": "attempt-planned",
                "stageId": "planned", "slotId": "test.quality.plan", "moduleId": "tea-test-design",
            },
        )

    def test_passed_tea_stage_requires_bound_receipt(self):
        active = self._active_planned()
        with self.assertRaisesRegex(HostError, "tea-receipt-missing"):
            self.host.apply_stage_result(active, self._stage_result())

    def test_valid_adapter_receipt_is_bound_and_audited(self):
        active = self._active_planned()
        receipt = self._receipt()
        result = self.host.apply_stage_result(
            active, self._stage_result(receipt), tea_runtime_root=str(self.runtime),
        )
        self.assertEqual(result["stages"][4]["teaReceiptHashes"], [receipt["receiptHash"]])
        self.assertEqual(result["stages"][4]["teaReceipts"], [receipt])
        from selfworkflow.v3.contracts import validate_run_ledger
        validate_run_ledger(result, self.plan.document, tea_runtime_root=self.runtime)

        tampered = copy.deepcopy(result)
        tampered["stages"][4]["teaReceipts"][0]["outputHash"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(Exception, "tea-receipt"):
            validate_run_ledger(tampered, self.plan.document)

    def test_tampered_or_stale_receipt_is_rejected_without_mutating_ledger(self):
        active = self._active_planned()
        receipt = self._receipt()
        tampered = copy.deepcopy(receipt)
        tampered["outputHash"] = "sha256:" + "f" * 64
        before = copy.deepcopy(active)
        with self.assertRaisesRegex(HostError, "tea-receipt"):
            self.host.apply_stage_result(
                active, self._stage_result(tampered), tea_runtime_root=str(self.runtime),
            )
        self.assertEqual(active, before)

    def test_runtime_reference_drift_rejects_old_receipt(self):
        active = self._active_planned()
        receipt = self._receipt()
        reference_file = self.runtime / "skills/tea-quality/references/bmad-testarch-test-design/SKILL.md"
        reference_file.write_text(reference_file.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(HostError, "tea-runtime-reference-stale"):
            self.host.apply_stage_result(
                active, self._stage_result(receipt), tea_runtime_root=str(self.runtime),
            )

    def test_legacy_ledger_without_tea_fields_can_continue_non_tea_stage(self):
        legacy = copy.deepcopy(self.ledger)
        for stage in legacy["stages"]:
            stage.pop("teaReceipts", None)
            stage.pop("teaReceiptHashes", None)
        active = self.host.start_stage(
            legacy, "discovered", "attempt-discovered", "2026-08-09T00:00:00Z",
        )
        passed = self._pass(self.host, self.plan, active, "discovered", "attempt-discovered")
        self.assertEqual(passed["stages"][0]["teaReceipts"], [])


if __name__ == "__main__":
    unittest.main()
