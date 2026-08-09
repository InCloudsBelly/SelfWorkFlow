"""Host-side verification of clean post-Grill review inputs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Callable

from selfworkflow.v3.contracts import ContractError, load_contract
from selfworkflow.v3.hashing import HashingError, clone, content_hash, require_hash


class ReviewInputError(ValueError):
    def __init__(self, reason: str = "post-grill-review-input-invalid") -> None:
        self.reason = reason
        super().__init__(reason)


_INPUT_TOKEN = object()


class VerifiedReviewInput:
    """Sealed summary whose clean provenance and Grill completion were checked."""

    __slots__ = ("_summary", "_summary_attestation_hash", "_completion_hash", "_token")

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("VerifiedReviewInput is Host-issued")

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("VerifiedReviewInput is immutable")

    @property
    def summary(self) -> dict[str, Any]:
        return clone(self._summary)

    def _is_valid(self) -> bool:
        return self._token is _INPUT_TOKEN


def _load(name: str, value: object) -> dict[str, Any]:
    if type(value) is not dict:
        raise ReviewInputError()
    try:
        return load_contract(
            name, json.dumps(value, ensure_ascii=False, allow_nan=False),
        )
    except (ContractError, TypeError, ValueError, OverflowError):
        raise ReviewInputError() from None


def _valid_hash(document: dict[str, Any], field: str) -> bool:
    return document[field] == content_hash({
        key: value for key, value in document.items() if key != field
    })


def _valid_window(value: dict[str, Any], now: datetime) -> bool:
    try:
        issued = datetime.fromisoformat(value["issuedAt"][:-1] + "+00:00")
        expires = datetime.fromisoformat(value["expiresAt"][:-1] + "+00:00")
        return issued <= now.astimezone(timezone.utc) < expires
    except (TypeError, ValueError, OverflowError):
        return False


def _resolve(
    resolver: Callable[[str], object], reference: str,
    schema_name: str, *, reference_is_attestation: bool = True,
) -> dict[str, Any]:
    try:
        require_hash(reference)
        value = _load(schema_name, resolver(reference))
        if (
            (reference_is_attestation and value["attestationHash"] != reference)
            or not _valid_hash(value, "attestationHash")
        ):
            raise ReviewInputError()
        return value
    except (HashingError, ReviewInputError):
        raise ReviewInputError() from None
    except Exception:
        raise ReviewInputError() from None


def verify_review_inputs(
    summary: object,
    *,
    summary_attestation_resolver: Callable[[str], object],
    grill_completion_ref: str,
    grill_completion_resolver: Callable[[str], object],
    reviewer_policy_hash: str,
    plan_hash: str,
    attempt_ref: str,
    now: datetime,
) -> VerifiedReviewInput:
    """Validate Host-resolved provenance; Agent-provided claims are insufficient."""

    try:
        for value in (reviewer_policy_hash, plan_hash):
            require_hash(value)
        if type(now) is not datetime or type(attempt_ref) is not str or not attempt_ref:
            raise ReviewInputError()
        normalized = _load("design-review-summary.schema.json", summary)
        if (
            not _valid_hash(normalized, "summaryHash")
            or normalized["reviewerPolicyHash"] != reviewer_policy_hash
            or len({item["alternativeId"] for item in normalized["alternatives"]}) != len(normalized["alternatives"])
            or len({item["riskId"] for item in normalized["risks"]}) != len(normalized["risks"])
            or len({item["criterionId"] for item in normalized["acceptanceCriteria"]}) != len(normalized["acceptanceCriteria"])
        ):
            raise ReviewInputError()
        provenance = _resolve(
            summary_attestation_resolver, normalized["summaryHash"],
            "design-review-summary-attestation.schema.json",
            reference_is_attestation=False,
        )
        completion = _resolve(
            grill_completion_resolver, grill_completion_ref,
            "grill-completion-attestation.schema.json",
        )
        bindings = {
            "summaryHash": normalized["summaryHash"],
            "designHash": normalized["designHash"],
            "reviewerPolicyHash": reviewer_policy_hash,
            "planHash": plan_hash,
            "attemptRef": attempt_ref,
        }
        if (
            any(provenance[key] != value for key, value in bindings.items())
            or not _valid_window(provenance, now)
            or any(completion[key] != value for key, value in bindings.items() if key != "reviewerPolicyHash")
            or not _valid_window(completion, now)
        ):
            raise ReviewInputError()
    except (HashingError, KeyError, ReviewInputError, TypeError, ValueError):
        raise ReviewInputError() from None
    result = object.__new__(VerifiedReviewInput)
    object.__setattr__(result, "_summary", clone(normalized))
    object.__setattr__(result, "_summary_attestation_hash", provenance["attestationHash"])
    object.__setattr__(result, "_completion_hash", completion["attestationHash"])
    object.__setattr__(result, "_token", _INPUT_TOKEN)
    return result
