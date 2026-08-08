"""Deterministic, bounded Skill routing over a compiled Catalog."""

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Mapping


_EXTENSION = re.compile(r"\.[a-z0-9][a-z0-9+._-]{0,31}")
_REASON_ORDER = {
    "mandatory": 0,
    "explicit": 1,
    "deterministic:file-extension": 2,
    "deterministic:operation-type": 3,
    "semantic": 4,
}


class RouteError(ValueError):
    """Stable, redacted route input failure."""

    def __init__(self, code: str = "route-input-invalid") -> None:
        self.code = code
        super().__init__("route-failed")


@dataclass(frozen=True)
class RouteRequest:
    stage: str
    operation_type: str
    file_extensions: tuple[str, ...] = ()
    semantic_terms: tuple[str, ...] = ()
    explicit_skills: tuple[str, ...] = ()
    mandatory_scopes: tuple[str, ...] = ("global", "safety", "project")
    capability_states: Mapping[str, str] | None = None
    context_budget: int = 4096
    max_semantic_candidates: int = 4


@dataclass(frozen=True)
class RouteCandidate:
    skill_id: str
    reasons: tuple[str, ...]
    semantic_score: int


@dataclass(frozen=True)
class RouteExclusion:
    skill_id: str
    reason: str


@dataclass(frozen=True)
class RouteStage:
    skill_ids: tuple[str, ...]
    context_cost: int


@dataclass(frozen=True)
class RouteResult:
    status: str
    selected: tuple[str, ...]
    candidates: tuple[RouteCandidate, ...]
    exclusions: tuple[RouteExclusion, ...]
    stages: tuple[RouteStage, ...]
    catalog_hash: str
    missing_capabilities: tuple[str, ...]
    issues: tuple[str, ...]


@dataclass(frozen=True)
class ModuleRouteRequest:
    slot_id: str
    cardinality: str
    operation_type: str
    strength: str
    write_task: bool
    explicit_module_ids: tuple[str, ...] = ()
    project_default_module_ids: tuple[str, ...] = ()
    capability_states: Mapping[str, str] | None = None


@dataclass(frozen=True)
class ModuleRouteResult:
    status: str
    selected_modules: tuple[str, ...]
    excluded_modules: tuple[tuple[str, str], ...]
    missing_capabilities: tuple[str, ...]
    reason_codes: tuple[str, ...]


def _canonical_hash(catalog: object) -> str:
    payload = json.dumps(
        catalog,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _load_envelope(content: bytes | str | Mapping[str, object]) -> dict[str, object]:
    if isinstance(content, bytes):
        if len(content) > 16 * 1024 * 1024:
            raise RouteError("catalog-too-large")
        value = json.loads(content.decode("utf-8"))
    elif isinstance(content, str):
        if len(content.encode("utf-8")) > 16 * 1024 * 1024:
            raise RouteError("catalog-too-large")
        value = json.loads(content)
    elif isinstance(content, Mapping):
        value = dict(content)
    else:
        raise RouteError()
    if (
        type(value) is not dict
        or set(value) != {"schemaVersion", "catalog", "catalogHash"}
        or value["schemaVersion"] not in {1, 2}
        or type(value["catalog"]) is not dict
        or type(value["catalogHash"]) is not str
        or _canonical_hash(value["catalog"]) != value["catalogHash"]
    ):
        raise RouteError("catalog-hash-invalid")
    return value


def _normalized_terms(values: tuple[str, ...]) -> set[str]:
    if len(values) > 256 or any(type(value) is not str or len(value) > 512 for value in values):
        raise RouteError()
    return {value.strip().casefold() for value in values if value.strip()}


def _conditional_mandatory(entry: dict[str, object], request: RouteRequest) -> bool:
    if entry["mandatory"]:
        return True
    condition = entry["mandatoryWhen"]
    checks: list[bool] = []
    if condition["scopes"]:
        checks.append(bool(set(condition["scopes"]) & set(request.mandatory_scopes)))
    if condition["fileExtensions"]:
        checks.append(bool(set(condition["fileExtensions"]) & set(request.file_extensions)))
    if condition["operationTypes"]:
        checks.append(request.operation_type in condition["operationTypes"])
    if not checks:
        return False
    return all(checks) if condition["match"] == "all" else any(checks)


def _reason_key(reason: str) -> tuple[int, str]:
    if reason.startswith("dependency:"):
        return (5, reason)
    return (_REASON_ORDER.get(reason, 99), reason)


def _route_skills(
    content: bytes | str | Mapping[str, object],
    request: RouteRequest,
) -> RouteResult:
    envelope = _load_envelope(content)
    catalog = envelope["catalog"]
    entries = catalog.get("entries")
    if type(entries) is not list or len(entries) > 4096:
        raise RouteError()
    entry_by_id: dict[str, dict[str, object]] = {}
    aliases: dict[str, str] = {}
    for entry in entries:
        if type(entry) is not dict or type(entry.get("id")) is not str:
            raise RouteError()
        skill_id = entry["id"]
        if skill_id in entry_by_id:
            raise RouteError()
        entry_by_id[skill_id] = entry
        for alias in entry.get("aliases", ()):
            if type(alias) is not dict:
                raise RouteError()
            aliases[alias["name"]] = alias["target"]

    if (
        type(request.stage) is not str
        or type(request.operation_type) is not str
        or type(request.context_budget) is not int
        or request.context_budget <= 0
        or type(request.max_semantic_candidates) is not int
        or not 0 <= request.max_semantic_candidates <= 32
        or len(request.file_extensions) > 128
        or any(
            type(extension) is not str or _EXTENSION.fullmatch(extension) is None
            for extension in request.file_extensions
        )
    ):
        raise RouteError()
    semantic_terms = _normalized_terms(request.semantic_terms)
    request_extensions = tuple(dict.fromkeys(request.file_extensions))
    issues: set[str] = set()
    exclusions: dict[str, str] = {}
    proposals: dict[str, dict[str, object]] = {}

    def propose(skill_id: str, rank: int, reason: str, score: int = 0) -> None:
        if skill_id not in entry_by_id:
            issues.add(f"unknown-skill:{skill_id}")
            return
        proposal = proposals.setdefault(
            skill_id,
            {"rank": rank, "reasons": set(), "semantic_score": 0},
        )
        proposal["rank"] = max(proposal["rank"], rank)
        proposal["reasons"].add(reason)
        proposal["semantic_score"] = max(proposal["semantic_score"], score)

    explicit_ids: list[str] = []
    for requested in request.explicit_skills:
        resolved = aliases.get(requested, requested)
        if resolved not in explicit_ids:
            explicit_ids.append(resolved)
            propose(resolved, 400, "explicit")

    mandatory_ids: set[str] = set()
    for skill_id, entry in entry_by_id.items():
        if _conditional_mandatory(entry, request):
            mandatory_ids.add(skill_id)
            propose(skill_id, 500, "mandatory")

    semantic_matches: list[tuple[int, int, str]] = []
    for skill_id, entry in entry_by_id.items():
        if entry["supportStatus"] != "supported" or request.stage not in entry["stages"]:
            continue
        if request.operation_type == "read-only":
            continue
        excluded_terms = {term.strip().casefold() for term in entry["exclusions"]}
        if semantic_terms & excluded_terms:
            exclusions[skill_id] = "explicit-exclusion"
            continue
        selectors = entry["selectors"]
        extension_match = bool(set(request_extensions) & set(selectors["fileExtensions"]))
        operation_match = request.operation_type in selectors["operationTypes"]
        if extension_match:
            propose(skill_id, 200, "deterministic:file-extension")
        if operation_match:
            propose(skill_id, 200, "deterministic:operation-type")
        entry_terms = {term.strip().casefold() for term in selectors["semanticTerms"]}
        score = len(semantic_terms & entry_terms)
        if score:
            semantic_matches.append((score, entry["priority"], skill_id))
    semantic_matches.sort(key=lambda item: (-item[0], -item[1], item[2]))
    for score, _, skill_id in semantic_matches[: request.max_semantic_candidates]:
        propose(skill_id, 100, "semantic", score)

    pending = list(proposals)
    while pending:
        skill_id = pending.pop(0)
        proposal = proposals[skill_id]
        for dependency in entry_by_id[skill_id]["dependencies"]:
            if dependency not in proposals:
                pending.append(dependency)
            propose(dependency, proposal["rank"], f"dependency:{skill_id}")

    proposed_ids = set(proposals)
    conflict_pairs: set[tuple[str, str]] = set()
    for left in proposed_ids:
        for right in proposed_ids:
            if left >= right:
                continue
            if (
                right in entry_by_id[left]["conflicts"]
                or left in entry_by_id[right]["conflicts"]
            ):
                conflict_pairs.add((left, right))
    removed: set[str] = set()
    for left, right in sorted(conflict_pairs):
        if left in removed or right in removed:
            continue
        winner = min(
            (left, right),
            key=lambda skill_id: (
                -proposals[skill_id]["rank"],
                -entry_by_id[skill_id]["priority"],
                skill_id,
            ),
        )
        loser = right if winner == left else left
        removed.add(loser)
        exclusions[loser] = f"conflict:{winner}"
        if loser in explicit_ids and winner in mandatory_ids:
            issues.add(f"explicit-conflicts-mandatory:{loser}:{winner}")

    changed = True
    while changed:
        changed = False
        for skill_id in sorted(proposed_ids - removed):
            missing = set(entry_by_id[skill_id]["dependencies"]) & removed
            if missing:
                removed.add(skill_id)
                exclusions[skill_id] = "dependency-unavailable"
                changed = True

    survivors = proposed_ids - removed
    ordered: list[str] = []
    visiting: set[str] = set()

    def append_with_dependencies(skill_id: str) -> None:
        if skill_id in ordered or skill_id not in survivors:
            return
        if skill_id in visiting:
            raise RouteError("dependency-cycle")
        visiting.add(skill_id)
        for dependency in sorted(entry_by_id[skill_id]["dependencies"]):
            append_with_dependencies(dependency)
        visiting.remove(skill_id)
        ordered.append(skill_id)

    proposal_order = sorted(
        survivors,
        key=lambda skill_id: (
            -proposals[skill_id]["rank"],
            -entry_by_id[skill_id]["priority"],
            skill_id,
        ),
    )
    for skill_id in proposal_order:
        append_with_dependencies(skill_id)

    capability_states = dict(request.capability_states or {})
    missing_capabilities = sorted(
        {
            capability
            for skill_id in ordered
            for capability in entry_by_id[skill_id]["requiredCapabilities"]
            if capability_states.get(capability) != "supported"
        }
    )
    for skill_id in ordered:
        if entry_by_id[skill_id]["supportStatus"] != "supported":
            issues.add(f"skill-unverified:{skill_id}")

    stages: list[RouteStage] = []
    stage_ids: list[str] = []
    stage_cost = 0
    for skill_id in ordered:
        cost = entry_by_id[skill_id]["contextCost"]
        if stage_ids and stage_cost + cost > request.context_budget:
            stages.append(RouteStage(tuple(stage_ids), stage_cost))
            stage_ids = []
            stage_cost = 0
        stage_ids.append(skill_id)
        stage_cost += cost
        if cost > request.context_budget:
            issues.add(f"context-cost-exceeds-budget:{skill_id}")
    if stage_ids:
        stages.append(RouteStage(tuple(stage_ids), stage_cost))

    candidate_output = tuple(
        RouteCandidate(
            skill_id,
            tuple(sorted(proposals[skill_id]["reasons"], key=_reason_key)),
            proposals[skill_id]["semantic_score"],
        )
        for skill_id in proposal_order
    )
    exclusion_output = tuple(
        RouteExclusion(
            skill_id,
            exclusions.get(
                skill_id,
                "support-unverified"
                if entry["supportStatus"] != "supported"
                else "not-matched",
            ),
        )
        for skill_id, entry in sorted(entry_by_id.items())
        if skill_id not in ordered
    )
    status = "paused" if issues or missing_capabilities else "routed"
    return RouteResult(
        status=status,
        selected=tuple(ordered),
        candidates=candidate_output,
        exclusions=exclusion_output,
        stages=tuple(stages),
        catalog_hash=envelope["catalogHash"],
        missing_capabilities=tuple(missing_capabilities),
        issues=tuple(sorted(issues)),
    )


def route_skills(
    content: bytes | str | Mapping[str, object],
    request: RouteRequest,
) -> RouteResult:
    """Route the minimum sufficient ordered Skill set without invoking an LLM."""

    try:
        return _route_skills(content, request)
    except RouteError:
        raise
    except Exception:
        raise RouteError() from None


def route_modules(
    content: bytes | str | Mapping[str, object], request: ModuleRouteRequest
) -> ModuleRouteResult:
    """Select one Pipeline slot without semantic activation or side effects."""

    try:
        envelope = _load_envelope(content)
        modules = envelope["catalog"].get("modules", [])
        if (
            type(modules) is not list
            or request.cardinality not in {"exactly-one", "zero-or-one", "zero-or-many", "gate"}
            or request.strength not in {"Light", "Full", "Deep"}
            or type(request.write_task) is not bool
        ):
            raise RouteError()
        explicit = tuple(dict.fromkeys(request.explicit_module_ids))
        defaults = set(request.project_default_module_ids)
        states = dict(request.capability_states or {})
        candidates: list[tuple[int, int, str, dict[str, object]]] = []
        excluded: list[tuple[str, str]] = []
        early_reasons: set[str] = set()
        known_ids = {module.get("id") for module in modules if type(module) is dict}
        for module in modules:
            if type(module) is not dict or type(module.get("id")) is not str:
                raise RouteError()
            module_id = module["id"]
            if module["slot"] != request.slot_id:
                continue
            when = module["when"]
            if when["operationTypes"] and request.operation_type not in when["operationTypes"]:
                excluded.append((module_id, "condition-not-matched"))
                continue
            if request.strength not in when["strengths"] or (
                when["writeTask"] != "any" and when["writeTask"] is not request.write_task
            ):
                excluded.append((module_id, "condition-not-matched"))
                continue
            activation = module["activation"]
            rank = 0
            if activation == "mandatory":
                rank = 400
            elif module_id in explicit:
                rank = 300
            elif activation == "default":
                rank = 250 if module_id in defaults else 200
            elif activation == "deterministic" and set(module["dependencies"]) <= set(explicit):
                rank = 100
            if not rank:
                excluded.append((module_id, "not-selected"))
                continue
            evidence = module["supportEvidence"]
            static_layers = ("sourceIntegrity", "adapterSupport", "behaviorEvidence")
            if any(evidence[layer] != "supported" for layer in static_layers):
                excluded.append((module_id, "support-unverified"))
                if module_id in explicit:
                    early_reasons.add("unsupported-contract")
                continue
            candidates.append((rank, module["priority"], module_id, module))
        candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
        selected = candidates if request.cardinality == "zero-or-many" else candidates[:1]
        selected_ids = tuple(item[2] for item in selected)
        reasons: set[str] = set(early_reasons)
        candidate_by_id = {item[2]: item[3] for item in candidates}
        candidate_ids = set(candidate_by_id)
        if any(
            set(module["conflicts"]) & (candidate_ids - {module_id})
            for module_id, module in candidate_by_id.items()
        ):
            reasons.add("module-conflict")
        if request.cardinality in {"exactly-one", "gate"} and not selected_ids:
            reasons.add("gate-unavailable" if request.cardinality == "gate" else "primary-module-unavailable")
        if request.cardinality in {"exactly-one", "gate", "zero-or-one"} and len(
            [item for item in candidates if item[0] == 400]
        ) > 1:
            reasons.add("slot-cardinality-invalid")
        missing = sorted(
            {
                capability
                for _, _, _, module in selected
                for capability in module["requiredCapabilities"]
                if states.get(capability) != "supported"
            }
        )
        if missing:
            reasons.add("required-capability-unavailable")
        invalid_explicit = sorted(
            module_id for module_id in explicit if module_id not in known_ids
        )
        if invalid_explicit:
            reasons.add("explicit-selection-invalid")
        return ModuleRouteResult(
            status="paused" if reasons else "routed",
            selected_modules=selected_ids,
            excluded_modules=tuple(sorted(set(excluded))),
            missing_capabilities=tuple(missing),
            reason_codes=tuple(sorted(reasons)),
        )
    except RouteError:
        raise
    except Exception:
        raise RouteError() from None
