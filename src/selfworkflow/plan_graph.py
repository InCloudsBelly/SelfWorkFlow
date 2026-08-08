"""Pure construction of immutable modular PlanGraph values."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

import yaml

from selfworkflow.pipeline import canonical_hash, load_pipeline
from selfworkflow.router import ModuleRouteRequest, route_modules
from selfworkflow.classifier import workflow_strength as base_workflow_strength


_LEVEL = {"Light": 0, "Full": 1, "Deep": 2}
_CLASS_LEVEL = {"C0": 0, "C1": 1, "C2": 2, "C3": 3, "R0": 0, "R1": 1, "R2": 2, "R3": 3}


def workflow_strength(complexity: str, risk: str, project_minimum: str = "Light") -> str:
    base = base_workflow_strength(complexity, risk)
    return max((base, project_minimum), key=lambda item: _LEVEL[item])


def _condition(value: object, request: Mapping[str, object], states: Mapping[str, str]) -> bool:
    if value is None:
        return True
    operator, operand = next(iter(value.items()))
    if operator == "all":
        return all(_condition(item, request, states) for item in operand)
    if operator == "any":
        return any(_condition(item, request, states) for item in operand)
    if operator == "not":
        return not _condition(operand, request, states)
    field, expected = operand
    actual = states if field == "capabilityStates" else request[field]
    if operator == "eq":
        return actual == expected
    if operator == "contains":
        return expected in actual
    if operator == "gte":
        return _CLASS_LEVEL.get(actual, actual) >= _CLASS_LEVEL.get(expected, expected)
    raise ValueError("condition-invalid")


def build_plan_graph(
    catalog_content: bytes | str | Mapping[str, object], request: Mapping[str, object],
    request_hash: str, capability_snapshot_hash: str, capability_states: Mapping[str, str],
    repository_root: Path,
) -> tuple[dict[str, object], tuple[str, ...]]:
    pipeline = load_pipeline(repository_root / "workflow/pipeline.yaml", repository_root / "schemas/pipeline.schema.json")
    envelope = json.loads(catalog_content.decode("utf-8") if isinstance(catalog_content, bytes) else catalog_content) if not isinstance(catalog_content, Mapping) else dict(catalog_content)
    strength = workflow_strength(request["complexity"], request["risk"], request["projectMinimums"]["strength"])
    stages = []
    reasons: set[str] = set()
    for stage in pipeline.document["stages"]:
        slots = []
        for slot in stage["slots"]:
            applicable = _condition(slot.get("condition"), request, capability_states)
            if not applicable:
                slots.append({"slotId": slot["id"], "cardinality": slot["cardinality"], "applicability": "not-applicable", "selectedModules": [], "gates": []})
                continue
            route = route_modules(
                envelope,
                ModuleRouteRequest(
                    slot_id=slot["id"], cardinality=slot["cardinality"], operation_type=request["operationType"],
                    strength=strength, write_task=request["writeTask"], explicit_module_ids=tuple(request["explicitModuleIds"]),
                    project_default_module_ids=tuple(request["projectDefaultModuleIds"]), capability_states=capability_states,
                ),
            )
            reasons.update(route.reason_codes)
            slots.append({
                "slotId": slot["id"], "cardinality": slot["cardinality"],
                "applicability": "blocked" if route.status == "paused" else "applicable",
                "selectedModules": list(route.selected_modules),
                "gates": list(route.selected_modules) if slot["cardinality"] == "gate" else [],
            })
        stage_applicability = "blocked" if any(slot["applicability"] == "blocked" for slot in slots) else "applicable" if any(slot["applicability"] == "applicable" for slot in slots) else "not-applicable"
        stages.append({"stageId": stage["id"], "failureOwner": stage["failureOwner"], "applicability": stage_applicability, "slots": slots})
    module_by_id = {
        module["id"]: module for module in envelope["catalog"].get("modules", [])
    }
    selected_ids = {
        module_id
        for stage in stages
        for slot in stage["slots"]
        for module_id in slot["selectedModules"]
    }
    dependency_blocked = {
        module_id
        for module_id in selected_ids
        if any(
            dependency not in selected_ids
            for dependency in module_by_id[module_id]["dependencies"]
        )
    }
    conflict_blocked = {
        module_id
        for module_id in selected_ids
        if set(module_by_id[module_id]["conflicts"]) & selected_ids
    }
    if dependency_blocked:
        reasons.add("module-dependency-unavailable")
    if conflict_blocked:
        reasons.add("module-conflict")
    blocked_modules = dependency_blocked | conflict_blocked
    if blocked_modules:
        for stage in stages:
            for slot in stage["slots"]:
                if blocked_modules & set(slot["selectedModules"]):
                    slot["applicability"] = "blocked"
            if any(slot["applicability"] == "blocked" for slot in stage["slots"]):
                stage["applicability"] = "blocked"
    policies = yaml.safe_load((repository_root / "workflow/policies.yaml").read_text(encoding="utf-8"))
    graph = {
        "schemaVersion": 2, "requestHash": request_hash, "capabilitySnapshotHash": capability_snapshot_hash,
        "pipelineHash": pipeline.pipeline_hash, "policyHash": canonical_hash(policies), "catalogHash": envelope["catalogHash"],
        "strength": strength, "stages": stages,
    }
    graph["planHash"] = canonical_hash(graph)
    return graph, tuple(sorted(reasons))
