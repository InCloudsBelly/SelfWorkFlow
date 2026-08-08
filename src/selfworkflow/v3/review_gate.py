"""Fail-closed post-Grill review independence truth table."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any

from selfworkflow.v3.contracts import ContractError, load_contract
from selfworkflow.v3.hashing import HashingError, content_hash, require_hash


@dataclass(frozen=True)
class PostGrillReviewDecision:
    status: str
    independence: str
    reason_code: str | None
    review_mode: str
    fallback_authorization_ref: str | None


def _decision(status: str, independence: str, reason: str | None, mode: str, ref: str | None = None) -> PostGrillReviewDecision:
    return PostGrillReviewDecision(status, independence, reason, mode, ref)


def _load(name: str, value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if type(value) is not dict:
        raise ValueError
    return load_contract(name, json.dumps(value, ensure_ascii=False, allow_nan=False))


def _hash_valid(document: dict[str, Any], field: str) -> bool:
    return document[field] == content_hash({
        key: value for key, value in document.items() if key != field
    })


def _valid_fallback(
    authorization: dict[str, Any] | None,
    *,
    expected_mode: str,
    design_hash: str,
    policy_hash: str,
    now: datetime,
) -> bool:
    if authorization is None:
        return False
    issued = datetime.fromisoformat(authorization["issuedAt"][:-1] + "+00:00")
    expires = datetime.fromisoformat(authorization["expiresAt"][:-1] + "+00:00")
    return (
        _hash_valid(authorization, "authorizationHash")
        and authorization["fallbackMode"] == expected_mode
        and authorization["designHash"] == design_hash
        and authorization["reviewerPolicyHash"] == policy_hash
        and authorization["revocationState"] == "active"
        and issued <= now < expires
    )


def evaluate_post_grill_review(
    *,
    independent_context_available: bool,
    receipt: object,
    fallback_authorization: object,
    design_hash: str,
    reviewer_policy_hash: str,
    input_summary_hash: str,
    now: datetime,
    host_attestation_resolver=None,
) -> PostGrillReviewDecision:
    """Evaluate the fixed five-row policy; invalid evidence never grants access."""

    if type(independent_context_available) is not bool or type(now) is not datetime:
        return _decision("pause", "unverified", "post-grill-review-input-invalid", "none")
    try:
        for value in (design_hash, reviewer_policy_hash, input_summary_hash):
            require_hash(value)
        observed_at = now.astimezone(timezone.utc)
        parsed_receipt = _load("review-independence-receipt.schema.json", receipt)
        fallback = _load("review-fallback-authorization.schema.json", fallback_authorization)
        if parsed_receipt is not None and (
            not _hash_valid(parsed_receipt, "receiptHash")
            or parsed_receipt["designHash"] != design_hash
            or parsed_receipt["reviewerPolicyHash"] != reviewer_policy_hash
            or parsed_receipt["inputSummaryHash"] != input_summary_hash
            or parsed_receipt["forkContext"] is not False
            or parsed_receipt["inputMode"] != "summary-only"
            or parsed_receipt["parentContextImported"] is not False
            or parsed_receipt["grillReasoningReceived"] is not False
            or parsed_receipt["reviewerAgentIdentity"]
            == parsed_receipt["implementationAgentIdentity"]
            or parsed_receipt["reviewerContextIdentity"]
            == parsed_receipt["implementationContextIdentity"]
        ):
            raise ValueError
        if fallback is not None and not _hash_valid(fallback, "authorizationHash"):
            raise ValueError
    except (ContractError, HashingError, TypeError, ValueError, OverflowError):
        return _decision("pause", "unverified", "post-grill-review-input-invalid", "none")

    if independent_context_available:
        attested = False
        if (
            parsed_receipt is not None
            and parsed_receipt["hostAttestationRef"] is not None
            and parsed_receipt["independence"] == "independent"
        ):
            try:
                attested = bool(
                    host_attestation_resolver(parsed_receipt["hostAttestationRef"])
                ) if callable(host_attestation_resolver) else False
            except Exception:
                return _decision(
                    "pause", "unverified", "post-grill-review-input-invalid", "none"
                )
        if attested:
            return _decision("proceed", "independent", None, "independent-context")
        if _valid_fallback(
            fallback,
            expected_mode="independent-context-without-attestation",
            design_hash=design_hash,
            policy_hash=reviewer_policy_hash,
            now=observed_at,
        ) and parsed_receipt is not None and (
            parsed_receipt["fallbackAuthorizationRef"]
            == fallback["authorizationHash"]
        ):
            return _decision(
                "proceed", "unverified", None,
                "independent-context-without-attestation",
                fallback["authorizationHash"],
            )
        return _decision(
            "pause", "unverified", "post-grill-review-attestation-missing",
            "independent-context",
        )

    if _valid_fallback(
        fallback,
        expected_mode="same-agent-structured-review",
        design_hash=design_hash,
        policy_hash=reviewer_policy_hash,
        now=observed_at,
    ):
        return _decision(
            "proceed", "unverified", None, "same-agent-structured-review",
            fallback["authorizationHash"],
        )
    return _decision(
        "pause", "unverified", "post-grill-review-user-authorization-required",
        "none",
    )
