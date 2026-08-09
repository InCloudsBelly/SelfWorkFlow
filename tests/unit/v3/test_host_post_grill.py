from datetime import datetime, timezone
from pathlib import Path
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
        from selfworkflow.v3.review_policy import load_post_grill_review_policy

        self.review_policy = load_post_grill_review_policy(
            Path(__file__).resolve().parents[3] / "workflow/v3/post-grill-review.yaml"
        )
        self.summary = _summary()
        self.summary["reviewerPolicyHash"] = self.review_policy.policy_hash
        self.summary["summaryHash"] = content_hash({
            key: value for key, value in self.summary.items()
            if key != "summaryHash"
        })
        self.port = _SpyPort()
        self.consumer = _Consumer()
        self.fallback_store = {}
        self.summary_attestation = self._summary_attestation()
        self.grill_completion = self._grill_completion()
        self.host = self._host_with_port(self.port)
        ledger = self.host.new_ledger()
        for ordinal, stage_id in enumerate(("discovered", "capability-checked", "classified"), start=1):
            attempt = f"attempt-{stage_id}"
            ledger = self.host.start_stage(ledger, stage_id, attempt, f"2026-08-09T00:0{ordinal}:00Z")
            ledger = self.host.apply_stage_result(ledger, self._result(stage_id, attempt))
        self.ledger = self.host.start_stage(
            ledger, "designed", "attempt-designed", "2026-08-09T00:10:00Z"
        )

    def _summary_attestation(self, **changes):
        value = {
            "schemaVersion": 3,
            "summaryHash": self.summary["summaryHash"],
            "designHash": self.summary["designHash"],
            "reviewerPolicyHash": self.review_policy.policy_hash,
            "planHash": self.plan.plan_hash,
            "attemptRef": "attempt-designed",
            "sourceClasses": ["acceptance-criteria", "confirmed-design"],
            "sourceFields": [
                "acceptanceCriteria", "alternatives", "assumptions", "constraints",
                "objective", "risks", "scope.excluded", "scope.included",
            ],
            "grillTranscriptReceived": False,
            "grillReasoningReceived": False,
            "parentContextReceived": False,
            "issuedAt": "2026-08-09T11:59:00Z",
            "expiresAt": "2026-08-09T12:05:00Z",
            "nonce": "summary-provenance-1",
        }
        value.update(changes)
        value["attestationHash"] = content_hash(value)
        return value

    def _grill_completion(self, **changes):
        value = {
            "schemaVersion": 3,
            "moduleId": "design-grill-me",
            "triggerSource": "explicit-user-request",
            "grillStatus": "completed",
            "commonUnderstandingConfirmed": True,
            "confirmationSource": "user-confirmation",
            "designHash": self.summary["designHash"],
            "summaryHash": self.summary["summaryHash"],
            "planHash": self.plan.plan_hash,
            "attemptRef": "attempt-designed",
            "issuedAt": "2026-08-09T11:59:00Z",
            "expiresAt": "2026-08-09T12:05:00Z",
            "nonce": "grill-completion-1",
        }
        value.update(changes)
        value["attestationHash"] = content_hash(value)
        return value

    def _host_with_port(
        self, port, *, fallback_resolver=None, consumer=None,
        summary_attestation=None, grill_completion=None,
    ):
        from selfworkflow.v3.host import Host
        from selfworkflow.v3.review_services import bind_review_host_services

        service_attestation = {
            "schemaVersion": 3, "backendClass": "fake-test",
            "dispatchPortBound": True, "artifactResolversBound": True,
            "replayConsumersBound": True,
            "reviewPolicyHash": self.review_policy.policy_hash,
        }
        service_attestation["attestationHash"] = content_hash(service_attestation)
        use_consumer = consumer or getattr(self, "consumer", _Consumer())
        services = bind_review_host_services(
            dispatch_port=port,
            summary_resolver=lambda ref: self.summary if ref == self.summary["summaryHash"] else None,
            summary_attestation_resolver=lambda ref: (
                summary_attestation if summary_attestation is not None
                else self.summary_attestation
            ) if ref == self.summary["summaryHash"] else None,
            grill_completion_resolver=lambda ref: (
                grill_completion if grill_completion is not None
                else self.grill_completion
            ) if ref == (
                grill_completion if grill_completion is not None
                else self.grill_completion
            )["attestationHash"] else None,
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
            review_policy=self.review_policy,
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
            grill_completion_ref=self.grill_completion["attestationHash"],
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
                summary_attestation_resolver=lambda ref: self.summary_attestation,
                grill_completion_resolver=lambda ref: self.grill_completion,
                host_attestation_resolver=lambda ref: None,
                host_attestation_consumer=_Consumer(),
                fallback_authorization_resolver=lambda ref: None,
                fallback_authorization_consumer=_Consumer(),
                review_policy=self.review_policy,
                service_attestation=attestation,
            )
        with self.assertRaisesRegex(HostError, "post-grill-review-host-services-required"):
            Host(self.plan, self.request, self.catalog, self.pipeline).dispatch_post_grill_review(
                self.ledger, self.summary["summaryHash"],
                implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                independent_context_available=True,
                now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
                grill_completion_ref=self.grill_completion["attestationHash"],
            )

        mismatched_request = dict(self.request)
        mismatched_request["explicitModuleIds"] = []
        with self.assertRaisesRegex(HostError, "v3-host-request-plan-mismatch"):
            Host(self.plan, mismatched_request, self.catalog, self.pipeline)

        before = len(self.port.calls)
        with self.assertRaises(HostError):
            self.host.dispatch_post_grill_review(
                self.ledger, {"forged": "summary"},
                implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                independent_context_available=True,
                now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
                grill_completion_ref=self.grill_completion["attestationHash"],
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
                grill_completion_ref=self.grill_completion["attestationHash"],
            )

    def test_same_agent_fallback_is_resolved_before_dispatch_and_consumed_once(self):
        from selfworkflow.v3.host import HostError

        fallback = _fallback(
            "same-agent-structured-review",
            design_hash=self.summary["designHash"],
            policy_hash=self.review_policy.policy_hash,
            plan_hash=self.plan.plan_hash,
            summary_hash=self.summary["summaryHash"],
        )
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
                grill_completion_ref=self.grill_completion["attestationHash"],
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
            grill_completion_ref=self.grill_completion["attestationHash"],
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
                grill_completion_ref=self.grill_completion["attestationHash"],
            )

    def test_summary_provenance_and_grill_completion_are_host_verified(self):
        from selfworkflow.v3.host import HostError

        unsafe_summary = dict(self.summary)
        unsafe_summary["objective"] = "Q: why? A: because this arbitrary text came from Grill."
        unsafe_summary["summaryHash"] = content_hash({
            key: value for key, value in unsafe_summary.items()
            if key != "summaryHash"
        })
        original = self.summary
        self.summary = unsafe_summary
        try:
            host = self._host_with_port(self.port, summary_attestation=None)
            with self.assertRaisesRegex(HostError, "post-grill-review-input-invalid"):
                host.dispatch_post_grill_review(
                    self.ledger, unsafe_summary["summaryHash"],
                    implementation_agent_identity="implementation-agent",
                    implementation_context_identity="implementation-context",
                    independent_context_available=True,
                    now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
                    grill_completion_ref=self.grill_completion["attestationHash"],
                )
        finally:
            self.summary = original

        for changes in (
            {"commonUnderstandingConfirmed": False},
            {"planHash": "sha256:" + "6" * 64},
            {"attemptRef": "attempt-other"},
            {"summaryHash": "sha256:" + "5" * 64},
            {"expiresAt": "2026-08-09T12:00:00Z"},
        ):
            with self.subTest(completion_changes=changes):
                bad_completion = self._grill_completion(**changes)
                host = self._host_with_port(self.port, grill_completion=bad_completion)
                with self.assertRaisesRegex(HostError, "post-grill-review-input-invalid"):
                    host.dispatch_post_grill_review(
                        self.ledger, self.summary["summaryHash"],
                        implementation_agent_identity="implementation-agent",
                        implementation_context_identity="implementation-context",
                        independent_context_available=True,
                        now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
                        grill_completion_ref=bad_completion["attestationHash"],
                    )

        leaked = self._summary_attestation(grillReasoningReceived=True)
        host = self._host_with_port(self.port, summary_attestation=leaked)
        with self.assertRaisesRegex(HostError, "post-grill-review-input-invalid"):
            host.dispatch_post_grill_review(
                self.ledger, self.summary["summaryHash"],
                implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                independent_context_available=True,
                now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
                grill_completion_ref=self.grill_completion["attestationHash"],
            )

    def test_review_policy_hash_is_loaded_from_authoritative_policy(self):
        from selfworkflow.v3.host import HostError

        drifted = dict(self.summary)
        drifted["reviewerPolicyHash"] = "sha256:" + "7" * 64
        drifted["summaryHash"] = content_hash({
            key: value for key, value in drifted.items() if key != "summaryHash"
        })
        original = self.summary
        self.summary = drifted
        try:
            host = self._host_with_port(self.port)
            with self.assertRaisesRegex(HostError, "post-grill-review-input-invalid"):
                host.dispatch_post_grill_review(
                    self.ledger, drifted["summaryHash"],
                    implementation_agent_identity="implementation-agent",
                    implementation_context_identity="implementation-context",
                    independent_context_available=True,
                    now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
                    grill_completion_ref=self.grill_completion["attestationHash"],
                )
        finally:
            self.summary = original


if __name__ == "__main__":
    unittest.main()
