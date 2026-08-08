"""Pure, fail-closed Host RunLedger validation and transition helpers."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Mapping

from jsonschema import Draft202012Validator

from selfworkflow.capability_snapshot import normalize_capability_snapshot
from selfworkflow.pipeline import canonical_hash


_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class LedgerError(ValueError):
    def __init__(self, code: str = "ledger-invalid") -> None:
        self.code = code
        super().__init__(code)


def _schema(name: str) -> dict[str, object]:
    root = Path(__file__).resolve().parents[2]
    return json.loads((root / "schemas" / name).read_text(encoding="utf-8"))


def _plan_reasons(plan: Mapping[str, object]) -> set[str]:
    reasons: set[str] = set()
    try:
        if next(Draft202012Validator(_schema("plan-graph.schema.json")).iter_errors(plan), None) is not None:
            reasons.add("plan-schema-invalid")
        material = deepcopy(dict(plan))
        embedded = material.pop("planHash")
        if canonical_hash(material) != embedded:
            reasons.add("plan-hash-invalid")
        if any(stage["applicability"] == "blocked" for stage in plan["stages"]):
            reasons.add("plan-blocked")
    except Exception:
        reasons.add("plan-schema-invalid")
    return reasons


def _stage(ledger: dict[str, object], stage_id: str) -> dict[str, object]:
    try:
        return next(stage for stage in ledger["stages"] if stage["stageId"] == stage_id)
    except (KeyError, StopIteration, TypeError):
        raise LedgerError("ledger-stage-unknown") from None


def _plan_stage(plan: Mapping[str, object], stage_id: str) -> Mapping[str, object]:
    try:
        return next(stage for stage in plan["stages"] if stage["stageId"] == stage_id)
    except (KeyError, StopIteration, TypeError):
        raise LedgerError("plan-stage-unknown") from None


def new_ledger(plan: Mapping[str, object]) -> dict[str, object]:
    reasons = _plan_reasons(plan)
    if reasons:
        raise LedgerError(sorted(reasons)[0])
    return {
        "schemaVersion": 1, "planHash": plan["planHash"], "requestHash": plan["requestHash"],
        "capabilitySnapshotHash": plan["capabilitySnapshotHash"], "status": "pending",
        "stages": [
            {
                "stageId": stage["stageId"],
                "status": "skipped" if stage["applicability"] == "not-applicable" else "pending",
                "attempts": [], "slotResults": [], "gateResults": [], "runtimeSkips": [],
            }
            for stage in plan["stages"]
        ],
    }


def validate_ledger(
    ledger: Mapping[str, object], plan: Mapping[str, object], capability_snapshot: Mapping[str, object]
) -> dict[str, object]:
    reasons = _plan_reasons(plan)
    try:
        if next(Draft202012Validator(_schema("run-ledger.schema.json")).iter_errors(ledger), None) is not None:
            reasons.add("ledger-schema-invalid")
        _, snapshot_hash, _, stale = normalize_capability_snapshot(capability_snapshot)
        if stale:
            reasons.add("capability-snapshot-stale")
        if ledger.get("planHash") != plan.get("planHash") or ledger.get("requestHash") != plan.get("requestHash"):
            reasons.add("ledger-plan-binding-invalid")
        if ledger.get("capabilitySnapshotHash") != snapshot_hash or plan.get("capabilitySnapshotHash") != snapshot_hash:
            reasons.add("capability-snapshot-changed")
        expected = [stage["stageId"] for stage in plan["stages"]]
        actual = [stage["stageId"] for stage in ledger["stages"]]
        if actual != expected:
            reasons.add("ledger-stage-order-invalid")
        active_count = sum(stage["status"] == "active" for stage in ledger["stages"])
        if active_count > 1:
            reasons.add("multiple-active-stages")
        plan_stages = {stage["stageId"]: stage for stage in plan["stages"]}
        for stage in ledger["stages"]:
            plan_stage = plan_stages.get(stage["stageId"])
            if plan_stage is None:
                continue
            if stage["status"] == "passed" and not _requirements_met(stage, plan_stage):
                reasons.add("stage-results-incomplete")
            if (stage["status"] == "skipped") != (plan_stage["applicability"] == "not-applicable"):
                reasons.add("stage-applicability-invalid")
        statuses = [stage["status"] for stage in ledger["stages"]]
        execution_statuses = [
            stage["status"]
            for stage in ledger["stages"]
            if plan_stages[stage["stageId"]]["applicability"] == "applicable"
        ]
        non_prefix = next(
            (index for index, status in enumerate(execution_statuses) if status != "passed"),
            len(execution_statuses),
        )
        if any(status != "pending" for status in execution_statuses[non_prefix + 1:]):
            reasons.add("ledger-stage-sequence-invalid")
        ledger_status = ledger.get("status")
        if ledger_status != "superseded":
            expected_status = (
                "completed" if all(status in {"passed", "skipped"} for status in statuses)
                else "failed" if statuses.count("failed") == 1
                else "paused" if statuses.count("paused") == 1
                else "active" if active_count == 1
                else "pending"
            )
            if ledger_status != expected_status:
                reasons.add("ledger-status-inconsistent")
    except Exception:
        reasons.add("ledger-schema-invalid")
    return {"valid": not reasons, "reasonCodes": sorted(reasons)}


def _requirements_met(ledger_stage: Mapping[str, object], plan_stage: Mapping[str, object]) -> bool:
    slot_modules = {
        module_id
        for slot in plan_stage["slots"]
        for module_id in slot["selectedModules"]
        if module_id not in slot["gates"]
    }
    completed_modules = {item.split(":", 1)[0] for item in ledger_stage["slotResults"]}
    required_gates = {gate for slot in plan_stage["slots"] for gate in slot["gates"]}
    passed_gates = {
        parts[0]
        for item in ledger_stage["gateResults"]
        if len(parts := item.split(":", 2)) == 3 and parts[1] == "passed"
    }
    return slot_modules <= completed_modules and required_gates <= passed_gates


def transition_stage(
    ledger: Mapping[str, object], plan: Mapping[str, object], stage_id: str, target_status: str,
    *, capability_snapshot: Mapping[str, object], attempt_ref: str | None = None,
) -> dict[str, object]:
    validation = validate_ledger(ledger, plan, capability_snapshot)
    if not validation["valid"]:
        raise LedgerError(validation["reasonCodes"][0])
    result = deepcopy(dict(ledger))
    stage = _stage(result, stage_id)
    plan_stage = _plan_stage(plan, stage_id)
    index = next(i for i, item in enumerate(result["stages"]) if item["stageId"] == stage_id)
    if target_status == "active":
        if (
            stage["status"] != "pending"
            or plan_stage["applicability"] != "applicable"
            or type(attempt_ref) is not str
            or _REFERENCE.fullmatch(attempt_ref) is None
            or any(item["status"] not in {"passed", "skipped"} for item in result["stages"][:index])
            or any(item["status"] == "active" for item in result["stages"])
        ):
            raise LedgerError("ledger-transition-invalid")
        stage["status"] = "active"
        stage["attempts"].append(attempt_ref)
        result["status"] = "active"
        return result
    if target_status not in {"passed", "failed", "paused"} or stage["status"] != "active":
        raise LedgerError("ledger-transition-invalid")
    if target_status == "passed" and not _requirements_met(stage, plan_stage):
        raise LedgerError("stage-results-incomplete")
    stage["status"] = target_status
    if target_status == "failed":
        result["status"] = "failed"
    elif target_status == "paused":
        result["status"] = "paused"
    elif all(item["status"] in {"passed", "skipped"} for item in result["stages"]):
        result["status"] = "completed"
    else:
        result["status"] = "pending"
    return result


def _record(ledger, plan, stage_id, collection, value):
    if _plan_reasons(plan):
        raise LedgerError("plan-invalid")
    result = deepcopy(dict(ledger))
    if result.get("planHash") != plan.get("planHash"):
        raise LedgerError("ledger-plan-binding-invalid")
    stage = _stage(result, stage_id)
    if stage["status"] != "active":
        raise LedgerError("ledger-stage-not-active")
    if value in stage[collection]:
        raise LedgerError("ledger-result-duplicate")
    stage[collection].append(value)
    return result


def record_slot_result(ledger, plan, stage_id: str, module_id: str, result_ref: str):
    plan_stage = _plan_stage(plan, stage_id)
    modules = {module for slot in plan_stage["slots"] for module in slot["selectedModules"] if module not in slot["gates"]}
    if module_id not in modules or _REFERENCE.fullmatch(result_ref or "") is None:
        raise LedgerError("slot-result-invalid")
    return _record(ledger, plan, stage_id, "slotResults", f"{module_id}:{result_ref}")


def record_runtime_skip(ledger, plan, stage_id: str, slot_id: str, evidence_ref: str):
    plan_stage = _plan_stage(plan, stage_id)
    try:
        slot = next(slot for slot in plan_stage["slots"] if slot["slotId"] == slot_id)
    except StopIteration:
        raise LedgerError("plan-slot-unknown") from None
    if slot["cardinality"] not in {"zero-or-one", "zero-or-many"} or _REFERENCE.fullmatch(evidence_ref or "") is None:
        raise LedgerError("runtime-skip-not-optional")
    return _record(ledger, plan, stage_id, "runtimeSkips", f"{slot_id}:{evidence_ref}")


def record_gate_result(ledger, plan, stage_id: str, gate_id: str, result_ref: str, *, outcome: str = "passed"):
    plan_stage = _plan_stage(plan, stage_id)
    gates = {gate for slot in plan_stage["slots"] for gate in slot["gates"]}
    if gate_id not in gates or outcome not in {"passed", "failed", "paused"} or _REFERENCE.fullmatch(result_ref or "") is None:
        raise LedgerError("gate-result-invalid")
    return _record(ledger, plan, stage_id, "gateResults", f"{gate_id}:{outcome}:{result_ref}")


def failure_owner_for(plan: Mapping[str, object], failed_stage_id: str) -> str:
    if _plan_reasons(plan):
        raise LedgerError("plan-invalid")
    return str(_plan_stage(plan, failed_stage_id)["failureOwner"])


def supersede_ledger(ledger: Mapping[str, object], new_plan_hash: str) -> dict[str, object]:
    if type(new_plan_hash) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", new_plan_hash) or new_plan_hash == ledger.get("planHash"):
        raise LedgerError("superseding-plan-invalid")
    result = deepcopy(dict(ledger))
    result["status"] = "superseded"
    result["supersededByPlanHash"] = new_plan_hash
    return result
