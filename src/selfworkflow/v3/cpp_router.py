"""Bounded, provider-neutral C++ capability routing.

The router selects reasoning lenses only.  It never launches a debugger,
compiler, indexer, or heavy audit provider; those remain separately planned and
authorized operations.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping


_CPP_LANGUAGES = frozenset({"c", "cpp", "c++", "objective-c++", "cuda"})
_CPP_EXTENSIONS = frozenset({
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl",
    ".ixx", ".cppm", ".cu", ".cuh",
})
_OPERATIONS = frozenset({"analyze", "design", "plan", "implement", "debug", "review", "verify"})
_RISKS = frozenset({"R0", "R1", "R2", "R3"})
_MODULE_ORDER = (
    "cpp-core",
    "cpp.ownership",
    "cpp.type-system",
    "cpp.concurrency",
    "cpp.abi",
    "cpp.performance",
    "cpp.safety",
    "cpp.build",
    "cpp.debugging",
    "cpp.engine.unreal",
    "cpp.audit",
)
_MODULE_COST = MappingProxyType({
    "cpp-core": 420,
    "cpp.ownership": 180,
    "cpp.type-system": 190,
    "cpp.concurrency": 220,
    "cpp.abi": 210,
    "cpp.performance": 190,
    "cpp.safety": 200,
    "cpp.build": 180,
    "cpp.debugging": 210,
    "cpp.engine.unreal": 240,
    "cpp.audit": 360,
})
_SIGNALS = MappingProxyType({
    "cpp.ownership": frozenset({
        "ownership", "lifetime", "raii", "resource", "pointer", "reference",
        "smart-pointer", "use-after-free", "double-free", "memory-leak",
    }),
    "cpp.type-system": frozenset({
        "template", "concept", "overload", "deduction", "metaprogramming",
        "sfinae", "constexpr", "type-system",
    }),
    "cpp.concurrency": frozenset({
        "thread", "lock", "deadlock", "race", "atomic", "atomics",
        "memory-order", "async", "coroutine", "concurrency",
    }),
    "cpp.abi": frozenset({
        "abi", "binary-compatibility", "odr", "layout", "vtable", "export",
        "serialization-compatibility", "plugin-boundary",
    }),
    "cpp.performance": frozenset({
        "performance", "allocation", "cache", "copy", "simd", "complexity",
        "hot-path", "profiling", "latency", "throughput",
    }),
    "cpp.safety": frozenset({
        "undefined-behavior", "ub", "integer-overflow", "bounds", "aliasing",
        "iterator", "exception-safety", "security-critical", "memory-corruption",
    }),
    "cpp.build": frozenset({
        "compile", "compiler", "link", "linker", "macro", "preprocessor",
        "toolchain", "cmake", "build-system", "pch", "unity-build",
    }),
    "cpp.debugging": frozenset({
        "debug", "native-crash", "crash", "stack-trace", "core-dump",
        "sanitizer", "asan", "tsan", "ubsan", "symbols",
    }),
    "cpp.engine.unreal": frozenset({
        "unreal", "unreal-engine", "ue", "ue5", "uobject", "uht", "ubt",
        "game-thread", "render-thread", "rhi-thread", "reflection", "gc",
    }),
})
_SPECIALISTS = frozenset(_MODULE_ORDER[1:-1])
_HEAVY_SIGNALS = frozenset({
    "memory-corruption", "security-critical", "complex-concurrency",
    "forensic", "deep-audit",
})
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class CppRouteError(ValueError):
    """Stable failure for malformed or out-of-scope route requests."""


@dataclass(frozen=True)
class CppRouteRequest:
    operation_type: str
    languages: tuple[str, ...]
    file_extensions: tuple[str, ...]
    task_signals: tuple[str, ...]
    risk: str
    explicit_module_ids: tuple[str, ...]
    user_confirmed_heavy: bool
    project_allows_execution: bool


@dataclass(frozen=True)
class CppRouteResult:
    selected_module_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    recommended_capability_ids: tuple[str, ...]
    unverified_items: tuple[str, ...]
    module_load_trace: tuple[MappingProxyType, ...]
    context_cost: int
    route_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "selectedModuleIds": list(self.selected_module_ids),
            "capabilityIds": list(self.capability_ids),
            "recommendedCapabilityIds": list(self.recommended_capability_ids),
            "unverifiedItems": list(self.unverified_items),
            "moduleLoadTrace": [dict(item) for item in self.module_load_trace],
            "contextCost": self.context_cost,
            "routeHash": self.route_hash,
        }


def route_cpp_capabilities(request: CppRouteRequest) -> CppRouteResult:
    """Select only the C++ lenses justified by immutable request signals."""

    _validate_request(request)
    cpp_task = bool(
        _CPP_LANGUAGES.intersection(item.casefold() for item in request.languages)
        or _CPP_EXTENSIONS.intersection(item.casefold() for item in request.file_extensions)
    ) and request.operation_type in _OPERATIONS
    if not cpp_task:
        if request.explicit_module_ids:
            raise CppRouteError("cpp-route-explicit-module-not-applicable")
        return _result((), (), (), (), ())

    signals = {item.casefold() for item in request.task_signals}
    selected = {"cpp-core"}
    reasons: dict[str, str] = {"cpp-core": "cpp-task-common-invariants"}
    for module_id, triggers in _SIGNALS.items():
        matches = sorted(signals & triggers)
        if matches:
            selected.add(module_id)
            reasons[module_id] = "signal:" + matches[0]
    if request.operation_type == "debug":
        selected.add("cpp.debugging")
        reasons["cpp.debugging"] = "operation:debug"

    heavy_explicit = False
    for module_id in request.explicit_module_ids:
        if module_id not in _SPECIALISTS and module_id != "cpp.audit":
            raise CppRouteError("cpp-route-explicit-module-unknown")
        if module_id == "cpp.audit" and not request.user_confirmed_heavy:
            raise CppRouteError("cpp-route-heavy-confirmation-required")
        if module_id == "cpp.audit":
            heavy_explicit = True
            continue
        selected.add(module_id)
        reasons[module_id] = "explicit-module"

    heavy_recommended = (
        request.risk == "R3"
        and bool(signals & _HEAVY_SIGNALS)
        and request.operation_type in {"review", "debug", "analyze"}
    )
    recommendations: tuple[str, ...] = (
        ("cpp.audit",) if heavy_recommended or heavy_explicit else ()
    )
    unverified: set[str] = set()
    if heavy_recommended or heavy_explicit:
        if not request.user_confirmed_heavy:
            unverified.add("heavy-audit-user-confirmation-required")
        else:
            unverified.add("heavy-audit-provider-unverified")
    if "cpp.engine.unreal" in selected:
        unverified.add("native-build-unverified")
    if request.operation_type == "debug":
        unverified.add("runtime-debugger-not-authorized")

    ordered = tuple(item for item in _MODULE_ORDER if item in selected)
    capabilities = ["cpp.reasoning"]
    if request.operation_type == "debug":
        capabilities.append("debug.reason")
    capabilities.extend(item for item in ordered if item != "cpp-core")
    trace = tuple(
        MappingProxyType({
            "moduleId": module_id,
            "estimatedContextCost": _MODULE_COST[module_id],
            "reason": reasons[module_id],
        })
        for module_id in ordered
    )
    return _result(
        ordered,
        tuple(dict.fromkeys(capabilities)),
        recommendations,
        tuple(sorted(unverified)),
        trace,
    )


def _validate_request(request: CppRouteRequest) -> None:
    if type(request) is not CppRouteRequest:
        raise CppRouteError("cpp-route-request-not-typed")
    if request.operation_type not in {
        "analyze", "design", "plan", "implement", "debug", "review", "verify", "document"
    } or request.risk not in _RISKS:
        raise CppRouteError("cpp-route-request-invalid")
    for values in (
        request.languages, request.file_extensions, request.task_signals,
        request.explicit_module_ids,
    ):
        if type(values) is not tuple or any(
            type(item) is not str or not item or len(item.encode("utf-8")) > 256
            for item in values
        ):
            raise CppRouteError("cpp-route-request-invalid")
    if len(request.explicit_module_ids) != len(set(request.explicit_module_ids)):
        raise CppRouteError("cpp-route-explicit-module-duplicate")
    if any(_ID.fullmatch(item) is None for item in request.explicit_module_ids):
        raise CppRouteError("cpp-route-explicit-module-invalid")
    if type(request.user_confirmed_heavy) is not bool or type(request.project_allows_execution) is not bool:
        raise CppRouteError("cpp-route-request-invalid")


def _result(
    modules: tuple[str, ...],
    capabilities: tuple[str, ...],
    recommendations: tuple[str, ...],
    unverified: tuple[str, ...],
    trace: tuple[MappingProxyType, ...],
) -> CppRouteResult:
    context_cost = sum(item["estimatedContextCost"] for item in trace)
    material = {
        "selectedModuleIds": list(modules),
        "capabilityIds": list(capabilities),
        "recommendedCapabilityIds": list(recommendations),
        "unverifiedItems": list(unverified),
        "moduleLoadTrace": [dict(item) for item in trace],
        "contextCost": context_cost,
    }
    payload = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return CppRouteResult(
        modules, capabilities, recommendations, unverified, trace, context_cost,
        "sha256:" + hashlib.sha256(payload).hexdigest(),
    )


def request_from_code_signals(
    request: Mapping[str, Any], code_signals: Mapping[str, Any],
) -> CppRouteRequest:
    """Build the typed router input only from the closed V3 signal object."""

    return CppRouteRequest(
        operation_type=request["operationType"],
        languages=tuple(code_signals["languages"]),
        file_extensions=tuple(code_signals["fileExtensions"]),
        task_signals=tuple(code_signals["taskSignals"]),
        risk=request["risk"],
        explicit_module_ids=tuple(code_signals["explicitCppModuleIds"]),
        user_confirmed_heavy=code_signals["userConfirmedHeavy"],
        project_allows_execution=code_signals["projectAllowsExecution"],
    )
