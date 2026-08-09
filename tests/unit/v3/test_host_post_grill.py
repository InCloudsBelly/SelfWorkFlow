from datetime import datetime, timezone
import unittest

from tests.unit.v3.test_cpp_router import _v3_request
from tests.unit.v3.test_review_dispatch import _SpyPort, _summary
from tests.unit.v3.test_post_grill_review_gate import _Consumer, _fallback
from selfworkflow.v3.hashing import content_hash


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
        self.request = request
        self.summary = _summary()
        self.port = _SpyPort()
        self.consumer = _Consumer()
        self.fallback_store = {}
        self.host = self._host_with_port(self.port)
        ledger = self.host.new_ledger()
        for ordinal, stage_id in enumerate(("discovered", "capability-checked", "classified"), start=1):
            attempt = f"attempt-{stage_id}"
            ledger = self.host.start_stage(ledger, stage_id, attempt, f"2026-08-09T00:0{ordinal}:00Z")
            ledger = self.host.apply_stage_result(ledger, self._result(stage_id, attempt))
        self.ledger = self.host.start_stage(
            ledger, "designed", "attempt-designed", "2026-08-09T00:10:00Z"
        )

    def _host_with_port(self, port, *, fallback_resolver=None, consumer=None):
        from selfworkflow.v3.host import Host
        from selfworkflow.v3.review_services import bind_review_host_services

        service_attestation = {
            "schemaVersion": 3, "backendClass": "fake-test",
            "dispatchPortBound": True, "artifactResolversBound": True,
            "replayConsumersBound": True,
        }
        service_attestation["attestationHash"] = content_hash(service_attestation)
        use_consumer = consumer or getattr(self, "consumer", _Consumer())
        services = bind_review_host_services(
            dispatch_port=port,
            summary_resolver=lambda ref: self.summary if ref == self.summary["summaryHash"] else None,
            host_attestation_resolver=lambda ref: (
                port.last_attestation
                if port.last_attestation and port.last_attestation["attestationHash"] == ref
                else None
            ),
            host_attestation_consumer=use_consumer,
            fallback_authorization_resolver=(
                fallback_resolver if fallback_resolver is not None
                else lambda ref: self.fallback_store.get(ref)
            ),
            fallback_authorization_consumer=use_consumer,
            service_attestation=service_attestation,
            test_mode=True,
        )
        return Host(
            self.plan, self.request, self.catalog, self.pipeline,
            review_services=services, review_test_mode=True,
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
        self.assertFalse(hasattr(PostGrillReviewEvidence, "_issue"))

    def test_host_dispatch_receipt_is_required_and_bound_to_design_attempt(self):
        from selfworkflow.v3.host import HostError

        evidence = self.host.dispatch_post_grill_review(
            self.ledger, self.summary["summaryHash"],
            implementation_agent_identity="implementation-agent",
            implementation_context_identity="implementation-context",
            independent_context_available=True,
            now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
        )
        with self.assertRaises(AttributeError):
            evidence._plan_hash = "sha256:" + "0" * 64
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

        with self.assertRaisesRegex(HostError, "post-grill-independent-review-required"):
            self.host.apply_stage_result(
                self.ledger, result, post_grill_review_evidence=evidence,
            )

        rebound = self.host.start_stage(
            passed, "planned", "attempt-planned", "2026-08-09T00:21:00Z"
        )
        self.assertEqual(rebound["stages"][4]["status"], "active")

    def test_review_services_are_constructor_bound_and_fake_services_are_test_only(self):
        from selfworkflow.v3.host import Host, HostError
        from selfworkflow.v3.review_services import ReviewServiceError, bind_review_host_services

        attestation = {
            "schemaVersion": 3, "backendClass": "fake-test",
            "dispatchPortBound": True, "artifactResolversBound": True,
            "replayConsumersBound": True,
        }
        attestation["attestationHash"] = content_hash(attestation)
        with self.assertRaisesRegex(ReviewServiceError, "review-host-service-attestation-invalid"):
            bind_review_host_services(
                dispatch_port=self.port, summary_resolver=lambda ref: self.summary,
                host_attestation_resolver=lambda ref: None,
                host_attestation_consumer=_Consumer(),
                fallback_authorization_resolver=lambda ref: None,
                fallback_authorization_consumer=_Consumer(),
                service_attestation=attestation,
            )
        with self.assertRaisesRegex(HostError, "post-grill-review-host-services-required"):
            Host(self.plan, self.request, self.catalog, self.pipeline).dispatch_post_grill_review(
                self.ledger, self.summary["summaryHash"],
                implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                independent_context_available=True,
                now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
            )

        before = len(self.port.calls)
        with self.assertRaises(HostError):
            self.host.dispatch_post_grill_review(
                self.ledger, {"forged": "summary"},
                implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                independent_context_available=True,
                now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
            )
        self.assertEqual(len(self.port.calls), before)

    def test_changes_required_result_never_issues_host_evidence(self):
        from selfworkflow.v3.host import HostError

        port = _SpyPort(verdict="changes-required")
        host = self._host_with_port(port)
        with self.assertRaisesRegex(HostError, "post-grill-review-changes-required"):
            host.dispatch_post_grill_review(
                self.ledger, self.summary["summaryHash"],
                implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                independent_context_available=True,
                now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
            )

    def test_same_agent_fallback_is_resolved_before_dispatch_and_consumed_once(self):
        from selfworkflow.v3.host import HostError

        fallback = _fallback("same-agent-structured-review")
        port = _SpyPort(attested=False, same_identity=True)
        invalid_host = self._host_with_port(port, fallback_resolver=lambda _ref: None)
        with self.assertRaisesRegex(HostError, "post-grill-review-input-invalid"):
            invalid_host.dispatch_post_grill_review(
                self.ledger, self.summary["summaryHash"],
                implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                independent_context_available=False,
                now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
                fallback_authorization_ref=fallback["authorizationHash"],
            )
        self.assertEqual(port.calls, [])

        consumer = _Consumer()
        self.fallback_store[fallback["authorizationHash"]] = fallback
        fallback_host = self._host_with_port(port, consumer=consumer)
        evidence = fallback_host.dispatch_post_grill_review(
            self.ledger, self.summary["summaryHash"],
            implementation_agent_identity="implementation-agent",
            implementation_context_identity="implementation-context",
            independent_context_available=False,
            now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
            fallback_authorization_ref=fallback["authorizationHash"],
        )
        self.assertEqual(evidence.receipt["independence"], "unverified")
        with self.assertRaisesRegex(HostError, "post-grill-review-authorization-replayed"):
            fallback_host.dispatch_post_grill_review(
                self.ledger, self.summary["summaryHash"],
                implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                independent_context_available=False,
                now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
                fallback_authorization_ref=fallback["authorizationHash"],
            )


if __name__ == "__main__":
    unittest.main()
