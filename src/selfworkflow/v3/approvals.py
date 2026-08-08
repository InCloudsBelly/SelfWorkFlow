"""Non-circular approval subjects and approval receipts for Provider V3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Protocol

from selfworkflow.v3.contracts import (
    validate_provider_approval_receipt,
    validate_provider_machine_authorization,
)
from selfworkflow.v3.hashing import clone, content_hash, project_root_hash, require_hash


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


class ReplayStore(Protocol):
    """Atomic replay state machine supplied by the trusted host."""

    def reserve(self, key: str) -> bool: ...
    def commit(self, key: str, terminal_state: str) -> bool: ...
    def abort(self, key: str) -> bool: ...


@dataclass(frozen=True)
class AuthorizationResolution:
    """Current authoritative status for one immutable authorization document."""

    document: dict[str, Any]
    status: str
    issuer_trusted: bool
    authority_class: str


class AuthorizationResolver(Protocol):
    """Resolve current authorization state; serialized plan copies are not authority."""

    def resolve(self, authorization_hash: str) -> AuthorizationResolution | None: ...


@dataclass(frozen=True)
class MachineAuthorization:
    document: dict[str, Any]

    @property
    def authorization_hash(self) -> str:
        return self.document["authorizationHash"]


def build_machine_authorization(
    *, provider_id: str, project_root: str, subject_kind: str,
    operation_id: str, side_effect_class: str, execution_nonce: str,
    attempt_ref: str, issued_at: datetime | str, expires_at: datetime | str,
    nonce: str, confirmation_source: str = "machine-policy",
    issuer_id: str = "host-local-authority", test_mode: bool = False,
) -> MachineAuthorization:
    if subject_kind not in {"operation-plan", "query-plan"}:
        raise ApprovalError("machine-authorization-subject-invalid")
    if side_effect_class not in {"local-write", "network"}:
        raise ApprovalError("machine-authorization-side-effect-invalid")
    if confirmation_source not in {"user-confirmation", "machine-policy", "test-fixture"}:
        raise ApprovalError("machine-authorization-source-invalid")
    if not isinstance(issuer_id, str) or not issuer_id or issuer_id == "test-fixture":
        if not (test_mode and issuer_id == "test-fixture"):
            raise ApprovalError("machine-authorization-issuer-invalid")
    if confirmation_source == "test-fixture" and not test_mode:
        raise ApprovalError("test-authorization-rejected")
    body: dict[str, Any] = {
        "schemaVersion": 3,
        "providerId": provider_id,
        "canonicalProjectRootHash": project_root_hash(project_root),
        "subjectKind": subject_kind,
        "operationId": operation_id,
        "sideEffectClass": side_effect_class,
        "executionNonce": execution_nonce,
        "attemptRef": attempt_ref,
        "issuedAt": _utc(issued_at),
        "expiresAt": _utc(expires_at),
        "nonce": nonce,
        "issuerId": issuer_id,
        "confirmationSource": confirmation_source,
        "revocationState": "active",
    }
    body["authorizationHash"] = content_hash(body)
    try:
        validate_provider_machine_authorization(body, allow_test_issuer=test_mode)
    except Exception as error:
        raise ApprovalError("machine-authorization-invalid") from error
    return MachineAuthorization(clone(body))


def validate_machine_authorization(
    authorization: MachineAuthorization | Mapping[str, Any], *,
    provider_id: str, project_root_hash: str, subject_kind: str,
    operation_id: str, side_effect_class: str, execution_nonce: str,
    attempt_ref: str, now: datetime | str, test_mode: bool = False,
    issuer_trusted: bool = True,
) -> None:
    document = authorization.document if isinstance(authorization, MachineAuthorization) else dict(authorization)
    try:
        validate_provider_machine_authorization(document, allow_test_issuer=test_mode)
    except Exception as error:
        raise ApprovalError("machine-authorization-invalid") from error
    expected = {
        "providerId": provider_id,
        "canonicalProjectRootHash": project_root_hash,
        "subjectKind": subject_kind,
        "operationId": operation_id,
        "sideEffectClass": side_effect_class,
        "executionNonce": execution_nonce,
        "attemptRef": attempt_ref,
    }
    if any(document.get(key) != value for key, value in expected.items()):
        raise ApprovalError("machine-authorization-scope-mismatch")
    if document.get("revocationState") != "active":
        raise ApprovalError("machine-authorization-revoked")
    if not issuer_trusted:
        raise ApprovalError("machine-authorization-issuer-untrusted")
    current = _utc(now)
    if not (document["issuedAt"] <= current <= document["expiresAt"]):
        raise ApprovalError("machine-authorization-expired")
    if document.get("confirmationSource") == "test-fixture" and not test_mode:
        raise ApprovalError("test-authorization-rejected")


def resolve_machine_authorization(
    resolver: AuthorizationResolver | None, *, authorization_hash: str,
    provider_id: str, project_root_hash: str, subject_kind: str,
    operation_id: str, side_effect_class: str, execution_nonce: str,
    attempt_ref: str, now: datetime | str, test_mode: bool = False,
) -> dict[str, Any]:
    """Resolve and validate the current authoritative authorization on every run."""

    if resolver is None:
        raise ApprovalError("machine-authorization-resolver-required")
    try:
        resolution = resolver.resolve(require_hash(authorization_hash))
    except Exception:
        raise ApprovalError("machine-authorization-resolution-failed") from None
    if not isinstance(resolution, AuthorizationResolution):
        raise ApprovalError("machine-authorization-resolution-invalid")
    if resolution.status != "active":
        raise ApprovalError("machine-authorization-revoked")
    if resolution.authority_class not in {"external-host", "fake-test"}:
        raise ApprovalError("machine-authorization-resolution-invalid")
    if resolution.authority_class == "fake-test" and not test_mode:
        raise ApprovalError("test-authorization-resolver-rejected")
    document = clone(resolution.document)
    if document.get("authorizationHash") != authorization_hash:
        raise ApprovalError("machine-authorization-hash-mismatch")
    validate_machine_authorization(
        document,
        provider_id=provider_id,
        project_root_hash=project_root_hash,
        subject_kind=subject_kind,
        operation_id=operation_id,
        side_effect_class=side_effect_class,
        execution_nonce=execution_nonce,
        attempt_ref=attempt_ref,
        now=now,
        test_mode=test_mode,
        issuer_trusted=resolution.issuer_trusted,
    )
    return document


def _subject(kind: str, body: Mapping[str, Any], final_hash_field: str) -> AuthorizationSubject:
    if kind not in {"operation-plan", "query-plan", "provider-selection-exception"}:
        raise ApprovalError("approval-subject-kind-invalid")
    material = clone(dict(body))
    for key in (
        "approvalReceipt", "approvalReceiptRef", "approvalReceiptHash", "receiptHash", final_hash_field,
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
    expected_provider_id: str | None = None,
    expected_project_root_hash: str | None = None,
    expected_attempt_ref: str | None = None,
    expected_operation_id: str | None = None,
    expected_execution_nonce: str | None = None,
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
    if expected_operation_id is not None and document.get("operationId") != expected_operation_id:
        raise ApprovalError("approval-operation-mismatch")
    expected_nonce = expected_execution_nonce or subject.body.get("executionNonce")
    if document["nonce"] != expected_nonce:
        raise ApprovalError("approval-nonce-mismatch")


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
