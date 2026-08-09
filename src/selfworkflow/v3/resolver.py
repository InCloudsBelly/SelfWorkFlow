"""Explicit V3 resolver: compile inputs and return an immutable PlanGraph."""

from __future__ import annotations

from collections.abc import Mapping
import copy
from typing import Any

from selfworkflow.v3.catalog import CompiledCatalog, CatalogError, compile_catalog
from selfworkflow.v3.contracts import ContractError, load_contract, validate_resolve_result
from selfworkflow.v3.pipeline import LoadedPipeline, PipelineError, load_pipeline
from selfworkflow.v3.plan_graph import PlanGraphError, build_plan_graph
from selfworkflow.v3.cpp_router import (
    CppRouteError,
    request_from_code_signals,
    route_cpp_capabilities,
)


class ResolveError(ValueError):
    """Stable V3 resolution error for malformed input."""

    def __init__(self, reason: str = "v3-resolve-failed") -> None:
        self.reason = reason
        super().__init__(reason)


def _load_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise ResolveError("v3-request-not-object")
    try:
        return load_contract(
            "resolve-request.schema.json",
            __import__("json").dumps(dict(request), sort_keys=True, separators=(",", ":")),
        )
    except ContractError as error:
        raise ResolveError(error.reason) from None


def _artifact_or_compile_catalog(source: object) -> CompiledCatalog:
    if type(source) is CompiledCatalog:
        return source
    try:
        return compile_catalog(source)
    except CatalogError as error:
        raise ResolveError(error.reason) from None


def _artifact_or_load_pipeline(source: object) -> LoadedPipeline:
    if type(source) is LoadedPipeline:
        return source
    try:
        return load_pipeline(source)
    except PipelineError as error:
        raise ResolveError(error.reason) from None


def resolve_request(
    request: Mapping[str, Any],
    *,
    catalog_source: object = None,
    pipeline_source: object = None,
    capability_snapshot: Mapping[str, Any] | None = None,
    provider_preference_snapshot: Mapping[str, Any] | None = None,
    provider_binding_snapshot: Mapping[str, Any] | None = None,
    execution_policy_snapshot: Mapping[str, Any] | None = None,
    policy_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a schema-valid V3 ResolveResult containing only its PlanGraph."""

    normalized = _load_request(request)
    plan_request = copy.deepcopy(normalized)
    capability_route = None
    if "codeSignals" in normalized:
        try:
            capability_route = route_cpp_capabilities(
                request_from_code_signals(normalized, normalized["codeSignals"])
            ).as_dict()
            plan_request["explicitModuleIds"] = sorted(set(
                plan_request["explicitModuleIds"]
            ) | set(capability_route["selectedModuleIds"]))
        except CppRouteError as error:
            raise ResolveError(str(error)) from None
    catalog = _artifact_or_compile_catalog(catalog_source)
    pipeline = _artifact_or_load_pipeline(pipeline_source)
    try:
        plan = build_plan_graph(
            plan_request,
            catalog,
            pipeline,
            capability_snapshot=capability_snapshot,
            provider_preference_snapshot=provider_preference_snapshot,
            provider_binding_snapshot=provider_binding_snapshot,
            execution_policy_snapshot=execution_policy_snapshot,
            policy_snapshot=policy_snapshot,
        )
    except PlanGraphError as error:
        result = {
            "schemaVersion": 3,
            "status": "paused",
            "reasonCodes": [getattr(error, "reason", "v3-resolution-failed")],
            "diagnostics": [{
                "code": getattr(error, "reason", "v3-resolution-failed"),
                "severity": "error",
                "message": getattr(error, "reason", "v3-resolution-failed"),
            }],
            "planGraph": None,
        }
        if capability_route is not None:
            result["capabilityRoute"] = capability_route
        try:
            validate_resolve_result(result)
        except ContractError as contract_error:
            raise ResolveError(contract_error.reason) from None
        return result
    result = {
        "schemaVersion": 3,
        "status": "active",
        "reasonCodes": [],
        "diagnostics": [],
        "planGraph": plan.as_dict(),
    }
    if capability_route is not None:
        result["capabilityRoute"] = capability_route
    try:
        validate_resolve_result(result)
    except ContractError as error:
        raise ResolveError(error.reason) from None
    return result


def resolve_task(
    catalog_source: object,
    request: Mapping[str, Any],
    *,
    pipeline_source: object = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """V2-shaped positional facade for callers migrating to explicit V3."""

    return resolve_request(
        request,
        catalog_source=catalog_source,
        pipeline_source=pipeline_source,
        **kwargs,
    )


resolve_v3 = resolve_request
