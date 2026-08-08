"""Non-circular approval subjects and approval receipts for Provider V3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from selfworkflow.v3.contracts import validate_provider_approval_receipt
from selfworkflow.v3.hashing import clone, content_hash, require_hash


class ApprovalError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _utc(value: datetime | str) -> str:
    if isinstance(value, str):
        return value
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ApprovalError("approval-time-not-utc")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class AuthorizationSubject:
    kind: str
    body: dict[str, Any]
    subject_hash: str


@dataclass(frozen=True)
class ApprovalReceipt:
    document: dict[str, Any]

    @property
    def receipt_hash(self) -> str:
        return self.document["receiptHash"]


def _subject(kind: str, body: Mapping[str, Any], final_hash_field: str) -> AuthorizationSubject:
    if kind not in {"operation-plan", "query-plan", "provider-selection-exception"}:
        raise ApprovalError("approval-subject-kind-invalid")
    material = clone(dict(body))
    for key in (
        "approvalReceiptRef", "approvalReceiptHash", "receiptHash", final_hash_field,
        "operationPlanHash", "queryPlanHash", "requestHash",
        "operationAuthorizationSubjectHash", "queryAuthorizationSubjectHash",
    ):
        material.pop(key, None)
    material["subjectKind"] = kind
    return AuthorizationSubject(kind, material, content_hash(material))


def build_operation_plan_subject(plan: Mapping[str, Any]) -> AuthorizationSubject:
    """Only operation-plan fields are accepted by this builder."""

    required = ("providerId", "operationId", "bindingSnapshotHash", "executionNonce", "attemptRef")
    if any(key not in plan for key in required):
        raise ApprovalError("operation-subject-incomplete")
    body = {"providerId": plan["providerId"], "operationId": plan["operationId"]}
    body.update({key: plan[key] for key in plan if key not in {"queryPlanHash", "requestHash"}})
    return _subject("operation-plan", body, "operationPlanHash")


def build_query_plan_subject(plan: Mapping[str, Any]) -> AuthorizationSubject:
    required = ("providerId", "operationId", "bindingSnapshotHash", "executionNonce", "attemptRef", "sideEffects")
    if any(key not in plan for key in required):
        raise ApprovalError("query-subject-incomplete")
    body = {key: plan[key] for key in plan if key not in {"operationPlanHash", "requestHash"}}
    return _subject("query-plan", body, "queryPlanHash")


def build_selection_exception_subject(
    *,
    base_request_hash: str,
    support_matrix_hash: str,
    support_matrix_entry_hash: str,
    capability_id: str,
    operation_id: str,
    platform: str,
    adapter_hash: str,
    task_scope_hash: str,
    provider_id: str,
    execution_nonce: str,
    attempt_ref: str,
) -> AuthorizationSubject:
    for value in (base_request_hash, support_matrix_hash, support_matrix_entry_hash, adapter_hash, task_scope_hash):
        require_hash(value)
    return _subject("provider-selection-exception", {
        "baseRequestHash": base_request_hash,
        "supportMatrixHash": support_matrix_hash,
        "supportMatrixEntryHash": support_matrix_entry_hash,
        "capabilityId": capability_id,
        "operationId": operation_id,
        "platform": platform,
        "adapterHash": adapter_hash,
        "taskScopeHash": task_scope_hash,
        "providerId": provider_id,
        "executionNonce": execution_nonce,
        "attemptRef": attempt_ref,
    }, "requestHash")


def issue_approval(
    subject: AuthorizationSubject,
    *,
    confirmation_source: str,
    scope: str,
    target_hashes: Iterable[str],
    issued_at: datetime | str,
    expires_at: datetime | str,
    nonce: str,
    provider_id: str | None = None,
    canonical_project_root_hash: str | None = None,
    operation_id: str | None = None,
    attempt_ref: str | None = None,
) -> ApprovalReceipt:
    if confirmation_source not in {"user-confirmation", "machine-policy", "test-fixture"}:
        raise ApprovalError("approval-confirmation-source-invalid")
    provider_id = provider_id or subject.body.get("providerId")
    canonical_project_root_hash = canonical_project_root_hash or subject.body.get("canonicalProjectRootHash")
    operation_id = operation_id or subject.body.get("operationId")
    attempt_ref = attempt_ref or subject.body.get("attemptRef")
    targets = sorted(set(target_hashes))
    for item in targets:
        require_hash(item)
    body: dict[str, Any] = {
        "schemaVersion": 3,
        "subjectKind": subject.kind,
        "authorizationSubjectHash": subject.subject_hash,
        "decision": "approved",
        "confirmationSource": confirmation_source,
        "scope": scope,
        "targetHashes": targets,
        "issuedAt": _utc(issued_at),
        "expiresAt": _utc(expires_at),
        "nonce": nonce,
        "revocationState": "active",
    }
    for key, value in {
        "providerId": provider_id,
        "canonicalProjectRootHash": canonical_project_root_hash,
        "operationId": operation_id,
        "attemptRef": attempt_ref,
    }.items():
        if value is not None:
            body[key] = value
    if canonical_project_root_hash is not None:
        require_hash(canonical_project_root_hash)
    body["receiptHash"] = content_hash(body)
    try:
        validate_provider_approval_receipt(body)
    except Exception as error:
        raise ApprovalError("approval-receipt-invalid") from error
    return ApprovalReceipt(clone(body))


def validate_approval(
    subject: AuthorizationSubject,
    receipt: Mapping[str, Any] | ApprovalReceipt,
    *,
    now: datetime | str,
    expected_target_hashes: Iterable[str] = (),
    used_nonces: set[str] | None = None,
    expected_provider_id: str | None = None,
    expected_project_root_hash: str | None = None,
    expected_attempt_ref: str | None = None,
) -> None:
    document = receipt.document if isinstance(receipt, ApprovalReceipt) else dict(receipt)
    try:
        validate_provider_approval_receipt(document)
    except Exception as error:
        raise ApprovalError("approval-receipt-invalid") from error
    if document["receiptHash"] != content_hash({key: value for key, value in document.items() if key != "receiptHash"}):
        raise ApprovalError("approval-receipt-hash-invalid")
    if document["subjectKind"] != subject.kind:
        raise ApprovalError("approval-subject-kind-mismatch")
    if document["authorizationSubjectHash"] != subject.subject_hash:
        raise ApprovalError("approval-subject-drift")
    if document["decision"] != "approved" or document["revocationState"] != "active":
        raise ApprovalError("approval-revoked")
    current = _utc(now)
    if not (document["issuedAt"] <= current <= document["expiresAt"]):
        raise ApprovalError("approval-expired")
    expected = sorted(set(expected_target_hashes))
    if sorted(document["targetHashes"]) != expected:
        raise ApprovalError("approval-target-drift")
    if expected_provider_id is not None and document.get("providerId") != expected_provider_id:
        raise ApprovalError("approval-provider-mismatch")
    if expected_project_root_hash is not None and document.get("canonicalProjectRootHash") != expected_project_root_hash:
        raise ApprovalError("approval-project-mismatch")
    if expected_attempt_ref is not None and document.get("attemptRef") != expected_attempt_ref:
        raise ApprovalError("approval-attempt-mismatch")
    if document["nonce"] != subject.body.get("executionNonce"):
        raise ApprovalError("approval-nonce-mismatch")
    if used_nonces is not None and document["nonce"] in used_nonces:
        raise ApprovalError("approval-replay")


def finalize_document(
    subject: AuthorizationSubject,
    approval: ApprovalReceipt | Mapping[str, Any],
    *,
    final_hash_field: str,
    base_document: Mapping[str, Any],
) -> dict[str, Any]:
    receipt = approval.document if isinstance(approval, ApprovalReceipt) else dict(approval)
    if receipt["authorizationSubjectHash"] != subject.subject_hash:
        raise ApprovalError("approval-subject-drift")
    document = clone(dict(base_document))
    document["approvalReceiptRef"] = "approval-" + receipt["receiptHash"][7:]
    document["approvalReceiptHash"] = receipt["receiptHash"]
    document.pop(final_hash_field, None)
    document[final_hash_field] = content_hash(document)
    return document
