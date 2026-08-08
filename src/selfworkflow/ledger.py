"""Pure Host RunLedger creation, validation, and transition helpers."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Mapping

from jsonschema import Draft202012Validator


class LedgerError(ValueError):
    def __init__(self, code: str = "ledger-invalid") -> None:
        self.code = code
        super().__init__(code)


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
    try:
        stages = [
            {
                "stageId": stage["stageId"],
                "status": "skipped" if stage["applicability"] == "not-applicable" else "pending",
                "attempts": [], "slotResults": [], "gateResults": [], "runtimeSkips": [],
            }
            for stage in plan["stages"]
        ]
        return {
            "schemaVersion": 1, "planHash": plan["planHash"], "requestHash": plan["requestHash"],
            "capabilitySnapshotHash": plan["capabilitySnapshotHash"], "status": "pending", "stages": stages,
        }
    except Exception:
        raise LedgerError("plan-invalid") from None


def validate_ledger(ledger: Mapping[str, object], plan: Mapping[str, object], capability_snapshot_hash: str) -> dict[str, object]:
    reasons: set[str] = set()
    try:
        schema_path = Path(__file__).resolve().parents[2] / "schemas/run-ledger.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        if next(Draft202012Validator(schema).iter_errors(ledger), None) is not None:
            reasons.add("ledger-schema-invalid")
        if ledger.get("planHash") != plan.get("planHash") or ledger.get("requestHash") != plan.get("requestHash"):
            reasons.add("ledger-plan-binding-invalid")
        if ledger.get("capabilitySnapshotHash") != capability_snapshot_hash or plan.get("capabilitySnapshotHash") != capability_snapshot_hash:
            reasons.add("capability-snapshot-changed")
        expected = [stage["stageId"] for stage in plan["stages"]]
        actual = [stage["stageId"] for stage in ledger["stages"]]
        if actual != expected:
            reasons.add("ledger-stage-order-invalid")
        if sum(stage["status"] == "active" for stage in ledger["stages"]) > 1:
            reasons.add("multiple-active-stages")
    except Exception:
        reasons.add("ledger-schema-invalid")
    return {"valid": not reasons, "reasonCodes": sorted(reasons)}


def transition_stage(
    ledger: Mapping[str, object], plan: Mapping[str, object], stage_id: str, target_status: str,
    *, capability_snapshot_hash: str, attempt_ref: str | None = None,
) -> dict[str, object]:
    validation = validate_ledger(ledger, plan, capability_snapshot_hash)
    if not validation["valid"]:
        raise LedgerError(validation["reasonCodes"][0])
    result = deepcopy(dict(ledger))
    stage = _stage(result, stage_id)
    current = stage["status"]
    if target_status == "active":
        if current != "pending" or type(attempt_ref) is not str or not attempt_ref:
            raise LedgerError("ledger-transition-invalid")
        if any(item["status"] == "active" for item in result["stages"]):
            raise LedgerError("multiple-active-stages")
        stage["status"] = "active"
        stage["attempts"].append(attempt_ref)
        result["status"] = "active"
    elif target_status in {"passed", "failed", "paused", "skipped"}:
        if current != "active":
            raise LedgerError("ledger-transition-invalid")
        stage["status"] = target_status
        if target_status == "failed":
            result["status"] = "failed"
        elif target_status == "paused":
            result["status"] = "paused"
        elif all(item["status"] in {"passed", "skipped"} for item in result["stages"]):
            result["status"] = "completed"
        else:
            result["status"] = "active"
    else:
        raise LedgerError("ledger-transition-invalid")
    return result


def record_runtime_skip(ledger: Mapping[str, object], plan: Mapping[str, object], stage_id: str, slot_id: str, evidence_ref: str) -> dict[str, object]:
    plan_stage = _plan_stage(plan, stage_id)
    try:
        slot = next(slot for slot in plan_stage["slots"] if slot["slotId"] == slot_id)
    except StopIteration:
        raise LedgerError("plan-slot-unknown") from None
    if slot["cardinality"] not in {"zero-or-one", "zero-or-many"} or type(evidence_ref) is not str or not evidence_ref:
        raise LedgerError("runtime-skip-not-optional")
    result = deepcopy(dict(ledger))
    _stage(result, stage_id)["runtimeSkips"].append(f"{slot_id}:{evidence_ref}")
    return result


def record_gate_result(ledger: Mapping[str, object], plan: Mapping[str, object], stage_id: str, gate_id: str, result_ref: str) -> dict[str, object]:
    plan_stage = _plan_stage(plan, stage_id)
    gates = {gate for slot in plan_stage["slots"] for gate in slot["gates"]}
    if gate_id not in gates or type(result_ref) is not str or not result_ref:
        raise LedgerError("gate-result-invalid")
    result = deepcopy(dict(ledger))
    _stage(result, stage_id)["gateResults"].append(f"{gate_id}:{result_ref}")
    return result


def failure_owner_for(plan: Mapping[str, object], failed_stage_id: str) -> str:
    return str(_plan_stage(plan, failed_stage_id)["failureOwner"])


def supersede_ledger(ledger: Mapping[str, object], new_plan_hash: str) -> dict[str, object]:
    if type(new_plan_hash) is not str or not new_plan_hash.startswith("sha256:") or new_plan_hash == ledger.get("planHash"):
        raise LedgerError("superseding-plan-invalid")
    result = deepcopy(dict(ledger))
    result["status"] = "superseded"
    result["supersededByPlanHash"] = new_plan_hash
    return result
