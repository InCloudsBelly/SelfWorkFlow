"""Host-owned dispatch boundaries for design and code Review."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Protocol

from selfworkflow.v3.contracts import ContractError, load_contract
from selfworkflow.v3.hashing import (
    HashingError, clone, content_hash, hash_bytes, require_hash,
)
from selfworkflow.v3.review_inputs import VerifiedReviewInput


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
    project_review_context: Mapping[str, object] | None = None


class ReviewDispatchPort(Protocol):
    def dispatch_review(
        self, *, review_mode: str, fork_context: bool, payload: dict[str, Any],
        implementation_agent_identity: str,
        implementation_context_identity: str,
        plan_hash: str,
        attempt_ref: str,
        project_review_context: Mapping[str, object] | None = None,
    ) -> HostDispatchObservation: ...


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


def _load_result(
    value: object, summary: dict[str, Any], *, review_mode: str,
) -> dict[str, Any]:
    if type(value) is not dict:
        raise ReviewDispatchError("review-result-invalid")
    try:
        if review_mode == "independent-code-review":
            result = load_contract(
                "code-review-result.schema.json",
                json.dumps(value, ensure_ascii=False, allow_nan=False),
            )
            subject_matches = result["reviewSubjectHash"] == content_hash(summary)
        elif review_mode == "independent-design-review":
            result = load_contract(
                "design-review-result.schema.json",
                json.dumps(value, ensure_ascii=False, allow_nan=False),
            )
            subject_matches = (
                result["summaryHash"] == summary["summaryHash"]
                and result["designHash"] == summary["designHash"]
            )
        else:
            raise ReviewDispatchError("review-dispatch-input-invalid")
        finding_ids = [item["findingId"] for item in result["findings"]]
        if (
            result["resultHash"] != content_hash(
                {key: item for key, item in result.items() if key != "resultHash"}
            )
            or not subject_matches
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


def _project_review_payload(
    context: Mapping[str, object],
) -> tuple[dict[str, object], Mapping[str, object]]:
    """Validate and JSON-project the paired project Review inputs."""

    try:
        from selfworkflow.project_review import ProjectReviewContext
    except ImportError:
        raise ReviewDispatchError("project-review-context-invalid") from None
    if not isinstance(context, ProjectReviewContext) or not context._is_valid():
        raise ReviewDispatchError("project-review-context-invalid")
    if set(context) != {"status", "blocking", "sessionBindingHash", "issues", "reviewers"}:
        raise ReviewDispatchError("project-review-context-invalid")
    if context["status"] not in {"absent", "loaded", "unverified", "not-applicable"}:
        raise ReviewDispatchError("project-review-context-invalid")
    if type(context["blocking"]) is not bool:
        raise ReviewDispatchError("project-review-context-invalid")
    if context["blocking"]:
        raise ReviewDispatchError("project-review-required-unverified")
    session_hash = context["sessionBindingHash"]
    if session_hash is not None:
        try:
            require_hash(session_hash)
        except HashingError:
            raise ReviewDispatchError("project-review-context-invalid") from None
    issues = context["issues"]
    if not isinstance(issues, tuple) or not all(
        type(item) is str and 1 <= len(item) <= 256 for item in issues
    ):
        raise ReviewDispatchError("project-review-context-invalid")
    reviewers = context["reviewers"]
    if not isinstance(reviewers, Mapping) or set(reviewers) != {"standards", "spec"}:
        raise ReviewDispatchError("project-review-context-invalid")
    axis_payloads: dict[str, object] = {}
    axis_inputs: dict[str, tuple[object, tuple[bytes, ...]]] = {}
    for axis in ("standards", "spec"):
        value = reviewers[axis]
        if not isinstance(value, Mapping) or set(value) != {"manifest", "skillBytes"}:
            raise ReviewDispatchError("project-review-context-invalid")
        manifest = value["manifest"]
        skill_bytes = value["skillBytes"]
        if not isinstance(manifest, tuple) or not isinstance(skill_bytes, tuple):
            raise ReviewDispatchError("project-review-context-invalid")
        if len(manifest) != len(skill_bytes):
            raise ReviewDispatchError("project-review-context-invalid")
        projected_manifest: list[dict[str, object]] = []
        normalized_bytes: list[bytes] = []
        for item, content in zip(manifest, skill_bytes):
            if not isinstance(item, Mapping) or type(content) is not bytes:
                raise ReviewDispatchError("project-review-context-invalid")
            normalized_item = dict(item)
            if set(normalized_item) != {"id", "path", "contentHash", "required"}:
                raise ReviewDispatchError("project-review-context-invalid")
            if (
                type(normalized_item["id"]) is not str
                or re.fullmatch(r"^[a-z0-9][a-z0-9._-]{0,127}$", normalized_item["id"]) is None
                or type(normalized_item["path"]) is not str
                or type(normalized_item["required"]) is not bool
            ):
                raise ReviewDispatchError("project-review-context-invalid")
            try:
                from selfworkflow.project_review import _validated_relative_path

                _validated_relative_path(normalized_item["path"])
                require_hash(normalized_item["contentHash"])
            except (HashingError, ValueError, TypeError):
                raise ReviewDispatchError("project-review-context-invalid") from None
            if normalized_item["contentHash"] != hash_bytes(content):
                raise ReviewDispatchError("project-review-context-invalid")
            projected_manifest.append(normalized_item)
            normalized_bytes.append(content)
        immutable_manifest = tuple(
            MappingProxyType(item) for item in projected_manifest
        )
        axis_inputs[axis] = (immutable_manifest, tuple(normalized_bytes))
        axis_payloads[axis] = {
            "manifest": projected_manifest,
            "skillHashes": [hash_bytes(item) for item in normalized_bytes],
        }
    if axis_inputs["standards"] != axis_inputs["spec"]:
        raise ReviewDispatchError("project-review-context-mismatch")
    payload = {
        "status": context["status"],
        "blocking": context["blocking"],
        "sessionBindingHash": session_hash,
        "issues": list(issues),
        "reviewers": axis_payloads,
    }
    normalized_reviewers = MappingProxyType({
        axis: MappingProxyType({
            "manifest": axis_inputs[axis][0],
            "skillBytes": axis_inputs[axis][1],
        })
        for axis in ("standards", "spec")
    })
    normalized_context = MappingProxyType({
        "status": context["status"],
        "blocking": context["blocking"],
        "sessionBindingHash": session_hash,
        "issues": issues,
        "reviewers": normalized_reviewers,
    })
    return payload, normalized_context


def _dispatch_review(
    verified_input: VerifiedReviewInput,
    *,
    implementation_agent_identity: str,
    implementation_context_identity: str,
    port: ReviewDispatchPort,
    fork_context: bool,
    fallback_authorization_ref: str | None,
    plan_hash: str,
    attempt_ref: str,
    project_review_context: Mapping[str, object] | None,
    review_axis: str | None = None,
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
    if type(verified_input) is not VerifiedReviewInput or not verified_input._is_valid():
        raise ReviewDispatchError("post-grill-review-input-invalid")
    normalized = verified_input.summary
    if project_review_context is not None and not isinstance(project_review_context, Mapping):
        raise ReviewDispatchError("project-review-context-invalid")
    if review_axis is None:
        review_mode = "independent-design-review"
        subject_field = "designReviewSummary"
    else:
        if review_axis not in {"standards", "spec"}:
            raise ReviewDispatchError("review-dispatch-input-invalid")
        review_mode = "independent-code-review"
        subject_field = "codeReviewSubject"
    payload = {
        "schemaVersion": 3,
        "reviewMode": review_mode,
        subject_field: clone(normalized),
    }
    if review_axis is not None:
        payload["reviewAxis"] = review_axis
    project_review_payload = None
    normalized_project_review_context = None
    if project_review_context is not None:
        project_review_payload, normalized_project_review_context = (
            _project_review_payload(project_review_context)
        )
    if project_review_payload is not None:
        payload["projectReview"] = project_review_payload
    try:
        dispatch_arguments = {
            "review_mode": review_mode,
            "fork_context": fork_context,
            "payload": clone(payload),
            "implementation_agent_identity": implementation_agent_identity,
            "implementation_context_identity": implementation_context_identity,
            "plan_hash": plan_hash,
            "attempt_ref": attempt_ref,
        }
        if normalized_project_review_context is not None:
            dispatch_arguments["project_review_context"] = normalized_project_review_context
        observation = port.dispatch_review(
            **dispatch_arguments,
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
        observation.review_mode != review_mode
        or observation.fork_context is not fork_context
        or observed_payload != payload
        or observation.project_review_context != normalized_project_review_context
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

    result = _load_result(
        observation.returned_value, normalized, review_mode=review_mode,
    )
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
        "reviewMode": review_mode,
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
        "inputMode": (
            "summary-only"
            if review_mode == "independent-design-review"
            else "code-review-subject-only"
        ),
        "parentContextImported": fork_context,
        "grillReasoningReceived": False,
        "payloadHash": payload_hash,
        "reviewerPolicyHash": normalized["reviewerPolicyHash"],
        "resultHash": result["resultHash"],
        "reviewVerdict": result["verdict"],
        "reviewLevel": result["reviewLevel"],
        "fallbackAuthorizationRef": fallback_authorization_ref,
        "independence": independence,
    }
    if review_mode == "independent-design-review":
        receipt.update({
            "inputSummaryHash": normalized["summaryHash"],
            "designHash": normalized["designHash"],
        })
    else:
        receipt["reviewSubjectHash"] = content_hash(normalized)
    receipt["receiptHash"] = content_hash(receipt)
    try:
        return load_contract(
            (
                "review-independence-receipt.schema.json"
                if review_mode == "independent-design-review"
                else "code-review-independence-receipt.schema.json"
            ),
            json.dumps(receipt, ensure_ascii=False, allow_nan=False),
        )
    except ContractError:
        raise ReviewDispatchError("review-dispatch-observation-invalid") from None


def dispatch_independent_review(
    verified_input: VerifiedReviewInput,
    *,
    implementation_agent_identity: str,
    implementation_context_identity: str,
    port: ReviewDispatchPort,
    fallback_authorization_ref: str | None = None,
    plan_hash: str,
    attempt_ref: str,
    project_review_context: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Force a fresh-context dispatch and derive a receipt from Host observations."""

    return _dispatch_review(
        verified_input,
        implementation_agent_identity=implementation_agent_identity,
        implementation_context_identity=implementation_context_identity,
        port=port,
        fork_context=False,
        fallback_authorization_ref=fallback_authorization_ref,
        plan_hash=plan_hash,
        attempt_ref=attempt_ref,
        project_review_context=project_review_context,
    )


def dispatch_dual_code_review(
    verified_input: VerifiedReviewInput,
    *,
    implementation_agent_identity: str,
    implementation_context_identity: str,
    port: ReviewDispatchPort,
    plan_hash: str,
    attempt_ref: str,
    project_review_context: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Run distinct Standards and Spec reviewer dispatches with one bundle."""

    if project_review_context is not None:
        shared_payload, _normalized = _project_review_payload(project_review_context)
        shared_project_review_hash = content_hash(shared_payload)
    else:
        shared_project_review_hash = None
    receipts = {}
    for axis in ("standards", "spec"):
        receipts[axis] = _dispatch_review(
            verified_input,
            implementation_agent_identity=implementation_agent_identity,
            implementation_context_identity=implementation_context_identity,
            port=port,
            fork_context=False,
            fallback_authorization_ref=None,
            plan_hash=plan_hash,
            attempt_ref=attempt_ref,
            project_review_context=project_review_context,
            review_axis=axis,
        )
    standards = receipts["standards"]
    spec = receipts["spec"]
    if (
        standards["dispatchId"] == spec["dispatchId"]
        or standards["dispatchNonce"] == spec["dispatchNonce"]
        or standards["reviewerAgentIdentity"] == spec["reviewerAgentIdentity"]
        or standards["reviewerContextIdentity"] == spec["reviewerContextIdentity"]
    ):
        raise ReviewDispatchError("review-code-review-not-independent")
    return {
        "schemaVersion": 1,
        "reviewMode": "independent-code-review",
        "projectReviewHash": shared_project_review_hash,
        "reviewers": receipts,
    }


def dispatch_same_agent_fallback_review(
    verified_input: VerifiedReviewInput,
    *,
    implementation_agent_identity: str,
    implementation_context_identity: str,
    port: ReviewDispatchPort,
    fallback_authorization_ref: str,
    plan_hash: str,
    attempt_ref: str,
    project_review_context: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Record the explicitly authorized same-Agent structured review path."""

    return _dispatch_review(
        verified_input,
        implementation_agent_identity=implementation_agent_identity,
        implementation_context_identity=implementation_context_identity,
        port=port,
        fork_context=True,
        fallback_authorization_ref=fallback_authorization_ref,
        plan_hash=plan_hash,
        attempt_ref=attempt_ref,
        project_review_context=project_review_context,
    )
