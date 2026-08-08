"""Content-addressed Provider plans containing the exact executable command."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
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
from selfworkflow.v3.contracts import validate_provider_operation_plan, validate_provider_query_plan
from selfworkflow.v3.hashing import (
    HashingError,
    canonical_project_root,
    canonical_relative_path,
    clone,
    content_hash,
    project_root_hash,
    require_hash,
)


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
_ACTIONS = {
    "exact-file": {"create", "modify", "delete"},
    "directory-subtree": {"create", "modify", "delete"},
    "managed-state-root": {"initialize", "sync", "rebuild", "upgrade", "repair"},
    "process": {"start", "stop", "inspect", "mutate"},
    "service": {"start", "stop", "connect", "configure"},
    "network": {"connect", "listen", "download", "upload"},
}


def _safe_id(value: object, reason: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", value):
        raise PlanError(reason)
    return value


def _safe_hash(value: object) -> str:
    try:
        return require_hash(value)
    except Exception:
        raise PlanError("plan-hash-invalid") from None


def _safe_argv(values: Iterable[str]) -> list[str]:
    argv = list(values)
    if not argv or len(argv) > 256:
        raise PlanError("command-argv-invalid")
    for value in argv:
        if not isinstance(value, str) or not value or len(value) > 4096 or _SHELL.search(value):
            raise PlanError("argv-template-injection")
    if not os.path.isabs(argv[0]):
        raise PlanError("argv-executable-not-absolute")
    return argv


def _env(env: Mapping[str, str], allowlist: Iterable[str]) -> dict[str, str]:
    allowed = set(allowlist)
    if set(env) - allowed:
        raise PlanError("env-injection")
    result: dict[str, str] = {}
    for key, value in env.items():
        if (
            not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", key)
            or not isinstance(value, str) or len(value) > 8192 or _SHELL.search(value)
        ):
            raise PlanError("env-injection")
        result[key] = value
    return dict(sorted(result.items()))


def _cwd(root: Path, value: str | None) -> Path:
    try:
        cwd = canonical_project_root(root if value is None else value)
        cwd.relative_to(root)
        return cwd
    except (HashingError, ValueError):
        raise PlanError("command-cwd-outside-project") from None


def _target_id(kind: str, value: object) -> str:
    if kind in {"exact-file", "directory-subtree"}:
        try:
            return canonical_relative_path(value)
        except HashingError:
            raise PlanError("mutation-target-invalid") from None
    if not isinstance(value, str) or not value or len(value) > 512 or _SHELL.search(value):
        raise PlanError("mutation-target-invalid")
    return value


def _targets(
    targets: Iterable[Mapping[str, Any]], *, root_hash: str,
    allow_empty: bool = False,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    for source in targets:
        kind = source.get("targetKind")
        if kind not in _ACTIONS:
            raise PlanError("mutation-target-invalid")
        target_id = _target_id(kind, source.get("targetId"))
        identity = (kind, target_id)
        if identity in identities:
            raise PlanError("mutation-target-duplicate")
        identities.add(identity)
        actions = sorted(set(source.get("allowedActions", ())))
        if not actions or not set(actions).issubset(_ACTIONS[kind]):
            raise PlanError("mutation-target-action-invalid")
        canonical_hash = content_hash({"targetKind": kind, "targetId": target_id})
        containment_hash = (
            root_hash if kind in {"exact-file", "directory-subtree", "managed-state-root"}
            else content_hash({"targetKind": kind, "scope": target_id})
        )
        if source.get("canonicalTargetHash", canonical_hash) != canonical_hash:
            raise PlanError("mutation-target-hash-invalid")
        if source.get("containmentRootHash", containment_hash) != containment_hash:
            raise PlanError("mutation-containment-hash-invalid")
        evidence_required = source.get("evidenceRequired", True)
        if not isinstance(evidence_required, bool):
            raise PlanError("mutation-target-evidence-policy-invalid")
        result.append({
            "targetKind": kind,
            "targetId": target_id,
            "canonicalTargetHash": canonical_hash,
            "containmentRootHash": containment_hash,
            "recursion": source.get("recursion", "none"),
            "reparsePolicy": source.get("reparsePolicy", "reject"),
            "allowedActions": actions,
            "evidenceRequired": evidence_required,
        })
    if not result and not allow_empty:
        raise PlanError("mutation-targets-required")
    return sorted(result, key=lambda item: (item["targetKind"], item["targetId"]))


def _command_spec(
    *, root: Path, cwd: Path, argv: Iterable[str], env: Mapping[str, str],
    env_allowlist: Iterable[str], side_effect_class: str, network_policy: str,
    mutation_targets: list[dict[str, Any]],
) -> dict[str, Any]:
    if side_effect_class not in {"none", "local-write", "network"}:
        raise PlanError("side-effect-class-invalid")
    if network_policy not in {"none", "local-only", "explicit-approved", "allowed"}:
        raise PlanError("network-policy-invalid")
    if side_effect_class == "network" and network_policy not in {"explicit-approved", "allowed"}:
        raise PlanError("network-authorization-required")
    if side_effect_class == "none" and network_policy != "none":
        raise PlanError("network-policy-invalid")
    if side_effect_class == "local-write" and network_policy not in {"none", "local-only"}:
        raise PlanError("network-policy-invalid")
    if side_effect_class == "network" and not any(item["targetKind"] == "network" for item in mutation_targets):
        raise PlanError("network-target-required")
    if side_effect_class != "network" and any(item["targetKind"] == "network" for item in mutation_targets):
        raise PlanError("undeclared-network-policy")
    command = {
        "argv": _safe_argv(argv),
        "env": _env(env, env_allowlist),
        "canonicalProjectRoot": str(root),
        "cwd": str(cwd),
        "sideEffectClass": side_effect_class,
        "networkPolicy": network_policy,
        "mutationTargets": clone(mutation_targets),
    }
    command["commandSpecHash"] = content_hash(command)
    return command


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
    plan_hash: str, project_root: str, executable: str,
    env: Mapping[str, str] = {}, env_allowlist: Iterable[str] = (),
    network_policy: str = "none", timeout_seconds: int = 60,
    output_limit_bytes: int = 1024 * 1024,
    mutation_targets: Iterable[Mapping[str, Any]], execution_nonce: str,
    attempt_ref: str, adapter_render_hash: str,
    ownership_domain: str,
    cwd: str | None = None,
    approval: ApprovalReceipt | Mapping[str, Any] | None = None,
) -> OperationPlan:
    assert_maintenance_operation(operation_id, ownership_domain=ownership_domain)
    root = canonical_project_root(project_root)
    working = _cwd(root, cwd)
    for value in (binding_snapshot_hash, plan_hash, adapter_render_hash):
        _safe_hash(value)
    provider_id = _safe_id(provider_id, "provider-id-invalid")
    operation_id = _safe_id(operation_id, "operation-id-invalid")
    execution_nonce = _safe_id(execution_nonce, "nonce-invalid")
    attempt_ref = _safe_id(attempt_ref, "attempt-invalid")
    root_hash = project_root_hash(root)
    target_list = _targets(mutation_targets, root_hash=root_hash)
    env_names = tuple(env_allowlist)
    side_effect_class = "none" if operation_id == "inspect" else "local-write"
    if network_policy in {"explicit-approved", "allowed"}:
        side_effect_class = "network"
    argv = (executable, "--operation", operation_id, "--project-root", str(root))
    command = _command_spec(
        root=root, cwd=working, argv=argv, env=env, env_allowlist=env_names,
        side_effect_class=side_effect_class, network_policy=network_policy,
        mutation_targets=target_list,
    )
    body: dict[str, Any] = {
        "schemaVersion": 3,
        "planHash": plan_hash,
        "providerId": provider_id,
        "operationId": operation_id,
        "bindingSnapshotHash": binding_snapshot_hash,
        "canonicalTargetHash": content_hash([item["canonicalTargetHash"] for item in target_list]),
        "containmentRootHash": content_hash([item["containmentRootHash"] for item in target_list]),
        "adapterRenderHash": adapter_render_hash,
        "argvHash": content_hash(command["argv"]),
        "cwdHash": content_hash(command["cwd"]),
        "envAllowlist": sorted(set(env_names)),
        "networkPolicy": network_policy,
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
    subject = build_operation_plan_subject(body)
    body["operationAuthorizationSubjectHash"] = subject.subject_hash
    if approval is not None:
        body = finalize_document(subject, approval, final_hash_field="operationPlanHash", base_document=body)
        approval_document = approval.document if isinstance(approval, ApprovalReceipt) else dict(approval)
        body["approvalReceipt"] = clone(approval_document)
        body["approvalReceiptRef"] = "approval-" + approval_document["receiptHash"][7:]
        body["approvalReceiptHash"] = approval_document["receiptHash"]
        body["operationPlanHash"] = content_hash({key: value for key, value in body.items() if key != "operationPlanHash"})
    else:
        body["operationPlanHash"] = content_hash(body)
    validate_provider_operation_plan(body)
    return OperationPlan(clone(body), subject)


def build_query_plan(
    *, provider_id: str, operation_id: str, binding_snapshot_hash: str,
    plan_hash: str, adapter_hash: str, typed_input_schema_ref: str,
    typed_input: Any, adapter_render_hash: str, project_root: str,
    project_state_receipt_hash: str, workspace_fingerprint_hash: str,
    query_byte_budget: int, call_limit: int, timeout_seconds: int,
    side_effects: str, mutation_targets: Iterable[Mapping[str, Any]],
    execution_nonce: str, attempt_ref: str, executable: str,
    arguments: Iterable[str] = (), env: Mapping[str, str] = {},
    env_allowlist: Iterable[str] = (), cwd: str | None = None,
    network_policy: str = "none",
    machine_authorization: MachineAuthorization | Mapping[str, Any] | None = None,
    now: datetime | str | None = None,
    approval: ApprovalReceipt | Mapping[str, Any] | None = None,
) -> QueryPlan:
    if side_effects not in {"none", "local-write", "network"}:
        raise PlanError("query-side-effects-invalid")
    for value in (
        binding_snapshot_hash, plan_hash, adapter_hash, adapter_render_hash,
        project_state_receipt_hash, workspace_fingerprint_hash,
    ):
        _safe_hash(value)
    root = canonical_project_root(project_root)
    working = _cwd(root, cwd)
    root_hash = project_root_hash(root)
    provider_id = _safe_id(provider_id, "provider-id-invalid")
    operation_id = _safe_id(operation_id, "operation-id-invalid")
    execution_nonce = _safe_id(execution_nonce, "nonce-invalid")
    attempt_ref = _safe_id(attempt_ref, "attempt-invalid")
    target_list = _targets(mutation_targets, root_hash=root_hash, allow_empty=side_effects == "none")
    if side_effects != "none":
        if machine_authorization is None or now is None:
            raise PlanError("machine-project-authorization-required")
        try:
            validate_machine_authorization(
                machine_authorization,
                provider_id=provider_id, project_root_hash=root_hash,
                subject_kind="query-plan", operation_id=operation_id,
                side_effect_class=side_effects, execution_nonce=execution_nonce,
                attempt_ref=attempt_ref, now=now,
            )
        except ApprovalError as error:
            raise PlanError(error.reason) from None
    command = _command_spec(
        root=root, cwd=working, argv=(executable, *tuple(arguments)),
        env=env, env_allowlist=env_allowlist, side_effect_class=side_effects,
        network_policy=network_policy, mutation_targets=target_list,
    )
    body: dict[str, Any] = {
        "schemaVersion": 3,
        "planHash": plan_hash,
        "providerId": provider_id,
        "operationId": operation_id,
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
        "networkPolicy": network_policy,
        "mutationTargets": target_list,
        "commandSpec": command,
        "executionNonce": execution_nonce,
        "attemptRef": attempt_ref,
    }
    if machine_authorization is not None:
        authorization_document = (
            machine_authorization.document
            if isinstance(machine_authorization, MachineAuthorization)
            else dict(machine_authorization)
        )
        body["machineAuthorization"] = clone(authorization_document)
        body["machineAuthorizationHash"] = authorization_document["authorizationHash"]
    subject = build_query_plan_subject(body)
    body["queryAuthorizationSubjectHash"] = subject.subject_hash
    if approval is not None:
        body = finalize_document(subject, approval, final_hash_field="queryPlanHash", base_document=body)
        approval_document = approval.document if isinstance(approval, ApprovalReceipt) else dict(approval)
        body["approvalReceipt"] = clone(approval_document)
        body["approvalReceiptRef"] = "approval-" + approval_document["receiptHash"][7:]
        body["approvalReceiptHash"] = approval_document["receiptHash"]
        body["queryPlanHash"] = content_hash({key: value for key, value in body.items() if key != "queryPlanHash"})
    else:
        body["queryPlanHash"] = content_hash(body)
    validate_provider_query_plan(body)
    return QueryPlan(clone(body), subject)


def assert_maintenance_operation(operation_id: str, *, ownership_domain: str) -> None:
    if operation_id not in OPERATION_IDS or operation_id in FORBIDDEN_OPERATION_IDS:
        raise PlanError("operation-not-allowed")
    if operation_id in {"upgrade-managed-adapter", "repair-managed-state"} and ownership_domain != "selfworkflow-managed":
        raise PlanError("user-owned-source-protected")
