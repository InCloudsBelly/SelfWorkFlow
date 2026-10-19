"""Pure V3 RunLedger construction and state transitions.

The ledger is deliberately a value object: every operation validates its input,
deep-copies it, and returns a new document.  Persistence and process execution
remain outside this module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
import re
from typing import Any

from selfworkflow.v3.contracts import ContractError, validate_run_ledger
from selfworkflow.v3.plan_graph import PlanGraphArtifact
from selfworkflow.v3.tea_adapter import is_tea_module_id, validate_tea_receipt


_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class LedgerError(ValueError):
    """Stable, fail-closed V3 ledger error."""

    def __init__(self, reason: str = "v3-ledger-invalid") -> None:
        self.reason = reason
        super().__init__(reason)


def _plan_document(plan: PlanGraphArtifact | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(plan, PlanGraphArtifact):
        try:
            document, _ = plan._trusted_snapshot()
        except Exception as error:
            raise LedgerError(getattr(error, "reason", "v3-plan-invalid")) from None
        return document
    if type(plan) is not dict:
        raise LedgerError("v3-plan-not-typed")
    return copy.deepcopy(plan)


def _receipt_document(receipt: Any) -> dict[str, Any]:
    if hasattr(receipt, "as_dict") and callable(receipt.as_dict):
        receipt = receipt.as_dict()
    if type(receipt) is not dict:
        raise LedgerError("v3-selection-receipt-not-typed")
    return copy.deepcopy(receipt)


def _hash(value: object, reason: str) -> str:
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise LedgerError(reason)
    return value


def _id(value: object, reason: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise LedgerError(reason)
    return value


def _hashes(value: object, reason: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise LedgerError(reason)
    items = [_hash(item, reason) for item in value]
    if len(items) != len(set(items)):
        raise LedgerError(reason)
    return sorted(items)


def _validate_or_raise(
    ledger: Mapping[str, Any],
    plan: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]] = (),
    *,
    successor: str | None = None,
    tea_runtime_root: str | None = None,
) -> None:
    try:
        validate_run_ledger(
            dict(ledger), dict(plan), tuple(dict(item) for item in receipts),
            expected_successor_plan_hash=successor,
            tea_runtime_root=tea_runtime_root,
        )
    except ContractError as error:
        raise LedgerError(error.reason) from None


def validate_ledger(
    ledger: Mapping[str, Any],
    plan: PlanGraphArtifact | Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]] = (),
    *,
    expected_successor_plan_hash: str | None = None,
) -> dict[str, Any]:
    """Return a machine-readable validation result without changing state."""

    try:
        document = _plan_document(plan)
        receipt_documents = tuple(_receipt_document(item) for item in receipts)
        _validate_or_raise(
            ledger, document, receipt_documents,
            successor=expected_successor_plan_hash,
        )
    except (LedgerError, TypeError, ValueError) as error:
        return {"valid": False, "reasonCodes": [getattr(error, "reason", str(error))]}
    return {"valid": True, "reasonCodes": []}


def assert_valid_ledger(
    ledger: Mapping[str, Any],
    plan: PlanGraphArtifact | Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]] = (),
    *,
    expected_successor_plan_hash: str | None = None,
) -> None:
    document = _plan_document(plan)
    receipt_documents = tuple(_receipt_document(item) for item in receipts)
    _validate_or_raise(
        ledger, document, receipt_documents,
        successor=expected_successor_plan_hash,
    )


def new_ledger(plan: PlanGraphArtifact | Mapping[str, Any]) -> dict[str, Any]:
    """Issue an empty V3 ledger bound to one immutable PlanGraph."""

    document = _plan_document(plan)
    stages = []
    for stage in document["stages"]:
        stages.append({
            "stageId": stage["stageId"],
            "status": "skipped" if stage["applicability"] == "not-applicable" else "pending",
            "attempts": [],
            "slotResults": [],
            "gateResults": [],
            "runtimeSkips": [],
            "selectionReceiptRefs": [],
            "teaReceipts": [],
            "teaReceiptHashes": [],
            "reviewAggregateHashes": [],
            "coverageResultHashes": [],
            "artifactHashes": [],
        })
    result = {
        "schemaVersion": 3,
        "planHash": document["planHash"],
        "requestHash": document["requestHash"],
        "capabilitySnapshotHash": document["capabilitySnapshotHash"],
        "status": "completed" if not any(
            item["status"] == "pending" for item in stages
        ) else "pending",
        "stages": stages,
    }
    try:
        _validate_or_raise(result, document)
    except LedgerError:
        # An all-not-applicable plan is still a valid pending ledger; the
        # contract intentionally permits the host to report completion later.
        raise
    return result


def _stage(ledger: dict[str, Any], stage_id: str) -> dict[str, Any]:
    for stage in ledger["stages"]:
        if stage["stageId"] == stage_id:
            return stage
    raise LedgerError("v3-stage-unknown")


def _plan_stage(plan: Mapping[str, Any], stage_id: str) -> Mapping[str, Any]:
    for stage in plan["stages"]:
        if stage["stageId"] == stage_id:
            return stage
    raise LedgerError("v3-stage-unknown")


def _copy_and_validate_active(
    ledger: Mapping[str, Any], plan: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], dict[str, Any]]:
    result = copy.deepcopy(dict(ledger))
    _validate_or_raise(result, plan, receipts)
    if result["status"] == "superseded":
        raise LedgerError("v3-ledger-superseded")
    active = [stage for stage in result["stages"] if stage["status"] == "active"]
    return result, (active[0] if active else {})


def start_stage(
    ledger: Mapping[str, Any],
    plan: PlanGraphArtifact | Mapping[str, Any],
    stage_id: str,
    attempt_ref: str,
    started_at: str,
    receipts: Sequence[Any] = (),
    *,
    input_artifact_hashes: Sequence[str] = (),
) -> dict[str, Any]:
    """Activate exactly the next applicable stage."""

    plan_document = _plan_document(plan)
    receipt_documents = tuple(_receipt_document(item) for item in receipts)
    result, _ = _copy_and_validate_active(ledger, plan_document, receipt_documents)
    stage = _stage(result, stage_id)
    plan_stage = _plan_stage(plan_document, stage_id)
    if (
        stage["status"] not in {"pending", "failed", "paused"}
        or plan_stage["applicability"] != "applicable"
    ):
        raise LedgerError("v3-stage-transition-invalid")
    index = next(i for i, item in enumerate(result["stages"]) if item["stageId"] == stage_id)
    for previous, previous_plan in zip(
        result["stages"][:index], plan_document["stages"][:index], strict=True,
    ):
        if previous_plan["applicability"] == "applicable" and previous["status"] != "passed":
            raise LedgerError("v3-stage-predecessor-incomplete")
    if any(item["status"] == "active" for item in result["stages"]):
        raise LedgerError("v3-stage-active-exists")
    _id(attempt_ref, "v3-attempt-invalid")
    registered_inputs = _hashes(
        input_artifact_hashes, "v3-attempt-input-artifacts-invalid",
    )
    if any(
        attempt["attemptRef"] == attempt_ref
        for item in result["stages"] for attempt in item["attempts"]
    ):
        raise LedgerError("v3-attempt-duplicate")
    stage["status"] = "active"
    previous_attempt = stage["attempts"][-1] if stage["attempts"] else None
    stage["attempts"].append({
        "attemptRef": attempt_ref,
        "ordinal": len(stage["attempts"]) + 1,
        "previousAttemptRef": (
            previous_attempt["attemptRef"] if previous_attempt else None
        ),
        "startedAt": started_at,
        "inputArtifactHashes": registered_inputs,
    })
    stage["artifactHashes"] = sorted(set(
        stage["artifactHashes"] + registered_inputs
    ))
    result["status"] = "active"
    _validate_or_raise(result, plan_document, receipt_documents)
    return result


def apply_stage_result(
    ledger: Mapping[str, Any],
    plan: PlanGraphArtifact | Mapping[str, Any],
    stage_result: Mapping[str, Any],
    receipts: Sequence[Any] = (),
    *,
    tea_runtime_root: str | None = None,
) -> dict[str, Any]:
    """Commit one typed stage result as a new ledger value."""

    plan_document = _plan_document(plan)
    supplied_receipts = list(receipts)
    new_receipts: list[Any] = []
    if type(stage_result) is dict and "selectionReceipts" in stage_result:
        if type(stage_result["selectionReceipts"]) is not list:
            raise LedgerError("v3-stage-result-receipts-invalid")
        new_receipts = list(stage_result["selectionReceipts"])
        supplied_receipts.extend(new_receipts)
    receipt_documents = tuple(_receipt_document(item) for item in supplied_receipts)
    new_receipt_documents = tuple(_receipt_document(item) for item in new_receipts)
    result, active = _copy_and_validate_active(ledger, plan_document, receipt_documents)
    if type(stage_result) is not dict or stage_result.get("schemaVersion") != 3:
        raise LedgerError("v3-stage-result-schema-invalid")
    required = {
        "schemaVersion", "planHash", "stageId", "attemptRef",
        "capabilitySnapshotHash", "inputArtifactHashes", "outputArtifactHashes",
        "slotResults", "gateResults", "runtimeSkips", "artifactHashes", "status",
        "completedAt",
    }
    allowed = required | {"selectionReceipts", "teaReceipts"}
    if set(stage_result) - allowed:
        raise LedgerError("v3-stage-result-unknown-field")
    if stage_result["planHash"] != plan_document["planHash"]:
        raise LedgerError("v3-stage-result-plan-binding-invalid")
    if stage_result["capabilitySnapshotHash"] != plan_document["capabilitySnapshotHash"]:
        raise LedgerError("v3-stage-result-capability-binding-invalid")
    if stage_result["status"] not in {"passed", "failed", "paused"}:
        raise LedgerError("v3-stage-result-status-invalid")
    if not active or active["stageId"] != stage_result["stageId"]:
        raise LedgerError("v3-stage-result-stage-not-active")
    current_attempt = active["attempts"][-1]
    if stage_result["attemptRef"] != current_attempt["attemptRef"]:
        raise LedgerError("v3-stage-result-attempt-stale")
    if not isinstance(stage_result["completedAt"], str):
        raise LedgerError("v3-stage-result-time-invalid")

    input_hashes = _hashes(
        stage_result["inputArtifactHashes"], "v3-stage-result-hash-list-invalid",
    )
    output_hashes = _hashes(
        stage_result["outputArtifactHashes"], "v3-stage-result-hash-list-invalid",
    )
    artifact_hashes = _hashes(
        stage_result["artifactHashes"], "v3-stage-result-hash-list-invalid",
    )
    registered_inputs = sorted(current_attempt.get("inputArtifactHashes", []))
    if input_hashes != registered_inputs:
        raise LedgerError("v3-stage-result-input-binding-invalid")
    if artifact_hashes != sorted(set(input_hashes + output_hashes)):
        raise LedgerError("v3-stage-result-artifact-binding-invalid")
    declared_artifacts = set(input_hashes + output_hashes)

    plan_stage = _plan_stage(plan_document, active["stageId"])
    slots = {slot["slotId"]: slot for slot in plan_stage["slots"]}
    for receipt in receipt_documents:
        from selfworkflow.v3.contracts import validate_selection_receipt
        try:
            validate_selection_receipt(receipt, plan_document)
        except ContractError as error:
            raise LedgerError(error.reason) from None
    runtime_selected: dict[str, set[str]] = {}
    for receipt in new_receipt_documents:
        if (
            receipt["stageId"] != active["stageId"]
            or receipt["attemptRef"] != stage_result["attemptRef"]
        ):
            raise LedgerError("v3-stage-result-receipt-binding-invalid")
        runtime_selected[receipt["slotId"]] = set(receipt["selectedModuleIds"])
    slot_results = copy.deepcopy(stage_result["slotResults"])
    gate_results = copy.deepcopy(stage_result["gateResults"])
    runtime_skips = copy.deepcopy(stage_result["runtimeSkips"])
    tea_receipts = stage_result.get("teaReceipts", [])
    if type(tea_receipts) is not list:
        raise LedgerError("v3-stage-result-tea-receipts-invalid")
    if tea_receipts and tea_runtime_root is None:
        raise LedgerError("v3-tea-runtime-reference-required")
    if not all(type(item) is dict for item in slot_results + gate_results + runtime_skips):
        raise LedgerError("v3-stage-result-artifact-invalid")
    seen_slot_results: set[tuple[str, str]] = set()
    for item in slot_results:
        if set(item) != {"slotId", "moduleId", "artifactHash"}:
            raise LedgerError("v3-stage-result-slot-result-invalid")
        _id(item["slotId"], "v3-stage-result-slot-invalid")
        _id(item["moduleId"], "v3-stage-result-module-invalid")
        _hash(item["artifactHash"], "v3-stage-result-artifact-invalid")
        if item["artifactHash"] not in declared_artifacts:
            raise LedgerError("v3-stage-result-artifact-unbound")
        identity = (item["slotId"], item["moduleId"])
        if identity in seen_slot_results:
            raise LedgerError("v3-stage-result-slot-result-duplicate")
        seen_slot_results.add(identity)
        slot = slots.get(item["slotId"])
        allowed = (
            set(slot["selectedModules"]) if slot is not None and slot["selectionMode"] == "static"
            else runtime_selected.get(item["slotId"], set())
        )
        if slot is None or item["moduleId"] not in allowed:
            raise LedgerError("v3-stage-result-module-not-selected")
    tea_receipt_hashes: list[str] = []
    tea_receipt_keys: set[tuple[str, str]] = set()
    slot_result_by_key = {
        (item["slotId"], item["moduleId"]): item
        for item in slot_results
    }
    for raw_receipt in tea_receipts:
        if type(raw_receipt) is not dict:
            raise LedgerError("v3-stage-result-tea-receipt-invalid")
        key = (raw_receipt.get("slotId"), raw_receipt.get("moduleId"))
        slot_result = slot_result_by_key.get(key)
        if slot_result is None:
            raise LedgerError("v3-stage-result-tea-receipt-binding-invalid")
        try:
            receipt = validate_tea_receipt(
                raw_receipt,
                plan_hash=plan_document["planHash"],
                stage_id=active["stageId"],
                attempt_ref=stage_result["attemptRef"],
                slot_id=slot_result["slotId"],
                module_id=slot_result["moduleId"],
                output_hash=slot_result["artifactHash"],
                runtime_root=tea_runtime_root,
            )
        except Exception as error:
            raise LedgerError(getattr(error, "reason", "v3-stage-result-tea-receipt-invalid")) from None
        receipt_key = (receipt["slotId"], receipt["moduleId"])
        if receipt_key in tea_receipt_keys:
            raise LedgerError("v3-stage-result-tea-receipt-duplicate")
        tea_receipt_keys.add(receipt_key)
        tea_receipt_hashes.append(receipt["receiptHash"])
    if stage_result["status"] == "passed":
        required_tea_keys = {
            (slot["slotId"], module_id)
            for slot in slots.values()
            if slot["selectionMode"] == "static"
            for module_id in slot["selectedModules"]
            if is_tea_module_id(module_id)
        }
        if required_tea_keys - tea_receipt_keys:
            raise LedgerError("v3-stage-result-tea-receipt-missing")
    seen_gate_results: set[str] = set()
    for item in gate_results:
        if set(item) != {"gateId", "outcome", "artifactHash"}:
            raise LedgerError("v3-stage-result-gate-result-invalid")
        _id(item["gateId"], "v3-stage-result-gate-invalid")
        if item["outcome"] not in {"passed", "failed", "paused"}:
            raise LedgerError("v3-stage-result-gate-outcome-invalid")
        _hash(item["artifactHash"], "v3-stage-result-artifact-invalid")
        if item["artifactHash"] not in declared_artifacts:
            raise LedgerError("v3-stage-result-artifact-unbound")
        if item["gateId"] in seen_gate_results:
            raise LedgerError("v3-stage-result-gate-result-duplicate")
        seen_gate_results.add(item["gateId"])
    for item in runtime_skips:
        if set(item) != {"slotId", "reasonCode", "evidenceHash"}:
            raise LedgerError("v3-stage-result-runtime-skip-invalid")
        slot = slots.get(item["slotId"])
        if slot is None or slot["cardinality"] not in {"zero-or-one", "zero-or-many"}:
            raise LedgerError("v3-stage-result-runtime-skip-invalid")
        _id(item["slotId"], "v3-stage-result-slot-invalid")
        _id(item["reasonCode"], "v3-stage-result-reason-invalid")
        _hash(item["evidenceHash"], "v3-stage-result-evidence-invalid")

    receipt_refs = [
        {"attemptRef": stage_result["attemptRef"], "receiptHash": item["receiptHash"]}
        for item in new_receipt_documents
    ]
    target = _stage(result, active["stageId"])
    target["status"] = stage_result["status"]
    target["attempts"][-1]["completedAt"] = stage_result["completedAt"]
    target["slotResults"].extend([
        {"attemptRef": stage_result["attemptRef"], **item}
        for item in slot_results
    ])
    target["gateResults"].extend([
        {"attemptRef": stage_result["attemptRef"], **item}
        for item in gate_results
    ])
    target["runtimeSkips"].extend([
        {"attemptRef": stage_result["attemptRef"], **item}
        for item in runtime_skips
    ])
    target.setdefault("teaReceipts", []).extend(copy.deepcopy(tea_receipts))
    target["selectionReceiptRefs"].extend(receipt_refs)
    target["teaReceiptHashes"] = sorted(set(
        target.get("teaReceiptHashes", []) + tea_receipt_hashes
    ))
    target["artifactHashes"] = sorted(set(
        target["artifactHashes"] + artifact_hashes
    ))
    if stage_result["status"] == "failed":
        result["status"] = "failed"
    elif stage_result["status"] == "paused":
        result["status"] = "paused"
    elif all(item["status"] in {"passed", "skipped"} for item in result["stages"]):
        result["status"] = "completed"
    else:
        result["status"] = "pending"
    _validate_or_raise(
        result, plan_document, receipt_documents,
        tea_runtime_root=tea_runtime_root,
    )
    return result


def supersede_ledger(
    ledger: Mapping[str, Any],
    plan: PlanGraphArtifact | Mapping[str, Any],
    new_plan_hash: str,
    superseded_at: str,
    receipts: Sequence[Any] = (),
) -> dict[str, Any]:
    """Close any active attempt and bind the old ledger to a successor plan."""

    plan_document = _plan_document(plan)
    receipt_documents = tuple(_receipt_document(item) for item in receipts)
    result, _ = _copy_and_validate_active(ledger, plan_document, receipt_documents)
    _hash(new_plan_hash, "v3-superseding-plan-invalid")
    if new_plan_hash == plan_document["planHash"]:
        raise LedgerError("v3-superseding-plan-invalid")
    for stage in result["stages"]:
        if stage["status"] == "active":
            attempt = stage["attempts"][-1]
            if not isinstance(superseded_at, str):
                raise LedgerError("v3-superseding-time-invalid")
            attempt["completedAt"] = superseded_at
            stage["status"] = "paused"
    result["status"] = "superseded"
    result["supersededByPlanHash"] = new_plan_hash
    _validate_or_raise(
        result, plan_document, receipt_documents, successor=new_plan_hash,
    )
    return result


# Explicit aliases make the host boundary discoverable without duplicating state.
create_ledger = new_ledger
activate_stage = start_stage
record_stage_result = apply_stage_result
