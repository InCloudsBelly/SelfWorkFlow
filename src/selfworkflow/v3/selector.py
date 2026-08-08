"""Pure, bounded V3 runtime selection.

The selector accepts only a PlanGraph artifact and a typed SelectionInput.  It
does not have effect ports and intentionally has no process, network, clock,
filesystem, or subprocess dependencies.
"""

from dataclasses import dataclass
import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from selfworkflow.v3.contracts import ContractError, validate_selection_receipt
from selfworkflow.v3.plan_graph import PlanGraphArtifact, ModuleSpec


_DEFAULT_SELECTOR_SOURCE_HASH = "sha256:" + hashlib.sha256(
    b"selfworkflow.v3.bounded-selector"
).hexdigest()


class SelectorError(ValueError):
    """Stable fail-closed selector input or invariant error."""

    def __init__(self, reason: str = "v3-selector-invalid") -> None:
        self.reason = reason
        super().__init__(reason)


class SelectionPaused(SelectorError):
    """Compatibility error type for callers that choose exception handling."""


@dataclass(frozen=True)
class SelectionInput:
    artifact_id: str
    artifact_hash: str
    candidate_module_ids: tuple[str, ...] | None = None
    preferred_module_ids: tuple[str, ...] = ()
    signal_evidence_refs: tuple[str, ...] = ()
    context_budget: int | None = None
    execution_budget: int | None = None
    requested_module_ids: tuple[str, ...] = ()
    coverage_by_module: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SelectionInput":
        if not isinstance(value, Mapping):
            raise SelectorError("v3-selection-input-not-typed")
        coverage = value.get("coverageByModule", {})
        if not isinstance(coverage, Mapping):
            raise SelectorError("v3-selection-coverage-invalid")
        return cls(
            artifact_id=value.get("artifactId", ""),
            artifact_hash=value.get("artifactHash", ""),
            candidate_module_ids=_tuple_or_none(value.get("candidateModuleIds")),
            preferred_module_ids=_tuple(value.get("preferredModuleIds", ())),
            signal_evidence_refs=_tuple(value.get("signalEvidenceRefs", ())),
            context_budget=value.get("contextBudget"),
            execution_budget=value.get("executionBudget"),
            requested_module_ids=_tuple(value.get("requestedModuleIds", ())),
            coverage_by_module=tuple(
                (str(module_id), tuple(values))
                for module_id, values in sorted(coverage.items())
            ),
        )


@dataclass(frozen=True)
class SelectionReceiptArtifact:
    document: dict[str, Any]
    selection_policy_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "document", copy.deepcopy(self.document))

    @property
    def receipt_hash(self) -> str:
        return self.document["receiptHash"]

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.document)


@dataclass(frozen=True)
class SelectionResult:
    status: str
    receipt: SelectionReceiptArtifact | None = None
    reason: str | None = None
    next_stage_request: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "receipt": self.receipt.as_dict() if self.receipt else None,
            "nextStageRequest": copy.deepcopy(self.next_stage_request),
        }


def select_modules(
    plan_graph: PlanGraphArtifact | Mapping[str, Any],
    stage_id: str,
    slot_id: str,
    attempt_ref: str,
    selection_input: SelectionInput | Mapping[str, Any],
    *,
    selector_module_id: str = "bounded-selector",
    selector_source_hash: str = _DEFAULT_SELECTOR_SOURCE_HASH,
) -> SelectionResult:
    """Select a bounded subset and emit a schema-valid SelectionReceipt."""

    graph = _coerce_graph(plan_graph)
    typed_input = _coerce_input(selection_input)
    stage, slot = _find_slot(graph.document, stage_id, slot_id)
    _validate_stable_text(attempt_ref, "v3-selection-attempt-invalid")
    _validate_stable_text(selector_module_id, "v3-selector-module-invalid")
    _validate_hash(selector_source_hash, "v3-selector-source-hash-invalid")
    _validate_input(typed_input)

    eligible = list(slot["eligibleModules"])
    _validate_unique(eligible, "v3-plan-eligible-duplicate")
    requested = list(typed_input.requested_module_ids)
    _validate_unique(requested, "v3-requested-module-duplicate")
    outside_requested = sorted(set(requested) - set(eligible))
    if outside_requested:
        known_module_ids = set(graph.spec_by_id())
        if known_module_ids and not set(outside_requested) <= known_module_ids:
            raise SelectorError("v3-selector-requested-module-unknown")
        return SelectionResult(
            status="next-stage-request",
            reason="outside-eligible-set",
            next_stage_request={
                "schemaVersion": 3,
                "kind": "nextStageRequest",
                "planHash": graph.plan_hash,
                "stageId": stage_id,
                "slotId": slot_id,
                "requestedModuleIds": outside_requested,
                "reason": "outside-eligible-set",
            },
        )

    candidates = eligible if typed_input.candidate_module_ids is None else list(typed_input.candidate_module_ids)
    _validate_unique(candidates, "v3-selector-candidate-duplicate")
    outside = sorted(set(candidates) - set(eligible))
    if outside:
        raise SelectorError("v3-selector-candidate-outside-eligible")
    preferred = list(typed_input.preferred_module_ids)
    _validate_unique(preferred, "v3-selector-preferred-duplicate")
    if not set(preferred) <= set(candidates):
        raise SelectorError("v3-selector-preferred-outside-candidates")

    if slot["selectionMode"] == "static":
        selected = list(slot["selectedModules"])
        if selected and not set(selected) <= set(candidates):
            raise SelectorError("v3-static-selection-not-candidate")
    else:
        selected = _choose(
            slot, candidates, preferred, graph.spec_by_id(),
            typed_input.context_budget, typed_input.execution_budget,
        )

    reason_ids = ["selection.deterministic-order", f"selection.cardinality.{slot['cardinality']}"]
    context_cost, execution_cost = _costs(selected, graph.spec_by_id())
    if typed_input.context_budget is not None and context_cost > typed_input.context_budget:
        if slot["cardinality"] in {"exactly-one", "gate"}:
            return SelectionResult(status="paused", reason="context-budget-exceeded")
        selected = []
        context_cost, execution_cost = 0, 0
        reason_ids.append("selection.optional-budget-pruned")
    if typed_input.execution_budget is not None and execution_cost > typed_input.execution_budget:
        if slot["cardinality"] in {"exactly-one", "gate"}:
            return SelectionResult(status="paused", reason="execution-budget-exceeded")
        selected = []
        context_cost, execution_cost = 0, 0
        reason_ids.append("selection.optional-budget-pruned")

    cardinality = slot["cardinality"]
    if cardinality in {"exactly-one", "gate"} and not selected:
        if _any_candidate_exceeds_budget(
            candidates, graph.spec_by_id(), typed_input.context_budget,
            typed_input.execution_budget,
        ):
            reason = (
                "context-budget-exceeded"
                if typed_input.context_budget is not None
                and any(
                    graph.spec_by_id().get(item, ModuleSpec(item, (), (), 0, 0)).context_cost
                    > typed_input.context_budget for item in candidates
                )
                else "execution-budget-exceeded"
            )
            return SelectionResult(status="paused", reason=reason)
        return SelectionResult(status="paused", reason="required-module-unavailable")
    coverage = _coverage_decisions(slot, selected, typed_input, reason_ids)
    document_without_hash = {
        "schemaVersion": 3,
        "planHash": graph.plan_hash,
        "stageId": stage_id,
        "slotId": slot_id,
        "attemptRef": attempt_ref,
        "selectorModuleId": selector_module_id,
        "selectorSourceHash": selector_source_hash,
        "inputArtifactId": typed_input.artifact_id,
        "inputArtifactHash": typed_input.artifact_hash,
        "eligibleModuleIds": eligible,
        "selectedModuleIds": selected,
        "selectionReasons": sorted(set(reason_ids)),
        "signalEvidenceRefs": list(typed_input.signal_evidence_refs),
        "estimatedContextCost": context_cost,
        "estimatedExecutionCost": execution_cost,
        "coverageDecisions": coverage,
    }
    document = {
        **document_without_hash,
        "receiptHash": _value_hash(document_without_hash),
    }
    try:
        validate_selection_receipt(document, graph.document)
    except ContractError as error:
        raise SelectorError(error.reason) from None
    return SelectionResult(
        status="selected",
        receipt=SelectionReceiptArtifact(document, slot["selectionPolicyHash"]),
    )


def _coerce_graph(value: PlanGraphArtifact | Mapping[str, Any]) -> PlanGraphArtifact:
    if isinstance(value, PlanGraphArtifact):
        return value
    if isinstance(value, Mapping):
        return PlanGraphArtifact(dict(value))
    raise SelectorError("v3-plan-graph-not-typed")


def _coerce_input(value: SelectionInput | Mapping[str, Any]) -> SelectionInput:
    if isinstance(value, SelectionInput):
        return value
    if isinstance(value, Mapping):
        return SelectionInput.from_mapping(value)
    raise SelectorError("v3-selection-input-not-typed")


def _find_slot(
    document: Mapping[str, Any], stage_id: str, slot_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    for stage in document.get("stages", ()):
        if stage.get("stageId") != stage_id:
            continue
        for slot in stage.get("slots", ()):
            if slot.get("slotId") == slot_id:
                if slot.get("applicability") != "applicable":
                    raise SelectorError("v3-selector-slot-not-applicable")
                return stage, slot
        raise SelectorError("v3-selector-slot-unknown")
    raise SelectorError("v3-selector-stage-unknown")


def _validate_input(value: SelectionInput) -> None:
    _validate_stable_text(value.artifact_id, "v3-selection-artifact-id-invalid")
    _validate_hash(value.artifact_hash, "v3-selection-artifact-hash-invalid")
    for ref in value.signal_evidence_refs:
        _validate_stable_text(ref, "v3-selection-signal-ref-invalid")
    for ids in (
        value.candidate_module_ids or (),
        value.preferred_module_ids,
        value.requested_module_ids,
    ):
        if any(not isinstance(module_id, str) for module_id in ids):
            raise SelectorError("v3-selection-module-id-invalid")
    for budget in (value.context_budget, value.execution_budget):
        if budget is not None and (type(budget) is not int or budget < 0):
            raise SelectorError("v3-selection-budget-invalid")


def _validate_stable_text(value: Any, reason: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise SelectorError(reason)


def _validate_hash(value: Any, reason: str) -> None:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
        raise SelectorError(reason)
    try:
        int(value[7:], 16)
    except ValueError:
        raise SelectorError(reason) from None


def _tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SelectorError("v3-selection-list-invalid")
    if any(not isinstance(item, str) for item in value):
        raise SelectorError("v3-selection-list-invalid")
    return tuple(value)


def _tuple_or_none(value: Any) -> tuple[str, ...] | None:
    return None if value is None else _tuple(value)


def _validate_unique(values: Sequence[str], reason: str) -> None:
    if len(values) != len(set(values)):
        raise SelectorError(reason)


def _choose(
    slot: Mapping[str, Any], candidates: Sequence[str], preferred: Sequence[str],
    specs: Mapping[str, ModuleSpec], context_budget: int | None,
    execution_budget: int | None,
) -> list[str]:
    order = list(preferred) + sorted(set(candidates) - set(preferred))
    selected: list[str] = []
    for module_id in order:
        if module_id not in specs:
            spec = ModuleSpec(module_id, (), (), 0, 0)
        else:
            spec = specs[module_id]
        closure = _dependency_closure(module_id, specs, set(candidates))
        if closure is None:
            continue
        additions = [item for item in closure if item not in selected]
        if any(_conflicts(item, selected, specs) for item in additions):
            continue
        candidate_selection = selected + additions
        context_cost, execution_cost = _costs(candidate_selection, specs)
        if context_budget is not None and context_cost > context_budget:
            continue
        if execution_budget is not None and execution_cost > execution_budget:
            continue
        selected = candidate_selection
        if slot["cardinality"] in {"exactly-one", "zero-or-one"}:
            break
    if slot["cardinality"] in {"exactly-one", "gate"} and not selected:
        return []
    return sorted(selected)


def _dependency_closure(
    module_id: str, specs: Mapping[str, ModuleSpec], candidates: set[str],
) -> list[str] | None:
    result: list[str] = []
    visiting: set[str] = set()

    def visit(current: str) -> bool:
        if current in result:
            return True
        if current in visiting:
            return False
        visiting.add(current)
        spec = specs.get(current, ModuleSpec(current, (), (), 0, 0))
        for dependency in spec.dependencies:
            if dependency not in candidates:
                return False
            if not visit(dependency):
                return False
        visiting.remove(current)
        result.append(current)
        return True

    return result if visit(module_id) else None


def _conflicts(
    module_id: str, selected: Sequence[str], specs: Mapping[str, ModuleSpec],
) -> bool:
    spec = specs.get(module_id, ModuleSpec(module_id, (), (), 0, 0))
    return any(
        module_id in specs.get(item, ModuleSpec(item, (), (), 0, 0)).conflicts
        or item in spec.conflicts
        for item in selected
    )


def _costs(selected: Sequence[str], specs: Mapping[str, ModuleSpec]) -> tuple[int, int]:
    context = execution = 0
    for module_id in selected:
        spec = specs.get(module_id, ModuleSpec(module_id, (), (), 0, 0))
        context += spec.context_cost
        execution += spec.execution_cost
    return context, execution


def _any_candidate_exceeds_budget(
    candidates: Sequence[str], specs: Mapping[str, ModuleSpec],
    context_budget: int | None, execution_budget: int | None,
) -> bool:
    for module_id in candidates:
        spec = specs.get(module_id, ModuleSpec(module_id, (), (), 0, 0))
        if context_budget is not None and spec.context_cost > context_budget:
            return True
        if execution_budget is not None and spec.execution_cost > execution_budget:
            return True
    return False


def _coverage_decisions(
    slot: Mapping[str, Any], selected: Sequence[str], value: SelectionInput,
    reasons: list[str],
) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    coverage = dict(value.coverage_by_module)
    for obligation in slot.get("coverageObligations", ()):
        evidence = sorted({
            ref for module_id in selected for ref in coverage.get(module_id, ())
        })
        if selected and (not coverage or evidence):
            decisions.append({
                "obligationId": obligation,
                "decision": "fulfilled",
                "evidenceRefs": evidence,
            })
            reasons.append("coverage.fulfilled")
        else:
            decisions.append({
                "obligationId": obligation,
                "decision": "blocked",
                "evidenceRefs": evidence,
            })
    return decisions


def _value_hash(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()
