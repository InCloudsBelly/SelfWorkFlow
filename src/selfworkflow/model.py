"""Immutable, vendor-neutral workflow domain models."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum


class WorkflowInputError(ValueError):
    """Stable domain input failure that never includes the rejected value."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _materialize_ordered(value: object, code: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes, set, frozenset, Mapping)) or not isinstance(
        value, Iterable
    ):
        raise WorkflowInputError(code)
    try:
        return tuple(value)
    except Exception:
        raise WorkflowInputError(code) from None


def _materialize_mapping_items(
    value: Mapping[object, object],
    code: str,
) -> tuple[object, ...]:
    try:
        items = value.items()
    except Exception:
        raise WorkflowInputError(code) from None
    return _materialize_ordered(items, code)


def _normalize_string_sequence(value: object, code: str) -> tuple[str, ...]:
    normalized = _materialize_ordered(value, code)
    if any(type(item) is not str for item in normalized):
        raise WorkflowInputError(code)
    return normalized


def _normalize_string_pairs(
    value: object,
    code: str,
) -> tuple[tuple[str, str], ...]:
    is_mapping = isinstance(value, Mapping)
    if is_mapping:
        entries = _materialize_mapping_items(value, code)
    else:
        entries = _materialize_ordered(value, code)

    normalized: list[tuple[str, str]] = []
    for entry in entries:
        pair = _materialize_ordered(entry, code)
        if len(pair) != 2 or any(type(item) is not str for item in pair):
            raise WorkflowInputError(code)
        normalized.append((pair[0], pair[1]))
    if is_mapping:
        normalized.sort(key=lambda pair: pair[0])
    return tuple(normalized)


class Complexity(str, Enum):
    C0 = "C0"
    C1 = "C1"
    C2 = "C2"
    C3 = "C3"


class Risk(str, Enum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


def _coerce_complexity(value: object) -> Complexity:
    if type(value) is Complexity:
        return value
    if type(value) is not str:
        raise WorkflowInputError("classification-input-invalid")
    try:
        return Complexity(value)
    except (TypeError, ValueError):
        raise WorkflowInputError("classification-input-invalid") from None


def _coerce_risk(value: object) -> Risk:
    if type(value) is Risk:
        return value
    if type(value) is not str:
        raise WorkflowInputError("classification-input-invalid")
    try:
        return Risk(value)
    except (TypeError, ValueError):
        raise WorkflowInputError("classification-input-invalid") from None


class CapabilityState(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNVERIFIED = "unverified"


class ExecutionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"


class VerificationStatus(str, Enum):
    NOT_APPLICABLE = "not-applicable"
    NOT_RUN = "not-run"
    PARTIAL = "partial"
    PASSED = "passed"
    FAILED = "failed"

    @property
    def is_unverified(self) -> bool:
        """Return whether this status derives the user-visible unverified result."""

        return self in {VerificationStatus.NOT_RUN, VerificationStatus.PARTIAL}


REQUIRED_CAPABILITY_EVIDENCE_BOUNDARY = (
    "required capability cannot be treated as supported without evidence"
)


@dataclass(frozen=True, init=False)
class CapabilityReport:
    states: tuple[tuple[str, CapabilityState], ...]

    def __init__(
        self,
        states: Mapping[str, CapabilityState | str]
        | Iterable[tuple[str, CapabilityState | str]],
    ) -> None:
        if isinstance(states, Mapping):
            entries = _materialize_mapping_items(
                states,
                "capability-report-invalid",
            )
        else:
            entries = _materialize_ordered(states, "capability-report-invalid")

        normalized: dict[str, CapabilityState] = {}
        for entry in entries:
            pair = _materialize_ordered(entry, "capability-report-invalid")
            if len(pair) != 2:
                raise WorkflowInputError("capability-report-invalid")
            name, state = pair
            if type(name) is not str or not name:
                raise WorkflowInputError("capability-report-invalid")
            if name in normalized:
                raise WorkflowInputError("capability-report-invalid")
            if type(state) is CapabilityState:
                normalized[name] = state
                continue
            if type(state) is not str:
                raise WorkflowInputError("capability-report-invalid")
            try:
                normalized[name] = CapabilityState(state)
            except (TypeError, ValueError):
                raise WorkflowInputError("capability-report-invalid") from None
        object.__setattr__(self, "states", tuple(sorted(normalized.items())))

    def state_for(self, name: str) -> CapabilityState | None:
        """Return the declared state for a capability, if reported."""

        if type(name) is not str or not name:
            raise WorkflowInputError("capability-report-invalid")
        return dict(self.states).get(name)


@dataclass(frozen=True)
class PauseResult:
    missing_capabilities: tuple[str, ...]
    purposes: tuple[tuple[str, str], ...]
    reasons: tuple[tuple[str, str], ...]
    recommendations: tuple[tuple[str, str], ...]
    one_time_alternatives: tuple[tuple[str, str], ...] = ()
    non_waivable_boundaries: tuple[str, ...] = ()
    status: ExecutionStatus = field(default=ExecutionStatus.PAUSED, init=False)
    code: str = field(default="required-capabilities-unavailable", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "missing_capabilities",
            _normalize_string_sequence(
                self.missing_capabilities,
                "pause-result-invalid",
            ),
        )
        for field_name in (
            "purposes",
            "reasons",
            "recommendations",
            "one_time_alternatives",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_string_pairs(
                    getattr(self, field_name),
                    "pause-result-invalid",
                ),
            )
        object.__setattr__(
            self,
            "non_waivable_boundaries",
            _normalize_string_sequence(
                self.non_waivable_boundaries,
                "pause-result-invalid",
            ),
        )
        missing = self.missing_capabilities
        if (
            not missing
            or any(not name for name in missing)
            or len(set(missing)) != len(missing)
            or missing != tuple(sorted(missing))
        ):
            raise WorkflowInputError("pause-result-invalid")
        for field_name in (
            "purposes",
            "reasons",
            "recommendations",
            "one_time_alternatives",
        ):
            pairs = getattr(self, field_name)
            if (
                tuple(name for name, _ in pairs) != missing
                or any(not value for _, value in pairs)
            ):
                raise WorkflowInputError("pause-result-invalid")
        boundaries = self.non_waivable_boundaries
        if (
            not boundaries
            or any(not boundary for boundary in boundaries)
            or len(set(boundaries)) != len(boundaries)
            or boundaries != tuple(sorted(boundaries))
            or REQUIRED_CAPABILITY_EVIDENCE_BOUNDARY not in boundaries
        ):
            raise WorkflowInputError("pause-result-invalid")


@dataclass(frozen=True)
class TaskClassification:
    complexity: Complexity
    risk: Risk
    reasons: tuple[str, ...] = ()
    requires_full_design: bool = field(init=False)
    suggest_grill_me: bool = field(init=False)

    def __post_init__(self) -> None:
        complexity = _coerce_complexity(self.complexity)
        risk = _coerce_risk(self.risk)
        object.__setattr__(self, "complexity", complexity)
        object.__setattr__(self, "risk", risk)
        object.__setattr__(
            self,
            "reasons",
            _normalize_string_sequence(
                self.reasons,
                "classification-input-invalid",
            ),
        )
        requires_full_design = (
            int(complexity.value[1]) >= 2 or int(risk.value[1]) >= 2
        )
        object.__setattr__(self, "requires_full_design", requires_full_design)
        suggest_grill_me = (
            int(complexity.value[1]) >= 3
            or int(risk.value[1]) >= 3
            or (complexity is Complexity.C2 and risk is Risk.R2)
        )
        object.__setattr__(self, "suggest_grill_me", suggest_grill_me)

    @property
    def requiresFullDesign(self) -> bool:
        """Return the contract-facing full design threshold."""

        return self.requires_full_design

    @property
    def suggestGrillMe(self) -> bool:
        """Return the contract-facing Grill-me suggestion threshold."""

        return self.suggest_grill_me
