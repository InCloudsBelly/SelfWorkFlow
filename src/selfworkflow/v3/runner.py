"""Side-effect runners with explicit EffectPort and fresh workspace observation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Callable, Mapping, Protocol

from selfworkflow.v3.approvals import ApprovalError, ApprovalReceipt, validate_approval
from selfworkflow.v3.effects import EffectPort, EffectResult
from selfworkflow.v3.hashing import content_hash
from selfworkflow.v3.plans import OperationPlan, PlanError, QueryPlan
from selfworkflow.v3.project_state import WorkspaceObservation
from selfworkflow.v3.receipts import build_operation_receipt, build_query_receipt


class RunnerError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class WorkspaceObserver(Protocol):
    def capture(self) -> WorkspaceObservation:
        ...


@dataclass(frozen=True)
class QueryExecution:
    receipt: dict[str, Any]
    effect_result: EffectResult


def _approved(plan_document: Mapping[str, Any], approval: ApprovalReceipt | Mapping[str, Any] | None, *, now: datetime, test_mode: bool) -> None:
    if approval is None:
        raise RunnerError("approval-required")
    doc = approval.document if isinstance(approval, ApprovalReceipt) else approval
    if doc.get("confirmationSource") == "test-fixture" and not test_mode:
        raise RunnerError("test-approval-rejected")
    from selfworkflow.v3.approvals import build_operation_plan_subject, build_query_plan_subject
    subject = build_operation_plan_subject(plan_document) if "operationPlanHash" in plan_document else build_query_plan_subject(plan_document)
    target_hashes = (
        [item["canonicalTargetHash"] for item in plan_document.get("mutationTargets", [])]
        if "operationPlanHash" in plan_document
        else list(plan_document.get("mutationTargets", []))
    )
    try:
        final_field = "operationPlanHash" if "operationPlanHash" in plan_document else "queryPlanHash"
        if plan_document.get(final_field) != content_hash({key: value for key, value in plan_document.items() if key != final_field}):
            raise RunnerError("plan-hash-invalid")
        validate_approval(subject, doc, now=now, expected_target_hashes=target_hashes, expected_attempt_ref=plan_document.get("attemptRef"))
    except ApprovalError as error:
        raise RunnerError(error.reason) from None


def run_operation(
    plan: OperationPlan,
    *,
    approval: ApprovalReceipt | Mapping[str, Any] | None,
    effect_port: EffectPort,
    now: datetime,
    test_mode: bool = False,
    used_nonces: set[str] | None = None,
) -> tuple[dict[str, Any], EffectResult]:
    if not test_mode and getattr(effect_port, "is_test_port", False):
        raise RunnerError("test-effect-port-rejected")
    _approved(plan.document, approval, now=now, test_mode=test_mode)
    if content_hash(list(plan.argv)) != plan.document["argvHash"] or content_hash(plan.cwd) != plan.document["cwdHash"]:
        raise RunnerError("rendered-command-drift")
    try:
        result = effect_port.run(
            plan.argv, env=plan.env, cwd=plan.cwd,
            timeout_seconds=plan.document["timeoutSeconds"],
            output_limit_bytes=plan.document["outputLimitBytes"],
        )
    except Exception as error:
        raise RunnerError("effect-port-failed") from error
    receipt = build_operation_receipt(
        operation_plan_hash=plan.operation_plan_hash,
        execution_nonce=plan.document["executionNonce"],
        attempt_ref=plan.document["attemptRef"],
        provider_id=plan.document["providerId"],
        binding_snapshot_hash=plan.document["bindingSnapshotHash"],
        started_at=result.started_at,
        completed_at=result.completed_at,
        outcome="succeeded" if result.exit_code == 0 else "failed",
        approval_receipt_ref=(approval.document if isinstance(approval, ApprovalReceipt) else approval)["receiptHash"],
        mutation_evidence_refs=(),
        output_hash=content_hash({"stdout": result.stdout_summary, "stderr": result.stderr_summary, "exit": result.exit_code}),
    )
    return receipt, result


def run_query(
    plan: QueryPlan,
    *,
    approval: ApprovalReceipt | Mapping[str, Any] | None,
    effect_port: EffectPort,
    observer: WorkspaceObserver,
    argv: tuple[str, ...],
    env: Mapping[str, str],
    cwd: str,
    now: datetime,
    returned_files: list[Mapping[str, Any]],
    index_revision: str,
    index_completeness: str,
    actual_side_effects: str,
    mutation_evidence_refs: list[str] = [],
    test_mode: bool = False,
) -> QueryExecution:
    if not test_mode and getattr(effect_port, "is_test_port", False):
        raise RunnerError("test-effect-port-rejected")
    _approved(plan.document, approval, now=now, test_mode=test_mode)
    if any(not isinstance(item, str) or not item or any(token in item for token in ("\x00", "\r", "\n", ";", "&", "|", "`", "$", "<", ">")) for item in argv):
        raise RunnerError("query-argv-injection")
    if any(not isinstance(key, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", key) is None or not isinstance(value, str) or any(token in value for token in ("\x00", "\r", "\n", ";", "&", "|", "`", "$")) for key, value in env.items()):
        raise RunnerError("query-env-injection")
    if not isinstance(cwd, str) or not cwd or any(token in cwd for token in ("\x00", "\r", "\n", ";", "&", "|", "`", "$")):
        raise RunnerError("query-cwd-injection")
    pre = observer.capture()
    result = effect_port.run(argv, env=env, cwd=cwd, timeout_seconds=plan.document["timeoutSeconds"], output_limit_bytes=plan.document["queryByteBudget"])
    post = observer.capture()
    if pre.identity_hash != post.identity_hash or pre.fingerprint_hash != post.fingerprint_hash:
        declared = set(plan.document.get("mutationTargets", []))
        if not declared or set(post.changed_paths) - declared:
            raise RunnerError("workspace-drift-during-query")
    if plan.document["sideEffects"] == "none" and actual_side_effects != "none":
        raise RunnerError("undeclared-query-side-effect")
    if plan.document["sideEffects"] == "local-write" and actual_side_effects == "unknown":
        raise RunnerError("required-mutation-unobservable")
    receipt = build_query_receipt(
        query_plan_hash=plan.query_plan_hash,
        execution_nonce=plan.document["executionNonce"],
        attempt_ref=plan.document["attemptRef"],
        provider_id=plan.document["providerId"],
        adapter_hash=plan.document["adapterHash"],
        source_identity_hash=plan.document.get("sourceIdentityHash", plan.document["adapterHash"]),
        project_state_receipt_hash=plan.document["projectStateReceiptHash"],
        workspace_fingerprint_hash=plan.document["workspaceFingerprintHash"],
        index_revision=index_revision,
        index_completeness=index_completeness,
        returned_files=returned_files,
        truncated=False,
        pre_fingerprint_hash=pre.fingerprint_hash,
        post_fingerprint_hash=post.fingerprint_hash,
        actual_side_effects=actual_side_effects,
        mutation_evidence_refs=mutation_evidence_refs,
        approval_receipt_ref=(approval.document if isinstance(approval, ApprovalReceipt) else approval)["receiptHash"],
        pre_workspace_identity_hash=pre.identity_hash,
        post_workspace_identity_hash=post.identity_hash,
    )
    return QueryExecution(receipt, result)
