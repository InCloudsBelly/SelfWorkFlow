import copy
from datetime import datetime, timezone
import json
import unittest

from selfworkflow.v3.hashing import content_hash


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
PLAN_HASH = "sha256:" + "f" * 64


def _summary():
    value = {
        "schemaVersion": 3,
        "summaryId": "phase-4-post-grill-review",
        "designHash": HASH_A,
        "reviewerPolicyHash": HASH_B,
        "objective": "Enforce an independent post-Grill Brainstorming review.",
        "scope": {"included": ["review dispatch", "review gate"], "excluded": ["provider execution"]},
        "constraints": ["fork_context must be false"],
        "assumptions": ["The Host can attest dispatch metadata."],
        "alternatives": [{"alternativeId": "fresh-subagent", "summary": "Use a fresh SubAgent.", "disposition": "selected"}],
        "risks": [{"riskId": "self-report-spoofing", "description": "A reviewer may self-report independence.", "mitigation": "Trust only Host observations."}],
        "acceptanceCriteria": [{"criterionId": "fresh-context", "description": "The reviewer receives no inherited context.", "evidenceExpectation": "A Host-observed dispatch receipt."}],
    }
    value["summaryHash"] = content_hash(value)
    return value


def _verified(summary=None):
    from selfworkflow.v3.review_inputs import verify_review_inputs

    value = _summary() if summary is None else summary
    provenance = {
        "schemaVersion": 3,
        "summaryHash": value["summaryHash"], "designHash": value["designHash"],
        "reviewerPolicyHash": value["reviewerPolicyHash"],
        "planHash": PLAN_HASH, "attemptRef": "attempt-designed",
        "sourceClasses": ["acceptance-criteria", "confirmed-design"],
        "sourceFields": [
            "acceptanceCriteria", "alternatives", "assumptions", "constraints",
            "objective", "risks", "scope.excluded", "scope.included",
        ],
        "grillTranscriptReceived": False, "grillReasoningReceived": False,
        "parentContextReceived": False,
        "issuedAt": "2026-08-09T11:59:00Z", "expiresAt": "2026-08-09T12:05:00Z",
        "nonce": "summary-provenance-1",
    }
    provenance["attestationHash"] = content_hash(provenance)
    completion = {
        "schemaVersion": 3, "moduleId": "design-grill-me",
        "triggerSource": "explicit-user-request", "grillStatus": "completed",
        "commonUnderstandingConfirmed": True, "confirmationSource": "user-confirmation",
        "designHash": value["designHash"], "summaryHash": value["summaryHash"],
        "planHash": PLAN_HASH, "attemptRef": "attempt-designed",
        "issuedAt": "2026-08-09T11:59:00Z", "expiresAt": "2026-08-09T12:05:00Z",
        "nonce": "grill-completion-1",
    }
    completion["attestationHash"] = content_hash(completion)
    return verify_review_inputs(
        value,
        summary_attestation_resolver=lambda ref: provenance if ref == value["summaryHash"] else None,
        grill_completion_ref=completion["attestationHash"],
        grill_completion_resolver=lambda ref: completion if ref == completion["attestationHash"] else None,
        reviewer_policy_hash=value["reviewerPolicyHash"], plan_hash=PLAN_HASH,
        attempt_ref="attempt-designed",
        now=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
    )


def _result(summary, *, verdict="approve", findings=None):
    value = {
        "schemaVersion": 3,
        "verdict": verdict,
        "reviewLevel": "L2",
        "summaryHash": summary["summaryHash"],
        "designHash": summary["designHash"],
        "findings": findings or [],
    }
    value["resultHash"] = content_hash(value)
    return value


def _attestation(observation, implementation_agent, implementation_context):
    value = {
        "schemaVersion": 3,
        "dispatchId": observation["dispatchId"],
        "dispatchNonce": observation["dispatchNonce"],
        "planHash": observation["planHash"],
        "attemptRef": observation["attemptRef"],
        "issuedAt": observation["issuedAt"],
        "expiresAt": observation["expiresAt"],
        "reviewMode": observation["reviewMode"],
        "forkContext": observation["forkContext"],
        "payloadHash": content_hash(observation["payload"]),
        "implementationAgentIdentity": implementation_agent,
        "implementationContextIdentity": implementation_context,
        "hostAgentIdentity": "host-agent",
        "hostContextIdentity": "host-context",
        "reviewerAgentIdentity": observation["reviewerAgent"],
        "reviewerContextIdentity": observation["reviewerContext"],
        "resultHash": observation["result"]["resultHash"],
    }
    value["attestationHash"] = content_hash(value)
    return value


class _SpyPort:
    def __init__(self, *, attested=True, same_identity=False, verdict="approve", tamper_attestation=False):
        self.calls = []
        self.attested = attested
        self.same_identity = same_identity
        self.verdict = verdict
        self.tamper_attestation = tamper_attestation
        self.last_attestation = None

    def dispatch_review(self, **call):
        self.calls.append(call)
        from selfworkflow.v3.review_dispatch import HostDispatchObservation

        summary = call["payload"]["designReviewSummary"]
        result = _result(
            summary,
            verdict=self.verdict,
            findings=([{"findingId": "important-1", "severity": "important", "summary": "Fix the gate."}] if self.verdict == "changes-required" else []),
        )
        reviewer_agent = call["implementation_agent_identity"] if self.same_identity else "review-agent"
        reviewer_context = call["implementation_context_identity"] if self.same_identity else "review-context"
        observed = {
            "dispatchId": "dispatch-1", "reviewMode": call["review_mode"],
            "dispatchNonce": "dispatch-nonce-1",
            "planHash": call["plan_hash"], "attemptRef": call["attempt_ref"],
            "issuedAt": "2026-08-09T11:59:00Z", "expiresAt": "2026-08-09T12:05:00Z",
            "forkContext": call["fork_context"], "payload": call["payload"],
            "reviewerAgent": reviewer_agent, "reviewerContext": reviewer_context,
            "result": result,
        }
        attestation = _attestation(
            observed, call["implementation_agent_identity"],
            call["implementation_context_identity"],
        ) if self.attested else None
        if attestation is not None and self.tamper_attestation:
            attestation["dispatchId"] = "replayed-dispatch"
            attestation["attestationHash"] = content_hash({key: value for key, value in attestation.items() if key != "attestationHash"})
        self.last_attestation = attestation
        return HostDispatchObservation(
            dispatch_id="dispatch-1", dispatch_nonce="dispatch-nonce-1",
            plan_hash=call["plan_hash"], attempt_ref=call["attempt_ref"],
            issued_at="2026-08-09T11:59:00Z", expires_at="2026-08-09T12:05:00Z",
            review_mode=call["review_mode"],
            fork_context=call["fork_context"], sent_payload=call["payload"],
            host_agent_identity="host-agent", host_context_identity="host-context",
            reviewer_agent_identity=reviewer_agent,
            reviewer_context_identity=reviewer_context,
            host_attestation=attestation, returned_value=result,
        )


class ReviewDispatchTests(unittest.TestCase):
    def test_dispatch_forces_fresh_context_and_summary_only_payload(self):
        from selfworkflow.v3.review_dispatch import dispatch_independent_review

        port = _SpyPort()
        receipt = dispatch_independent_review(
            _verified(), implementation_agent_identity="implementation-agent",
            implementation_context_identity="implementation-context", port=port,
            plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
        )
        self.assertEqual(len(port.calls), 1)
        call = port.calls[0]
        self.assertEqual(call["review_mode"], "brainstorming-cross-review")
        self.assertIs(call["fork_context"], False)
        self.assertEqual(set(call["payload"]), {"schemaVersion", "reviewMode", "designReviewSummary"})
        self.assertEqual(receipt["independence"], "independent")
        self.assertEqual(receipt["reviewVerdict"], "approve")
        self.assertFalse(receipt["parentContextImported"])

    def test_agent_self_report_fields_are_rejected_and_host_identity_wins(self):
        from selfworkflow.v3.review_dispatch import ReviewDispatchError, dispatch_independent_review

        class SelfReportingPort(_SpyPort):
            def dispatch_review(self, **call):
                observation = super().dispatch_review(**call)
                value = copy.deepcopy(observation.returned_value)
                value["agentInstanceId"] = "implementation-agent"
                return observation.__class__(
                    **{**observation.__dict__, "returned_value": value}
                )

        with self.assertRaisesRegex(ReviewDispatchError, "review-result-invalid"):
            dispatch_independent_review(
                _verified(), implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context", port=SelfReportingPort(),
                plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
            )

    def test_attestation_is_bound_to_actual_dispatch_payload_identities_and_result(self):
        from selfworkflow.v3.review_dispatch import ReviewDispatchError, dispatch_independent_review

        with self.assertRaisesRegex(ReviewDispatchError, "review-host-attestation"):
            dispatch_independent_review(
                _verified(), implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                port=_SpyPort(tamper_attestation=True),
                plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
            )

    def test_missing_attestation_or_same_host_identity_cannot_claim_independence(self):
        from selfworkflow.v3.review_dispatch import ReviewDispatchError, dispatch_independent_review

        receipt = dispatch_independent_review(
            _verified(), implementation_agent_identity="implementation-agent",
            implementation_context_identity="implementation-context", port=_SpyPort(attested=False),
            plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
        )
        self.assertEqual(receipt["independence"], "unverified")
        with self.assertRaisesRegex(ReviewDispatchError, "review-identity-not-independent"):
            dispatch_independent_review(
                _verified(), implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context", port=_SpyPort(same_identity=True),
                plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
            )

    def test_changes_required_is_preserved_and_unverified_summary_is_rejected(self):
        from selfworkflow.v3.review_dispatch import ReviewDispatchError, dispatch_independent_review

        receipt = dispatch_independent_review(
            _verified(), implementation_agent_identity="implementation-agent",
            implementation_context_identity="implementation-context", port=_SpyPort(verdict="changes-required"),
            plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
        )
        self.assertEqual(receipt["reviewVerdict"], "changes-required")
        with self.assertRaisesRegex(ReviewDispatchError, "post-grill-review-input-invalid"):
            dispatch_independent_review(
                _summary(), implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context", port=_SpyPort(),
                plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
            )

    def test_duplicate_semantic_ids_are_rejected(self):
        from selfworkflow.v3.review_inputs import ReviewInputError

        duplicate = _summary()
        duplicate["risks"].append({**duplicate["risks"][0], "description": "different"})
        duplicate["summaryHash"] = content_hash({key: value for key, value in duplicate.items() if key != "summaryHash"})
        with self.assertRaisesRegex(ReviewInputError, "post-grill-review-input-invalid"):
            _verified(duplicate)


if __name__ == "__main__":
    unittest.main()
