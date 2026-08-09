"""Fail-closed post-Grill review independence truth table."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Callable

from selfworkflow.v3.contracts import ContractError, load_contract
from selfworkflow.v3.hashing import HashingError, content_hash, require_hash


@dataclass(frozen=True)
class PostGrillReviewDecision:
    status: str
    independence: str
    reason_code: str | None
    review_mode: str
    fallback_authorization_ref: str | None


def _decision(
    status: str, independence: str, reason: str | None, mode: str,
    ref: str | None = None,
) -> PostGrillReviewDecision:
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


def _resolve_fallback(
    reference: str | None,
    resolver: Callable[[str], object] | None,
) -> dict[str, Any] | None:
    if reference is None:
        return None
    require_hash(reference)
    if not callable(resolver):
        raise ValueError
    value = resolver(reference)
    authorization = _load("review-fallback-authorization.schema.json", value)
    if (
        authorization is None
        or authorization["authorizationHash"] != reference
        or not _hash_valid(authorization, "authorizationHash")
    ):
        raise ValueError
    return authorization


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
        authorization["fallbackMode"] == expected_mode
        and authorization["designHash"] == design_hash
        and authorization["reviewerPolicyHash"] == policy_hash
        and authorization["revocationState"] == "active"
        and issued <= now < expires
    )


def _resolve_attestation(
    receipt: dict[str, Any], resolver: Callable[[str], object] | None,
    consumer: Callable[[str, str], bool] | None, *, now: datetime,
    plan_hash: str, attempt_ref: str,
) -> str:
    try:
        reference = receipt["hostAttestationRef"]
        if reference is None or not callable(resolver):
            return "missing"
        value = resolver(reference)
        attestation = _load("review-host-attestation.schema.json", value)
        if (
            attestation is None
            or attestation["attestationHash"] != reference
            or not _hash_valid(attestation, "attestationHash")
        ):
            return "missing"
        bindings = {
            "dispatchId": "dispatchId",
            "reviewMode": "reviewMode",
            "forkContext": "forkContext",
            "payloadHash": "payloadHash",
            "implementationAgentIdentity": "implementationAgentIdentity",
            "implementationContextIdentity": "implementationContextIdentity",
            "hostAgentIdentity": "hostAgentIdentity",
            "hostContextIdentity": "hostContextIdentity",
            "reviewerAgentIdentity": "reviewerAgentIdentity",
            "reviewerContextIdentity": "reviewerContextIdentity",
            "resultHash": "resultHash",
            "dispatchNonce": "dispatchNonce",
            "planHash": "planHash",
            "attemptRef": "attemptRef",
            "issuedAt": "issuedAt",
            "expiresAt": "expiresAt",
        }
        issued = datetime.fromisoformat(attestation["issuedAt"][:-1] + "+00:00")
        expires = datetime.fromisoformat(attestation["expiresAt"][:-1] + "+00:00")
        if (
            not all(attestation[left] == receipt[right] for left, right in bindings.items())
            or attestation["planHash"] != plan_hash
            or attestation["attemptRef"] != attempt_ref
            or not (issued <= now < expires)
        ):
            return "missing"
        if not callable(consumer):
            return "missing"
        return (
            "valid"
            if consumer(attestation["attestationHash"], attestation["dispatchNonce"]) is True
            else "replayed"
        )
    except (ContractError, HashingError, TypeError, ValueError, OverflowError):
        return "missing"


def _receipt_semantics_valid(
    receipt: dict[str, Any],
    *, design_hash: str, reviewer_policy_hash: str, input_summary_hash: str,
    plan_hash: str, attempt_ref: str, now: datetime,
) -> bool:
    try:
        issued = datetime.fromisoformat(receipt["issuedAt"][:-1] + "+00:00")
        expires = datetime.fromisoformat(receipt["expiresAt"][:-1] + "+00:00")
    except (TypeError, ValueError, OverflowError):
        return False
    if (
        not _hash_valid(receipt, "receiptHash")
        or receipt["designHash"] != design_hash
        or receipt["reviewerPolicyHash"] != reviewer_policy_hash
        or receipt["inputSummaryHash"] != input_summary_hash
        or receipt["inputMode"] != "summary-only"
        or receipt["grillReasoningReceived"] is not False
        or receipt["planHash"] != plan_hash
        or receipt["attemptRef"] != attempt_ref
        or not (issued <= now < expires)
    ):
        return False
    if receipt["reviewVerdict"] != "approve" or receipt["reviewLevel"] not in {"L2", "L3"}:
        return False
    if receipt["forkContext"] is False:
        return (
            receipt["parentContextImported"] is False
            and receipt["reviewerAgentIdentity"] != receipt["implementationAgentIdentity"]
            and receipt["reviewerContextIdentity"] != receipt["implementationContextIdentity"]
        )
    return (
        receipt["parentContextImported"] is True
        and receipt["independence"] == "unverified"
        and receipt["hostAttestationRef"] is None
        and receipt["reviewerAgentIdentity"] == receipt["implementationAgentIdentity"]
        and receipt["reviewerContextIdentity"] == receipt["implementationContextIdentity"]
    )


def _consume_fallback(
    authorization: dict[str, Any],
    consumer: Callable[[str, str], bool] | None,
) -> bool:
    if not callable(consumer):
        return False
    try:
        return consumer(authorization["authorizationHash"], authorization["nonce"]) is True
    except Exception:
        return False


def evaluate_post_grill_review(
    *,
    independent_context_available: bool,
    receipt: object,
    fallback_authorization_ref: str | None,
    design_hash: str,
    reviewer_policy_hash: str,
    input_summary_hash: str,
    plan_hash: str,
    attempt_ref: str,
    now: datetime,
    host_attestation_resolver: Callable[[str], object] | None = None,
    host_attestation_consumer: Callable[[str, str], bool] | None = None,
    fallback_authorization_resolver: Callable[[str], object] | None = None,
    fallback_authorization_consumer: Callable[[str, str], bool] | None = None,
) -> PostGrillReviewDecision:
    """Evaluate the policy; only Host-resolved, one-shot evidence can proceed."""

    if type(independent_context_available) is not bool or type(now) is not datetime:
        return _decision("pause", "unverified", "post-grill-review-input-invalid", "none")
    try:
        for value in (design_hash, reviewer_policy_hash, input_summary_hash, plan_hash):
            require_hash(value)
        if type(attempt_ref) is not str or not attempt_ref:
            raise ValueError
        observed_at = now.astimezone(timezone.utc)
        parsed_receipt = _load("review-independence-receipt.schema.json", receipt)
        fallback = _resolve_fallback(
            fallback_authorization_ref, fallback_authorization_resolver,
        )
        if parsed_receipt is not None and not _receipt_semantics_valid(
            parsed_receipt,
            design_hash=design_hash,
            reviewer_policy_hash=reviewer_policy_hash,
            input_summary_hash=input_summary_hash,
            plan_hash=plan_hash,
            attempt_ref=attempt_ref,
            now=observed_at,
        ):
            if parsed_receipt.get("reviewVerdict") == "changes-required":
                return _decision(
                    "pause", parsed_receipt.get("independence", "unverified"),
                    "post-grill-review-changes-required", "none",
                )
            raise ValueError
    except (ContractError, HashingError, TypeError, ValueError, OverflowError):
        return _decision("pause", "unverified", "post-grill-review-input-invalid", "none")

    if independent_context_available:
        attestation_state = "missing"
        if parsed_receipt is not None and parsed_receipt["forkContext"] is False:
            attestation_state = _resolve_attestation(
                parsed_receipt, host_attestation_resolver,
                host_attestation_consumer, now=observed_at,
                plan_hash=plan_hash, attempt_ref=attempt_ref,
            )
        if (
            parsed_receipt is not None
            and parsed_receipt["forkContext"] is False
            and parsed_receipt["independence"] == "independent"
            and attestation_state == "valid"
        ):
            return _decision("proceed", "independent", None, "independent-context")
        if attestation_state == "replayed":
            return _decision(
                "pause", "unverified", "post-grill-review-attestation-replayed",
                "independent-context",
            )
        if (
            _valid_fallback(
                fallback,
                expected_mode="independent-context-without-attestation",
                design_hash=design_hash,
                policy_hash=reviewer_policy_hash,
                now=observed_at,
            )
            and parsed_receipt is not None
            and parsed_receipt["forkContext"] is False
            and parsed_receipt["fallbackAuthorizationRef"] == fallback["authorizationHash"]
        ):
            if not _consume_fallback(fallback, fallback_authorization_consumer):
                return _decision(
                    "pause", "unverified", "post-grill-review-authorization-replayed",
                    "independent-context-without-attestation",
                )
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
        if parsed_receipt is None:
            return _decision(
                "review-required", "unverified", None,
                "same-agent-structured-review", fallback["authorizationHash"],
            )
        if (
            parsed_receipt["forkContext"] is True
            and parsed_receipt["fallbackAuthorizationRef"] == fallback["authorizationHash"]
        ):
            if not _consume_fallback(fallback, fallback_authorization_consumer):
                return _decision(
                    "pause", "unverified", "post-grill-review-authorization-replayed",
                    "same-agent-structured-review",
                )
            return _decision(
                "proceed", "unverified", None, "same-agent-structured-review",
                fallback["authorizationHash"],
            )
    return _decision(
        "pause", "unverified", "post-grill-review-user-authorization-required",
        "none",
    )
