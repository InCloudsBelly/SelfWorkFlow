import copy
from datetime import datetime, timezone
import unittest

from selfworkflow.v3.hashing import content_hash


DESIGN_HASH = "sha256:" + "a" * 64
POLICY_HASH = "sha256:" + "b" * 64
SUMMARY_HASH = "sha256:" + "c" * 64
PAYLOAD_HASH = "sha256:" + "d" * 64
RESULT_HASH = "sha256:" + "e" * 64
PLAN_HASH = "sha256:" + "f" * 64
NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def _fallback(
    mode, *, design_hash=DESIGN_HASH, policy_hash=POLICY_HASH,
    plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
    summary_hash=SUMMARY_HASH,
):
    value = {
        "schemaVersion": 3, "designHash": design_hash,
        "reviewerPolicyHash": policy_hash,
        "planHash": plan_hash, "attemptRef": attempt_ref,
        "inputSummaryHash": summary_hash,
        "reason": "host-attestation-unavailable" if mode == "independent-context-without-attestation" else "independent-context-unavailable",
        "fallbackMode": mode, "confirmationSource": "user-confirmation",
        "issuedAt": "2026-08-09T11:00:00Z", "expiresAt": "2026-08-09T13:00:00Z",
        "nonce": "fallback-1", "revocationState": "active",
    }
    value["authorizationHash"] = content_hash(value)
    return value


def _receipt(*, attested=True, same_agent=False, fallback_ref=None, verdict="approve"):
    value = {
        "schemaVersion": 3, "reviewMode": "independent-design-review",
        "dispatchId": "dispatch-1", "forkContext": same_agent,
        "dispatchNonce": "dispatch-nonce-1", "planHash": PLAN_HASH,
        "attemptRef": "attempt-designed",
        "issuedAt": "2026-08-09T11:59:00Z", "expiresAt": "2026-08-09T12:05:00Z",
        "implementationAgentIdentity": "implementation-agent",
        "implementationContextIdentity": "implementation-context",
        "reviewerAgentIdentity": "implementation-agent" if same_agent else "review-agent",
        "reviewerContextIdentity": "implementation-context" if same_agent else "review-context",
        "hostAgentIdentity": "host-agent", "hostContextIdentity": "host-context",
        "hostAttestationRef": None, "inputMode": "summary-only",
        "parentContextImported": same_agent, "grillReasoningReceived": False,
        "payloadHash": PAYLOAD_HASH, "inputSummaryHash": SUMMARY_HASH,
        "designHash": DESIGN_HASH, "reviewerPolicyHash": POLICY_HASH,
        "resultHash": RESULT_HASH, "reviewVerdict": verdict, "reviewLevel": "L2",
        "fallbackAuthorizationRef": fallback_ref,
        "independence": "unverified",
    }
    attestation = None
    if attested:
        attestation = {
            "schemaVersion": 3, "dispatchId": value["dispatchId"],
            "dispatchNonce": value["dispatchNonce"], "planHash": value["planHash"],
            "attemptRef": value["attemptRef"], "issuedAt": value["issuedAt"],
            "expiresAt": value["expiresAt"],
            "reviewMode": value["reviewMode"], "forkContext": value["forkContext"],
            "payloadHash": value["payloadHash"],
            "implementationAgentIdentity": value["implementationAgentIdentity"],
            "implementationContextIdentity": value["implementationContextIdentity"],
            "hostAgentIdentity": value["hostAgentIdentity"],
            "hostContextIdentity": value["hostContextIdentity"],
            "reviewerAgentIdentity": value["reviewerAgentIdentity"],
            "reviewerContextIdentity": value["reviewerContextIdentity"],
            "resultHash": value["resultHash"],
        }
        attestation["attestationHash"] = content_hash(attestation)
        value["hostAttestationRef"] = attestation["attestationHash"]
        value["independence"] = "independent"
    value["receiptHash"] = content_hash(value)
    return value, attestation


class _Consumer:
    def __init__(self):
        self.used = set()

    def __call__(self, authorization_hash, nonce):
        key = (authorization_hash, nonce)
        if key in self.used:
            return False
        self.used.add(key)
        return True


class PostGrillReviewGateTests(unittest.TestCase):
    def _evaluate(self, independent, receipt=None, fallback=None, *, consumer=None, attestation=None):
        from selfworkflow.v3.review_gate import evaluate_post_grill_review

        fallback_store = {} if fallback is None else {fallback["authorizationHash"]: fallback}
        attestation_store = {} if attestation is None else {attestation["attestationHash"]: attestation}
        return evaluate_post_grill_review(
            independent_context_available=independent, receipt=receipt,
            fallback_authorization_ref=None if fallback is None else fallback["authorizationHash"],
            design_hash=DESIGN_HASH, reviewer_policy_hash=POLICY_HASH,
            input_summary_hash=SUMMARY_HASH, now=NOW,
            plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
            host_attestation_resolver=attestation_store.get,
            host_attestation_consumer=consumer or _Consumer(),
            fallback_authorization_resolver=fallback_store.get,
            fallback_authorization_consumer=consumer or _Consumer(),
        )

    def test_five_row_truth_table_and_same_agent_requires_completed_review(self):
        independent_receipt, attestation = _receipt()
        unattested, _ = _receipt(attested=False)
        independent_fallback = _fallback("independent-context-without-attestation")
        fallback_receipt, _ = _receipt(attested=False, fallback_ref=independent_fallback["authorizationHash"])
        same_fallback = _fallback("same-agent-structured-review")
        same_receipt, _ = _receipt(attested=False, same_agent=True, fallback_ref=same_fallback["authorizationHash"])
        cases = (
            (True, independent_receipt, None, attestation, "proceed", "independent", None),
            (True, unattested, None, None, "pause", "unverified", "post-grill-review-attestation-missing"),
            (True, fallback_receipt, independent_fallback, None, "proceed", "unverified", None),
            (False, None, None, None, "pause", "unverified", "post-grill-review-user-authorization-required"),
            (False, None, same_fallback, None, "review-required", "unverified", None),
            (False, same_receipt, same_fallback, None, "proceed", "unverified", None),
        )
        for independent, receipt, fallback, host_attestation, status, independence, reason in cases:
            with self.subTest(independent=independent, status=status):
                result = self._evaluate(independent, receipt, fallback, attestation=host_attestation)
                self.assertEqual((result.status, result.independence, result.reason_code), (status, independence, reason))

    def test_fallback_is_resolved_by_host_and_consumed_once(self):
        fallback = _fallback("same-agent-structured-review")
        receipt, _ = _receipt(attested=False, same_agent=True, fallback_ref=fallback["authorizationHash"])
        consumer = _Consumer()
        self.assertEqual(self._evaluate(False, receipt, fallback, consumer=consumer).status, "proceed")
        replay = self._evaluate(False, receipt, fallback, consumer=consumer)
        self.assertEqual((replay.status, replay.reason_code), ("pause", "post-grill-review-authorization-replayed"))

    def test_unresolved_fallback_and_hash_drift_fail_closed(self):
        from selfworkflow.v3.review_gate import evaluate_post_grill_review

        fallback = _fallback("same-agent-structured-review")
        result = evaluate_post_grill_review(
            independent_context_available=False, receipt=None,
            fallback_authorization_ref=fallback["authorizationHash"],
            design_hash=DESIGN_HASH, reviewer_policy_hash=POLICY_HASH,
            input_summary_hash=SUMMARY_HASH, now=NOW,
            plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
            fallback_authorization_resolver=lambda _ref: None,
        )
        self.assertEqual(result.reason_code, "post-grill-review-input-invalid")
        drift = copy.deepcopy(fallback)
        drift["nonce"] = "tampered"
        self.assertEqual(self._evaluate(False, None, drift).reason_code, "post-grill-review-input-invalid")

    def test_fallback_is_bound_to_plan_attempt_and_summary(self):
        for field, replacement in (
            ("planHash", "sha256:" + "0" * 64),
            ("attemptRef", "attempt-other"),
            ("inputSummaryHash", "sha256:" + "1" * 64),
        ):
            with self.subTest(field=field):
                fallback = _fallback("same-agent-structured-review")
                fallback[field] = replacement
                fallback["authorizationHash"] = content_hash({
                    key: value for key, value in fallback.items()
                    if key != "authorizationHash"
                })
                result = self._evaluate(False, None, fallback)
                self.assertEqual(result.reason_code, "post-grill-review-user-authorization-required")

    def test_attestation_replay_and_changes_required_cannot_proceed(self):
        original_receipt, original_attestation = _receipt()
        consumer = _Consumer()
        self.assertEqual(
            self._evaluate(
                True, original_receipt, None,
                attestation=original_attestation, consumer=consumer,
            ).status,
            "proceed",
        )
        exact_replay = self._evaluate(
            True, original_receipt, None,
            attestation=original_attestation, consumer=consumer,
        )
        self.assertEqual(
            (exact_replay.status, exact_replay.reason_code),
            ("pause", "post-grill-review-attestation-replayed"),
        )

        receipt, attestation = _receipt()
        replayed = copy.deepcopy(attestation)
        replayed["dispatchId"] = "other-dispatch"
        replayed["attestationHash"] = content_hash({key: value for key, value in replayed.items() if key != "attestationHash"})
        receipt["hostAttestationRef"] = replayed["attestationHash"]
        receipt["receiptHash"] = content_hash({key: value for key, value in receipt.items() if key != "receiptHash"})
        result = self._evaluate(True, receipt, None, attestation=replayed)
        self.assertEqual((result.status, result.reason_code), ("pause", "post-grill-review-attestation-missing"))

        changed, changed_attestation = _receipt(verdict="changes-required")
        blocked = self._evaluate(True, changed, None, attestation=changed_attestation)
        self.assertEqual((blocked.status, blocked.reason_code), ("pause", "post-grill-review-changes-required"))

    def test_review_contract_schemas_are_registered_and_closed(self):
        from selfworkflow.v3.contracts import ContractError, load_contract

        for name in (
            "design-review-summary.schema.json", "design-review-result.schema.json",
            "design-review-summary-attestation.schema.json",
            "grill-completion-attestation.schema.json",
            "post-grill-review-policy.schema.json",
            "review-host-attestation.schema.json", "review-fallback-authorization.schema.json",
            "review-independence-receipt.schema.json",
        ):
            with self.subTest(name=name):
                with self.assertRaises(ContractError) as error:
                    load_contract(name, "{}")
                self.assertNotEqual(error.exception.reason, "contract-schema-not-registered")


if __name__ == "__main__":
    unittest.main()
