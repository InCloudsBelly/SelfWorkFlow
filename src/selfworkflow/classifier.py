"""Deterministic workflow classification and capability policies."""

from collections.abc import Iterable, Mapping

from selfworkflow.model import (
    CapabilityReport,
    CapabilityState,
    Complexity,
    PauseResult,
    Risk,
    TaskClassification,
)


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


def check_capabilities(
    required_capabilities: Iterable[str],
    report: CapabilityReport,
    *,
    purposes: Mapping[str, str] | None = None,
) -> PauseResult | None:
    """Pause unless every required capability is reported as supported."""

    purpose_by_name = dict(purposes or {})
    missing = tuple(
        sorted(
            {
                name
                for name in required_capabilities
                if report.state_for(name) is not CapabilityState.SUPPORTED
            }
        )
    )
    if not missing:
        return None

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

    resolved_complexity = Complexity(complexity)
    resolved_risk = Risk(risk)
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

    minimum_complexity = Complexity(global_minimum_complexity)
    minimum_risk = Risk(global_minimum_risk)

    if project_minimum_complexity is not None:
        project_complexity = Complexity(project_minimum_complexity)
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
        project_risk = Risk(project_minimum_risk)
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
        requested_complexity = Complexity(user_complexity)
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
        requested_risk = Risk(user_risk)
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
