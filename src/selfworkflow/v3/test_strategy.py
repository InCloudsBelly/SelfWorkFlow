"""Issuers for content-addressed V3 test strategy and coverage artifacts."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from selfworkflow.v3.contracts import (
    VerificationReceiptResolver,
    validate_coverage_result,
    validate_test_strategy,
)
from selfworkflow.v3.hashing import clone


class TestStrategyError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


_STRATEGY_FIELDS = {
    "schemaVersion", "planHash", "attemptRef", "createdAt", "basisKind",
    "finalDiffHash", "diffSignalSetHash", "testLevel", "testLevelFloor",
    "source", "grillMeImplementation", "risks", "acceptanceConditions",
    "dimensions", "techniques", "authorizationRequirements",
    "coverageObligations",
}
_RISK_FIELDS = {
    "riskId", "probability", "impact", "residualStatus", "acceptanceConditionIds",
}


def _priority(score: int) -> str:
    if score == 9:
        return "P0"
    if score >= 6:
        return "P1"
    if score >= 3:
        return "P2"
    return "P3"


def _contract_hash(document: dict[str, Any]) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def issue_test_strategy(
    material: Mapping[str, Any], *, plan_graph: dict[str, Any],
    run_ledger: dict[str, Any], diff_signal_set: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Issue one enriched strategy; callers cannot supply derived identity fields."""

    if not isinstance(material, Mapping) or set(material) != _STRATEGY_FIELDS - (
        set() if material.get("basisKind") == "diff" else {"finalDiffHash", "diffSignalSetHash"}
    ):
        raise TestStrategyError("test-strategy-material-invalid")
    document = clone(dict(material))
    risks = document.get("risks")
    if not isinstance(risks, list) or not risks:
        raise TestStrategyError("test-strategy-risk-invalid")
    seen: set[str] = set()
    residual: list[str] = []
    for risk in risks:
        if not isinstance(risk, dict) or set(risk) != _RISK_FIELDS:
            raise TestStrategyError("test-strategy-risk-invalid")
        risk_id = risk.get("riskId")
        probability = risk.get("probability")
        impact = risk.get("impact")
        if (
            not isinstance(risk_id, str) or risk_id in seen
            or type(probability) is not int or probability not in {1, 2, 3}
            or type(impact) is not int or impact not in {1, 2, 3}
            or risk.get("residualStatus") not in {"verified", "unverified"}
        ):
            raise TestStrategyError("test-strategy-risk-invalid")
        seen.add(risk_id)
        score = probability * impact
        risk["score"] = score
        risk["priority"] = _priority(score)
        if risk["residualStatus"] == "unverified":
            residual.append(risk_id)
    document["residualUnverified"] = sorted(residual)
    document["strategyHash"] = _contract_hash(document)
    try:
        validate_test_strategy(document, plan_graph, run_ledger, diff_signal_set)
    except Exception as error:
        reason = getattr(error, "reason", "test-strategy-material-invalid")
        raise TestStrategyError(reason) from None
    return clone(document)


def issue_coverage_result(
    material: Mapping[str, Any], *, diff_signal_set: dict[str, Any],
    test_strategy: dict[str, Any], run_ledger: dict[str, Any],
    verification_receipt_resolver: VerificationReceiptResolver | None = None,
) -> dict[str, Any]:
    """Issue coverage only after the existing trusted receipt validation succeeds."""

    if not isinstance(material, Mapping) or "resultHash" in material:
        raise TestStrategyError("coverage-result-material-invalid")
    document = clone(dict(material))
    document["resultHash"] = _contract_hash(document)
    validate_coverage_result(
        document,
        diff_signal_set,
        test_strategy,
        run_ledger,
        verification_receipt_resolver,
    )
    return clone(document)
