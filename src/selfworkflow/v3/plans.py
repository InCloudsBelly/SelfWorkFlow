"""Fail-closed, content-addressed Provider operation and query plans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Iterable, Mapping

from selfworkflow.v3.approvals import (
    ApprovalError,
    ApprovalReceipt,
    AuthorizationSubject,
    MachineAuthorization,
    build_operation_plan_subject,
    build_query_plan_subject,
    finalize_document,
    validate_machine_authorization,
)
from selfworkflow.v3.command_registry import (
    CommandRegistryError,
    TrustedCommandRegistry,
    render_command,
)
from selfworkflow.v3.contracts import validate_provider_operation_plan, validate_provider_query_plan
from selfworkflow.v3.hashing import clone, content_hash, canonical_project_root, project_root_hash, require_hash


class PlanError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


OPERATION_IDS = (
    "inspect", "initialize-index", "sync-incremental", "rebuild-index",
    "upgrade-managed-adapter", "repair-managed-state",
)
FORBIDDEN_OPERATION_IDS = {"remove", "delete", "upgrade-user-source", "repair-user-source"}
_OPERATION_ACTION = {
    "initialize-index": "initialize",
    "sync-incremental": "sync",
    "rebuild-index": "rebuild",
    "upgrade-managed-adapter": "upgrade",
    "repair-managed-state": "repair",
}
_MANAGED_ACTIONS = frozenset(_OPERATION_ACTION.values())


def _safe_id(value: object, reason: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", value):
        raise PlanError(reason)
    return value


def _safe_hash(value: object) -> str:
    try:
        return require_hash(value)
    except Exception:
        raise PlanError("plan-hash-invalid") from None


def _targets(
    targets: Iterable[Mapping[str, Any]], *, root_hash: str,
    side_effect_class: str, operation_id: str,
) -> list[dict[str, Any]]:
    sources = list(targets)
    if side_effect_class == "none":
        if sources:
            raise PlanError("readonly-mutation-target-unsupported")
        return []
    if side_effect_class == "network":
        raise PlanError("network-unsupported")
    if not sources:
        raise PlanError("mutation-targets-required")
    expected_action = _OPERATION_ACTION.get(operation_id)
    result: list[dict[str, Any]] = []
    identities: set[str] = set()
    for source in sources:
        if source.get("targetKind") != "managed-state-root":
            raise PlanError("mvp-managed-state-target-required")
        target_id = source.get("targetId")
        if not isinstance(target_id, str) or not target_id or len(target_id) > 512 or any(ord(c) < 32 for c in target_id):
            raise PlanError("mutation-target-invalid")
        if target_id in identities:
            raise PlanError("mutation-target-duplicate")
        identities.add(target_id)
        actions = sorted(set(source.get("allowedActions", ())))
        if len(actions) != 1 or actions[0] not in _MANAGED_ACTIONS:
            raise PlanError("mutation-target-action-invalid")
        if expected_action is not None and actions != [expected_action]:
            raise PlanError("mutation-target-action-invalid")
        if source.get("evidenceRequired", True) is not True:
            raise PlanError("required-evidence-cannot-be-disabled")
        canonical_hash = content_hash({"targetKind": "managed-state-root", "targetId": target_id})
        target_hash = content_hash({
            "targetKind": "managed-state-root",
            "targetId": target_id,
            "allowedActions": actions,
            "evidenceRequired": True,
        })
        if source.get("canonicalTargetHash", canonical_hash) != canonical_hash:
            raise PlanError("mutation-target-hash-invalid")
        if source.get("mutationTargetHash", target_hash) != target_hash:
            raise PlanError("mutation-target-hash-invalid")
        if source.get("containmentRootHash", root_hash) != root_hash:
            raise PlanError("mutation-containment-hash-invalid")
        result.append({
            "targetKind": "managed-state-root",
            "targetId": target_id,
            "canonicalTargetHash": canonical_hash,
            "mutationTargetHash": target_hash,
            "containmentRootHash": root_hash,
            "recursion": "none",
            "reparsePolicy": "reject",
            "allowedActions": actions,
            "evidenceRequired": True,
        })
    return sorted(result, key=lambda item: item["targetId"])


def _machine_hash(
    authorization: MachineAuthorization | Mapping[str, Any] | None, *,
    provider_id: str, root_hash: str, subject_kind: str, operation_id: str,
    side_effect_class: str, execution_nonce: str, attempt_ref: str,
    now: datetime | str | None, test_mode: bool,
) -> str | None:
    if side_effect_class == "none":
        if authorization is not None:
            raise PlanError("readonly-machine-authorization-unexpected")
        return None
    if authorization is None or now is None:
        raise PlanError("machine-project-authorization-required")
    document = authorization.document if isinstance(authorization, MachineAuthorization) else dict(authorization)
    try:
        validate_machine_authorization(
            document,
            provider_id=provider_id,
            project_root_hash=root_hash,
            subject_kind=subject_kind,
            operation_id=operation_id,
            side_effect_class=side_effect_class,
            execution_nonce=execution_nonce,
            attempt_ref=attempt_ref,
            now=now,
            test_mode=test_mode,
        )
    except ApprovalError as error:
        raise PlanError(error.reason) from None
    return document["authorizationHash"]


def _finalize(
    body: dict[str, Any], subject: AuthorizationSubject,
    approval: ApprovalReceipt | Mapping[str, Any] | None, *, hash_field: str,
) -> dict[str, Any]:
    if approval is None:
        body[hash_field] = content_hash(body)
        return body
    body = finalize_document(subject, approval, final_hash_field=hash_field, base_document=body)
    approval_document = approval.document if isinstance(approval, ApprovalReceipt) else dict(approval)
    body["approvalReceipt"] = clone(approval_document)
    body["approvalReceiptRef"] = "approval-" + approval_document["receiptHash"][7:]
    body["approvalReceiptHash"] = approval_document["receiptHash"]
    body[hash_field] = content_hash({key: value for key, value in body.items() if key != hash_field})
    return body


@dataclass(frozen=True)
class OperationPlan:
    document: dict[str, Any]
    subject: AuthorizationSubject

    @property
    def operation_plan_hash(self) -> str:
        return self.document["operationPlanHash"]

    @property
    def argv(self) -> tuple[str, ...]:
        return tuple(self.document["commandSpec"]["argv"])

    @property
    def env(self) -> dict[str, str]:
        return clone(self.document["commandSpec"]["env"])

    @property
    def cwd(self) -> str:
        return self.document["commandSpec"]["cwd"]


@dataclass(frozen=True)
class QueryPlan:
    document: dict[str, Any]
    subject: AuthorizationSubject

    @property
    def query_plan_hash(self) -> str:
        return self.document["queryPlanHash"]


def build_operation_plan(
    *, provider_id: str, operation_id: str, binding_snapshot_hash: str,
    adapter_hash: str, plan_hash: str, project_root: str,
    command_registry: TrustedCommandRegistry, command_template_id: str,
    command_parameters: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: int = 60, output_limit_bytes: int = 1024 * 1024,
    mutation_targets: Iterable[Mapping[str, Any]] = (), execution_nonce: str,
    attempt_ref: str, ownership_domain: str,
    machine_authorization: MachineAuthorization | Mapping[str, Any] | None = None,
    now: datetime | str | None = None, test_mode: bool = False,
    approval: ApprovalReceipt | Mapping[str, Any] | None = None,
) -> OperationPlan:
    assert_maintenance_operation(operation_id, ownership_domain=ownership_domain)
    for value in (binding_snapshot_hash, adapter_hash, plan_hash):
        _safe_hash(value)
    provider_id = _safe_id(provider_id, "provider-id-invalid")
    operation_id = _safe_id(operation_id, "operation-id-invalid")
    execution_nonce = _safe_id(execution_nonce, "nonce-invalid")
    attempt_ref = _safe_id(attempt_ref, "attempt-invalid")
    root = canonical_project_root(project_root)
    root_hash = project_root_hash(root)
    side_effect_class = "none" if operation_id == "inspect" else "local-write"
    if side_effect_class != "none" and ownership_domain != "selfworkflow-managed":
        raise PlanError("user-owned-source-protected")
    target_list = _targets(
        mutation_targets, root_hash=root_hash,
        side_effect_class=side_effect_class, operation_id=operation_id,
    )
    authorization_hash = _machine_hash(
        machine_authorization,
        provider_id=provider_id, root_hash=root_hash, subject_kind="operation-plan",
        operation_id=operation_id, side_effect_class=side_effect_class,
        execution_nonce=execution_nonce, attempt_ref=attempt_ref, now=now,
        test_mode=test_mode,
    )
    try:
        command = render_command(
            command_registry,
            template_id=command_template_id,
            provider_id=provider_id,
            binding_snapshot_hash=binding_snapshot_hash,
            adapter_hash=adapter_hash,
            operation_id=operation_id,
            side_effect_class=side_effect_class,
            canonical_project_root=str(root),
            parameters=command_parameters,
            env=env,
        )
    except CommandRegistryError as error:
        raise PlanError(error.reason) from None
    body: dict[str, Any] = {
        "schemaVersion": 3,
        "planHash": plan_hash,
        "providerId": provider_id,
        "operationId": operation_id,
        "bindingSnapshotHash": binding_snapshot_hash,
        "adapterHash": adapter_hash,
        "commandRegistryHash": command_registry.registry_hash,
        "commandTemplateHash": command["templateHash"],
        "adapterRenderHash": command["commandSpecHash"],
        "canonicalTargetHash": content_hash([item["mutationTargetHash"] for item in target_list]),
        "containmentRootHash": content_hash([item["containmentRootHash"] for item in target_list]),
        "networkPolicy": "none",
        "sideEffectClass": side_effect_class,
        "timeoutSeconds": timeout_seconds,
        "outputLimitBytes": output_limit_bytes,
        "mutationTargets": target_list,
        "commandSpec": command,
        "executionNonce": execution_nonce,
        "attemptRef": attempt_ref,
        "canonicalProjectRootHash": root_hash,
        "ownershipDomain": ownership_domain,
    }
    if authorization_hash is not None:
        body["machineAuthorizationHash"] = authorization_hash
    subject = build_operation_plan_subject(body)
    body["operationAuthorizationSubjectHash"] = subject.subject_hash
    body = _finalize(body, subject, approval, hash_field="operationPlanHash")
    validate_provider_operation_plan(body)
    return OperationPlan(clone(body), subject)


def build_query_plan(
    *, provider_id: str, operation_id: str, binding_snapshot_hash: str,
    plan_hash: str, adapter_hash: str, typed_input_schema_ref: str,
    typed_input: Any, project_root: str,
    project_state_receipt_hash: str, workspace_fingerprint_hash: str,
    query_byte_budget: int, call_limit: int, timeout_seconds: int,
    side_effects: str, mutation_targets: Iterable[Mapping[str, Any]],
    execution_nonce: str, attempt_ref: str,
    command_registry: TrustedCommandRegistry, command_template_id: str,
    command_parameters: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
    ownership_domain: str = "user-owned",
    machine_authorization: MachineAuthorization | Mapping[str, Any] | None = None,
    now: datetime | str | None = None, test_mode: bool = False,
    approval: ApprovalReceipt | Mapping[str, Any] | None = None,
) -> QueryPlan:
    if side_effects == "network":
        raise PlanError("network-unsupported")
    if side_effects not in {"none", "local-write"}:
        raise PlanError("query-side-effects-invalid")
    if side_effects == "local-write" and ownership_domain != "selfworkflow-managed":
        raise PlanError("user-owned-source-protected")
    for value in (
        binding_snapshot_hash, plan_hash, adapter_hash,
        project_state_receipt_hash, workspace_fingerprint_hash,
    ):
        _safe_hash(value)
    root = canonical_project_root(project_root)
    root_hash = project_root_hash(root)
    provider_id = _safe_id(provider_id, "provider-id-invalid")
    operation_id = _safe_id(operation_id, "operation-id-invalid")
    execution_nonce = _safe_id(execution_nonce, "nonce-invalid")
    attempt_ref = _safe_id(attempt_ref, "attempt-invalid")
    target_list = _targets(
        mutation_targets, root_hash=root_hash,
        side_effect_class=side_effects, operation_id=operation_id,
    )
    authorization_hash = _machine_hash(
        machine_authorization,
        provider_id=provider_id, root_hash=root_hash, subject_kind="query-plan",
        operation_id=operation_id, side_effect_class=side_effects,
        execution_nonce=execution_nonce, attempt_ref=attempt_ref, now=now,
        test_mode=test_mode,
    )
    try:
        command = render_command(
            command_registry,
            template_id=command_template_id,
            provider_id=provider_id,
            binding_snapshot_hash=binding_snapshot_hash,
            adapter_hash=adapter_hash,
            operation_id=operation_id,
            side_effect_class=side_effects,
            canonical_project_root=str(root),
            parameters=command_parameters,
            env=env,
        )
    except CommandRegistryError as error:
        raise PlanError(error.reason) from None
    body: dict[str, Any] = {
        "schemaVersion": 3,
        "planHash": plan_hash,
        "providerId": provider_id,
        "operationId": operation_id,
        "bindingSnapshotHash": binding_snapshot_hash,
        "adapterHash": adapter_hash,
        "typedInputSchemaRef": _safe_id(typed_input_schema_ref, "typed-input-schema-invalid"),
        "typedInputHash": content_hash(typed_input),
        "commandRegistryHash": command_registry.registry_hash,
        "commandTemplateHash": command["templateHash"],
        "adapterRenderHash": command["commandSpecHash"],
        "canonicalProjectRootHash": root_hash,
        "projectStateReceiptHash": project_state_receipt_hash,
        "workspaceFingerprintHash": workspace_fingerprint_hash,
        "queryByteBudget": query_byte_budget,
        "callLimit": call_limit,
        "timeoutSeconds": timeout_seconds,
        "sideEffects": side_effects,
        "networkPolicy": "none",
        "mutationTargets": target_list,
        "commandSpec": command,
        "executionNonce": execution_nonce,
        "attemptRef": attempt_ref,
        "ownershipDomain": ownership_domain,
    }
    if authorization_hash is not None:
        body["machineAuthorizationHash"] = authorization_hash
    subject = build_query_plan_subject(body)
    body["queryAuthorizationSubjectHash"] = subject.subject_hash
    body = _finalize(body, subject, approval, hash_field="queryPlanHash")
    validate_provider_query_plan(body)
    return QueryPlan(clone(body), subject)


def assert_maintenance_operation(operation_id: str, *, ownership_domain: str) -> None:
    if operation_id not in OPERATION_IDS or operation_id in FORBIDDEN_OPERATION_IDS:
        raise PlanError("operation-not-allowed")
    if operation_id != "inspect" and ownership_domain != "selfworkflow-managed":
        raise PlanError("user-owned-source-protected")
