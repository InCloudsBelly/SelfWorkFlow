"""Host-owned dispatch boundary for post-Grill Brainstorming review."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol

from selfworkflow.v3.contracts import ContractError, load_contract
from selfworkflow.v3.hashing import HashingError, clone, content_hash


class ReviewDispatchError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class HostDispatchObservation:
    """Trusted Host observation; Agent output is isolated in returned_value."""

    dispatch_id: str
    review_mode: str
    fork_context: bool
    sent_payload: dict[str, Any]
    host_agent_identity: str
    host_context_identity: str
    reviewer_agent_identity: str
    reviewer_context_identity: str
    host_attestation_ref: str | None
    returned_value: dict[str, Any]


class ReviewDispatchPort(Protocol):
    def dispatch_review(
        self, *, review_mode: str, fork_context: bool, payload: dict[str, Any]
    ) -> HostDispatchObservation: ...


def _valid_identity(value: object) -> bool:
    return type(value) is str and 1 <= len(value.encode("utf-8")) <= 256


def _load_summary(value: object) -> dict[str, Any]:
    if type(value) is not dict:
        raise ReviewDispatchError("post-grill-review-input-invalid")
    try:
        summary = load_contract(
            "design-review-summary.schema.json",
            json.dumps(value, ensure_ascii=False, allow_nan=False),
        )
        if summary["summaryHash"] != content_hash(
            {key: item for key, item in summary.items() if key != "summaryHash"}
        ):
            raise ReviewDispatchError("post-grill-review-input-invalid")
        return summary
    except (ContractError, HashingError, TypeError, ValueError, OverflowError):
        raise ReviewDispatchError("post-grill-review-input-invalid") from None


def dispatch_independent_review(
    summary: object,
    *,
    implementation_agent_identity: str,
    implementation_context_identity: str,
    port: ReviewDispatchPort,
    fallback_authorization_ref: str | None = None,
) -> dict[str, Any]:
    """Force fresh-context dispatch and derive a receipt from Host observations."""

    if (
        not _valid_identity(implementation_agent_identity)
        or not _valid_identity(implementation_context_identity)
        or not hasattr(port, "dispatch_review")
    ):
        raise ReviewDispatchError("post-grill-review-input-invalid")
    if fallback_authorization_ref is not None:
        try:
            from selfworkflow.v3.hashing import require_hash
            require_hash(fallback_authorization_ref)
        except HashingError:
            raise ReviewDispatchError("post-grill-review-input-invalid") from None
    normalized = _load_summary(summary)
    payload = {
        "schemaVersion": 3,
        "reviewMode": "brainstorming-cross-review",
        "designReviewSummary": clone(normalized),
    }
    try:
        observation = port.dispatch_review(
            review_mode="brainstorming-cross-review",
            fork_context=False,
            payload=clone(payload),
        )
    except ReviewDispatchError:
        raise
    except Exception:
        raise ReviewDispatchError("review-dispatch-failed") from None
    if type(observation) is not HostDispatchObservation:
        raise ReviewDispatchError("review-dispatch-observation-invalid")
    try:
        observed_payload = clone(observation.sent_payload)
        result_hash = content_hash(observation.returned_value)
    except (HashingError, TypeError, ValueError, OverflowError):
        raise ReviewDispatchError("review-dispatch-observation-invalid") from None
    if (
        observation.review_mode != "brainstorming-cross-review"
        or observation.fork_context is not False
        or observed_payload != payload
    ):
        raise ReviewDispatchError("review-dispatch-observation-mismatch")
    identities = (
        observation.dispatch_id,
        observation.host_agent_identity,
        observation.host_context_identity,
        observation.reviewer_agent_identity,
        observation.reviewer_context_identity,
    )
    if any(not _valid_identity(item) for item in identities) or (
        observation.host_attestation_ref is not None
        and not _valid_identity(observation.host_attestation_ref)
    ):
        raise ReviewDispatchError("review-dispatch-observation-invalid")
    if (
        observation.reviewer_agent_identity == implementation_agent_identity
        or observation.reviewer_context_identity == implementation_context_identity
    ):
        raise ReviewDispatchError("review-identity-not-independent")

    receipt = {
        "schemaVersion": 3,
        "reviewMode": "brainstorming-cross-review",
        "dispatchId": observation.dispatch_id,
        "forkContext": False,
        "implementationAgentIdentity": implementation_agent_identity,
        "implementationContextIdentity": implementation_context_identity,
        "reviewerAgentIdentity": observation.reviewer_agent_identity,
        "reviewerContextIdentity": observation.reviewer_context_identity,
        "hostAgentIdentity": observation.host_agent_identity,
        "hostContextIdentity": observation.host_context_identity,
        "hostAttestationRef": observation.host_attestation_ref,
        "inputMode": "summary-only",
        "parentContextImported": False,
        "grillReasoningReceived": False,
        "inputSummaryHash": normalized["summaryHash"],
        "designHash": normalized["designHash"],
        "reviewerPolicyHash": normalized["reviewerPolicyHash"],
        "resultHash": result_hash,
        "fallbackAuthorizationRef": fallback_authorization_ref,
        "independence": (
            "independent" if observation.host_attestation_ref else "unverified"
        ),
    }
    receipt["receiptHash"] = content_hash(receipt)
    try:
        return load_contract(
            "review-independence-receipt.schema.json",
            json.dumps(receipt, ensure_ascii=False, allow_nan=False),
        )
    except ContractError:
        raise ReviewDispatchError("review-dispatch-observation-invalid") from None
