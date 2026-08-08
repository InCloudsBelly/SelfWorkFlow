"""Deterministic workflow classification and capability policies."""

from collections.abc import Iterable, Mapping

from selfworkflow.model import (
    CapabilityReport,
    CapabilityState,
    Complexity,
    MANDATORY_CAPABILITY_BOUNDARIES,
    OneTimeAlternative,
    OneTimeAlternativeAction,
    PauseResult,
    Risk,
    TaskClassification,
    WorkflowInputError,
    _coerce_complexity,
    _coerce_risk,
    _normalize_string_pairs,
    _normalize_string_sequence,
)


def workflow_strength(complexity: Complexity | str, risk: Risk | str) -> str:
    """Return the pure Light/Full/Deep matrix used by modular planning."""

    c = int(_coerce_complexity(complexity).value[1])
    r = int(_coerce_risk(risk).value[1])
    if c == 3 or r == 3 or (c == 2 and r == 2):
        return "Deep"
    if c == 2 or r == 2:
        return "Full"
    return "Light"


def _capability_gap_reason(state: CapabilityState | None) -> str:
    if state is CapabilityState.UNSUPPORTED:
        return "capability is unsupported"
    if state is CapabilityState.UNVERIFIED:
        return "capability support is unverified"
    return "capability was not reported"


def _capability_gap_recommendation(
    name: str,
    state: CapabilityState | None,
) -> str:
    if state is CapabilityState.UNSUPPORTED:
        return f"provide supported capability: {name}"
    if state is CapabilityState.UNVERIFIED:
        return f"manually verify support or provide capability: {name}"
    return f"report and verify capability support: {name}"


def _capability_one_time_alternative(
    name: str,
    state: CapabilityState | None,
) -> OneTimeAlternative:
    if state is CapabilityState.UNSUPPORTED:
        action = OneTimeAlternativeAction.MANUAL_ALTERNATIVE
    elif state is CapabilityState.UNVERIFIED:
        action = OneTimeAlternativeAction.MANUAL_VERIFY
    else:
        action = OneTimeAlternativeAction.MANUAL_REPORT_AND_VERIFY
    return OneTimeAlternative(name, action)


def check_capabilities(
    required_capabilities: Iterable[str],
    report: CapabilityReport,
    *,
    purposes: Mapping[str, str] | None = None,
) -> PauseResult | None:
    """Pause unless every required capability is reported as supported."""

    if not isinstance(report, CapabilityReport):
        raise WorkflowInputError("capability-gate-input-invalid")
    required = _normalize_string_sequence(
        required_capabilities,
        "capability-gate-input-invalid",
    )
    if any(not name for name in required):
        raise WorkflowInputError("capability-gate-input-invalid")

    if purposes is None:
        purpose_by_name: dict[str, str] = {}
    elif not isinstance(purposes, Mapping):
        raise WorkflowInputError("capability-gate-input-invalid")
    else:
        normalized_purposes = _normalize_string_pairs(
            purposes,
            "capability-gate-input-invalid",
        )
        if any(not name for name, _ in normalized_purposes):
            raise WorkflowInputError("capability-gate-input-invalid")
        purpose_by_name = dict(normalized_purposes)

    missing = tuple(
        sorted(
            {
                name
                for name in required
                if report.state_for(name) is not CapabilityState.SUPPORTED
            }
        )
    )
    if not missing:
        return None

    one_time_alternatives = tuple(
        _capability_one_time_alternative(
            name,
            report.state_for(name),
        )
        for name in missing
    )

    return PauseResult(
        missing_capabilities=missing,
        purposes=tuple(
            (name, purpose_by_name.get(name, "required task capability"))
            for name in missing
        ),
        reasons=tuple(
            (name, _capability_gap_reason(report.state_for(name)))
            for name in missing
        ),
        recommendations=tuple(
            (name, _capability_gap_recommendation(name, report.state_for(name)))
            for name in missing
        ),
        one_time_alternatives=one_time_alternatives,
        non_waivable_boundaries=MANDATORY_CAPABILITY_BOUNDARIES,
    )


def classify_task(
    complexity: Complexity | str,
    risk: Risk | str,
    *,
    ambiguity: bool = False,
    global_minimum_complexity: Complexity | str = Complexity.C0,
    global_minimum_risk: Risk | str = Risk.R0,
    project_minimum_complexity: Complexity | str | None = None,
    project_minimum_risk: Risk | str | None = None,
    user_complexity: Complexity | str | None = None,
    user_risk: Risk | str | None = None,
) -> TaskClassification:
    """Return a classification for explicit C/R inputs without semantic inference."""

    if not isinstance(ambiguity, bool):
        raise WorkflowInputError("classification-input-invalid")
    resolved_complexity = _coerce_complexity(complexity)
    resolved_risk = _coerce_risk(risk)
    reasons: list[str] = []

    if ambiguity:
        complexity_level = int(resolved_complexity.value[1])
        risk_level = int(resolved_risk.value[1])
        if complexity_level < 3:
            upgraded_complexity = Complexity(f"C{complexity_level + 1}")
            reasons.append(
                "ambiguity upgraded complexity "
                f"from {resolved_complexity.value} to {upgraded_complexity.value}"
            )
            resolved_complexity = upgraded_complexity
        else:
            reasons.append("ambiguity kept complexity at C3 (maximum)")

        if risk_level < 3:
            upgraded_risk = Risk(f"R{risk_level + 1}")
            reasons.append(
                "ambiguity upgraded risk "
                f"from {resolved_risk.value} to {upgraded_risk.value}"
            )
            resolved_risk = upgraded_risk
        else:
            reasons.append("ambiguity kept risk at R3 (maximum)")

    minimum_complexity = _coerce_complexity(global_minimum_complexity)
    minimum_risk = _coerce_risk(global_minimum_risk)

    if project_minimum_complexity is not None:
        project_complexity = _coerce_complexity(project_minimum_complexity)
        if project_complexity.value < minimum_complexity.value:
            reasons.append(
                "project minimum complexity "
                f"{project_complexity.value} rejected below global minimum "
                f"{minimum_complexity.value}"
            )
        elif project_complexity.value > minimum_complexity.value:
            reasons.append(
                "project minimum complexity raised global minimum "
                f"from {minimum_complexity.value} to {project_complexity.value}"
            )
            minimum_complexity = project_complexity

    if project_minimum_risk is not None:
        project_risk = _coerce_risk(project_minimum_risk)
        if project_risk.value < minimum_risk.value:
            reasons.append(
                "project minimum risk "
                f"{project_risk.value} rejected below global minimum "
                f"{minimum_risk.value}"
            )
        elif project_risk.value > minimum_risk.value:
            reasons.append(
                "project minimum risk raised global minimum "
                f"from {minimum_risk.value} to {project_risk.value}"
            )
            minimum_risk = project_risk

    if resolved_complexity.value < minimum_complexity.value:
        reasons.append(
            "minimum upgraded complexity "
            f"from {resolved_complexity.value} to {minimum_complexity.value}"
        )
        resolved_complexity = minimum_complexity
    if resolved_risk.value < minimum_risk.value:
        reasons.append(
            "minimum upgraded risk "
            f"from {resolved_risk.value} to {minimum_risk.value}"
        )
        resolved_risk = minimum_risk

    if user_complexity is not None:
        requested_complexity = _coerce_complexity(user_complexity)
        if requested_complexity.value < minimum_complexity.value:
            reasons.append(
                "user complexity "
                f"{requested_complexity.value} rejected below minimum "
                f"{minimum_complexity.value}"
            )
        elif requested_complexity.value > resolved_complexity.value:
            reasons.append(
                "user upgraded complexity "
                f"from {resolved_complexity.value} to {requested_complexity.value}"
            )
            resolved_complexity = requested_complexity
        elif requested_complexity.value < resolved_complexity.value:
            reasons.append(
                "user complexity "
                f"{requested_complexity.value} rejected downgrade from "
                f"{resolved_complexity.value}"
            )

    if user_risk is not None:
        requested_risk = _coerce_risk(user_risk)
        if requested_risk.value < minimum_risk.value:
            reasons.append(
                f"user risk {requested_risk.value} rejected below minimum "
                f"{minimum_risk.value}"
            )
        elif requested_risk.value > resolved_risk.value:
            reasons.append(
                "user upgraded risk "
                f"from {resolved_risk.value} to {requested_risk.value}"
            )
            resolved_risk = requested_risk
        elif requested_risk.value < resolved_risk.value:
            reasons.append(
                f"user risk {requested_risk.value} rejected downgrade from "
                f"{resolved_risk.value}"
            )

    return TaskClassification(resolved_complexity, resolved_risk, tuple(reasons))
