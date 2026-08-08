"""Pure construction of a provenance-bound V3 PlanGraph artifact."""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import copy
import hashlib
import json
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
    """Stable fail-closed PlanGraph construction or provenance error."""

    def __init__(self, reason: str = "v3-plan-graph-invalid") -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ModuleSpec:
    id: str
    stage: str
    slot: str
    source_hash: str
    dependencies: tuple[str, ...]
    conflicts: tuple[str, ...]
    context_cost: int
    execution_cost: int


_ARTIFACT_TOKEN = object()


class PlanGraphArtifact:
    """Builder-only immutable view over a PlanGraph and bound module metadata."""

    __slots__ = (
        "__document", "__module_specs", "__provenance_hash", "__token",
    )

    def __init__(
        self,
        token: object,
        document: dict[str, Any],
        module_specs: tuple[ModuleSpec, ...],
        provenance_hash: str,
    ) -> None:
        if token is not _ARTIFACT_TOKEN:
            raise TypeError("PlanGraphArtifact is builder-only")
        self.__document = copy.deepcopy(document)
        self.__module_specs = tuple(module_specs)
        self.__provenance_hash = provenance_hash
        self.__token = token

    @classmethod
    def _from_builder(
        cls, document: dict[str, Any], module_specs: tuple[ModuleSpec, ...],
    ) -> "PlanGraphArtifact":
        provenance_hash = _artifact_provenance_hash(document, module_specs)
        return cls(_ARTIFACT_TOKEN, document, module_specs, provenance_hash)

    @property
    def document(self) -> dict[str, Any]:
        return copy.deepcopy(self.__document)

    @property
    def plan_hash(self) -> str:
        return self.__document["planHash"]

    def __getitem__(self, key: str) -> Any:
        return copy.deepcopy(self.__document[key])

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.__document)

    def spec_by_id(self) -> dict[str, ModuleSpec]:
        return {spec.id: spec for spec in self.__module_specs}

    def _trusted_snapshot(
        self,
    ) -> tuple[dict[str, Any], dict[str, ModuleSpec]]:
        if self.__token is not _ARTIFACT_TOKEN:
            raise PlanGraphError("v3-plan-artifact-provenance-invalid")
        actual = _artifact_provenance_hash(
            self.__document, self.__module_specs,
        )
        if actual != self.__provenance_hash:
            raise PlanGraphError("v3-plan-artifact-provenance-invalid")
        try:
            validate_plan_graph(self.__document)
        except ContractError as error:
            raise PlanGraphError(error.reason) from None
        return copy.deepcopy(self.__document), self.spec_by_id()


PlanGraph = PlanGraphArtifact


def build_plan_graph(
    request: Mapping[str, Any],
    compiled_catalog: CompiledCatalog,
    pipeline: LoadedPipeline,
    *,
    capability_snapshot: Mapping[str, Any] | None = None,
    provider_preference_snapshot: Mapping[str, Any] | None = None,
    provider_binding_snapshot: Mapping[str, Any] | None = None,
    execution_policy_snapshot: Mapping[str, Any] | None = None,
    policy_snapshot: Mapping[str, Any] | None = None,
) -> PlanGraphArtifact:
    """Build a deterministic plan from strict loader artifacts and snapshots."""

    request_document = _validated_request(request)
    catalog_document, catalog_hash = _catalog_document(compiled_catalog)
    pipeline_document, pipeline_hash = _pipeline_document(pipeline)
    try:
        validate_catalog_pipeline(catalog_document, pipeline_document, "")
    except ContractError as error:
        raise PlanGraphError(error.reason) from None

    request_capability_snapshot = request_document["capabilityEvidenceSnapshot"]
    if capability_snapshot is not None and not _canonical_equal(
        capability_snapshot, request_capability_snapshot,
    ):
        raise PlanGraphError("v3-capability-snapshot-mismatch")
    capability_snapshot = request_capability_snapshot
    policy_snapshot = _snapshot(policy_snapshot, "policy")
    provider_preference_snapshot = _snapshot(
        provider_preference_snapshot, "provider-preference",
    )
    provider_binding_snapshot = _snapshot(
        provider_binding_snapshot, "provider-binding",
    )
    execution_policy_snapshot = _snapshot(
        execution_policy_snapshot, "execution-policy",
    )
    snapshots = {
        "capabilitySnapshotHash": _value_hash(capability_snapshot),
        "policyHash": _value_hash(policy_snapshot),
        "providerPreferenceHash": _value_hash(provider_preference_snapshot),
        "providerBindingHash": _value_hash(provider_binding_snapshot),
        "executionPolicyHash": _value_hash(execution_policy_snapshot),
    }

    explicit = _unique_ids(request_document["explicitModuleIds"], "explicit")
    project_defaults = _unique_ids(
        request_document["projectDefaultModuleIds"], "project-default",
    )
    requested = explicit | project_defaults
    modules = _module_map(catalog_document)
    _validate_module_graph(modules)
    _validate_dependency_boundaries(modules)
    _validate_requested_ids(requested, modules)
    _validate_explicit_conflicts(explicit, modules)
    allow_unverified = _approved_unverified_ids(
        execution_policy_snapshot, requested,
    )
    specs = tuple(
        _spec(module)
        for module in sorted(modules.values(), key=lambda item: item["id"])
    )
    module_specs = {spec.id: spec for spec in specs}

    condition_context = _condition_context(request_document)
    stages: list[dict[str, Any]] = []
    for stage_ordinal, stage in enumerate(pipeline_document["stages"], start=1):
        slots: list[dict[str, Any]] = []
        stage_has_applicable_slot = False
        for slot_ordinal, slot in enumerate(stage["slots"], start=1):
            applicable = _condition_matches(
                slot.get("condition"), condition_context,
            )
            stage_has_applicable_slot |= applicable
            slot_modules = [
                module for module in modules.values()
                if module["stage"] == stage["id"] and module["slot"] == slot["id"]
            ]
            if not applicable and any(
                module["id"] in requested for module in slot_modules
            ):
                raise PlanGraphError("v3-explicit-module-inapplicable")
            eligible = (
                _closed_eligible_modules(
                    slot_modules, modules, allow_unverified, requested,
                )
                if applicable else []
            )
            eligible_ids = sorted(module["id"] for module in eligible)
            if (
                applicable
                and slot["cardinality"] in {"exactly-one", "gate"}
                and not eligible_ids
            ):
                raise PlanGraphError("v3-required-module-unavailable")
            selected_ids = (
                _static_selection(
                    slot, eligible, explicit, project_defaults, module_specs,
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
                "coverageObligations": _coverage_obligations(
                    slot["id"], policy_snapshot,
                ),
                "gates": [],
                "applicability": (
                    "applicable" if applicable else "not-applicable"
                ),
            })
        stages.append({
            "stageId": stage["id"],
            "ordinal": stage_ordinal,
            "applicability": (
                "applicable" if stage_has_applicable_slot else "not-applicable"
            ),
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
    return PlanGraphArtifact._from_builder(document, specs)


def _validated_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise PlanGraphError("v3-request-not-object")
    for field, label in (
        ("explicitModuleIds", "explicit"),
        ("projectDefaultModuleIds", "project-default"),
    ):
        values = request.get(field)
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
            try:
                duplicate = len(values) != len(set(values))
            except TypeError:
                duplicate = False
            if duplicate:
                raise PlanGraphError(f"v3-{label}-module-duplicate")
    try:
        return load_contract(
            "resolve-request.schema.json", _canonical_bytes(dict(request)).decode(),
        )
    except (ContractError, UnicodeError) as error:
        reason = error.reason if isinstance(error, ContractError) else "contract-json-invalid"
        raise PlanGraphError(reason) from None


def _catalog_document(compiled: CompiledCatalog) -> tuple[dict[str, Any], str]:
    if type(compiled) is not CompiledCatalog:
        raise PlanGraphError("v3-catalog-not-compiled")
    envelope = compiled.document
    if not isinstance(envelope, dict) or set(envelope) != {
        "schemaVersion", "catalog", "catalogHash",
    }:
        raise PlanGraphError("v3-catalog-envelope-invalid")
    if compiled.content != _canonical_bytes(envelope):
        raise PlanGraphError("v3-catalog-content-mismatch")
    catalog = envelope.get("catalog")
    declared_hash = envelope.get("catalogHash")
    if not isinstance(catalog, dict) or catalog.get("schemaVersion") != 3:
        raise PlanGraphError("v3-catalog-invalid")
    if declared_hash != catalog.get("catalogHash") or declared_hash != compiled.catalog_hash:
        raise PlanGraphError("v3-catalog-hash-invalid")
    material = dict(catalog)
    material.pop("catalogHash", None)
    if declared_hash != _value_hash(material):
        raise PlanGraphError("v3-catalog-hash-mismatch")
    return copy.deepcopy(catalog), declared_hash


def _pipeline_document(pipeline: LoadedPipeline) -> tuple[dict[str, Any], str]:
    if type(pipeline) is not LoadedPipeline:
        raise PlanGraphError("v3-pipeline-not-loaded")
    document = pipeline.document
    if not isinstance(document, dict):
        raise PlanGraphError("v3-pipeline-invalid")
    if pipeline.content != _canonical_bytes(document):
        raise PlanGraphError("v3-pipeline-content-mismatch")
    if pipeline.pipeline_hash != _value_hash(document):
        raise PlanGraphError("v3-pipeline-hash-mismatch")
    try:
        validated = load_contract(
            "pipeline.schema.json", pipeline.content.decode("utf-8"),
        )
    except (ContractError, UnicodeError) as error:
        reason = error.reason if isinstance(error, ContractError) else "contract-json-invalid"
        raise PlanGraphError(reason) from None
    if validated != document:
        raise PlanGraphError("v3-pipeline-content-mismatch")
    return copy.deepcopy(validated), pipeline.pipeline_hash


def _snapshot(value: Mapping[str, Any] | None, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PlanGraphError(f"v3-{name}-snapshot-invalid")
    try:
        return json.loads(_canonical_bytes(dict(value)))
    except (TypeError, ValueError, OverflowError, RecursionError, json.JSONDecodeError):
        raise PlanGraphError(f"v3-{name}-snapshot-invalid") from None


def _canonical_equal(first: Any, second: Any) -> bool:
    try:
        return _canonical_bytes(first) == _canonical_bytes(second)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return False


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
        result[module_id] = copy.deepcopy(dict(module))
    return result


def _validate_module_graph(modules: Mapping[str, Mapping[str, Any]]) -> None:
    for module_id, module in modules.items():
        for dependency in module["dependencies"]:
            if dependency not in modules or dependency == module_id:
                raise PlanGraphError("v3-catalog-dependency-invalid")
        for conflict in module["conflicts"]:
            if conflict not in modules or conflict == module_id:
                raise PlanGraphError("v3-catalog-conflict-invalid")
            if module_id not in modules[conflict]["conflicts"]:
                raise PlanGraphError("v3-catalog-conflict-asymmetric")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module_id: str) -> None:
        if module_id in visiting:
            raise PlanGraphError("v3-catalog-dependency-cycle")
        if module_id in visited:
            return
        visiting.add(module_id)
        for dependency in modules[module_id]["dependencies"]:
            visit(dependency)
        visiting.remove(module_id)
        visited.add(module_id)

    for module_id in sorted(modules):
        visit(module_id)


def _validate_dependency_boundaries(
    modules: Mapping[str, Mapping[str, Any]],
) -> None:
    for module in modules.values():
        for dependency_id in module["dependencies"]:
            dependency = modules[dependency_id]
            if (
                dependency["stage"] != module["stage"]
                or dependency["slot"] != module["slot"]
            ):
                raise PlanGraphError("v3-cross-slot-dependency")


def _unique_ids(values: Sequence[Any], label: str) -> set[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise PlanGraphError(f"v3-{label}-modules-invalid")
    result: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise PlanGraphError(f"v3-{label}-modules-invalid")
        if value in result:
            raise PlanGraphError(f"v3-{label}-module-duplicate")
        result.add(value)
    return result


def _validate_requested_ids(
    requested: set[str], modules: Mapping[str, Any],
) -> None:
    if requested - set(modules):
        raise PlanGraphError("v3-request-module-unknown")


def _validate_explicit_conflicts(
    explicit: set[str], modules: Mapping[str, Mapping[str, Any]],
) -> None:
    for module_id in explicit:
        if set(modules[module_id]["conflicts"]) & explicit:
            raise PlanGraphError("v3-explicit-module-conflict")


def _approved_unverified_ids(
    policy: Mapping[str, Any], requested: set[str],
) -> set[str]:
    values = policy.get(
        "allowUnverifiedModuleIds", policy.get("approvedModuleIds", ()),
    )
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise PlanGraphError("v3-execution-policy-invalid")
    approved = set(values)
    if len(approved) != len(values) or not approved <= requested:
        raise PlanGraphError("v3-unverified-module-not-explicit")
    return approved


def _support_is_eligible(
    module: Mapping[str, Any], allow_unverified: set[str],
) -> bool:
    evidence = module.get("supportEvidence")
    if not isinstance(evidence, Mapping):
        return False
    states = tuple(evidence.get(field) for field in (
        "sourceIntegrity", "adapterSupport", "runtimeCapability",
        "behaviorEvidence",
    ))
    return all(state == "supported" for state in states) or (
        module["id"] in allow_unverified
        and all(state != "unsupported" for state in states)
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
            dependencies = set(module["dependencies"])
            closure = _module_closure(module_id, all_modules)
            if (
                not dependencies <= set(eligible)
                or _selection_has_conflict(closure, all_modules)
            ):
                del eligible[module_id]
                changed = True
    for module_id in requested:
        module = all_modules[module_id]
        if slot_modules and module["stage"] == slot_modules[0]["stage"]:
            if module_id not in eligible:
                if not _support_is_eligible(module, allow_unverified):
                    raise PlanGraphError("v3-explicit-module-unsupported")
                raise PlanGraphError(
                    "v3-explicit-module-dependency-unavailable",
                )
    return [eligible[module_id] for module_id in sorted(eligible)]


def _module_closure(
    module_id: str, modules: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    result: set[str] = set()

    def visit(current: str) -> None:
        if current in result:
            return
        result.add(current)
        for dependency in modules[current]["dependencies"]:
            visit(dependency)

    visit(module_id)
    return result


def _selection_has_conflict(
    selected: set[str], modules: Mapping[str, Mapping[str, Any]],
) -> bool:
    return any(
        set(modules[module_id]["conflicts"]) & (selected - {module_id})
        for module_id in selected
    )


def _spec(module: Mapping[str, Any]) -> ModuleSpec:
    costs = module["contextCost"]
    return ModuleSpec(
        id=module["id"],
        stage=module["stage"],
        slot=module["slot"],
        source_hash=module["sourceHash"],
        dependencies=tuple(sorted(module["dependencies"])),
        conflicts=tuple(sorted(module["conflicts"])),
        context_cost=costs["estimatedContextCost"],
        execution_cost=costs["estimatedExecutionCost"],
    )


def _static_selection(
    slot: Mapping[str, Any],
    eligible: Sequence[Mapping[str, Any]],
    explicit: set[str],
    project_defaults: set[str],
    specs: Mapping[str, ModuleSpec],
) -> list[str]:
    eligible_ids = {module["id"] for module in eligible}
    preferred = sorted(
        eligible_ids & (explicit | project_defaults),
    )
    ordered = preferred + sorted(eligible_ids - set(preferred))
    cardinality = slot["cardinality"]
    if cardinality in {"zero-or-one", "zero-or-many"} and not preferred:
        return []
    selected: list[str] = []
    for module_id in ordered:
        closure = _spec_closure(module_id, specs, eligible_ids)
        if closure is None or _spec_selection_conflicts(closure, specs):
            continue
        candidate = set(selected) | closure
        if _spec_selection_conflicts(candidate, specs):
            continue
        if cardinality in {"exactly-one", "zero-or-one"} and len(candidate) > 1:
            continue
        selected = sorted(candidate)
        if cardinality in {"exactly-one", "zero-or-one"}:
            break
    required_explicit = explicit & eligible_ids
    if not required_explicit <= set(selected):
        raise PlanGraphError("v3-static-selection-unavailable")
    if cardinality in {"exactly-one", "gate"} and not selected:
        raise PlanGraphError("v3-static-selection-unavailable")
    return selected


def _spec_closure(
    module_id: str, specs: Mapping[str, ModuleSpec], eligible: set[str],
) -> set[str] | None:
    result: set[str] = set()

    def visit(current: str) -> bool:
        if current in result:
            return True
        if current not in eligible or current not in specs:
            return False
        result.add(current)
        return all(visit(item) for item in specs[current].dependencies)

    return result if visit(module_id) else None


def _spec_selection_conflicts(
    selected: set[str], specs: Mapping[str, ModuleSpec],
) -> bool:
    return any(
        set(specs[module_id].conflicts) & (selected - {module_id})
        for module_id in selected
    )


def _coverage_obligations(
    slot_id: str, policy: Mapping[str, Any],
) -> list[str]:
    mapping = policy.get("coverageObligationsBySlot", {})
    if not isinstance(mapping, Mapping):
        raise PlanGraphError("v3-coverage-policy-invalid")
    unknown = set(mapping) - {slot_id}
    # Other slots are allowed because this function is called once per slot.
    del unknown
    values = mapping.get(slot_id, ())
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise PlanGraphError("v3-coverage-policy-invalid")
    if any(not isinstance(value, str) for value in values) or len(values) != len(set(values)):
        raise PlanGraphError("v3-coverage-policy-invalid")
    return sorted(values)


def _condition_context(request: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **request,
        "capabilityStates": {
            item["state"]
            for item in request["capabilityEvidenceSnapshot"]["evidence"]
        },
    }


def _condition_matches(
    condition: Mapping[str, Any] | None, context: Mapping[str, Any],
) -> bool:
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
        orders = {
            "complexity": ("C0", "C1", "C2", "C3"),
            "risk": ("R0", "R1", "R2", "R3"),
            "testLevelFloor": ("T0", "T1", "T2", "T3"),
            "projectMinimums": ("Light", "Full", "Deep"),
            "requirementsMaturity": ("exploratory", "defined", "approved"),
        }
        if field in orders:
            return orders[field].index(actual) >= orders[field].index(expected)
        return actual >= expected
    if "contains" in condition:
        field, expected = condition["contains"]
        return expected in context.get(field, ())
    raise PlanGraphError("v3-pipeline-condition-unsupported")


def _selection_policy_hash(
    stage_id: str,
    slot: Mapping[str, Any],
    eligible: Sequence[str],
    policy_hash: str,
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


def _artifact_provenance_hash(
    document: Mapping[str, Any], specs: Sequence[ModuleSpec],
) -> str:
    return _value_hash({
        "document": document,
        "moduleSpecs": [asdict(spec) for spec in specs],
    })


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _value_hash(value: Any) -> str:
    try:
        return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise PlanGraphError("v3-canonical-value-invalid") from None
