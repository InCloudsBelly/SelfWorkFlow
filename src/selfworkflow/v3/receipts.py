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
    provider_id: str, binding_snapshot_hash: str, canonical_project_root_hash: str,
    started_at: datetime | str, completed_at: datetime | str,
    outcome: str, approval_receipt_ref: str | None,
    mutation_evidence_refs: Iterable[str], output_hash: str | None = None,
) -> dict[str, Any]:
    for value in (operation_plan_hash, binding_snapshot_hash, canonical_project_root_hash):
        require_hash(value)
    body: dict[str, Any] = {
        "schemaVersion": 3,
        "operationPlanHash": operation_plan_hash,
        "executionNonce": execution_nonce,
        "attemptRef": attempt_ref,
        "providerId": provider_id,
        "bindingSnapshotHash": binding_snapshot_hash,
        "canonicalProjectRootHash": canonical_project_root_hash,
        "startedAt": _utc(started_at),
        "completedAt": _utc(completed_at),
        "outcome": outcome,
        "mutationEvidenceRefs": sorted(set(mutation_evidence_refs)),
    }
    if approval_receipt_ref is not None:
        body["approvalReceiptRef"] = (
            approval_receipt_ref if not approval_receipt_ref.startswith("sha256:")
            else "approval-" + approval_receipt_ref[7:]
        )
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
    canonical_project_root_hash: str,
    started_at: datetime | str, completed_at: datetime | str,
    index_revision: str, index_completeness: str,
    returned_files: Iterable[Mapping[str, Any]], truncated: bool,
    pre_fingerprint_hash: str, post_fingerprint_hash: str,
    actual_side_effects: str, mutation_evidence_refs: Iterable[str],
    approval_receipt_ref: str | None = None,
    pre_workspace_identity_hash: str | None = None,
    post_workspace_identity_hash: str | None = None,
) -> dict[str, Any]:
    for value in (
        query_plan_hash, adapter_hash, source_identity_hash, project_state_receipt_hash,
        workspace_fingerprint_hash, canonical_project_root_hash,
        pre_fingerprint_hash, post_fingerprint_hash,
    ):
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
        "schemaVersion": 3,
        "queryPlanHash": query_plan_hash,
        "executionNonce": execution_nonce,
        "attemptRef": attempt_ref,
        "providerId": provider_id,
        "adapterHash": adapter_hash,
        "sourceIdentityHash": source_identity_hash,
        "projectStateReceiptHash": project_state_receipt_hash,
        "workspaceFingerprintHash": workspace_fingerprint_hash,
        "canonicalProjectRootHash": canonical_project_root_hash,
        "startedAt": _utc(started_at),
        "completedAt": _utc(completed_at),
        "indexRevision": index_revision,
        "indexCompleteness": index_completeness,
        "returnedFiles": files,
        "truncated": bool(truncated),
        "preQueryWorkspaceFingerprintHash": pre_fingerprint_hash,
        "postQueryWorkspaceFingerprintHash": post_fingerprint_hash,
        "actualSideEffects": actual_side_effects,
        "mutationEvidenceRefs": sorted(set(mutation_evidence_refs)),
    }
    if approval_receipt_ref is not None:
        body["approvalReceiptRef"] = (
            approval_receipt_ref if not approval_receipt_ref.startswith("sha256:")
            else "approval-" + approval_receipt_ref[7:]
        )
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


def _normalize_actual(actual_targets: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in actual_targets:
        kind = item.get("targetKind")
        target = item.get("targetId")
        action = item.get("action")
        if kind not in {"filesystem", "managed-state", "process", "service"}:
            raise ReceiptError("mutation-actual-kind-invalid")
        if not isinstance(target, str) or not target or not isinstance(action, str) or not action:
            raise ReceiptError("mutation-actual-target-invalid")
        if kind == "filesystem":
            target = canonical_relative_path(target)
        identity = (kind, target, action)
        if identity in seen:
            raise ReceiptError("mutation-evidence-duplicate")
        seen.add(identity)
        result.append({"targetKind": kind, "targetId": target, "action": action})
    if not result:
        raise ReceiptError("mutation-actual-target-required")
    return sorted(result, key=lambda item: (item["targetKind"], item["targetId"], item["action"]))


def _actual_matches_target(actual: Mapping[str, str], target: Mapping[str, Any]) -> bool:
    kind_map = {
        "managed-state-root": "managed-state",
        "process": "process",
        "service": "service",
    }
    target_kind = target["targetKind"]
    if target_kind in {"exact-file", "directory-subtree"}:
        if actual["targetKind"] != "filesystem":
            return False
        actual_path = canonical_relative_path(actual["targetId"])
        declared_path = canonical_relative_path(target["targetId"])
        in_scope = actual_path == declared_path or (
            target_kind == "directory-subtree" and actual_path.startswith(declared_path + "/")
        )
    else:
        in_scope = actual["targetKind"] == kind_map.get(target_kind) and actual["targetId"] == target["targetId"]
    return in_scope and actual["action"] in target["allowedActions"]


def _validate_actual_subset(
    actual_targets: Iterable[Mapping[str, str]], declared_targets: Iterable[Mapping[str, Any]],
    mutation_target_hash: str,
) -> None:
    candidates = [
        target for target in declared_targets
        if target.get("canonicalTargetHash") == mutation_target_hash
    ]
    if len(candidates) != 1:
        raise ReceiptError("mutation-target-hash-mismatch")
    target = candidates[0]
    for actual in actual_targets:
        if not _actual_matches_target(actual, target):
            raise ReceiptError("mutation-target-out-of-bounds")


def build_mutation_evidence(
    *, subject_kind: str, subject_plan_hash: str, execution_nonce: str,
    attempt_ref: str, provider_binding_hash: str, project_root_hash: str,
    provider_id: str, started_at: datetime | str, completed_at: datetime | str,
    observed_at: datetime | str, pre_state_identity: str, post_state_identity: str,
    mutation_target_hash: str, evidence_kind: str,
    before: Any, after: Any,
    actual_targets: Iterable[Mapping[str, Any]],
    declared_targets: Iterable[Mapping[str, Any]],
    observable: bool = True, required: bool = True,
) -> dict[str, Any]:
    for value in (
        subject_plan_hash, provider_binding_hash, project_root_hash,
        pre_state_identity, post_state_identity, mutation_target_hash,
    ):
        require_hash(value)
    if not observable:
        if required:
            raise ReceiptError("required-mutation-unobservable")
        raise ReceiptError("redundant-mutation-unverified")
    expected_kind = {
        "filesystem-manifest": "filesystem",
        "managed-state-manifest": "managed-state",
        "process-state-delta": "process",
        "service-state-delta": "service",
    }.get(evidence_kind)
    if expected_kind is None:
        raise ReceiptError("mutation-evidence-kind-invalid")
    actual = _normalize_actual(actual_targets)
    if any(item["targetKind"] != expected_kind for item in actual):
        raise ReceiptError("mutation-evidence-kind-mismatch")
    targets = [clone(dict(item)) for item in declared_targets]
    _validate_actual_subset(actual, targets, mutation_target_hash)
    if evidence_kind == "filesystem-manifest":
        manifest_paths = {
            canonical_relative_path(item["path"])
            for item in after if isinstance(item, Mapping) and isinstance(item.get("path"), str)
        } if isinstance(after, list) else set()
        actual_paths = {item["targetId"] for item in actual}
        if manifest_paths != actual_paths or len(manifest_paths) != len(after):
            raise ReceiptError("mutation-evidence-manifest-mismatch")
    body: dict[str, Any] = {
        "schemaVersion": 3,
        "subjectKind": subject_kind,
        "subjectPlanHash": subject_plan_hash,
        "executionNonce": execution_nonce,
        "attemptRef": attempt_ref,
        "providerBindingHash": provider_binding_hash,
        "providerId": provider_id,
        "canonicalProjectRootHash": project_root_hash,
        "startedAt": _utc(started_at),
        "completedAt": _utc(completed_at),
        "observedAt": _utc(observed_at),
        "preStateIdentity": pre_state_identity,
        "postStateIdentity": post_state_identity,
        "mutationTargetHash": mutation_target_hash,
        "payloadHash": content_hash({"before": before, "after": after}),
        "evidenceKind": evidence_kind,
        "actualTargets": actual,
        "before": clone(before),
        "after": clone(after),
    }
    body["evidenceHash"] = _hash_document(body, "evidenceHash")
    try:
        validate_provider_mutation_evidence(body)
    except Exception as error:
        raise ReceiptError("mutation-evidence-invalid") from error
    return clone(body)


def validate_mutation_evidence(
    document: Mapping[str, Any], *, subject_plan_hash: str,
    execution_nonce: str, attempt_ref: str, provider_id: str,
    provider_binding_hash: str, project_root_hash: str, started_at: datetime | str,
    completed_at: datetime | str,
    declared_targets: Iterable[Mapping[str, Any]],
) -> None:
    material = dict(document)
    try:
        validate_provider_mutation_evidence(material)
    except Exception as error:
        raise ReceiptError("mutation-evidence-invalid") from error
    expected = {
        "subjectPlanHash": subject_plan_hash,
        "executionNonce": execution_nonce,
        "attemptRef": attempt_ref,
        "providerId": provider_id,
        "providerBindingHash": provider_binding_hash,
        "canonicalProjectRootHash": project_root_hash,
    }
    if any(material.get(key) != value for key, value in expected.items()):
        if material.get("providerId") != provider_id:
            raise ReceiptError("mutation-evidence-provider-mismatch")
        if material.get("providerBindingHash") != provider_binding_hash:
            raise ReceiptError("mutation-evidence-binding-mismatch")
        if material.get("canonicalProjectRootHash") != project_root_hash:
            raise ReceiptError("mutation-evidence-project-mismatch")
        raise ReceiptError("mutation-evidence-replay")
    start = _utc(started_at)
    end = _utc(completed_at)
    if material["startedAt"] != start or material["completedAt"] != end:
        raise ReceiptError("mutation-evidence-time-window")
    actual = _normalize_actual(material["actualTargets"])
    _validate_actual_subset(actual, declared_targets, material["mutationTargetHash"])
    expected_kind = {
        "filesystem-manifest": "filesystem",
        "managed-state-manifest": "managed-state",
        "process-state-delta": "process",
        "service-state-delta": "service",
    }[material["evidenceKind"]]
    if any(item["targetKind"] != expected_kind for item in actual):
        raise ReceiptError("mutation-evidence-kind-mismatch")
