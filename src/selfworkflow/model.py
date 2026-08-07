"""Immutable, vendor-neutral workflow domain models."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum


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


@dataclass(frozen=True, init=False)
class CapabilityReport:
    states: tuple[tuple[str, CapabilityState], ...]

    def __init__(
        self,
        states: Mapping[str, CapabilityState | str]
        | Iterable[tuple[str, CapabilityState | str]],
    ) -> None:
        entries = states.items() if isinstance(states, Mapping) else states
        normalized: dict[str, CapabilityState] = {}
        for name, state in entries:
            if not isinstance(name, str) or not name:
                raise ValueError("capability name must be a non-empty string")
            if name in normalized:
                raise ValueError(f"duplicate capability: {name}")
            normalized[name] = CapabilityState(state)
        object.__setattr__(self, "states", tuple(sorted(normalized.items())))

    def state_for(self, name: str) -> CapabilityState | None:
        """Return the declared state for a capability, if reported."""

        return dict(self.states).get(name)


@dataclass(frozen=True)
class PauseResult:
    missing_capabilities: tuple[str, ...]
    purposes: tuple[tuple[str, str], ...]
    reasons: tuple[tuple[str, str], ...]
    recommendations: tuple[tuple[str, str], ...]
    status: ExecutionStatus = field(default=ExecutionStatus.PAUSED, init=False)
    code: str = field(default="required-capabilities-unavailable", init=False)


@dataclass(frozen=True)
class TaskClassification:
    complexity: Complexity
    risk: Risk
    reasons: tuple[str, ...] = ()
    requires_full_design: bool = field(init=False)
    suggest_grill_me: bool = field(init=False)

    def __post_init__(self) -> None:
        complexity = Complexity(self.complexity)
        risk = Risk(self.risk)
        object.__setattr__(self, "complexity", complexity)
        object.__setattr__(self, "risk", risk)
        object.__setattr__(self, "reasons", tuple(self.reasons))
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
