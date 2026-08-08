"""Typed, fixed-command Provider operation and query plans."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any, Mapping, Iterable

from selfworkflow.v3.approvals import (
    ApprovalReceipt,
    AuthorizationSubject,
    build_operation_plan_subject,
    build_query_plan_subject,
    finalize_document,
)
from selfworkflow.v3.contracts import validate_provider_operation_plan, validate_provider_query_plan
from selfworkflow.v3.hashing import canonical_project_root, clone, content_hash, project_root_hash, require_hash


class PlanError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


OPERATION_IDS = (
    "inspect", "initialize-index", "sync-incremental", "rebuild-index",
    "upgrade-managed-adapter", "repair-managed-state",
)
FORBIDDEN_OPERATION_IDS = {"remove", "delete", "upgrade-user-source", "repair-user-source"}
_SHELL = re.compile(r"[\x00\r\n;&|<>`$(){}!]")


def _safe_id(value: object, reason: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", value):
        raise PlanError(reason)
    return value


def _safe_hash(value: object) -> str:
    try:
        return require_hash(value)
    except Exception:
        raise PlanError("plan-hash-invalid") from None


def _fixed_argv(executable: str, operation_id: str, root: str) -> tuple[str, ...]:
    if not isinstance(executable, str) or not executable or _SHELL.search(executable):
        raise PlanError("argv-template-injection")
    if not os.path.isabs(executable):
        raise PlanError("argv-executable-not-absolute")
    if operation_id not in OPERATION_IDS or operation_id in FORBIDDEN_OPERATION_IDS:
        raise PlanError("operation-not-allowed")
    if _SHELL.search(root):
        raise PlanError("argv-project-root-injection")
    # The command is a tuple, never a shell command or user-substituted string.
    return (executable, "--operation", operation_id, "--project-root", root)


def _env(env: Mapping[str, str], allowlist: Iterable[str]) -> dict[str, str]:
    allowed = set(allowlist)
    if set(env) - allowed:
        raise PlanError("env-injection")
    result: dict[str, str] = {}
    for key, value in env.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", key) or not isinstance(value, str) or _SHELL.search(value):
            raise PlanError("env-injection")
        result[key] = value
    return result


def _targets(targets: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = [clone(dict(target)) for target in targets]
    if not result:
        raise PlanError("mutation-targets-required")
    for target in result:
        if target.get("targetKind") not in {"exact-file", "directory-subtree", "managed-state-root", "process", "service"}:
            raise PlanError("mutation-target-invalid")
        for key in ("canonicalTargetHash", "containmentRootHash"):
            _safe_hash(target.get(key))
    return result


@dataclass(frozen=True)
class OperationPlan:
    document: dict[str, Any]
    argv: tuple[str, ...]
    env: dict[str, str]
    cwd: str
    subject: AuthorizationSubject

    @property
    def operation_plan_hash(self) -> str:
        return self.document["operationPlanHash"]


@dataclass(frozen=True)
class QueryPlan:
    document: dict[str, Any]
    subject: AuthorizationSubject

    @property
    def query_plan_hash(self) -> str:
        return self.document["queryPlanHash"]


def build_operation_plan(
    *,
    provider_id: str,
    operation_id: str,
    binding_snapshot_hash: str,
    plan_hash: str,
    project_root: str,
    executable: str,
    env: Mapping[str, str] = {},
    env_allowlist: Iterable[str] = (),
    network_policy: str = "none",
    timeout_seconds: int = 60,
    output_limit_bytes: int = 1024 * 1024,
    mutation_targets: Iterable[Mapping[str, Any]],
    execution_nonce: str,
    attempt_ref: str,
    adapter_render_hash: str,
    approval: ApprovalReceipt | Mapping[str, Any] | None = None,
) -> OperationPlan:
    if operation_id in FORBIDDEN_OPERATION_IDS or operation_id not in OPERATION_IDS:
        raise PlanError("operation-not-allowed")
    root = canonical_project_root(project_root)
    root_text = str(root)
    for value in (binding_snapshot_hash, plan_hash, adapter_render_hash):
        _safe_hash(value)
    _safe_id(provider_id, "provider-id-invalid")
    _safe_id(operation_id, "operation-id-invalid")
    _safe_id(execution_nonce, "nonce-invalid")
    _safe_id(attempt_ref, "attempt-invalid")
    env_names = tuple(env_allowlist)
    argv = _fixed_argv(executable, operation_id, root_text)
    safe_env = _env(env, env_names)
    target_list = _targets(mutation_targets)
    body: dict[str, Any] = {
        "schemaVersion": 3,
        "planHash": plan_hash,
        "providerId": provider_id,
        "operationId": operation_id,
        "bindingSnapshotHash": binding_snapshot_hash,
        "canonicalTargetHash": content_hash([item["canonicalTargetHash"] for item in target_list]),
        "containmentRootHash": content_hash([item["containmentRootHash"] for item in target_list]),
        "adapterRenderHash": adapter_render_hash,
        "argvHash": content_hash(list(argv)),
        "cwdHash": content_hash(root_text),
        "envAllowlist": sorted(set(env_names)),
        "networkPolicy": network_policy,
        "timeoutSeconds": timeout_seconds,
        "outputLimitBytes": output_limit_bytes,
        "mutationTargets": target_list,
        "executionNonce": execution_nonce,
        "attemptRef": attempt_ref,
        "canonicalProjectRootHash": project_root_hash(root),
    }
    subject = build_operation_plan_subject(body)
    body["operationAuthorizationSubjectHash"] = subject.subject_hash
    if approval is not None:
        body = finalize_document(subject, approval, final_hash_field="operationPlanHash", base_document=body)
    else:
        body["operationPlanHash"] = content_hash(body)
    # Optional security metadata is schema-registered by Phase 2B.
    if approval is not None:
        receipt_hash = (approval.document if isinstance(approval, ApprovalReceipt) else approval)["receiptHash"]
        body["approvalReceiptRef"] = "approval-" + receipt_hash[7:]
        body["approvalReceiptHash"] = receipt_hash
    validate_provider_operation_plan(body)
    return OperationPlan(clone(body), argv, safe_env, root_text, subject)


def build_query_plan(
    *,
    provider_id: str,
    operation_id: str,
    binding_snapshot_hash: str,
    plan_hash: str,
    adapter_hash: str,
    typed_input_schema_ref: str,
    typed_input: Any,
    adapter_render_hash: str,
    project_root: str,
    project_state_receipt_hash: str,
    workspace_fingerprint_hash: str,
    query_byte_budget: int,
    call_limit: int,
    timeout_seconds: int,
    side_effects: str,
    mutation_targets: Iterable[str],
    execution_nonce: str,
    attempt_ref: str,
    machine_authorized: bool = False,
    approval: ApprovalReceipt | Mapping[str, Any] | None = None,
) -> QueryPlan:
    if side_effects == "local-write" and not machine_authorized:
        raise PlanError("machine-project-authorization-required")
    if side_effects not in {"none", "local-write", "network"}:
        raise PlanError("query-side-effects-invalid")
    for value in (binding_snapshot_hash, plan_hash, adapter_hash, adapter_render_hash, project_state_receipt_hash, workspace_fingerprint_hash):
        _safe_hash(value)
    root_hash = project_root_hash(project_root)
    target_hashes = sorted(set(mutation_targets))
    for value in target_hashes:
        _safe_hash(value)
    body: dict[str, Any] = {
        "schemaVersion": 3,
        "planHash": plan_hash,
        "providerId": _safe_id(provider_id, "provider-id-invalid"),
        "operationId": _safe_id(operation_id, "operation-id-invalid"),
        "bindingSnapshotHash": binding_snapshot_hash,
        "adapterHash": adapter_hash,
        "typedInputSchemaRef": _safe_id(typed_input_schema_ref, "typed-input-schema-invalid"),
        "typedInputHash": content_hash(typed_input),
        "adapterRenderHash": adapter_render_hash,
        "canonicalProjectRootHash": root_hash,
        "projectStateReceiptHash": project_state_receipt_hash,
        "workspaceFingerprintHash": workspace_fingerprint_hash,
        "queryByteBudget": query_byte_budget,
        "callLimit": call_limit,
        "timeoutSeconds": timeout_seconds,
        "sideEffects": side_effects,
        "mutationTargets": target_hashes,
        "executionNonce": _safe_id(execution_nonce, "nonce-invalid"),
        "attemptRef": _safe_id(attempt_ref, "attempt-invalid"),
        "machineProjectAuthorization": bool(machine_authorized),
    }
    subject = build_query_plan_subject(body)
    body["queryAuthorizationSubjectHash"] = subject.subject_hash
    if approval is not None:
        body = finalize_document(subject, approval, final_hash_field="queryPlanHash", base_document=body)
    else:
        body["queryPlanHash"] = content_hash(body)
    if approval is not None:
        receipt_hash = (approval.document if isinstance(approval, ApprovalReceipt) else approval)["receiptHash"]
        body["approvalReceiptRef"] = "approval-" + receipt_hash[7:]
        body["approvalReceiptHash"] = receipt_hash
    validate_provider_query_plan(body)
    return QueryPlan(clone(body), subject)


def assert_maintenance_operation(operation_id: str, *, ownership_domain: str) -> None:
    if operation_id not in OPERATION_IDS or operation_id in FORBIDDEN_OPERATION_IDS:
        raise PlanError("operation-not-allowed")
    if operation_id in {"upgrade-managed-adapter", "repair-managed-state"} and ownership_domain != "selfworkflow-managed":
        raise PlanError("user-owned-source-protected")
