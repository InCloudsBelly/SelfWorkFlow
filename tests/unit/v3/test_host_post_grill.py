from datetime import datetime, timezone
import unittest

from tests.unit.v3.test_cpp_router import _v3_request
from tests.unit.v3.test_review_dispatch import _SpyPort, _summary
from tests.unit.v3.test_post_grill_review_gate import _Consumer, _fallback


class HostPostGrillGateTests(unittest.TestCase):
    def setUp(self):
        from selfworkflow.v3.host import Host
        from selfworkflow.v3.plan_graph import build_plan_graph
        from tests.unit.v3.artifact_fixtures import load_test_artifacts

        request = _v3_request()
        request["explicitModuleIds"] = ["design-grill-me"]
        module = {
            "schemaVersion": 3, "id": "design-grill-me",
            "sourceHash": "sha256:" + "9" * 64,
            "stage": "designed", "slot": "designed.primary",
            "selectionMode": "static",
            "invocation": {"kind": "agent-native", "ref": "design-grill-me"},
            "dependencies": [], "conflicts": [],
            "contextCost": {"estimatedContextCost": 1, "estimatedExecutionCost": 1},
            "supportEvidence": {
                "sourceIntegrity": "supported", "adapterSupport": "supported",
                "runtimeCapability": "supported", "behaviorEvidence": "supported",
            },
        }
        self.catalog, self.pipeline = load_test_artifacts([module], mode="static")
        self.plan = build_plan_graph(request, self.catalog, self.pipeline)
        self.host = Host(self.plan, request, self.catalog, self.pipeline)
        ledger = self.host.new_ledger()
        for ordinal, stage_id in enumerate(("discovered", "capability-checked", "classified"), start=1):
            attempt = f"attempt-{stage_id}"
            ledger = self.host.start_stage(ledger, stage_id, attempt, f"2026-08-09T00:0{ordinal}:00Z")
            ledger = self.host.apply_stage_result(ledger, self._result(stage_id, attempt))
        self.ledger = self.host.start_stage(
            ledger, "designed", "attempt-designed", "2026-08-09T00:10:00Z"
        )

    def _result(self, stage_id, attempt_ref, *, outputs=(), gates=()):
        artifacts = sorted(outputs)
        return {
            "schemaVersion": 3, "planHash": self.plan.plan_hash,
            "stageId": stage_id, "attemptRef": attempt_ref,
            "capabilitySnapshotHash": self.plan["capabilitySnapshotHash"],
            "inputArtifactHashes": [], "outputArtifactHashes": artifacts,
            "slotResults": [], "gateResults": list(gates), "runtimeSkips": [],
            "artifactHashes": artifacts, "status": "passed",
            "completedAt": "2026-08-09T00:20:00Z",
        }

    def test_selected_grill_module_cannot_pass_designed_stage_without_host_evidence(self):
        from selfworkflow.v3.host import HostError, PostGrillReviewEvidence

        selected = [
            module for stage in self.plan["stages"] for slot in stage["slots"]
            for module in slot["selectedModules"]
        ]
        self.assertIn("design-grill-me", selected)
        with self.assertRaisesRegex(HostError, "post-grill-independent-review-required"):
            self.host.apply_stage_result(
                self.ledger, self._result("designed", "attempt-designed")
            )
        with self.assertRaises(TypeError):
            PostGrillReviewEvidence()

    def test_host_dispatch_receipt_is_required_and_bound_to_design_attempt(self):
        port = _SpyPort()
        evidence = self.host.dispatch_post_grill_review(
            self.ledger, _summary(),
            implementation_agent_identity="implementation-agent",
            implementation_context_identity="implementation-context",
            port=port, independent_context_available=True,
            now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
            host_attestation_resolver=lambda ref: (
                port.last_attestation
                if port.last_attestation and port.last_attestation["attestationHash"] == ref
                else None
            ),
        )
        result = self._result(
            "designed", "attempt-designed",
            outputs=(evidence.design_hash, evidence.receipt_hash),
            gates=({"gateId": "design.post-grill-review", "outcome": "passed", "artifactHash": evidence.receipt_hash},),
        )
        result["slotResults"] = [{
            "slotId": "designed.primary", "moduleId": "design-grill-me",
            "artifactHash": evidence.design_hash,
        }]
        passed = self.host.apply_stage_result(
            self.ledger, result, post_grill_review_evidence=evidence,
        )
        self.assertEqual(passed["stages"][3]["status"], "passed")

        rebound = self.host.start_stage(
            passed, "planned", "attempt-planned", "2026-08-09T00:21:00Z"
        )
        self.assertEqual(rebound["stages"][4]["status"], "active")

    def test_changes_required_result_never_issues_host_evidence(self):
        from selfworkflow.v3.host import HostError

        port = _SpyPort(verdict="changes-required")
        with self.assertRaisesRegex(HostError, "post-grill-review-changes-required"):
            self.host.dispatch_post_grill_review(
                self.ledger, _summary(),
                implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                port=port, independent_context_available=True,
                now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
                host_attestation_resolver=lambda ref: port.last_attestation,
            )

    def test_same_agent_fallback_is_resolved_before_dispatch_and_consumed_once(self):
        from selfworkflow.v3.host import HostError

        fallback = _fallback("same-agent-structured-review")
        port = _SpyPort(attested=False, same_identity=True)
        with self.assertRaisesRegex(HostError, "post-grill-review-input-invalid"):
            self.host.dispatch_post_grill_review(
                self.ledger, _summary(),
                implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                port=port, independent_context_available=False,
                now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
                fallback_authorization_ref=fallback["authorizationHash"],
                fallback_authorization_resolver=lambda _ref: None,
            )
        self.assertEqual(port.calls, [])

        consumer = _Consumer()
        evidence = self.host.dispatch_post_grill_review(
            self.ledger, _summary(),
            implementation_agent_identity="implementation-agent",
            implementation_context_identity="implementation-context",
            port=port, independent_context_available=False,
            now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
            fallback_authorization_ref=fallback["authorizationHash"],
            fallback_authorization_resolver=lambda ref: fallback if ref == fallback["authorizationHash"] else None,
            fallback_authorization_consumer=consumer,
        )
        self.assertEqual(evidence.receipt["independence"], "unverified")
        with self.assertRaisesRegex(HostError, "post-grill-review-authorization-replayed"):
            self.host.dispatch_post_grill_review(
                self.ledger, _summary(),
                implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                port=port, independent_context_available=False,
                now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
                fallback_authorization_ref=fallback["authorizationHash"],
                fallback_authorization_resolver=lambda ref: fallback,
                fallback_authorization_consumer=consumer,
            )


if __name__ == "__main__":
    unittest.main()
