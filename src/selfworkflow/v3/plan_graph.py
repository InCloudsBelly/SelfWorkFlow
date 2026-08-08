"""Build the immutable, closed V3 PlanGraph.

This module is deliberately a pure boundary.  It validates already compiled
artifacts and snapshots; it never discovers providers, loads skills, starts a
process, accesses the network, or writes state.
"""

from dataclasses import dataclass
import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from selfworkflow.v3.catalog import CompiledCatalog
from selfworkflow.v3.contracts import (
    ContractError,
    load_contract,
    validate_catalog_pipeline,
    validate_plan_graph,
)
from selfworkflow.v3.pipeline import LoadedPipeline


class PlanGraphError(ValueError):
    """Stable fail-closed error while constructing a V3 PlanGraph."""

    def __init__(self, reason: str = "v3-plan-graph-invalid") -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ModuleSpec:
    """Selector-only metadata copied from a compiled catalog module."""

    id: str
    dependencies: tuple[str, ...]
    conflicts: tuple[str, ...]
    context_cost: int
    execution_cost: int


@dataclass(frozen=True)
class PlanGraphArtifact:
    """Typed PlanGraph plus immutable selector metadata.

    The JSON ``document`` is exactly the existing PlanGraph contract.  Module
    dependency and cost metadata stays outside that schema, but is copied from
    the compiled catalog and is therefore not runtime-discoverable.
    """

    document: dict[str, Any]
    module_specs: tuple[ModuleSpec, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "document", copy.deepcopy(self.document))
        normalized = []
        for spec in self.module_specs:
            if isinstance(spec, ModuleSpec):
                normalized.append(spec)
            elif isinstance(spec, Mapping):
                normalized.append(ModuleSpec(
                    id=spec["id"],
                    dependencies=tuple(spec.get("dependencies", ())),
                    conflicts=tuple(spec.get("conflicts", ())),
                    context_cost=spec.get("contextCost", spec.get("context_cost", 0)),
                    execution_cost=spec.get("executionCost", spec.get("execution_cost", 0)),
                ))
            else:
                raise TypeError("module spec must be typed")
        object.__setattr__(self, "module_specs", tuple(normalized))

    @property
    def plan_hash(self) -> str:
        return self.document["planHash"]

    def __getitem__(self, key: str) -> Any:
        return self.document[key]

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.document)

    def spec_by_id(self) -> dict[str, ModuleSpec]:
        return {spec.id: spec for spec in self.module_specs}


PlanGraph = PlanGraphArtifact


def build_plan_graph(
    request: Mapping[str, Any],
    compiled_catalog: CompiledCatalog | Mapping[str, Any],
    pipeline: LoadedPipeline | Mapping[str, Any],
    *,
    capability_snapshot: Mapping[str, Any] | None = None,
    provider_preference_snapshot: Mapping[str, Any] | None = None,
    provider_binding_snapshot: Mapping[str, Any] | None = None,
    execution_policy_snapshot: Mapping[str, Any] | None = None,
    policy_snapshot: Mapping[str, Any] | None = None,
    **aliases: Any,
) -> PlanGraphArtifact:
    """Build a deterministic PlanGraph from typed, already-bound inputs.

    All optional snapshots are treated as immutable values for this plan.  The
    accepted aliases are only naming conveniences for callers integrating the
    V3 resolver; they do not change the closed set or introduce discovery.
    """

    capability_snapshot = _take_alias(
        capability_snapshot, aliases, "capability_evidence_snapshot",
    )
    provider_preference_snapshot = _take_alias(
        provider_preference_snapshot, aliases, "provider_preferences",
    )
    provider_binding_snapshot = _take_alias(
        provider_binding_snapshot, aliases, "provider_binding",
    )
    execution_policy_snapshot = _take_alias(
        execution_policy_snapshot, aliases, "execution_policy",
    )
    if aliases:
        raise PlanGraphError("v3-plan-graph-unknown-input")

    request_document = _validated_request(request)
    catalog_document, catalog_hash = _catalog_document(compiled_catalog)
    pipeline_document, pipeline_hash = _pipeline_document(pipeline)
    try:
        validate_catalog_pipeline(catalog_document, pipeline_document, "")
    except ContractError as error:
        raise PlanGraphError(error.reason) from None

    if capability_snapshot is None:
        capability_snapshot = request_document["capabilityEvidenceSnapshot"]
    snapshots = {
        "capabilitySnapshotHash": _value_hash(capability_snapshot),
        "policyHash": _value_hash(
            policy_snapshot if policy_snapshot is not None else {}
        ),
        "providerPreferenceHash": _value_hash(
            provider_preference_snapshot if provider_preference_snapshot is not None else {}
        ),
        "providerBindingHash": _value_hash(
            provider_binding_snapshot if provider_binding_snapshot is not None else {}
        ),
        "executionPolicyHash": _value_hash(
            execution_policy_snapshot if execution_policy_snapshot is not None else {}
        ),
    }
    explicit = _unique_ids(request_document["explicitModuleIds"], "explicit")
    project_defaults = _unique_ids(
        request_document["projectDefaultModuleIds"], "project-default"
    )
    modules = _module_map(catalog_document)
    _validate_requested_ids(explicit | project_defaults, modules)
    _validate_explicit_conflicts(explicit, modules)
    allow_unverified = _approved_unverified_ids(
        execution_policy_snapshot or {}, explicit | project_defaults,
    )
    specs = tuple(_spec(module) for module in sorted(modules.values(), key=lambda item: item["id"]))
    module_specs = {spec.id: spec for spec in specs}

    condition_context = _condition_context(request_document)
    stages: list[dict[str, Any]] = []
    for stage_ordinal, stage in enumerate(pipeline_document["stages"], start=1):
        slots: list[dict[str, Any]] = []
        stage_has_applicable_slot = False
        for slot_ordinal, slot in enumerate(stage["slots"], start=1):
            applicable = _condition_matches(slot.get("condition"), condition_context)
            if applicable:
                stage_has_applicable_slot = True
            slot_modules = [
                module for module in modules.values()
                if module["stage"] == stage["id"] and module["slot"] == slot["id"]
            ]
            if not applicable and any(
                module["id"] in (explicit | project_defaults)
                for module in slot_modules
            ):
                raise PlanGraphError("v3-explicit-module-inapplicable")
            eligible = _closed_eligible_modules(
                slot_modules,
                modules,
                allow_unverified,
                explicit | project_defaults,
            ) if applicable else []
            eligible_ids = sorted(module["id"] for module in eligible)
            if applicable and slot["cardinality"] in {"exactly-one", "gate"} and not eligible_ids:
                raise PlanGraphError("v3-required-module-unavailable")
            selected_ids = (
                _static_selection(
                    slot,
                    eligible,
                    explicit,
                    project_defaults,
                    module_specs,
                )
                if applicable and slot["selectionMode"] == "static"
                else []
            )
            policy_hash = _selection_policy_hash(
                stage["id"], slot, eligible_ids, snapshots["policyHash"],
            )
            slots.append({
                "slotId": slot["id"],
                "ordinal": slot_ordinal,
                "cardinality": slot["cardinality"],
                "selectionMode": slot["selectionMode"],
                "selectedModules": selected_ids,
                "eligibleModules": eligible_ids,
                "selectionPolicyRef": slot["id"],
                "selectionPolicyHash": policy_hash,
                "coverageObligations": _coverage_obligations(slot, slot_modules),
                "gates": [],
                "applicability": "applicable" if applicable else "not-applicable",
            })
        stages.append({
            "stageId": stage["id"],
            "ordinal": stage_ordinal,
            "applicability": "applicable" if stage_has_applicable_slot else "not-applicable",
            "slots": slots,
        })

    plan_without_hash = {
        "schemaVersion": 3,
        "requestHash": _value_hash(request_document),
        "capabilitySnapshotHash": snapshots["capabilitySnapshotHash"],
        "pipelineHash": pipeline_hash,
        "policyHash": snapshots["policyHash"],
        "catalogHash": catalog_hash,
        "providerPreferenceHash": snapshots["providerPreferenceHash"],
        "providerBindingHash": snapshots["providerBindingHash"],
        "executionPolicyHash": snapshots["executionPolicyHash"],
        "stages": stages,
    }
    document = {
        **plan_without_hash,
        "planHash": _value_hash(plan_without_hash),
    }
    try:
        validate_plan_graph(document)
    except ContractError as error:
        raise PlanGraphError(error.reason) from None
    return PlanGraphArtifact(document, specs)


def _take_alias(
    value: Mapping[str, Any] | None,
    aliases: dict[str, Any],
    name: str,
) -> Mapping[str, Any] | None:
    if value is not None and name in aliases:
        raise PlanGraphError("v3-plan-graph-duplicate-input")
    return value if value is not None else aliases.pop(name, None)


def _validated_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise PlanGraphError("v3-request-not-object")
    for field, label in (
        ("explicitModuleIds", "explicit"),
        ("projectDefaultModuleIds", "project-default"),
    ):
        values = request.get(field)
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
            if len(values) != len(set(values)):
                raise PlanGraphError(f"v3-{label}-module-duplicate")
    try:
        return load_contract(
            "resolve-request.schema.json",
            json.dumps(dict(request), sort_keys=True, separators=(",", ":")),
        )
    except ContractError as error:
        raise PlanGraphError(error.reason) from None


def _catalog_document(
    compiled: CompiledCatalog | Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    if isinstance(compiled, CompiledCatalog):
        envelope = compiled.document
    elif isinstance(compiled, Mapping):
        envelope = dict(compiled)
    else:
        raise PlanGraphError("v3-catalog-not-compiled")
    if "catalog" in envelope:
        catalog = envelope["catalog"]
        declared_hash = envelope.get("catalogHash")
    else:
        catalog = envelope
        declared_hash = catalog.get("catalogHash") if isinstance(catalog, Mapping) else None
    if not isinstance(catalog, Mapping) or catalog.get("schemaVersion") != 3:
        raise PlanGraphError("v3-catalog-invalid")
    if not isinstance(declared_hash, str) or declared_hash != catalog.get("catalogHash"):
        raise PlanGraphError("v3-catalog-hash-invalid")
    catalog_without_hash = dict(catalog)
    catalog_without_hash.pop("catalogHash", None)
    if declared_hash != _value_hash(catalog_without_hash):
        raise PlanGraphError("v3-catalog-hash-mismatch")
    return dict(catalog), declared_hash


def _pipeline_document(
    pipeline: LoadedPipeline | Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    if isinstance(pipeline, LoadedPipeline):
        document, declared_hash = pipeline.document, pipeline.pipeline_hash
    elif isinstance(pipeline, Mapping):
        document = dict(pipeline)
        declared_hash = _value_hash(document)
    else:
        raise PlanGraphError("v3-pipeline-not-loaded")
    if document.get("schemaVersion") != 3 or not isinstance(document.get("stages"), list):
        raise PlanGraphError("v3-pipeline-invalid")
    try:
        validated = load_contract(
            "pipeline.schema.json",
            json.dumps(document, sort_keys=True, separators=(",", ":")),
        )
    except ContractError as error:
        raise PlanGraphError(error.reason) from None
    if declared_hash != _value_hash(validated):
        raise PlanGraphError("v3-pipeline-hash-mismatch")
    return validated, declared_hash


def _module_map(catalog: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    modules = catalog.get("modules")
    if not isinstance(modules, list):
        raise PlanGraphError("v3-catalog-modules-invalid")
    result: dict[str, dict[str, Any]] = {}
    for module in modules:
        if not isinstance(module, Mapping) or "stage" not in module:
            raise PlanGraphError("v3-catalog-modules-not-compiled")
        module_id = module.get("id")
        if not isinstance(module_id, str) or module_id in result:
            raise PlanGraphError("v3-catalog-module-duplicate")
        result[module_id] = dict(module)
    return result


def _unique_ids(values: Sequence[Any], label: str) -> set[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise PlanGraphError(f"v3-{label}-modules-invalid")
    result = set()
    for value in values:
        if not isinstance(value, str):
            raise PlanGraphError(f"v3-{label}-modules-invalid")
        if value in result:
            raise PlanGraphError(f"v3-{label}-module-duplicate")
        result.add(value)
    return result


def _validate_requested_ids(requested: set[str], modules: Mapping[str, Any]) -> None:
    unknown = sorted(requested - set(modules))
    if unknown:
        raise PlanGraphError("v3-request-module-unknown")


def _validate_explicit_conflicts(
    explicit: set[str], modules: Mapping[str, Mapping[str, Any]],
) -> None:
    for module_id in sorted(explicit):
        conflicts = set(modules[module_id].get("conflicts", ()))
        if conflicts & explicit:
            raise PlanGraphError("v3-explicit-module-conflict")


def _approved_unverified_ids(
    policy: Mapping[str, Any], requested: set[str],
) -> set[str]:
    values = policy.get("allowUnverifiedModuleIds", policy.get("approvedModuleIds", ()))
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise PlanGraphError("v3-execution-policy-invalid")
    approved = set(values)
    if not approved <= requested:
        raise PlanGraphError("v3-unverified-module-not-explicit")
    return approved


def _support_is_eligible(
    module: Mapping[str, Any], allow_unverified: set[str],
) -> bool:
    evidence = module.get("supportEvidence")
    if not isinstance(evidence, Mapping):
        return False
    states = tuple(evidence.get(field) for field in (
        "sourceIntegrity", "adapterSupport", "runtimeCapability", "behaviorEvidence",
    ))
    return all(state == "supported" for state in states) or (
        module.get("id") in allow_unverified and all(state != "unsupported" for state in states)
    )


def _closed_eligible_modules(
    slot_modules: Sequence[Mapping[str, Any]],
    all_modules: Mapping[str, Mapping[str, Any]],
    allow_unverified: set[str],
    requested: set[str],
) -> list[dict[str, Any]]:
    eligible = {
        module["id"]: dict(module)
        for module in slot_modules
        if _support_is_eligible(module, allow_unverified)
    }
    changed = True
    while changed:
        changed = False
        for module_id, module in tuple(eligible.items()):
            dependencies = module.get("dependencies", ())
            if any(
                dependency not in all_modules
                or not _support_is_eligible(all_modules[dependency], allow_unverified)
                for dependency in dependencies
            ):
                del eligible[module_id]
                changed = True
    for module_id in sorted(requested):
        module = all_modules.get(module_id)
        if (
            module is not None
            and slot_modules
            and module.get("stage") == slot_modules[0].get("stage")
        ):
            if module_id not in eligible:
                if not _support_is_eligible(module, allow_unverified):
                    raise PlanGraphError("v3-explicit-module-unsupported")
                raise PlanGraphError("v3-explicit-module-dependency-unavailable")
    return [eligible[module_id] for module_id in sorted(eligible)]


def _spec(module: Mapping[str, Any]) -> ModuleSpec:
    costs = module.get("contextCost", {})
    return ModuleSpec(
        id=module["id"],
        dependencies=tuple(sorted(module.get("dependencies", ()))),
        conflicts=tuple(sorted(module.get("conflicts", ()))),
        context_cost=costs.get("estimatedContextCost", 0),
        execution_cost=costs.get("estimatedExecutionCost", 0),
    )


def _static_selection(
    slot: Mapping[str, Any], eligible: Sequence[Mapping[str, Any]],
    explicit: set[str], project_defaults: set[str], specs: Mapping[str, ModuleSpec],
) -> list[str]:
    ids = sorted(module["id"] for module in eligible)
    preferred = [module_id for module_id in ids if module_id in explicit or module_id in project_defaults]
    if slot["cardinality"] == "exactly-one":
        return [_select_compatible(preferred + ids, specs)]
    if slot["cardinality"] == "gate":
        return _maximal_compatible(preferred + ids, specs)
    if not preferred:
        return []
    if slot["cardinality"] == "zero-or-one":
        return [_select_compatible(preferred, specs)]
    return _maximal_compatible(preferred, specs)


def _select_compatible(candidates: Sequence[str], specs: Mapping[str, ModuleSpec]) -> str:
    selected: list[str] = []
    for module_id in candidates:
        spec = specs[module_id]
        if not any(module_id in specs[item].conflicts or item in spec.conflicts for item in selected):
            return module_id
    raise PlanGraphError("v3-static-selection-conflict")


def _maximal_compatible(candidates: Sequence[str], specs: Mapping[str, ModuleSpec]) -> list[str]:
    selected: list[str] = []
    for module_id in candidates:
        spec = specs[module_id]
        if not any(module_id in specs[item].conflicts or item in spec.conflicts for item in selected):
            selected.append(module_id)
    return selected


def _coverage_obligations(
    slot: Mapping[str, Any], modules: Sequence[Mapping[str, Any]],
) -> list[str]:
    # Current pipeline stores obligations on future extensions; accept the
    # field only when a compiled extension supplies it, while keeping the
    # checked-in schema/catalog contract unchanged.
    values = slot.get("coverageObligations", ())
    if values:
        return sorted(set(values))
    return []


def _condition_context(request: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = request["capabilityEvidenceSnapshot"]
    return {
        **request,
        "capabilityStates": {item["state"] for item in snapshot["evidence"]},
    }


def _condition_matches(condition: Mapping[str, Any] | None, context: Mapping[str, Any]) -> bool:
    if condition is None:
        return True
    if "all" in condition:
        return all(_condition_matches(item, context) for item in condition["all"])
    if "any" in condition:
        return any(_condition_matches(item, context) for item in condition["any"])
    if "not" in condition:
        return not _condition_matches(condition["not"], context)
    if "eq" in condition:
        field, expected = condition["eq"]
        actual = context.get(field)
        if field == "projectMinimums":
            actual = context["projectMinimums"]["strength"]
        return actual == expected
    if "gte" in condition:
        field, expected = condition["gte"]
        actual = context.get(field)
        if field == "projectMinimums":
            actual = context["projectMinimums"]["strength"]
        if field in {"complexity", "risk", "testLevelFloor"}:
            order = {value: index for index, value in enumerate(
                ("C0", "C1", "C2", "C3") if field == "complexity" else
                ("R0", "R1", "R2", "R3") if field == "risk" else
                ("T0", "T1", "T2", "T3")
            )}
            return order[actual] >= order[expected]
        if field == "projectMinimums":
            return {"Light": 0, "Full": 1, "Deep": 2}[actual] >= {"Light": 0, "Full": 1, "Deep": 2}[expected]
        return actual >= expected
    if "contains" in condition:
        field, expected = condition["contains"]
        actual = context.get(field, ())
        if field == "capabilityStates":
            return expected in actual
        return expected in actual
    raise PlanGraphError("v3-pipeline-condition-unsupported")


def _selection_policy_hash(
    stage_id: str, slot: Mapping[str, Any], eligible: Sequence[str], policy_hash: str,
) -> str:
    return _value_hash({
        "schemaVersion": 3,
        "stageId": stage_id,
        "slotId": slot["id"],
        "cardinality": slot["cardinality"],
        "selectionMode": slot["selectionMode"],
        "allowedInvocationKinds": list(slot["allowedInvocationKinds"]),
        "eligibleModules": list(eligible),
        "policyHash": policy_hash,
    })


def _value_hash(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()
