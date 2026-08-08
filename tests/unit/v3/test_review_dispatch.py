import json
import unittest

from selfworkflow.v3.hashing import content_hash


HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def _summary():
    value = {
        "schemaVersion": 3,
        "summaryId": "phase-4-post-grill-review",
        "designHash": HASH_A,
        "reviewerPolicyHash": HASH_B,
        "objective": "Enforce an independent post-Grill Brainstorming review.",
        "scope": {
            "included": ["review dispatch", "review gate"],
            "excluded": ["provider execution"],
        },
        "constraints": ["fork_context must be false"],
        "assumptions": ["The Host can attest dispatch metadata."],
        "alternatives": [
            {
                "alternativeId": "fresh-subagent",
                "summary": "Use a fresh SubAgent.",
                "disposition": "selected",
            }
        ],
        "risks": [
            {
                "riskId": "self-report-spoofing",
                "description": "A reviewer may self-report independence.",
                "mitigation": "Trust only Host observations.",
            }
        ],
        "acceptanceCriteria": [
            {
                "criterionId": "fresh-context",
                "description": "The reviewer receives no inherited context.",
                "evidenceExpectation": "A Host-signed dispatch receipt.",
            }
        ],
    }
    value["summaryHash"] = content_hash(value)
    return value


class _SpyPort:
    def __init__(self, *, attested=True, same_identity=False):
        self.calls = []
        self.attested = attested
        self.same_identity = same_identity

    def dispatch_review(self, *, review_mode, fork_context, payload):
        self.calls.append((review_mode, fork_context, payload))
        from selfworkflow.v3.review_dispatch import HostDispatchObservation

        return HostDispatchObservation(
            dispatch_id="dispatch-1",
            review_mode=review_mode,
            fork_context=fork_context,
            sent_payload=payload,
            host_agent_identity="host-agent",
            host_context_identity="host-context",
            reviewer_agent_identity=(
                "implementation-agent" if self.same_identity else "review-agent"
            ),
            reviewer_context_identity=(
                "implementation-context" if self.same_identity else "review-context"
            ),
            host_attestation_ref="host-attestation-1" if self.attested else None,
            returned_value={
                "decision": "passed",
                "agentInstanceId": "implementation-agent",
                "forkContext": True,
                "inputMode": "full-transcript",
            },
        )


class ReviewDispatchTests(unittest.TestCase):
    def test_dispatch_forces_fresh_context_and_summary_only_payload(self):
        from selfworkflow.v3.review_dispatch import dispatch_independent_review

        port = _SpyPort()
        receipt = dispatch_independent_review(
            _summary(),
            implementation_agent_identity="implementation-agent",
            implementation_context_identity="implementation-context",
            port=port,
        )
        self.assertEqual(len(port.calls), 1)
        review_mode, fork_context, payload = port.calls[0]
        self.assertEqual(review_mode, "brainstorming-cross-review")
        self.assertIs(fork_context, False)
        self.assertEqual(
            set(payload),
            {"schemaVersion", "reviewMode", "designReviewSummary"},
        )
        serialized = json.dumps(payload).casefold()
        self.assertNotIn("transcript", serialized)
        self.assertNotIn("reasoning", serialized)
        self.assertEqual(receipt["independence"], "independent")
        self.assertFalse(receipt["parentContextImported"])
        self.assertFalse(receipt["grillReasoningReceived"])

    def test_collector_ignores_agent_self_reported_identity_and_dispatch_shape(self):
        from selfworkflow.v3.review_dispatch import dispatch_independent_review

        receipt = dispatch_independent_review(
            _summary(),
            implementation_agent_identity="implementation-agent",
            implementation_context_identity="implementation-context",
            port=_SpyPort(),
        )
        self.assertEqual(receipt["reviewerAgentIdentity"], "review-agent")
        self.assertEqual(receipt["reviewerContextIdentity"], "review-context")
        self.assertFalse(receipt["forkContext"])
        self.assertEqual(receipt["inputMode"], "summary-only")
        self.assertEqual(receipt["resultHash"], content_hash({
            "decision": "passed",
            "agentInstanceId": "implementation-agent",
            "forkContext": True,
            "inputMode": "full-transcript",
        }))

    def test_missing_attestation_or_same_host_identity_cannot_claim_independence(self):
        from selfworkflow.v3.review_dispatch import (
            ReviewDispatchError,
            dispatch_independent_review,
        )

        receipt = dispatch_independent_review(
            _summary(),
            implementation_agent_identity="implementation-agent",
            implementation_context_identity="implementation-context",
            port=_SpyPort(attested=False),
        )
        self.assertEqual(receipt["independence"], "unverified")
        self.assertIsNone(receipt["hostAttestationRef"])

        with self.assertRaisesRegex(ReviewDispatchError, "review-identity-not-independent"):
            dispatch_independent_review(
                _summary(),
                implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                port=_SpyPort(same_identity=True),
            )

    def test_port_observation_must_match_actual_host_call(self):
        from selfworkflow.v3.review_dispatch import (
            HostDispatchObservation,
            ReviewDispatchError,
            dispatch_independent_review,
        )

        class LyingPort:
            def dispatch_review(self, *, review_mode, fork_context, payload):
                return HostDispatchObservation(
                    dispatch_id="dispatch-1",
                    review_mode=review_mode,
                    fork_context=True,
                    sent_payload=payload,
                    host_agent_identity="host-agent",
                    host_context_identity="host-context",
                    reviewer_agent_identity="review-agent",
                    reviewer_context_identity="review-context",
                    host_attestation_ref="attestation",
                    returned_value={"decision": "passed"},
                )

        with self.assertRaisesRegex(ReviewDispatchError, "review-dispatch-observation-mismatch"):
            dispatch_independent_review(
                _summary(),
                implementation_agent_identity="implementation-agent",
                implementation_context_identity="implementation-context",
                port=LyingPort(),
            )


if __name__ == "__main__":
    unittest.main()
