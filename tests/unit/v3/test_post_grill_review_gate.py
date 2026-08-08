import copy
from datetime import datetime, timezone
import json
import unittest

from selfworkflow.v3.hashing import content_hash


DESIGN_HASH = "sha256:" + "a" * 64
POLICY_HASH = "sha256:" + "b" * 64
SUMMARY_HASH = "sha256:" + "c" * 64
NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def _receipt(*, attested=True, independence=None, fallback_ref=None):
    value = {
        "schemaVersion": 3,
        "reviewMode": "brainstorming-cross-review",
        "dispatchId": "dispatch-1",
        "forkContext": False,
        "implementationAgentIdentity": "implementation-agent",
        "implementationContextIdentity": "implementation-context",
        "reviewerAgentIdentity": "review-agent",
        "reviewerContextIdentity": "review-context",
        "hostAgentIdentity": "host-agent",
        "hostContextIdentity": "host-context",
        "hostAttestationRef": "host-attestation-1" if attested else None,
        "inputMode": "summary-only",
        "parentContextImported": False,
        "grillReasoningReceived": False,
        "inputSummaryHash": SUMMARY_HASH,
        "designHash": DESIGN_HASH,
        "reviewerPolicyHash": POLICY_HASH,
        "resultHash": "sha256:" + "d" * 64,
        "fallbackAuthorizationRef": fallback_ref,
        "independence": independence or ("independent" if attested else "unverified"),
    }
    value["receiptHash"] = content_hash(value)
    return value


def _fallback(mode):
    value = {
        "schemaVersion": 3,
        "designHash": DESIGN_HASH,
        "reviewerPolicyHash": POLICY_HASH,
        "reason": (
            "host-attestation-unavailable"
            if mode == "independent-context-without-attestation"
            else "independent-context-unavailable"
        ),
        "fallbackMode": mode,
        "confirmationSource": "explicit-user-confirmation",
        "issuedAt": "2026-08-09T11:00:00Z",
        "expiresAt": "2026-08-09T13:00:00Z",
        "nonce": "fallback-1",
        "revocationState": "active",
    }
    value["authorizationHash"] = content_hash(value)
    return value


class PostGrillReviewGateTests(unittest.TestCase):
    def _evaluate(self, independent, receipt=None, fallback=None):
        from selfworkflow.v3.review_gate import evaluate_post_grill_review

        return evaluate_post_grill_review(
            independent_context_available=independent,
            receipt=receipt,
            fallback_authorization=fallback,
            design_hash=DESIGN_HASH,
            reviewer_policy_hash=POLICY_HASH,
            input_summary_hash=SUMMARY_HASH,
            now=NOW,
            host_attestation_resolver=lambda ref: ref == "host-attestation-1",
        )

    def test_five_row_truth_table(self):
        cases = (
            (True, _receipt(), None, "proceed", "independent", None),
            (True, _receipt(attested=False), None, "pause", "unverified", "post-grill-review-attestation-missing"),
            (
                True,
                _receipt(
                    attested=False,
                    fallback_ref=_fallback("independent-context-without-attestation")["authorizationHash"],
                ),
                _fallback("independent-context-without-attestation"),
                "proceed", "unverified", None,
            ),
            (False, None, None, "pause", "unverified", "post-grill-review-user-authorization-required"),
            (False, None, _fallback("same-agent-structured-review"), "proceed", "unverified", None),
        )
        for independent, receipt, fallback, status, independence, reason in cases:
            with self.subTest(independent=independent, fallback=fallback):
                result = self._evaluate(independent, receipt, fallback)
                self.assertEqual(result.status, status)
                self.assertEqual(result.independence, independence)
                self.assertEqual(result.reason_code, reason)

    def test_fallback_mode_must_match_exact_truth_table_row(self):
        wrong_for_attestation = _fallback("same-agent-structured-review")
        wrong_for_context = _fallback("independent-context-without-attestation")
        self.assertEqual(
            self._evaluate(True, _receipt(attested=False), wrong_for_attestation).reason_code,
            "post-grill-review-attestation-missing",
        )
        self.assertEqual(
            self._evaluate(False, None, wrong_for_context).reason_code,
            "post-grill-review-user-authorization-required",
        )

    def test_expired_revoked_or_hash_drift_fallback_fails_closed(self):
        mutations = (
            lambda item: item.update({"expiresAt": "2026-08-09T11:59:59Z"}),
            lambda item: item.update({"revocationState": "revoked"}),
            lambda item: item.update({"designHash": "sha256:" + "e" * 64}),
            lambda item: item.update({"reviewerPolicyHash": "sha256:" + "f" * 64}),
        )
        for mutation in mutations:
            fallback = _fallback("same-agent-structured-review")
            mutation(fallback)
            fallback["authorizationHash"] = content_hash({
                key: value for key, value in fallback.items()
                if key != "authorizationHash"
            })
            with self.subTest(fallback=fallback):
                result = self._evaluate(False, None, fallback)
                self.assertEqual(result.status, "pause")
                self.assertEqual(result.reason_code, "post-grill-review-user-authorization-required")

    def test_tampering_content_hash_or_receipt_binding_is_input_invalid(self):
        fallback = _fallback("same-agent-structured-review")
        fallback["nonce"] = "tampered"
        self.assertEqual(
            self._evaluate(False, None, fallback).reason_code,
            "post-grill-review-input-invalid",
        )

        receipt = _receipt()
        receipt["inputSummaryHash"] = "sha256:" + "e" * 64
        receipt["receiptHash"] = content_hash({
            key: value for key, value in receipt.items() if key != "receiptHash"
        })
        self.assertEqual(
            self._evaluate(True, receipt, None).reason_code,
            "post-grill-review-input-invalid",
        )

    def test_host_attestation_reference_must_resolve_through_host_boundary(self):
        from selfworkflow.v3.review_gate import evaluate_post_grill_review

        result = evaluate_post_grill_review(
            independent_context_available=True,
            receipt=_receipt(),
            fallback_authorization=None,
            design_hash=DESIGN_HASH,
            reviewer_policy_hash=POLICY_HASH,
            input_summary_hash=SUMMARY_HASH,
            now=NOW,
            host_attestation_resolver=lambda ref: False,
        )
        self.assertEqual(result.status, "pause")
        self.assertEqual(result.reason_code, "post-grill-review-attestation-missing")

    def test_review_contract_schemas_are_registered_and_closed(self):
        from selfworkflow.v3.contracts import ContractError, load_contract

        names = (
            "design-review-summary.schema.json",
            "review-fallback-authorization.schema.json",
            "review-independence-receipt.schema.json",
        )
        for name in names:
            with self.subTest(name=name):
                with self.assertRaises(ContractError) as error:
                    load_contract(name, "{}")
                self.assertNotEqual(error.exception.reason, "contract-schema-not-registered")


if __name__ == "__main__":
    unittest.main()
