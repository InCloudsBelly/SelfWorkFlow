"""Builders and closed-world validators for Provider receipts and evidence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from selfworkflow.v3.contracts import (
    validate_provider_mutation_evidence,
    validate_provider_operation_receipt,
    validate_provider_query_receipt,
)
from selfworkflow.v3.hashing import canonical_relative_path, clone, content_hash, require_hash


class ReceiptError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _utc(value: datetime | str) -> str:
    if isinstance(value, str):
        return value
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ReceiptError("receipt-time-not-utc")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash_document(document: Mapping[str, Any], field: str) -> str:
    return content_hash({key: value for key, value in document.items() if key != field})


def build_operation_receipt(
    *, operation_plan_hash: str, execution_nonce: str, attempt_ref: str,
    provider_id: str, binding_snapshot_hash: str,
    started_at: datetime | str, completed_at: datetime | str,
    outcome: str, approval_receipt_ref: str | None,
    mutation_evidence_refs: Iterable[str], output_hash: str | None = None,
) -> dict[str, Any]:
    for value in (operation_plan_hash, binding_snapshot_hash):
        require_hash(value)
    body: dict[str, Any] = {
        "schemaVersion": 3, "operationPlanHash": operation_plan_hash,
        "executionNonce": execution_nonce, "attemptRef": attempt_ref,
        "providerId": provider_id, "bindingSnapshotHash": binding_snapshot_hash,
        "startedAt": _utc(started_at), "completedAt": _utc(completed_at),
        "outcome": outcome, "mutationEvidenceRefs": sorted(set(mutation_evidence_refs)),
    }
    if approval_receipt_ref is not None:
        body["approvalReceiptRef"] = approval_receipt_ref if not approval_receipt_ref.startswith("sha256:") else "approval-" + approval_receipt_ref[7:]
    if output_hash is not None:
        body["outputHash"] = require_hash(output_hash)
    body["receiptHash"] = _hash_document(body, "receiptHash")
    try:
        validate_provider_operation_receipt(body)
    except Exception as error:
        raise ReceiptError("operation-receipt-invalid") from error
    return clone(body)


def build_query_receipt(
    *, query_plan_hash: str, execution_nonce: str, attempt_ref: str,
    provider_id: str, adapter_hash: str, source_identity_hash: str,
    project_state_receipt_hash: str, workspace_fingerprint_hash: str,
    index_revision: str, index_completeness: str,
    returned_files: Iterable[Mapping[str, Any]], truncated: bool,
    pre_fingerprint_hash: str, post_fingerprint_hash: str,
    actual_side_effects: str, mutation_evidence_refs: Iterable[str],
    approval_receipt_ref: str | None = None,
    pre_workspace_identity_hash: str | None = None,
    post_workspace_identity_hash: str | None = None,
) -> dict[str, Any]:
    for value in (query_plan_hash, adapter_hash, source_identity_hash, project_state_receipt_hash, workspace_fingerprint_hash, pre_fingerprint_hash, post_fingerprint_hash):
        require_hash(value)
    files = []
    for item in returned_files:
        entry = dict(item)
        path = canonical_relative_path(entry["path"])
        if list(entry["byteRange"])[0] > list(entry["byteRange"])[1]:
            raise ReceiptError("returned-file-range-invalid")
        entry["path"] = path
        require_hash(entry["contentHash"])
        files.append(entry)
    body: dict[str, Any] = {
        "schemaVersion": 3, "queryPlanHash": query_plan_hash,
        "executionNonce": execution_nonce, "attemptRef": attempt_ref,
        "providerId": provider_id, "adapterHash": adapter_hash,
        "sourceIdentityHash": source_identity_hash,
        "projectStateReceiptHash": project_state_receipt_hash,
        "workspaceFingerprintHash": workspace_fingerprint_hash,
        "indexRevision": index_revision, "indexCompleteness": index_completeness,
        "returnedFiles": files, "truncated": bool(truncated),
        "preQueryWorkspaceFingerprintHash": pre_fingerprint_hash,
        "postQueryWorkspaceFingerprintHash": post_fingerprint_hash,
        "actualSideEffects": actual_side_effects,
        "mutationEvidenceRefs": sorted(set(mutation_evidence_refs)),
    }
    if approval_receipt_ref is not None:
        body["approvalReceiptRef"] = approval_receipt_ref if not approval_receipt_ref.startswith("sha256:") else "approval-" + approval_receipt_ref[7:]
    if pre_workspace_identity_hash is not None:
        body["preQueryWorkspaceIdentityHash"] = require_hash(pre_workspace_identity_hash)
    if post_workspace_identity_hash is not None:
        body["postQueryWorkspaceIdentityHash"] = require_hash(post_workspace_identity_hash)
    body["receiptHash"] = _hash_document(body, "receiptHash")
    try:
        validate_provider_query_receipt(body)
    except Exception as error:
        raise ReceiptError("query-receipt-invalid") from error
    return clone(body)


def _manifest_paths(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    result = set()
    for item in value:
        if isinstance(item, Mapping) and isinstance(item.get("path"), str):
            result.add(item["path"])
    return result


def build_mutation_evidence(
    *, subject_kind: str, subject_plan_hash: str, execution_nonce: str,
    attempt_ref: str, provider_binding_hash: str, project_root_hash: str,
    observed_at: datetime | str, pre_state_identity: str, post_state_identity: str,
    mutation_target_hash: str, provider_id: str, evidence_kind: str,
    before: Any, after: Any, declared_paths: Iterable[str] = (),
    observable: bool = True, required: bool = True,
) -> dict[str, Any]:
    for value in (subject_plan_hash, provider_binding_hash, project_root_hash, pre_state_identity, post_state_identity, mutation_target_hash):
        require_hash(value)
    if not observable:
        if required:
            raise ReceiptError("required-mutation-unobservable")
        raise ReceiptError("redundant-mutation-unverified")
    if evidence_kind not in {"filesystem-manifest", "managed-state-manifest", "process-state-delta", "service-state-delta"}:
        raise ReceiptError("mutation-evidence-kind-invalid")
    allowed = {canonical_relative_path(item) for item in declared_paths}
    if evidence_kind == "filesystem-manifest":
        actual = _manifest_paths(after)
        if not actual.issubset(allowed):
            raise ReceiptError("mutation-target-out-of-bounds")
        if isinstance(after, list) and len(actual) != len(after):
            raise ReceiptError("mutation-evidence-duplicate")
    body: dict[str, Any] = {
        "schemaVersion": 3, "subjectKind": subject_kind,
        "subjectPlanHash": subject_plan_hash, "executionNonce": execution_nonce,
        "attemptRef": attempt_ref, "providerBindingHash": provider_binding_hash,
        "canonicalProjectRootHash": project_root_hash,
        "observedAt": _utc(observed_at), "preStateIdentity": pre_state_identity,
        "postStateIdentity": post_state_identity, "mutationTargetHash": mutation_target_hash,
        "payloadHash": content_hash({"before": before, "after": after}),
        "evidenceKind": evidence_kind, "before": clone(before), "after": clone(after),
    }
    body["providerId"] = provider_id
    body["evidenceHash"] = _hash_document(body, "evidenceHash")
    try:
        validate_provider_mutation_evidence(body)
    except Exception as error:
        raise ReceiptError("mutation-evidence-invalid") from error
    return clone(body)


def validate_mutation_evidence(
    document: Mapping[str, Any], *, subject_plan_hash: str,
    execution_nonce: str, attempt_ref: str, provider_id: str | None = None,
    project_root_hash: str, observed_not_after: str | None = None,
    declared_paths: Iterable[str] = (), required: bool = True, expected_provider_id: str | None = None,
) -> None:
    try:
        validate_provider_mutation_evidence(dict(document))
    except Exception as error:
        raise ReceiptError("mutation-evidence-invalid") from error
    if document["evidenceHash"] != _hash_document(document, "evidenceHash"):
        raise ReceiptError("mutation-evidence-hash-invalid")
    if document["subjectPlanHash"] != subject_plan_hash or document["executionNonce"] != execution_nonce or document["attemptRef"] != attempt_ref:
        raise ReceiptError("mutation-evidence-replay")
    if document["canonicalProjectRootHash"] != project_root_hash:
        raise ReceiptError("mutation-evidence-project-mismatch")
    if expected_provider_id is not None and document.get("providerId") != expected_provider_id:
        raise ReceiptError("mutation-evidence-provider-mismatch")
    if observed_not_after is not None and document["observedAt"] > observed_not_after:
        raise ReceiptError("mutation-evidence-time-window")
    allowed = {canonical_relative_path(item) for item in declared_paths}
    if document["evidenceKind"] == "filesystem-manifest":
        actual = _manifest_paths(document["after"])
        if not actual.issubset(allowed):
            raise ReceiptError("mutation-target-out-of-bounds")
        if len(actual) != len(document["after"]):
            raise ReceiptError("mutation-evidence-duplicate")
