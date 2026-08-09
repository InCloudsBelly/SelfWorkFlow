"""Host-owned dispatch boundary for post-Grill Brainstorming review."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any, Protocol

from selfworkflow.v3.contracts import ContractError, load_contract
from selfworkflow.v3.hashing import HashingError, clone, content_hash, require_hash


class ReviewDispatchError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class HostDispatchObservation:
    """Trusted Host observation; Agent output is isolated in returned_value."""

    dispatch_id: str
    dispatch_nonce: str
    plan_hash: str
    attempt_ref: str
    issued_at: str
    expires_at: str
    review_mode: str
    fork_context: bool
    sent_payload: dict[str, Any]
    host_agent_identity: str
    host_context_identity: str
    reviewer_agent_identity: str
    reviewer_context_identity: str
    host_attestation: dict[str, Any] | None
    returned_value: dict[str, Any]


class ReviewDispatchPort(Protocol):
    def dispatch_review(
        self, *, review_mode: str, fork_context: bool, payload: dict[str, Any],
        implementation_agent_identity: str,
        implementation_context_identity: str,
        plan_hash: str,
        attempt_ref: str,
    ) -> HostDispatchObservation: ...


_FORBIDDEN_SUMMARY_MARKERS = (
    "transcript", "reasoning", "chain-of-thought", "chain of thought",
    "盘问记录", "推理过程",
)


def _valid_identity(value: object) -> bool:
    return type(value) is str and 1 <= len(value.encode("utf-8")) <= 256


def _valid_window(issued_at: object, expires_at: object) -> bool:
    try:
        if not isinstance(issued_at, str) or not isinstance(expires_at, str):
            return False
        issued = datetime.fromisoformat(issued_at[:-1] + "+00:00")
        expires = datetime.fromisoformat(expires_at[:-1] + "+00:00")
        return issued_at.endswith("Z") and expires_at.endswith("Z") and issued < expires
    except (TypeError, ValueError, OverflowError):
        return False


def _unique_object_ids(items: list[dict[str, Any]], key: str) -> bool:
    values = [item[key] for item in items]
    return len(values) == len(set(values))


def _contains_forbidden_summary_content(value: object) -> bool:
    if isinstance(value, str):
        folded = value.casefold()
        return any(marker in folded for marker in _FORBIDDEN_SUMMARY_MARKERS)
    if isinstance(value, list):
        return any(_contains_forbidden_summary_content(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_forbidden_summary_content(item) for item in value.values())
    return False


def _load_summary(value: object) -> dict[str, Any]:
    if type(value) is not dict:
        raise ReviewDispatchError("post-grill-review-input-invalid")
    try:
        summary = load_contract(
            "design-review-summary.schema.json",
            json.dumps(value, ensure_ascii=False, allow_nan=False),
        )
        if (
            summary["summaryHash"] != content_hash(
                {key: item for key, item in summary.items() if key != "summaryHash"}
            )
            or not _unique_object_ids(summary["alternatives"], "alternativeId")
            or not _unique_object_ids(summary["risks"], "riskId")
            or not _unique_object_ids(summary["acceptanceCriteria"], "criterionId")
            or _contains_forbidden_summary_content(summary)
        ):
            raise ReviewDispatchError("post-grill-review-input-invalid")
        return summary
    except (ContractError, HashingError, TypeError, ValueError, OverflowError):
        raise ReviewDispatchError("post-grill-review-input-invalid") from None


def _load_result(value: object, summary: dict[str, Any]) -> dict[str, Any]:
    if type(value) is not dict:
        raise ReviewDispatchError("review-result-invalid")
    try:
        result = load_contract(
            "design-review-result.schema.json",
            json.dumps(value, ensure_ascii=False, allow_nan=False),
        )
        finding_ids = [item["findingId"] for item in result["findings"]]
        if (
            result["resultHash"] != content_hash(
                {key: item for key, item in result.items() if key != "resultHash"}
            )
            or result["summaryHash"] != summary["summaryHash"]
            or result["designHash"] != summary["designHash"]
            or len(finding_ids) != len(set(finding_ids))
            or (
                result["verdict"] == "approve"
                and any(item["severity"] in {"critical", "important"} for item in result["findings"])
            )
        ):
            raise ReviewDispatchError("review-result-invalid")
        return result
    except (ContractError, HashingError, TypeError, ValueError, OverflowError):
        raise ReviewDispatchError("review-result-invalid") from None


def _load_attestation(
    value: object,
    *,
    observation: HostDispatchObservation,
    payload_hash: str,
    result_hash: str,
    implementation_agent_identity: str,
    implementation_context_identity: str,
    plan_hash: str,
    attempt_ref: str,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if type(value) is not dict:
        raise ReviewDispatchError("review-host-attestation-invalid")
    try:
        attestation = load_contract(
            "review-host-attestation.schema.json",
            json.dumps(value, ensure_ascii=False, allow_nan=False),
        )
        if attestation["attestationHash"] != content_hash(
            {key: item for key, item in attestation.items() if key != "attestationHash"}
        ):
            raise ReviewDispatchError("review-host-attestation-invalid")
        expected = {
            "dispatchId": observation.dispatch_id,
            "dispatchNonce": observation.dispatch_nonce,
            "planHash": plan_hash,
            "attemptRef": attempt_ref,
            "issuedAt": observation.issued_at,
            "expiresAt": observation.expires_at,
            "reviewMode": observation.review_mode,
            "forkContext": observation.fork_context,
            "payloadHash": payload_hash,
            "implementationAgentIdentity": implementation_agent_identity,
            "implementationContextIdentity": implementation_context_identity,
            "hostAgentIdentity": observation.host_agent_identity,
            "hostContextIdentity": observation.host_context_identity,
            "reviewerAgentIdentity": observation.reviewer_agent_identity,
            "reviewerContextIdentity": observation.reviewer_context_identity,
            "resultHash": result_hash,
        }
        if any(attestation[key] != item for key, item in expected.items()):
            raise ReviewDispatchError("review-host-attestation-binding-invalid")
        return attestation
    except (ContractError, HashingError, TypeError, ValueError, OverflowError):
        raise ReviewDispatchError("review-host-attestation-invalid") from None


def _dispatch_review(
    summary: object,
    *,
    implementation_agent_identity: str,
    implementation_context_identity: str,
    port: ReviewDispatchPort,
    fork_context: bool,
    fallback_authorization_ref: str | None,
    plan_hash: str,
    attempt_ref: str,
) -> dict[str, Any]:
    if (
        not _valid_identity(implementation_agent_identity)
        or not _valid_identity(implementation_context_identity)
        or not hasattr(port, "dispatch_review")
    ):
        raise ReviewDispatchError("post-grill-review-input-invalid")
    if fallback_authorization_ref is not None:
        try:
            require_hash(fallback_authorization_ref)
        except HashingError:
            raise ReviewDispatchError("post-grill-review-input-invalid") from None
    try:
        require_hash(plan_hash)
    except HashingError:
        raise ReviewDispatchError("post-grill-review-input-invalid") from None
    if not _valid_identity(attempt_ref):
        raise ReviewDispatchError("post-grill-review-input-invalid")
    normalized = _load_summary(summary)
    payload = {
        "schemaVersion": 3,
        "reviewMode": "brainstorming-cross-review",
        "designReviewSummary": clone(normalized),
    }
    try:
        observation = port.dispatch_review(
            review_mode="brainstorming-cross-review",
            fork_context=fork_context,
            payload=clone(payload),
            implementation_agent_identity=implementation_agent_identity,
            implementation_context_identity=implementation_context_identity,
            plan_hash=plan_hash,
            attempt_ref=attempt_ref,
        )
    except ReviewDispatchError:
        raise
    except Exception:
        raise ReviewDispatchError("review-dispatch-failed") from None
    if type(observation) is not HostDispatchObservation:
        raise ReviewDispatchError("review-dispatch-observation-invalid")
    try:
        observed_payload = clone(observation.sent_payload)
    except (HashingError, TypeError, ValueError, OverflowError):
        raise ReviewDispatchError("review-dispatch-observation-invalid") from None
    if (
        observation.review_mode != "brainstorming-cross-review"
        or observation.fork_context is not fork_context
        or observed_payload != payload
    ):
        raise ReviewDispatchError("review-dispatch-observation-mismatch")
    identities = (
        observation.dispatch_id,
        observation.host_agent_identity,
        observation.host_context_identity,
        observation.reviewer_agent_identity,
        observation.reviewer_context_identity,
        observation.dispatch_nonce,
        observation.attempt_ref,
    )
    if (
        any(not _valid_identity(item) for item in identities)
        or observation.plan_hash != plan_hash
        or observation.attempt_ref != attempt_ref
        or not _valid_window(observation.issued_at, observation.expires_at)
    ):
        raise ReviewDispatchError("review-dispatch-observation-invalid")
    independent_identity = (
        observation.reviewer_agent_identity != implementation_agent_identity
        and observation.reviewer_context_identity != implementation_context_identity
    )
    if fork_context is False and not independent_identity:
        raise ReviewDispatchError("review-identity-not-independent")
    if fork_context is True and independent_identity:
        raise ReviewDispatchError("fallback-review-identity-mismatch")

    result = _load_result(observation.returned_value, normalized)
    payload_hash = content_hash(payload)
    attestation = _load_attestation(
        observation.host_attestation,
        observation=observation,
        payload_hash=payload_hash,
        result_hash=result["resultHash"],
        implementation_agent_identity=implementation_agent_identity,
        implementation_context_identity=implementation_context_identity,
        plan_hash=plan_hash,
        attempt_ref=attempt_ref,
    )
    if fork_context is True and attestation is not None:
        raise ReviewDispatchError("fallback-review-attestation-invalid")
    independence = "independent" if attestation is not None else "unverified"
    receipt = {
        "schemaVersion": 3,
        "reviewMode": "brainstorming-cross-review",
        "dispatchId": observation.dispatch_id,
        "dispatchNonce": observation.dispatch_nonce,
        "planHash": plan_hash,
        "attemptRef": attempt_ref,
        "issuedAt": observation.issued_at,
        "expiresAt": observation.expires_at,
        "forkContext": fork_context,
        "implementationAgentIdentity": implementation_agent_identity,
        "implementationContextIdentity": implementation_context_identity,
        "reviewerAgentIdentity": observation.reviewer_agent_identity,
        "reviewerContextIdentity": observation.reviewer_context_identity,
        "hostAgentIdentity": observation.host_agent_identity,
        "hostContextIdentity": observation.host_context_identity,
        "hostAttestationRef": None if attestation is None else attestation["attestationHash"],
        "inputMode": "summary-only",
        "parentContextImported": fork_context,
        "grillReasoningReceived": False,
        "payloadHash": payload_hash,
        "inputSummaryHash": normalized["summaryHash"],
        "designHash": normalized["designHash"],
        "reviewerPolicyHash": normalized["reviewerPolicyHash"],
        "resultHash": result["resultHash"],
        "reviewVerdict": result["verdict"],
        "reviewLevel": result["reviewLevel"],
        "fallbackAuthorizationRef": fallback_authorization_ref,
        "independence": independence,
    }
    receipt["receiptHash"] = content_hash(receipt)
    try:
        return load_contract(
            "review-independence-receipt.schema.json",
            json.dumps(receipt, ensure_ascii=False, allow_nan=False),
        )
    except ContractError:
        raise ReviewDispatchError("review-dispatch-observation-invalid") from None


def dispatch_independent_review(
    summary: object,
    *,
    implementation_agent_identity: str,
    implementation_context_identity: str,
    port: ReviewDispatchPort,
    fallback_authorization_ref: str | None = None,
    plan_hash: str,
    attempt_ref: str,
) -> dict[str, Any]:
    """Force a fresh-context dispatch and derive a receipt from Host observations."""

    return _dispatch_review(
        summary,
        implementation_agent_identity=implementation_agent_identity,
        implementation_context_identity=implementation_context_identity,
        port=port,
        fork_context=False,
        fallback_authorization_ref=fallback_authorization_ref,
        plan_hash=plan_hash,
        attempt_ref=attempt_ref,
    )


def dispatch_same_agent_fallback_review(
    summary: object,
    *,
    implementation_agent_identity: str,
    implementation_context_identity: str,
    port: ReviewDispatchPort,
    fallback_authorization_ref: str,
    plan_hash: str,
    attempt_ref: str,
) -> dict[str, Any]:
    """Record the explicitly authorized same-Agent structured review path."""

    return _dispatch_review(
        summary,
        implementation_agent_identity=implementation_agent_identity,
        implementation_context_identity=implementation_context_identity,
        port=port,
        fork_context=True,
        fallback_authorization_ref=fallback_authorization_ref,
        plan_hash=plan_hash,
        attempt_ref=attempt_ref,
    )
