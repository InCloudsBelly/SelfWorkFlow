"""Plan-bound Provider execution through injected, observable effect ports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping, Protocol

from selfworkflow.v3.approvals import (
    ApprovalError,
    ApprovalReceipt,
    ReplayStore,
    build_operation_plan_subject,
    build_query_plan_subject,
    validate_approval,
)
from selfworkflow.v3.contracts import (
    validate_provider_operation_plan,
    validate_provider_operation_receipt,
    validate_provider_query_plan,
    validate_provider_query_receipt,
)
from selfworkflow.v3.effects import EffectMutation, EffectPort, EffectResult
from selfworkflow.v3.hashing import canonical_relative_path, content_hash
from selfworkflow.v3.plans import OperationPlan, QueryPlan
from selfworkflow.v3.project_lease import LeaseError, ProviderLeaseManager, ProviderProjectLease
from selfworkflow.v3.project_state import WorkspaceObservation
from selfworkflow.v3.receipts import (
    ReceiptError,
    build_operation_receipt,
    build_query_receipt,
    validate_mutation_evidence,
)


class RunnerError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class WorkspaceObserver(Protocol):
    def capture(self) -> WorkspaceObservation: ...


@dataclass(frozen=True)
class QueryExecution:
    receipt: dict[str, Any]
    effect_result: EffectResult


def _approval_document(value: ApprovalReceipt | Mapping[str, Any]) -> dict[str, Any]:
    return value.document if isinstance(value, ApprovalReceipt) else dict(value)


def _validate_and_consume_approval(
    plan_document: Mapping[str, Any],
    approval: ApprovalReceipt | Mapping[str, Any] | None, *,
    now: datetime, test_mode: bool, replay_store: ReplayStore | None,
) -> dict[str, Any]:
    if approval is None:
        raise RunnerError("approval-required")
    if replay_store is None:
        raise RunnerError("approval-replay-store-required")
    document = _approval_document(approval)
    embedded = plan_document.get("approvalReceipt")
    if embedded != document or plan_document.get("approvalReceiptHash") != document.get("receiptHash"):
        raise RunnerError("approval-plan-mismatch")
    if document.get("confirmationSource") == "test-fixture" and not test_mode:
        raise RunnerError("test-approval-rejected")
    is_operation = "operationPlanHash" in plan_document
    subject = (
        build_operation_plan_subject(plan_document)
        if is_operation else build_query_plan_subject(plan_document)
    )
    target_hashes = [item["canonicalTargetHash"] for item in plan_document.get("mutationTargets", [])]
    try:
        validate_approval(
            subject, document, now=now,
            expected_target_hashes=target_hashes,
            expected_provider_id=plan_document["providerId"],
            expected_project_root_hash=plan_document["canonicalProjectRootHash"],
            expected_attempt_ref=plan_document["attemptRef"],
            expected_operation_id=plan_document["operationId"],
            expected_execution_nonce=plan_document["executionNonce"],
        )
    except ApprovalError as error:
        raise RunnerError(error.reason) from None
    replay_key = content_hash({
        "approvalReceiptHash": document["receiptHash"],
        "planHash": plan_document["operationPlanHash" if is_operation else "queryPlanHash"],
        "providerId": plan_document["providerId"],
        "canonicalProjectRootHash": plan_document["canonicalProjectRootHash"],
        "operationId": plan_document["operationId"],
        "executionNonce": plan_document["executionNonce"],
        "attemptRef": plan_document["attemptRef"],
    })
    try:
        consumed = replay_store.consume(replay_key)
    except Exception:
        raise RunnerError("approval-replay-store-failed") from None
    if not consumed:
        raise RunnerError("approval-replay")
    return document


def _validate_lease(
    plan_document: Mapping[str, Any], lease: ProviderProjectLease | None,
    manager: ProviderLeaseManager | None,
) -> None:
    if lease is None or manager is None:
        raise RunnerError("live-provider-lease-required")
    try:
        manager.validate_live(
            lease,
            project_root_hash=plan_document["canonicalProjectRootHash"],
            provider_id=plan_document["providerId"],
            operation_id=plan_document["operationId"],
            nonce=plan_document["executionNonce"],
        )
    except LeaseError as error:
        raise RunnerError(error.reason) from None


def _target_matches(mutation: EffectMutation, target: Mapping[str, Any]) -> bool:
    if mutation.kind == "filesystem":
        if target["targetKind"] not in {"exact-file", "directory-subtree"}:
            return False
        try:
            actual = canonical_relative_path(mutation.target)
            declared = canonical_relative_path(target["targetId"])
        except Exception:
            return False
        scoped = actual == declared or (
            target["targetKind"] == "directory-subtree" and actual.startswith(declared + "/")
        )
    else:
        expected_kind = {
            "managed-state": "managed-state-root",
            "process": "process",
            "service": "service",
            "network": "network",
        }.get(mutation.kind)
        scoped = expected_kind == target["targetKind"] and mutation.target == target["targetId"]
    return scoped and mutation.action in target["allowedActions"]


def _actual_mutations(result: EffectResult) -> tuple[EffectMutation, ...]:
    mutations = list(result.mutations)
    known_paths = {item.target for item in mutations if item.kind == "filesystem"}
    for path in result.touched_paths:
        if path not in known_paths:
            mutations.append(EffectMutation("filesystem", canonical_relative_path(path), "modify"))
    identities = {(item.kind, item.target, item.action) for item in mutations}
    if len(identities) != len(mutations):
        raise RunnerError("duplicate-effect-observation")
    return tuple(mutations)


def _validate_effects(
    result: EffectResult, plan_document: Mapping[str, Any], *, subject_kind: str,
) -> tuple[str, list[str]]:
    planned_class = plan_document["commandSpec"]["sideEffectClass"]
    if planned_class != "none" and not result.observation_complete:
        raise RunnerError("required-effect-observation-missing")
    try:
        actual = _actual_mutations(result)
    except Exception:
        raise RunnerError("effect-observation-invalid") from None
    matched: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for mutation in actual:
        candidates = [target for target in plan_document["mutationTargets"] if _target_matches(mutation, target)]
        if len(candidates) != 1:
            raise RunnerError("undeclared-effect")
        matched[(mutation.kind, mutation.target, mutation.action)] = candidates[0]
    has_network = any(item.kind == "network" for item in actual)
    actual_class = "network" if has_network else ("local-write" if actual else "none")
    if planned_class == "none" and actual_class != "none":
        raise RunnerError("undeclared-effect")
    if planned_class == "local-write" and actual_class == "network":
        raise RunnerError("undeclared-network-effect")

    evidence_refs: list[str] = []
    evidenced: set[tuple[str, str, str]] = set()
    evidence_hashes: set[str] = set()
    for evidence in result.mutation_evidence:
        evidence_hash = evidence.get("evidenceHash")
        if not isinstance(evidence_hash, str) or evidence_hash in evidence_hashes:
            raise RunnerError("mutation-evidence-replay")
        evidence_hashes.add(evidence_hash)
        try:
            validate_mutation_evidence(
                evidence,
                subject_plan_hash=plan_document[
                    "operationPlanHash" if subject_kind == "operation-plan" else "queryPlanHash"
                ],
                execution_nonce=plan_document["executionNonce"],
                attempt_ref=plan_document["attemptRef"],
                provider_id=plan_document["providerId"],
                provider_binding_hash=plan_document["bindingSnapshotHash"],
                project_root_hash=plan_document["canonicalProjectRootHash"],
                started_at=result.started_at,
                completed_at=result.completed_at,
                declared_targets=plan_document["mutationTargets"],
            )
        except ReceiptError as error:
            raise RunnerError(error.reason) from None
        for item in evidence["actualTargets"]:
            key = (item["targetKind"], item["targetId"], item["action"])
            if key not in matched:
                raise RunnerError("redundant-mutation-evidence")
            evidenced.add(key)
        evidence_refs.append("evidence-" + evidence_hash[7:])
    unverified = False
    for identity, target in matched.items():
        if identity in evidenced:
            continue
        if target["evidenceRequired"]:
            raise RunnerError("required-mutation-evidence-missing")
        unverified = True
    return ("unverified" if unverified else actual_class), sorted(set(evidence_refs))


def _run_effect(plan_document: Mapping[str, Any], effect_port: EffectPort) -> EffectResult:
    command = plan_document["commandSpec"]
    try:
        output_limit = (
            plan_document["outputLimitBytes"]
            if "outputLimitBytes" in plan_document else plan_document["queryByteBudget"]
        )
        return effect_port.run(
            tuple(command["argv"]), env=dict(command["env"]), cwd=command["cwd"],
            timeout_seconds=plan_document["timeoutSeconds"],
            output_limit_bytes=output_limit,
        )
    except Exception as error:
        raise RunnerError("effect-port-failed") from error


def _validate_effect_window(result: EffectResult, invocation_time: datetime) -> None:
    for value in (invocation_time, result.started_at, result.completed_at):
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise RunnerError("effect-time-not-utc")
    if result.completed_at < result.started_at:
        raise RunnerError("effect-time-window-invalid")


def run_operation(
    plan: OperationPlan, *, approval: ApprovalReceipt | Mapping[str, Any] | None,
    effect_port: EffectPort, now: datetime,
    lease: ProviderProjectLease | None = None,
    lease_manager: ProviderLeaseManager | None = None,
    replay_store: ReplayStore | None = None,
    test_mode: bool = False,
) -> tuple[dict[str, Any], EffectResult]:
    if not test_mode and getattr(effect_port, "is_test_port", False):
        raise RunnerError("test-effect-port-rejected")
    try:
        validate_provider_operation_plan(plan.document)
    except Exception:
        raise RunnerError("operation-plan-invalid") from None
    _validate_lease(plan.document, lease, lease_manager)
    approval_document = _validate_and_consume_approval(
        plan.document, approval, now=now, test_mode=test_mode, replay_store=replay_store,
    )
    result = _run_effect(plan.document, effect_port)
    _validate_effect_window(result, now)
    evidence_state, evidence_refs = _validate_effects(result, plan.document, subject_kind="operation-plan")
    outcome = "failed" if result.exit_code != 0 else ("unverified" if evidence_state == "unverified" else "succeeded")
    receipt = build_operation_receipt(
        operation_plan_hash=plan.operation_plan_hash,
        execution_nonce=plan.document["executionNonce"],
        attempt_ref=plan.document["attemptRef"],
        provider_id=plan.document["providerId"],
        binding_snapshot_hash=plan.document["bindingSnapshotHash"],
        canonical_project_root_hash=plan.document["canonicalProjectRootHash"],
        started_at=result.started_at,
        completed_at=result.completed_at,
        outcome=outcome,
        approval_receipt_ref=approval_document["receiptHash"],
        mutation_evidence_refs=evidence_refs,
        output_hash=content_hash({
            "stdout": result.stdout_summary,
            "stderr": result.stderr_summary,
            "exit": result.exit_code,
        }),
    )
    validate_provider_operation_receipt(
        receipt, plan.document, tuple(dict(item) for item in result.mutation_evidence),
    )
    return receipt, result


def run_query(
    plan: QueryPlan, *, approval: ApprovalReceipt | Mapping[str, Any] | None,
    effect_port: EffectPort, observer: WorkspaceObserver, now: datetime,
    returned_files: list[Mapping[str, Any]], index_revision: str,
    index_completeness: str,
    lease: ProviderProjectLease | None = None,
    lease_manager: ProviderLeaseManager | None = None,
    replay_store: ReplayStore | None = None,
    test_mode: bool = False,
) -> QueryExecution:
    if not test_mode and getattr(effect_port, "is_test_port", False):
        raise RunnerError("test-effect-port-rejected")
    try:
        validate_provider_query_plan(plan.document)
    except Exception:
        raise RunnerError("query-plan-invalid") from None
    if plan.document["sideEffects"] != "none":
        _validate_lease(plan.document, lease, lease_manager)
    approval_document = _validate_and_consume_approval(
        plan.document, approval, now=now, test_mode=test_mode, replay_store=replay_store,
    )
    pre = observer.capture()
    if pre.fingerprint_hash != plan.document["workspaceFingerprintHash"]:
        raise RunnerError("query-workspace-snapshot-stale")
    result = _run_effect(plan.document, effect_port)
    _validate_effect_window(result, now)
    post = observer.capture()
    if pre.identity_hash != post.identity_hash or pre.fingerprint_hash != post.fingerprint_hash:
        if not result.touched_paths or set(post.changed_paths) - set(result.touched_paths):
            raise RunnerError("workspace-drift-during-query")
    evidence_state, evidence_refs = _validate_effects(result, plan.document, subject_kind="query-plan")
    actual_side_effects = (
        "unknown" if evidence_state == "unverified" else
        ("network" if any(item.kind == "network" for item in result.mutations) else
         ("local-write" if result.mutations or result.touched_paths else "none"))
    )
    receipt = build_query_receipt(
        query_plan_hash=plan.query_plan_hash,
        execution_nonce=plan.document["executionNonce"],
        attempt_ref=plan.document["attemptRef"],
        provider_id=plan.document["providerId"],
        adapter_hash=plan.document["adapterHash"],
        source_identity_hash=plan.document.get("sourceIdentityHash", plan.document["adapterHash"]),
        project_state_receipt_hash=plan.document["projectStateReceiptHash"],
        workspace_fingerprint_hash=plan.document["workspaceFingerprintHash"],
        canonical_project_root_hash=plan.document["canonicalProjectRootHash"],
        started_at=result.started_at,
        completed_at=result.completed_at,
        index_revision=index_revision,
        index_completeness=index_completeness,
        returned_files=returned_files,
        truncated=False,
        pre_fingerprint_hash=pre.fingerprint_hash,
        post_fingerprint_hash=post.fingerprint_hash,
        actual_side_effects=actual_side_effects,
        mutation_evidence_refs=evidence_refs,
        approval_receipt_ref=approval_document["receiptHash"],
        pre_workspace_identity_hash=pre.identity_hash,
        post_workspace_identity_hash=post.identity_hash,
    )
    validate_provider_query_receipt(
        receipt, plan.document, tuple(dict(item) for item in result.mutation_evidence),
    )
    return QueryExecution(receipt, result)
