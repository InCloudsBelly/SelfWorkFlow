"""Pure, fail-closed Host RunLedger v2 validation and transition helpers."""

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


def _attempt_ref(stage: Mapping[str, object]) -> str:
    try:
        return str(stage["attempts"][-1]["attemptRef"])
    except (KeyError, IndexError, TypeError):
        raise LedgerError("ledger-attempt-missing") from None


def _new_attempt(stage: Mapping[str, object], attempt_ref: str) -> dict[str, object]:
    attempts = stage["attempts"]
    return {
        "attemptRef": attempt_ref,
        "ordinal": len(attempts) + 1,
        "previousAttemptRef": attempts[-1]["attemptRef"] if attempts else None,
    }


def new_ledger(plan: Mapping[str, object]) -> dict[str, object]:
    reasons = _plan_reasons(plan)
    if reasons:
        raise LedgerError(sorted(reasons)[0])
    return {
        "schemaVersion": 2, "planHash": plan["planHash"], "requestHash": plan["requestHash"],
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


def _result_binding_reasons(
    ledger_stage: Mapping[str, object], plan_stage: Mapping[str, object]
) -> set[str]:
    reasons: set[str] = set()
    attempts = ledger_stage["attempts"]
    refs = [attempt["attemptRef"] for attempt in attempts]
    for index, attempt in enumerate(attempts):
        if (
            attempt["ordinal"] != index + 1
            or attempt["previousAttemptRef"] != (refs[index - 1] if index else None)
        ):
            reasons.add("ledger-attempt-chain-invalid")
    allowed = set(refs)
    modules = {
        module for slot in plan_stage["slots"] for module in slot["selectedModules"]
        if module not in slot["gates"]
    }
    gates = {gate for slot in plan_stage["slots"] for gate in slot["gates"]}
    optional_slots = {
        slot["slotId"] for slot in plan_stage["slots"]
        if slot["cardinality"] in {"zero-or-one", "zero-or-many"}
    }
    seen: set[tuple[str, str, str]] = set()
    for collection, identity_key, valid_ids in (
        ("slotResults", "moduleId", modules),
        ("gateResults", "gateId", gates),
        ("runtimeSkips", "slotId", optional_slots),
    ):
        for item in ledger_stage[collection]:
            if item["attemptRef"] not in allowed or item[identity_key] not in valid_ids:
                reasons.add("ledger-result-binding-invalid")
            key = (collection, item["attemptRef"], item[identity_key])
            if key in seen:
                reasons.add("ledger-result-duplicate")
            seen.add(key)
    if ledger_stage["status"] in {"active", "passed", "failed", "paused"} and not refs:
        reasons.add("ledger-attempt-missing")
    if ledger_stage["status"] in {"pending", "skipped"} and (
        refs or ledger_stage["slotResults"] or ledger_stage["gateResults"] or ledger_stage["runtimeSkips"]
    ):
        reasons.add("ledger-attempt-state-invalid")
    return reasons


def validate_ledger(
    ledger: Mapping[str, object], plan: Mapping[str, object], capability_snapshot: Mapping[str, object]
) -> dict[str, object]:
    reasons = _plan_reasons(plan)
    try:
        if ledger.get("schemaVersion") != 2:
            reasons.add("ledger-schema-version-unsupported")
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
        all_attempt_refs: list[str] = []
        for stage in ledger["stages"]:
            plan_stage = plan_stages.get(stage["stageId"])
            if plan_stage is None:
                continue
            reasons.update(_result_binding_reasons(stage, plan_stage))
            all_attempt_refs.extend(item["attemptRef"] for item in stage["attempts"])
            if stage["status"] == "passed" and not _requirements_met(stage, plan_stage):
                reasons.add("stage-results-incomplete")
            if (stage["status"] == "skipped") != (plan_stage["applicability"] == "not-applicable"):
                reasons.add("stage-applicability-invalid")
        if len(all_attempt_refs) != len(set(all_attempt_refs)):
            reasons.add("ledger-attempt-duplicate")
        statuses = [stage["status"] for stage in ledger["stages"]]
        execution_statuses = [
            stage["status"] for stage in ledger["stages"]
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
    try:
        current = _attempt_ref(ledger_stage)
    except LedgerError:
        return False
    slot_modules = {
        module_id for slot in plan_stage["slots"] for module_id in slot["selectedModules"]
        if module_id not in slot["gates"]
    }
    completed_modules = {
        item["moduleId"] for item in ledger_stage["slotResults"]
        if item["attemptRef"] == current
    }
    required_gates = {gate for slot in plan_stage["slots"] for gate in slot["gates"]}
    passed_gates = {
        item["gateId"] for item in ledger_stage["gateResults"]
        if item["attemptRef"] == current and item["outcome"] == "passed"
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
        existing_refs = {
            attempt["attemptRef"] for item in result["stages"] for attempt in item["attempts"]
        }
        if (
            stage["status"] != "pending" or plan_stage["applicability"] != "applicable"
            or type(attempt_ref) is not str or _REFERENCE.fullmatch(attempt_ref) is None
            or attempt_ref in existing_refs
            or any(item["status"] not in {"passed", "skipped"} for item in result["stages"][:index])
            or any(item["status"] == "active" for item in result["stages"])
        ):
            raise LedgerError("ledger-transition-invalid")
        stage["status"] = "active"
        stage["attempts"].append(_new_attempt(stage, attempt_ref))
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


def record_stage_attempt(
    ledger: Mapping[str, object], plan: Mapping[str, object], stage_id: str,
    attempt_ref: str, *, capability_snapshot: Mapping[str, object],
) -> dict[str, object]:
    validation = validate_ledger(ledger, plan, capability_snapshot)
    if not validation["valid"]:
        raise LedgerError(validation["reasonCodes"][0])
    result = deepcopy(dict(ledger))
    stage = _stage(result, stage_id)
    all_refs = {attempt["attemptRef"] for item in result["stages"] for attempt in item["attempts"]}
    if (
        stage["status"] != "active" or type(attempt_ref) is not str
        or _REFERENCE.fullmatch(attempt_ref) is None or attempt_ref in all_refs
    ):
        raise LedgerError("ledger-attempt-invalid")
    stage["attempts"].append(_new_attempt(stage, attempt_ref))
    return result


def _record(ledger, plan, stage_id, collection, value, identity_key):
    if _plan_reasons(plan):
        raise LedgerError("plan-invalid")
    result = deepcopy(dict(ledger))
    if result.get("schemaVersion") != 2:
        raise LedgerError("ledger-schema-version-unsupported")
    if result.get("planHash") != plan.get("planHash"):
        raise LedgerError("ledger-plan-binding-invalid")
    stage = _stage(result, stage_id)
    if stage["status"] != "active":
        raise LedgerError("ledger-stage-not-active")
    current = _attempt_ref(stage)
    value = {"attemptRef": current, **value}
    if any(
        item["attemptRef"] == current and item[identity_key] == value[identity_key]
        for item in stage[collection]
    ):
        raise LedgerError("ledger-result-duplicate")
    stage[collection].append(value)
    return result


def record_slot_result(ledger, plan, stage_id: str, module_id: str, result_ref: str):
    plan_stage = _plan_stage(plan, stage_id)
    modules = {module for slot in plan_stage["slots"] for module in slot["selectedModules"] if module not in slot["gates"]}
    if module_id not in modules or _REFERENCE.fullmatch(result_ref or "") is None:
        raise LedgerError("slot-result-invalid")
    return _record(ledger, plan, stage_id, "slotResults", {"moduleId": module_id, "resultRef": result_ref}, "moduleId")


def record_runtime_skip(ledger, plan, stage_id: str, slot_id: str, evidence_ref: str):
    plan_stage = _plan_stage(plan, stage_id)
    try:
        slot = next(slot for slot in plan_stage["slots"] if slot["slotId"] == slot_id)
    except StopIteration:
        raise LedgerError("plan-slot-unknown") from None
    if slot["cardinality"] not in {"zero-or-one", "zero-or-many"} or _REFERENCE.fullmatch(evidence_ref or "") is None:
        raise LedgerError("runtime-skip-not-optional")
    return _record(ledger, plan, stage_id, "runtimeSkips", {"slotId": slot_id, "evidenceRef": evidence_ref}, "slotId")


def record_gate_result(ledger, plan, stage_id: str, gate_id: str, result_ref: str, *, outcome: str = "passed"):
    plan_stage = _plan_stage(plan, stage_id)
    gates = {gate for slot in plan_stage["slots"] for gate in slot["gates"]}
    if gate_id not in gates or outcome not in {"passed", "failed", "paused"} or _REFERENCE.fullmatch(result_ref or "") is None:
        raise LedgerError("gate-result-invalid")
    return _record(ledger, plan, stage_id, "gateResults", {"gateId": gate_id, "outcome": outcome, "resultRef": result_ref}, "gateId")


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
