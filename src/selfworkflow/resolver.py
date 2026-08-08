"""Compose one deterministic, side-effect-free task execution plan."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json

from selfworkflow.classifier import check_capabilities, classify_task
from selfworkflow.model import CapabilityReport
from selfworkflow.router import RouteRequest, route_skills
from selfworkflow.superpowers import decide_overlay


_REQUIRED_KEYS = {
    "schemaVersion",
    "stage",
    "operationType",
    "complexity",
    "risk",
    "writeTask",
    "superpowersSourceStatus",
    "capabilityStates",
}
_OPTIONAL_KEYS = {
    "ambiguity",
    "explicitGrill",
    "fileExtensions",
    "semanticTerms",
    "explicitSkills",
    "contextBudget",
}
_STAGE_OPERATIONS = {
    ("discovered", "read-only"),
    ("designed", "design"),
    ("planned", "plan"),
    ("implemented", "implement"),
    ("implemented", "debug"),
    ("reviewed", "review"),
    ("verified", "verify"),
}
_SOURCE_STATUSES = {"supported", "unsupported", "unverified", "unselected"}


class ResolveError(ValueError):
    """Stable, redacted task-resolution failure."""

    def __init__(self, code: str = "resolve-input-invalid") -> None:
        self.code = code
        super().__init__("resolve-failed")


def _string_list(value: object, *, maximum: int) -> tuple[str, ...]:
    if (
        type(value) is not list
        or len(value) > maximum
        or any(type(item) is not str or len(item) > 512 for item in value)
    ):
        raise ResolveError()
    return tuple(value)


def _capability_states(value: object) -> dict[str, str]:
    if type(value) is not dict or len(value) > 64:
        raise ResolveError()
    result: dict[str, str] = {}
    for name, state in value.items():
        if (
            type(name) is not str
            or not name
            or len(name) > 128
            or type(state) is not str
            or state not in {"supported", "unsupported", "unverified"}
        ):
            raise ResolveError()
        result[name] = state
    return result


def _parse_request(request: Mapping[str, object]) -> dict[str, object]:
    if type(request) is not dict:
        raise ResolveError()
    keys = set(request)
    if not _REQUIRED_KEYS <= keys or not keys <= _REQUIRED_KEYS | _OPTIONAL_KEYS:
        raise ResolveError()
    if request["schemaVersion"] != 1 or type(request["schemaVersion"]) is not int:
        raise ResolveError()
    stage = request["stage"]
    operation = request["operationType"]
    if (
        type(stage) is not str
        or type(operation) is not str
        or (stage, operation) not in _STAGE_OPERATIONS
    ):
        raise ResolveError()
    write_task = request["writeTask"]
    ambiguity = request.get("ambiguity", False)
    explicit_grill = request.get("explicitGrill", False)
    if any(
        type(value) is not bool
        for value in (write_task, ambiguity, explicit_grill)
    ):
        raise ResolveError()
    if operation == "read-only" and write_task:
        raise ResolveError()
    if explicit_grill and operation != "design":
        raise ResolveError()
    source_status = request["superpowersSourceStatus"]
    if type(source_status) is not str or source_status not in _SOURCE_STATUSES:
        raise ResolveError()
    context_budget = request.get("contextBudget", 4096)
    if type(context_budget) is not int or not 1 <= context_budget <= 1_000_000:
        raise ResolveError()
    for name in ("complexity", "risk"):
        if type(request[name]) is not str:
            raise ResolveError()
    return {
        "stage": stage,
        "operation": operation,
        "complexity": request["complexity"],
        "risk": request["risk"],
        "write_task": write_task,
        "ambiguity": ambiguity,
        "explicit_grill": explicit_grill,
        "source_status": source_status,
        "capability_states": _capability_states(request["capabilityStates"]),
        "file_extensions": _string_list(
            request.get("fileExtensions", []), maximum=128
        ),
        "semantic_terms": _string_list(
            request.get("semanticTerms", []), maximum=256
        ),
        "explicit_skills": _string_list(
            request.get("explicitSkills", []), maximum=128
        ),
        "context_budget": context_budget,
    }


def _capability_output(pause) -> dict[str, object]:
    if pause is None:
        return {
            "status": "passed",
            "missingCapabilities": (),
            "reasons": (),
            "recommendations": (),
        }
    return {
        "status": "paused",
        "missingCapabilities": pause.missing_capabilities,
        "reasons": pause.reasons,
        "recommendations": pause.recommendations,
    }


def _request_hash(parsed: Mapping[str, object]) -> str:
    payload = {
        "schemaVersion": 1,
        "stage": parsed["stage"],
        "operationType": parsed["operation"],
        "complexity": parsed["complexity"],
        "risk": parsed["risk"],
        "writeTask": parsed["write_task"],
        "ambiguity": parsed["ambiguity"],
        "explicitGrill": parsed["explicit_grill"],
        "superpowersSourceStatus": parsed["source_status"],
        "capabilityStates": parsed["capability_states"],
        "fileExtensions": parsed["file_extensions"],
        "semanticTerms": parsed["semantic_terms"],
        "explicitSkills": parsed["explicit_skills"],
        "contextBudget": parsed["context_budget"],
    }
    content = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _catalog_has_skill(
    content: bytes | str | Mapping[str, object], skill_id: str
) -> bool:
    if isinstance(content, bytes):
        envelope = json.loads(content.decode("utf-8"))
    elif isinstance(content, str):
        envelope = json.loads(content)
    else:
        envelope = dict(content)
    return any(
        isinstance(entry, dict) and entry.get("id") == skill_id
        for entry in envelope["catalog"]["entries"]
    )


def resolve_task(
    catalog_content: bytes | str | Mapping[str, object],
    request: Mapping[str, object],
) -> dict[str, object]:
    """Return a deterministic plan without executing tasks or producing side effects."""

    try:
        parsed = _parse_request(request)
        classification = classify_task(
            parsed["complexity"],
            parsed["risk"],
            ambiguity=parsed["ambiguity"],
        )
        review_level = (
            "not-applicable"
            if not parsed["write_task"]
            else "L2" if classification.requires_full_design else "L0"
        )
        required_capabilities = ["filesystem-read"]
        purposes = {"filesystem-read": "read task context and workflow instructions"}
        if parsed["write_task"]:
            required_capabilities.append("filesystem-write")
            purposes["filesystem-write"] = "apply the requested modification"
        if parsed["explicit_grill"] or (
            parsed["operation"] == "review" and review_level == "L2"
        ):
            required_capabilities.append("independent-context")
            purposes["independent-context"] = (
                "perform the required independent post-Grill Brainstorming Review"
                if parsed["explicit_grill"]
                else "perform the required independent Review"
            )
        capability_report = CapabilityReport(parsed["capability_states"])
        capability_pause = check_capabilities(
            required_capabilities,
            capability_report,
            purposes=purposes,
        )
        route = route_skills(
            catalog_content,
            RouteRequest(
                stage=parsed["stage"],
                operation_type=parsed["operation"],
                file_extensions=parsed["file_extensions"],
                semantic_terms=parsed["semantic_terms"],
                explicit_skills=parsed["explicit_skills"],
                capability_states=parsed["capability_states"],
                context_budget=parsed["context_budget"],
            ),
        )
        overlay = decide_overlay(
            stage=parsed["stage"],
            operation=parsed["operation"],
            complexity=int(classification.complexity.value[1]),
            risk=int(classification.risk.value[1]),
            explicit_grill=parsed["explicit_grill"],
            source_status=parsed["source_status"],
            write_task=parsed["write_task"],
            grill_available=_catalog_has_skill(catalog_content, "grill-me"),
        )
    except ResolveError:
        raise
    except Exception:
        raise ResolveError() from None

    selected = tuple(dict.fromkeys((*route.selected, *overlay["selectedSkills"])))
    issues = set(overlay["issues"])
    issues.update(route.issues)
    issues.update(f"capability:{name}" for name in route.missing_capabilities)
    if capability_pause is not None:
        issues.update(
            f"capability:{name}" for name in capability_pause.missing_capabilities
        )
    status = (
        "active"
        if capability_pause is None
        and route.status == "routed"
        and overlay["status"] == "active"
        else "paused"
    )
    return {
        "schemaVersion": 1,
        "requestHash": _request_hash(parsed),
        "status": status,
        "task": {
            "stage": parsed["stage"],
            "operationType": parsed["operation"],
            "writeTask": parsed["write_task"],
            "superpowersSourceStatus": parsed["source_status"],
        },
        "classification": {
            "complexity": classification.complexity.value,
            "risk": classification.risk.value,
            "reasons": classification.reasons,
            "requiresFullDesign": classification.requires_full_design,
            "suggestGrillMe": classification.suggest_grill_me,
        },
        "capabilityGate": _capability_output(capability_pause),
        "catalogRoute": {
            "status": route.status,
            "catalogHash": route.catalog_hash,
            "selectedSkills": route.selected,
            "stages": tuple(
                {"skillIds": stage.skill_ids, "contextCost": stage.context_cost}
                for stage in route.stages
            ),
            "missingCapabilities": route.missing_capabilities,
            "issues": route.issues,
        },
        "superpowers": overlay,
        "selectedSkills": selected,
        "requirements": {
            "review": {
                "required": parsed["write_task"],
                "minimumIsolation": review_level,
            },
            "verification": {
                "required": parsed["write_task"],
                "policy": "narrowest-sufficient",
            },
        },
        "issues": tuple(sorted(issues)),
    }
