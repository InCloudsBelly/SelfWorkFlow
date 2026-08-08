"""Effect-free bounded selection over a provenance-bound PlanGraph."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import copy
import hashlib
import json
import re
from typing import Any

from selfworkflow.v3.contracts import ContractError, validate_selection_receipt
from selfworkflow.v3.plan_graph import (
    ModuleSpec,
    PlanGraphArtifact,
    PlanGraphError,
)


_STABLE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_DEFAULT_SELECTOR_SOURCE_HASH = "sha256:" + hashlib.sha256(
    b"selfworkflow.v3.bounded-selector.v2"
).hexdigest()
_RECEIPT_TOKEN = object()
_RESULT_TOKEN = object()


class SelectorError(ValueError):
    def __init__(self, reason: str = "v3-selector-invalid") -> None:
        self.reason = reason
        super().__init__(reason)


class SelectionPaused(SelectorError):
    """Compatibility error type for exception-oriented hosts."""


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
    coverage_evidence_by_obligation: tuple[
        tuple[str, tuple[str, ...]], ...
    ] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SelectionInput":
        if not isinstance(value, Mapping):
            raise SelectorError("v3-selection-input-not-typed")
        allowed = {
            "artifactId", "artifactHash", "candidateModuleIds",
            "preferredModuleIds", "signalEvidenceRefs", "contextBudget",
            "executionBudget", "requestedModuleIds",
            "coverageEvidenceByObligation",
        }
        if set(value) - allowed:
            if "coverageByModule" in value:
                raise SelectorError("v3-legacy-coverage-binding-forbidden")
            raise SelectorError("v3-selection-input-unknown-field")
        coverage = value.get("coverageEvidenceByObligation", {})
        if not isinstance(coverage, Mapping):
            raise SelectorError("v3-selection-coverage-invalid")
        normalized_coverage = []
        for obligation, evidence in sorted(coverage.items()):
            if not isinstance(obligation, str):
                raise SelectorError("v3-selection-coverage-invalid")
            normalized_coverage.append((obligation, _tuple(evidence)))
        return cls(
            artifact_id=value.get("artifactId", ""),
            artifact_hash=value.get("artifactHash", ""),
            candidate_module_ids=_tuple_or_none(value.get("candidateModuleIds")),
            preferred_module_ids=_tuple(value.get("preferredModuleIds", ())),
            signal_evidence_refs=_tuple(value.get("signalEvidenceRefs", ())),
            context_budget=value.get("contextBudget"),
            execution_budget=value.get("executionBudget"),
            requested_module_ids=_tuple(value.get("requestedModuleIds", ())),
            coverage_evidence_by_obligation=tuple(normalized_coverage),
        )


class SelectionReceiptArtifact:
    __slots__ = ("__document", "__token")

    def __init__(self, token: object, document: dict[str, Any]) -> None:
        if token is not _RECEIPT_TOKEN:
            raise TypeError("SelectionReceiptArtifact is selector-only")
        self.__document = copy.deepcopy(document)
        self.__token = token

    @classmethod
    def _create(cls, document: dict[str, Any]) -> "SelectionReceiptArtifact":
        return cls(_RECEIPT_TOKEN, document)

    @property
    def document(self) -> dict[str, Any]:
        return copy.deepcopy(self.__document)

    @property
    def selection_policy_hash(self) -> str:
        return self.__document["selectionPolicyHash"]

    @property
    def receipt_hash(self) -> str:
        return self.__document["receiptHash"]

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.__document)


class SelectionResult:
    """Immutable, content-addressed selector outcome."""

    __slots__ = ("__document", "__receipt", "__token")

    def __init__(
        self, token: object, document: dict[str, Any],
        receipt: SelectionReceiptArtifact | None,
    ) -> None:
        if token is not _RESULT_TOKEN:
            raise TypeError("SelectionResult is selector-only")
        _validate_result_document(document)
        self.__document = copy.deepcopy(document)
        self.__receipt = receipt
        self.__token = token

    @classmethod
    def _create(
        cls, document: dict[str, Any],
        receipt: SelectionReceiptArtifact | None = None,
    ) -> "SelectionResult":
        return cls(_RESULT_TOKEN, document, receipt)

    @property
    def status(self) -> str:
        return self.__document["status"]

    @property
    def reason(self) -> str | None:
        return self.__document.get("reason")

    @property
    def receipt(self) -> SelectionReceiptArtifact | None:
        return self.__receipt

    @property
    def next_stage_request(self) -> dict[str, Any] | None:
        return self.as_dict() if self.status == "next-stage-request" else None

    @property
    def result_hash(self) -> str:
        return self.__document["resultHash"]

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.__document)


def select_modules(
    plan_graph: PlanGraphArtifact,
    stage_id: str,
    slot_id: str,
    attempt_ref: str,
    selection_input: SelectionInput,
    *,
    selector_module_id: str = "bounded-selector",
    selector_source_hash: str = _DEFAULT_SELECTOR_SOURCE_HASH,
) -> SelectionResult:
    """Select only within one immutable slot using typed in-memory values."""

    if type(plan_graph) is not PlanGraphArtifact:
        raise SelectorError("v3-plan-graph-not-typed")
    if type(selection_input) is not SelectionInput:
        raise SelectorError("v3-selection-input-not-typed")
    try:
        plan, specs = plan_graph._trusted_snapshot()
    except PlanGraphError as error:
        raise SelectorError(error.reason) from None
    # Revalidation is intentional even though the artifact provenance check
    # already includes the document.  This keeps the selector entry fail closed
    # if contract semantics change independently.
    try:
        from selfworkflow.v3.contracts import validate_plan_graph
        validate_plan_graph(plan)
    except ContractError as error:
        raise SelectorError(error.reason) from None

    _, slot = _find_slot(plan, stage_id, slot_id)
    _validate_stable_id(attempt_ref, "v3-selection-attempt-invalid")
    _validate_stable_id(selector_module_id, "v3-selector-module-invalid")
    _validate_hash(selector_source_hash, "v3-selector-source-hash-invalid")
    _validate_input(selection_input, slot)

    eligible = list(slot["eligibleModules"])
    _validate_unique(eligible, "v3-plan-eligible-duplicate")
    _validate_eligible_closure(eligible, stage_id, slot_id, specs)
    requested = list(selection_input.requested_module_ids)
    _validate_unique(requested, "v3-requested-module-duplicate")
    outside_requested = sorted(set(requested) - set(eligible))
    if outside_requested:
        if not set(outside_requested) <= set(specs):
            raise SelectorError("v3-selector-requested-module-unknown")
        return _outcome(
            "next-stage-request", plan, slot, attempt_ref, selection_input,
            "outside-eligible-set", outside_requested,
        )

    candidates = (
        eligible if selection_input.candidate_module_ids is None
        else list(selection_input.candidate_module_ids)
    )
    _validate_unique(candidates, "v3-selector-candidate-duplicate")
    if not set(candidates) <= set(eligible):
        raise SelectorError("v3-selector-candidate-outside-eligible")
    preferred = list(selection_input.preferred_module_ids)
    _validate_unique(preferred, "v3-selector-preferred-duplicate")
    if not set(preferred) <= set(candidates):
        raise SelectorError("v3-selector-preferred-outside-candidates")

    if slot["selectionMode"] == "static":
        selected = list(slot["selectedModules"])
        if not set(selected) <= set(candidates):
            raise SelectorError("v3-static-selection-not-candidate")
    else:
        selected = _choose(
            slot, candidates, preferred, specs,
            selection_input.context_budget,
            selection_input.execution_budget,
        )
    _validate_selected_set(slot, selected, candidates, specs)

    context_cost, execution_cost = _costs(selected, specs)
    if (
        selection_input.context_budget is not None
        and context_cost > selection_input.context_budget
    ):
        if slot["cardinality"] in {"exactly-one", "gate"}:
            return _outcome(
                "paused", plan, slot, attempt_ref, selection_input,
                "context-budget-exceeded", (),
            )
        selected = []
        context_cost, execution_cost = 0, 0
    if (
        selection_input.execution_budget is not None
        and execution_cost > selection_input.execution_budget
    ):
        if slot["cardinality"] in {"exactly-one", "gate"}:
            return _outcome(
                "paused", plan, slot, attempt_ref, selection_input,
                "execution-budget-exceeded", (),
            )
        selected = []
        context_cost, execution_cost = 0, 0

    if slot["cardinality"] in {"exactly-one", "gate"} and not selected:
        reason = _unavailable_reason(
            candidates, specs, selection_input.context_budget,
            selection_input.execution_budget,
        )
        return _outcome(
            "paused", plan, slot, attempt_ref, selection_input, reason, (),
        )

    reasons = [
        "selection.deterministic-order",
        f"selection.cardinality.{slot['cardinality']}",
    ]
    coverage = _coverage_decisions(
        slot, selected, selection_input, reasons,
    )
    receipt_without_hash = {
        "schemaVersion": 3,
        "planHash": plan["planHash"],
        "stageId": stage_id,
        "slotId": slot_id,
        "attemptRef": attempt_ref,
        "selectionPolicyHash": slot["selectionPolicyHash"],
        "selectorModuleId": selector_module_id,
        "selectorSourceHash": selector_source_hash,
        "inputArtifactId": selection_input.artifact_id,
        "inputArtifactHash": selection_input.artifact_hash,
        "eligibleModuleIds": eligible,
        "selectedModuleIds": selected,
        "selectionReasons": sorted(set(reasons)),
        "signalEvidenceRefs": list(selection_input.signal_evidence_refs),
        "estimatedContextCost": context_cost,
        "estimatedExecutionCost": execution_cost,
        "coverageDecisions": coverage,
    }
    receipt_document = {
        **receipt_without_hash,
        "receiptHash": _value_hash(receipt_without_hash),
    }
    try:
        validate_selection_receipt(receipt_document, plan, specs)
    except ContractError as error:
        raise SelectorError(error.reason) from None
    receipt = SelectionReceiptArtifact._create(receipt_document)
    selected_result = _result_document(
        status="selected", plan=plan, slot=slot, attempt_ref=attempt_ref,
        selection_input=selection_input, reason="selection-complete",
        requested_module_ids=(), receipt_hash=receipt.receipt_hash,
    )
    return SelectionResult._create(selected_result, receipt)


def _outcome(
    status: str,
    plan: Mapping[str, Any],
    slot: Mapping[str, Any],
    attempt_ref: str,
    selection_input: SelectionInput,
    reason: str,
    requested_module_ids: Sequence[str],
) -> SelectionResult:
    document = _result_document(
        status=status, plan=plan, slot=slot, attempt_ref=attempt_ref,
        selection_input=selection_input, reason=reason,
        requested_module_ids=requested_module_ids, receipt_hash=None,
    )
    return SelectionResult._create(document)


def _result_document(
    *,
    status: str,
    plan: Mapping[str, Any],
    slot: Mapping[str, Any],
    attempt_ref: str,
    selection_input: SelectionInput,
    reason: str,
    requested_module_ids: Sequence[str],
    receipt_hash: str | None,
) -> dict[str, Any]:
    material = {
        "schemaVersion": 3,
        "status": status,
        "planHash": plan["planHash"],
        "stageId": next(
            stage["stageId"] for stage in plan["stages"]
            if any(item is slot for item in stage["slots"])
        ),
        "slotId": slot["slotId"],
        "attemptRef": attempt_ref,
        "inputArtifactHash": selection_input.artifact_hash,
        "selectionPolicyHash": slot["selectionPolicyHash"],
        "reason": reason,
        "requestedModuleIds": sorted(requested_module_ids),
        "receiptHash": receipt_hash,
    }
    return {**material, "resultHash": _value_hash(material)}


def _validate_result_document(document: Mapping[str, Any]) -> None:
    required = {
        "schemaVersion", "status", "planHash", "stageId", "slotId",
        "attemptRef", "inputArtifactHash", "selectionPolicyHash", "reason",
        "requestedModuleIds", "receiptHash", "resultHash",
    }
    if set(document) != required or document.get("schemaVersion") != 3:
        raise SelectorError("v3-selection-result-invalid")
    if document.get("status") not in {
        "selected", "paused", "next-stage-request",
    }:
        raise SelectorError("v3-selection-result-invalid")
    for field in (
        "planHash", "inputArtifactHash", "selectionPolicyHash", "resultHash",
    ):
        _validate_hash(document.get(field), "v3-selection-result-invalid")
    if document["receiptHash"] is not None:
        _validate_hash(document["receiptHash"], "v3-selection-result-invalid")
    expected = dict(document)
    expected.pop("resultHash")
    if document["resultHash"] != _value_hash(expected):
        raise SelectorError("v3-selection-result-hash-invalid")
    _validate_unique(
        document["requestedModuleIds"], "v3-selection-result-invalid",
    )


def _find_slot(
    document: Mapping[str, Any], stage_id: str, slot_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    for stage in document["stages"]:
        if stage["stageId"] != stage_id:
            continue
        for slot in stage["slots"]:
            if slot["slotId"] == slot_id:
                if slot["applicability"] != "applicable":
                    raise SelectorError("v3-selector-slot-not-applicable")
                return stage, slot
        raise SelectorError("v3-selector-slot-unknown")
    raise SelectorError("v3-selector-stage-unknown")


def _validate_input(value: SelectionInput, slot: Mapping[str, Any]) -> None:
    _validate_stable_id(value.artifact_id, "v3-selection-artifact-id-invalid")
    _validate_hash(value.artifact_hash, "v3-selection-artifact-hash-invalid")
    id_lists = (
        value.candidate_module_ids or (), value.preferred_module_ids,
        value.signal_evidence_refs, value.requested_module_ids,
    )
    for values in id_lists:
        for item in values:
            _validate_stable_id(item, "v3-selection-id-invalid")
        _validate_unique(values, "v3-selection-id-duplicate")
    for budget in (value.context_budget, value.execution_budget):
        if budget is not None and (type(budget) is not int or budget < 0):
            raise SelectorError("v3-selection-budget-invalid")

    obligations = set(slot["coverageObligations"])
    seen_obligations: set[str] = set()
    seen_evidence: set[str] = set()
    signal_evidence = set(value.signal_evidence_refs)
    for obligation, evidence_refs in value.coverage_evidence_by_obligation:
        if obligation in seen_obligations or obligation not in obligations:
            raise SelectorError("v3-selection-coverage-obligation-invalid")
        seen_obligations.add(obligation)
        _validate_unique(evidence_refs, "v3-selection-coverage-evidence-duplicate")
        if not set(evidence_refs) <= signal_evidence:
            raise SelectorError("v3-selection-coverage-evidence-invalid")
        if seen_evidence & set(evidence_refs):
            raise SelectorError("v3-selection-coverage-evidence-reused")
        seen_evidence.update(evidence_refs)


def _validate_eligible_closure(
    eligible: Sequence[str], stage_id: str, slot_id: str,
    specs: Mapping[str, ModuleSpec],
) -> None:
    eligible_set = set(eligible)
    for module_id in eligible:
        spec = specs.get(module_id)
        if spec is None:
            raise SelectorError("v3-selector-module-metadata-missing")
        if spec.stage != stage_id or spec.slot != slot_id:
            raise SelectorError("v3-selector-module-boundary-mismatch")
        if not set(spec.dependencies) <= eligible_set:
            raise SelectorError("v3-selector-eligible-dependency-open")


def _choose(
    slot: Mapping[str, Any], candidates: Sequence[str], preferred: Sequence[str],
    specs: Mapping[str, ModuleSpec], context_budget: int | None,
    execution_budget: int | None,
) -> list[str]:
    order = list(preferred) + sorted(set(candidates) - set(preferred))
    selected: set[str] = set()
    for module_id in order:
        closure = _dependency_closure(module_id, specs, set(candidates))
        if closure is None or _has_conflict(closure, specs):
            continue
        candidate_selection = selected | closure
        if _has_conflict(candidate_selection, specs):
            continue
        if (
            slot["cardinality"] in {"exactly-one", "zero-or-one"}
            and len(candidate_selection) > 1
        ):
            continue
        context_cost, execution_cost = _costs(candidate_selection, specs)
        if context_budget is not None and context_cost > context_budget:
            continue
        if execution_budget is not None and execution_cost > execution_budget:
            continue
        selected = candidate_selection
        if slot["cardinality"] in {"exactly-one", "zero-or-one"}:
            break
    return sorted(selected)


def _dependency_closure(
    module_id: str, specs: Mapping[str, ModuleSpec], candidates: set[str],
) -> set[str] | None:
    result: set[str] = set()
    visiting: set[str] = set()

    def visit(current: str) -> bool:
        if current in result:
            return True
        if current in visiting or current not in candidates or current not in specs:
            return False
        visiting.add(current)
        if not all(visit(item) for item in specs[current].dependencies):
            return False
        visiting.remove(current)
        result.add(current)
        return True

    return result if visit(module_id) else None


def _has_conflict(
    selected: set[str], specs: Mapping[str, ModuleSpec],
) -> bool:
    return any(
        set(specs[module_id].conflicts) & (selected - {module_id})
        for module_id in selected
    )


def _validate_selected_set(
    slot: Mapping[str, Any], selected: Sequence[str], candidates: Sequence[str],
    specs: Mapping[str, ModuleSpec],
) -> None:
    selected_set = set(selected)
    if len(selected_set) != len(selected) or not selected_set <= set(candidates):
        raise SelectorError("v3-selector-selected-set-invalid")
    for module_id in selected:
        if not set(specs[module_id].dependencies) <= selected_set:
            raise SelectorError("v3-selector-selected-dependency-open")
    if _has_conflict(selected_set, specs):
        raise SelectorError("v3-selector-selected-conflict")
    cardinality_valid = {
        "exactly-one": len(selected) == 1,
        "zero-or-one": len(selected) <= 1,
        "zero-or-many": True,
        "gate": len(selected) >= 1,
    }[slot["cardinality"]]
    if not cardinality_valid and selected:
        raise SelectorError("v3-selector-cardinality-invalid")


def _costs(
    selected: Sequence[str] | set[str], specs: Mapping[str, ModuleSpec],
) -> tuple[int, int]:
    return (
        sum(specs[item].context_cost for item in selected),
        sum(specs[item].execution_cost for item in selected),
    )


def _unavailable_reason(
    candidates: Sequence[str], specs: Mapping[str, ModuleSpec],
    context_budget: int | None, execution_budget: int | None,
) -> str:
    for module_id in candidates:
        closure = _dependency_closure(module_id, specs, set(candidates))
        if closure is None or _has_conflict(closure, specs):
            continue
        context_cost, execution_cost = _costs(closure, specs)
        if context_budget is not None and context_cost > context_budget:
            return "context-budget-exceeded"
        if execution_budget is not None and execution_cost > execution_budget:
            return "execution-budget-exceeded"
    return "required-module-unavailable"


def _coverage_decisions(
    slot: Mapping[str, Any], selected: Sequence[str], value: SelectionInput,
    reasons: list[str],
) -> list[dict[str, Any]]:
    bindings = dict(value.coverage_evidence_by_obligation)
    decisions = []
    for obligation in slot["coverageObligations"]:
        evidence = list(bindings.get(obligation, ()))
        if selected and evidence:
            decision = "fulfilled"
            reasons.append("coverage.fulfilled")
        elif selected:
            decision = "unverified"
        else:
            decision = "blocked"
        decisions.append({
            "obligationId": obligation,
            "decision": decision,
            "evidenceRefs": evidence,
        })
    return decisions


def _validate_stable_id(value: Any, reason: str) -> None:
    if not isinstance(value, str) or _STABLE_ID.fullmatch(value) is None:
        raise SelectorError(reason)


def _validate_hash(value: Any, reason: str) -> None:
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", value)
    ):
        raise SelectorError(reason)


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


def _value_hash(value: Any) -> str:
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise SelectorError("v3-selector-canonical-value-invalid") from None
    return "sha256:" + hashlib.sha256(payload).hexdigest()
