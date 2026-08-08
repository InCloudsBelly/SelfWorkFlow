"""Fail-closed execution of sealed Provider plans through injected host ports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping, Protocol

from selfworkflow.v3.approvals import (
    ApprovalError,
    ApprovalReceipt,
    AuthorizationResolver,
    ReplayStore,
    build_operation_plan_subject,
    build_query_plan_subject,
    resolve_machine_authorization,
    validate_approval,
)
from selfworkflow.v3.command_registry import (
    CommandRegistryError,
    TrustedCommandRegistry,
    validate_rendered_command,
)
from selfworkflow.v3.contracts import (
    validate_provider_operation_plan,
    validate_provider_operation_receipt,
    validate_provider_query_plan,
    validate_provider_query_receipt,
)
from selfworkflow.v3.effects import EffectMutation, EffectNotStarted, EffectPort, EffectResult
from selfworkflow.v3.hashing import clone, content_hash
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
    def __init__(
        self, reason: str, *, replay_state: str = "not-reserved",
        retryable: bool = False,
    ) -> None:
        self.reason = reason
        self.replay_state = replay_state
        self.retryable = retryable
        super().__init__(reason)


class WorkspaceObserver(Protocol):
    def capture(self) -> WorkspaceObservation: ...


@dataclass(frozen=True)
class QueryExecution:
    receipt: dict[str, Any]
    effect_result: EffectResult


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise RunnerError("effect-time-not-utc")
    return value


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise RunnerError("effect-time-window-invalid") from None
    return _utc(parsed)


def _approval_document(value: ApprovalReceipt | Mapping[str, Any]) -> dict[str, Any]:
    return clone(value.document if isinstance(value, ApprovalReceipt) else dict(value))


def _validate_approval_for_plan(
    plan_document: Mapping[str, Any],
    approval: ApprovalReceipt | Mapping[str, Any] | None, *,
    now: datetime, test_mode: bool,
) -> tuple[dict[str, Any], str]:
    if approval is None:
        raise RunnerError("approval-required")
    document = _approval_document(approval)
    embedded = plan_document.get("approvalReceipt")
    if embedded != document or plan_document.get("approvalReceiptHash") != document.get("receiptHash"):
        raise RunnerError("approval-plan-mismatch")
    if document.get("confirmationSource") == "test-fixture" and not test_mode:
        raise RunnerError("test-approval-rejected")
    is_operation = "operationPlanHash" in plan_document
    subject = build_operation_plan_subject(plan_document) if is_operation else build_query_plan_subject(plan_document)
    target_hashes = [item["mutationTargetHash"] for item in plan_document.get("mutationTargets", [])]
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
    plan_hash = plan_document["operationPlanHash" if is_operation else "queryPlanHash"]
    replay_key = content_hash({
        "approvalReceiptHash": document["receiptHash"],
        "planHash": plan_hash,
        "providerId": plan_document["providerId"],
        "canonicalProjectRootHash": plan_document["canonicalProjectRootHash"],
        "operationId": plan_document["operationId"],
        "executionNonce": plan_document["executionNonce"],
        "attemptRef": plan_document["attemptRef"],
    })
    return document, replay_key


def _reserve(replay_store: ReplayStore | None, replay_key: str) -> None:
    if replay_store is None:
        raise RunnerError("approval-replay-store-required")
    try:
        reserved = replay_store.reserve(replay_key)
    except Exception:
        raise RunnerError("approval-replay-store-failed") from None
    if not reserved:
        raise RunnerError("approval-replay", replay_state="already-reserved")


def _commit(replay_store: ReplayStore, replay_key: str, terminal_state: str) -> None:
    try:
        committed = replay_store.commit(replay_key, terminal_state)
    except Exception:
        raise RunnerError("approval-replay-commit-failed", replay_state="reserved") from None
    if not committed:
        raise RunnerError("approval-replay-commit-failed", replay_state="reserved")


def _abort(replay_store: ReplayStore, replay_key: str) -> None:
    try:
        aborted = replay_store.abort(replay_key)
    except Exception:
        raise RunnerError("approval-replay-abort-failed", replay_state="reserved") from None
    if not aborted:
        raise RunnerError("approval-replay-abort-failed", replay_state="reserved")


def _validate_effect_port(effect_port: EffectPort, *, test_mode: bool) -> None:
    try:
        attestation = clone(dict(effect_port.capability_attestation()))  # type: ignore[attr-defined]
    except Exception:
        raise RunnerError("effect-host-capability-required") from None
    required = {
        "schemaVersion", "backendClass", "sealedCommand", "liveLeaseGuard",
        "evidenceClass", "attestationHash",
    }
    if set(attestation) != required or attestation.get("schemaVersion") != 3:
        raise RunnerError("effect-host-capability-invalid")
    if (
        attestation.get("backendClass") not in {"external-host", "fake-test"}
        or attestation.get("sealedCommand") is not True
        or attestation.get("liveLeaseGuard") is not True
        or attestation.get("evidenceClass") not in {"host-observed", "fake-only"}
        or attestation.get("attestationHash") != content_hash({
            key: value for key, value in attestation.items() if key != "attestationHash"
        })
    ):
        raise RunnerError("effect-host-capability-invalid")
    if not test_mode and (
        attestation["backendClass"] == "fake-test"
        or attestation["evidenceClass"] == "fake-only"
    ):
        raise RunnerError("test-effect-port-rejected")


def _validate_registry(
    plan_document: Mapping[str, Any], registry: TrustedCommandRegistry | None, *,
    test_mode: bool,
) -> None:
    if registry is None:
        raise RunnerError("trusted-command-registry-required")
    if plan_document.get("commandRegistryHash") != registry.registry_hash:
        raise RunnerError("trusted-command-registry-drift")
    try:
        validate_rendered_command(plan_document["commandSpec"], registry, production=not test_mode)
    except CommandRegistryError as error:
        raise RunnerError(error.reason) from None


def _validate_machine_authority(
    plan_document: Mapping[str, Any], resolver: AuthorizationResolver | None, *,
    now: datetime, test_mode: bool, subject_kind: str,
) -> dict[str, Any] | None:
    side_effect_class = plan_document["sideEffectClass"] if subject_kind == "operation-plan" else plan_document["sideEffects"]
    if side_effect_class == "none":
        return None
    authorization_hash = plan_document.get("machineAuthorizationHash")
    if not isinstance(authorization_hash, str):
        raise RunnerError("machine-authorization-resolver-required")
    try:
        return resolve_machine_authorization(
            resolver,
            authorization_hash=authorization_hash,
            provider_id=plan_document["providerId"],
            project_root_hash=plan_document["canonicalProjectRootHash"],
            subject_kind=subject_kind,
            operation_id=plan_document["operationId"],
            side_effect_class=side_effect_class,
            execution_nonce=plan_document["executionNonce"],
            attempt_ref=plan_document["attemptRef"],
            now=now,
            test_mode=test_mode,
        )
    except ApprovalError as error:
        raise RunnerError(error.reason) from None


class _RunnerLeaseGuard:
    def __init__(
        self, plan_document: Mapping[str, Any], lease: ProviderProjectLease,
        manager: ProviderLeaseManager,
    ) -> None:
        self.plan_document = plan_document
        self.lease = lease
        self.manager = manager
        self.effect_checks = 0
        self._inside_effect = False

    def begin_effect(self) -> None:
        self._inside_effect = True

    def end_effect(self) -> None:
        self._inside_effect = False

    def check(self) -> str:
        try:
            self.manager.validate_live(
                self.lease,
                project_root_hash=self.plan_document["canonicalProjectRootHash"],
                provider_id=self.plan_document["providerId"],
                operation_id=self.plan_document["operationId"],
                nonce=self.plan_document["executionNonce"],
            )
            self.lease = self.manager.heartbeat(self.lease)
        except LeaseError as error:
            raise RunnerError(error.reason) from None
        if self._inside_effect:
            self.effect_checks += 1
        return self.lease.lease_hash


def _prepare_lease_guard(
    plan_document: Mapping[str, Any], lease: ProviderProjectLease | None,
    manager: ProviderLeaseManager | None, *, test_mode: bool, side_effect_class: str,
) -> _RunnerLeaseGuard | None:
    if side_effect_class == "none":
        return None
    if lease is None or manager is None:
        raise RunnerError("live-provider-lease-required")
    try:
        manager.assert_host_capability(test_mode=test_mode)
        manager.validate_live(
            lease,
            project_root_hash=plan_document["canonicalProjectRootHash"],
            provider_id=plan_document["providerId"],
            operation_id=plan_document["operationId"],
            nonce=plan_document["executionNonce"],
        )
    except LeaseError as error:
        raise RunnerError(error.reason) from None
    return _RunnerLeaseGuard(plan_document, lease, manager)


def _target_matches(mutation: EffectMutation, target: Mapping[str, Any]) -> bool:
    return (
        mutation.kind == "managed-state"
        and target["targetKind"] == "managed-state-root"
        and mutation.target == target["targetId"]
        and mutation.action in target["allowedActions"]
    )


def _validate_effects(
    result: EffectResult, plan_document: Mapping[str, Any], *, subject_kind: str,
) -> tuple[str, list[str], dict[str, dict[str, Any]]]:
    planned_class = plan_document["commandSpec"]["sideEffectClass"]
    if result.touched_paths:
        raise RunnerError("undeclared-effect")
    if planned_class != "none" and not result.observation_complete:
        raise RunnerError("required-effect-observation-missing")
    identities = {(item.kind, item.target, item.action) for item in result.mutations}
    if len(identities) != len(result.mutations):
        raise RunnerError("duplicate-effect-observation")
    matched: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for mutation in result.mutations:
        if mutation.kind == "network":
            raise RunnerError("network-unsupported")
        candidates = [target for target in plan_document["mutationTargets"] if _target_matches(mutation, target)]
        if len(candidates) != 1:
            raise RunnerError("undeclared-effect")
        matched[(mutation.kind, mutation.target, mutation.action)] = candidates[0]
    if planned_class == "none" and (result.mutations or result.mutation_evidence):
        raise RunnerError("undeclared-effect")
    evidence_by_target: dict[str, dict[str, Any]] = {}
    evidence_by_ref: dict[str, dict[str, Any]] = {}
    for source in result.mutation_evidence:
        evidence = clone(dict(source))
        target_hash = evidence.get("mutationTargetHash")
        if not isinstance(target_hash, str) or target_hash in evidence_by_target:
            raise RunnerError("mutation-evidence-replay")
        target = next((
            item for item in plan_document["mutationTargets"]
            if item["mutationTargetHash"] == target_hash
        ), None)
        if target is None:
            raise RunnerError("mutation-target-hash-mismatch")
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
        actual = evidence["actualTargets"]
        if len(actual) != 1 or (
            actual[0]["targetKind"] != "managed-state"
            or actual[0]["targetId"] != target["targetId"]
            or actual[0]["action"] not in target["allowedActions"]
        ):
            raise RunnerError("mutation-evidence-target-mismatch")
        evidence_by_target[target_hash] = evidence
        evidence_by_ref["evidence-" + evidence["evidenceHash"][7:]] = evidence
    required = {item["mutationTargetHash"] for item in plan_document["mutationTargets"] if item["evidenceRequired"]}
    if set(evidence_by_target) != required:
        raise RunnerError("required-mutation-evidence-missing")
    for identity, target in matched.items():
        evidence = evidence_by_target.get(target["mutationTargetHash"])
        if evidence is None:
            raise RunnerError("required-mutation-evidence-missing")
        actual = evidence["actualTargets"][0]
        if identity != (actual["targetKind"], actual["targetId"], actual["action"]):
            raise RunnerError("mutation-evidence-target-mismatch")
    actual_class = "local-write" if result.mutations else "none"
    return actual_class, sorted(evidence_by_ref), evidence_by_ref


def _run_effect(
    plan_document: Mapping[str, Any], effect_port: EffectPort, *,
    invocation_time: datetime, guard: _RunnerLeaseGuard | None,
) -> EffectResult:
    output_limit = plan_document.get("outputLimitBytes", plan_document.get("queryByteBudget"))
    if guard is not None:
        guard.begin_effect()
    try:
        return effect_port.run(
            clone(plan_document["commandSpec"]),
            timeout_seconds=plan_document["timeoutSeconds"],
            output_limit_bytes=output_limit,
            invocation_time=invocation_time,
            live_lease_guard=guard,
        )
    finally:
        if guard is not None:
            guard.end_effect()


def _validate_effect_window(
    result: EffectResult, invocation_time: datetime, *,
    lease: ProviderProjectLease | None,
    approval: Mapping[str, Any], machine_authorization: Mapping[str, Any] | None,
) -> None:
    invocation = _utc(invocation_time)
    started = _utc(result.started_at)
    completed = _utc(result.completed_at)
    if not (started <= invocation <= completed):
        raise RunnerError("effect-invocation-outside-window")
    if lease is not None and not (
        _parse_utc(lease.document["issuedAt"]) <= started <= completed <= _parse_utc(lease.document["expiresAt"])
    ):
        raise RunnerError("effect-outside-lease-window")
    if not (_parse_utc(approval["issuedAt"]) <= invocation <= completed <= _parse_utc(approval["expiresAt"])):
        raise RunnerError("effect-outside-approval-window")
    if machine_authorization is not None and not (
        _parse_utc(machine_authorization["issuedAt"]) <= invocation <= completed
        <= _parse_utc(machine_authorization["expiresAt"])
    ):
        raise RunnerError("effect-outside-machine-authorization-window")


def _terminal_failure(
    replay_store: ReplayStore, replay_key: str, reason: str,
) -> RunnerError:
    _commit(replay_store, replay_key, "terminal-failed")
    return RunnerError(reason, replay_state="terminal-failed", retryable=False)


def run_operation(
    plan: OperationPlan, *, approval: ApprovalReceipt | Mapping[str, Any] | None,
    effect_port: EffectPort, now: datetime,
    trusted_command_registry: TrustedCommandRegistry | None = None,
    authorization_resolver: AuthorizationResolver | None = None,
    lease: ProviderProjectLease | None = None,
    lease_manager: ProviderLeaseManager | None = None,
    replay_store: ReplayStore | None = None,
    test_mode: bool = False,
) -> tuple[dict[str, Any], EffectResult]:
    try:
        validate_provider_operation_plan(plan.document)
    except Exception:
        raise RunnerError("operation-plan-invalid") from None
    _validate_effect_port(effect_port, test_mode=test_mode)
    _validate_registry(plan.document, trusted_command_registry, test_mode=test_mode)
    machine = _validate_machine_authority(
        plan.document, authorization_resolver, now=now,
        test_mode=test_mode, subject_kind="operation-plan",
    )
    guard = _prepare_lease_guard(
        plan.document, lease, lease_manager, test_mode=test_mode,
        side_effect_class=plan.document["sideEffectClass"],
    )
    approval_document, replay_key = _validate_approval_for_plan(
        plan.document, approval, now=now, test_mode=test_mode,
    )
    _reserve(replay_store, replay_key)
    assert replay_store is not None
    try:
        if guard is not None:
            guard.check()
        result = _run_effect(plan.document, effect_port, invocation_time=now, guard=guard)
    except EffectNotStarted as error:
        _abort(replay_store, replay_key)
        raise RunnerError(error.reason, replay_state="aborted", retryable=True) from None
    except Exception:
        raise _terminal_failure(replay_store, replay_key, "effect-port-failed") from None
    try:
        if guard is not None:
            if guard.effect_checks < 1:
                raise RunnerError("effect-live-lease-guard-not-used")
            guard.check()
        _validate_effect_window(
            result, now, lease=None if guard is None else guard.lease,
            approval=approval_document, machine_authorization=machine,
        )
        _actual_class, evidence_refs, evidence_by_ref = _validate_effects(
            result, plan.document, subject_kind="operation-plan",
        )
        if guard is not None:
            guard.check()
        outcome = "failed" if result.exit_code != 0 else "succeeded"
        terminal_state = "terminal-failed" if result.exit_code != 0 else "terminal-succeeded"
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
            replay_state=terminal_state,
            approval_receipt_ref=approval_document["receiptHash"],
            mutation_evidence_refs=evidence_refs,
            output_hash=content_hash({
                "stdout": result.stdout_summary,
                "stderr": result.stderr_summary,
                "exit": result.exit_code,
            }),
        )
        validate_provider_operation_receipt(
            receipt, plan.document, evidence_by_ref.get,
        )
    except RunnerError as error:
        raise _terminal_failure(replay_store, replay_key, error.reason) from None
    except Exception:
        raise _terminal_failure(replay_store, replay_key, "operation-post-validation-failed") from None
    _commit(replay_store, replay_key, terminal_state)
    return receipt, result


def run_query(
    plan: QueryPlan, *, approval: ApprovalReceipt | Mapping[str, Any] | None,
    effect_port: EffectPort, observer: WorkspaceObserver, now: datetime,
    returned_files: list[Mapping[str, Any]], index_revision: str,
    index_completeness: str,
    trusted_command_registry: TrustedCommandRegistry | None = None,
    authorization_resolver: AuthorizationResolver | None = None,
    lease: ProviderProjectLease | None = None,
    lease_manager: ProviderLeaseManager | None = None,
    replay_store: ReplayStore | None = None,
    test_mode: bool = False,
) -> QueryExecution:
    try:
        validate_provider_query_plan(plan.document)
    except Exception:
        raise RunnerError("query-plan-invalid") from None
    _validate_effect_port(effect_port, test_mode=test_mode)
    _validate_registry(plan.document, trusted_command_registry, test_mode=test_mode)
    machine = _validate_machine_authority(
        plan.document, authorization_resolver, now=now,
        test_mode=test_mode, subject_kind="query-plan",
    )
    guard = _prepare_lease_guard(
        plan.document, lease, lease_manager, test_mode=test_mode,
        side_effect_class=plan.document["sideEffects"],
    )
    approval_document, replay_key = _validate_approval_for_plan(
        plan.document, approval, now=now, test_mode=test_mode,
    )
    pre = observer.capture()
    if pre.fingerprint_hash != plan.document["workspaceFingerprintHash"]:
        raise RunnerError("query-workspace-snapshot-stale")
    _reserve(replay_store, replay_key)
    assert replay_store is not None
    try:
        if guard is not None:
            guard.check()
        result = _run_effect(plan.document, effect_port, invocation_time=now, guard=guard)
    except EffectNotStarted as error:
        _abort(replay_store, replay_key)
        raise RunnerError(error.reason, replay_state="aborted", retryable=True) from None
    except Exception:
        raise _terminal_failure(replay_store, replay_key, "effect-port-failed") from None
    try:
        if guard is not None:
            if guard.effect_checks < 1:
                raise RunnerError("effect-live-lease-guard-not-used")
            guard.check()
        _validate_effect_window(
            result, now, lease=None if guard is None else guard.lease,
            approval=approval_document, machine_authorization=machine,
        )
        post = observer.capture()
        if pre.identity_hash != post.identity_hash or pre.fingerprint_hash != post.fingerprint_hash:
            raise RunnerError("workspace-drift-during-query")
        actual_side_effects, evidence_refs, evidence_by_ref = _validate_effects(
            result, plan.document, subject_kind="query-plan",
        )
        if result.exit_code != 0:
            raise RunnerError("query-effect-failed")
        if guard is not None:
            guard.check()
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
            replay_state="terminal-succeeded",
            approval_receipt_ref=approval_document["receiptHash"],
            pre_workspace_identity_hash=pre.identity_hash,
            post_workspace_identity_hash=post.identity_hash,
        )
        validate_provider_query_receipt(
            receipt, plan.document, evidence_by_ref.get,
        )
    except RunnerError as error:
        raise _terminal_failure(replay_store, replay_key, error.reason) from None
    except Exception:
        raise _terminal_failure(replay_store, replay_key, "query-post-validation-failed") from None
    _commit(replay_store, replay_key, "terminal-succeeded")
    return QueryExecution(receipt, result)
