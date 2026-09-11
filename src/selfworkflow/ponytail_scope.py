"""Small, stateless route selector for the code-scoped Ponytail skills."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json


_CODE_OPERATIONS = {"implement", "debug"}
_SIGNALLED_OPERATIONS = {"analyze", "design", "plan", "review", "verify"}
_CODE_EXTENSIONS = {
    ".c", ".cc", ".cpp", ".cppm", ".cs", ".cu", ".cuh", ".cxx", ".go",
    ".h", ".hh", ".hpp", ".hxx", ".inl", ".ixx", ".java", ".js", ".jsx",
    ".py", ".rs", ".shader", ".ts", ".tsx", ".ush", ".usf", ".hlsl",
}
_CODE_TERMS = {
    "api", "abi", "bug", "code", "compiler", "concurrency", "debug",
    "implementation", "refactor", "unreal", "ue5",
}
_MODES = {"lite", "full", "ultra", "off"}
_EXPLICIT_SKILLS = {
    "ponytail", "ponytail-review", "ponytail-audit", "ponytail-help",
}
_SKILL_MODULES = {
    "ponytail": "ponytail-coding",
    "ponytail-review": "ponytail-review",
    "ponytail-audit": "ponytail-audit",
    "ponytail-help": "ponytail-help",
}


@dataclass(frozen=True)
class PonytailRoute:
    """Immutable route decision; it does not persist or mutate host state."""

    enabled: bool
    skill_ids: tuple[str, ...]
    mode: str
    reason: str

    @property
    def module_ids(self) -> tuple[str, ...]:
        return tuple(_SKILL_MODULES[skill_id] for skill_id in self.skill_ids)

    def as_dict(self) -> dict[str, object]:
        material = {
            "enabled": self.enabled,
            "skillIds": list(self.skill_ids),
            "selectedModuleIds": list(self.module_ids),
            "mode": self.mode,
            "reason": self.reason,
        }
        payload = json.dumps(
            material, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return {
            **material,
            "routeHash": "sha256:" + hashlib.sha256(payload).hexdigest(),
        }


def select_ponytail_route(
    operation_type: str,
    *,
    file_extensions: tuple[str, ...] = (),
    semantic_terms: tuple[str, ...] = (),
    explicit_skill: str | None = None,
    mode: str = "full",
) -> PonytailRoute:
    """Select Ponytail only for code work or an explicit Ponytail request."""

    if type(mode) is not str or mode not in _MODES:
        raise ValueError("ponytail-mode-invalid")
    if operation_type not in _CODE_OPERATIONS | _SIGNALLED_OPERATIONS:
        if explicit_skill is not None:
            raise ValueError("ponytail-explicit-operation-invalid")
        return PonytailRoute(False, (), mode, "non-code-operation")
    if explicit_skill is not None and explicit_skill not in _EXPLICIT_SKILLS:
        raise ValueError("ponytail-skill-invalid")
    if mode == "off":
        return PonytailRoute(False, (), mode, "explicitly-off")

    if explicit_skill == "ponytail-help":
        return PonytailRoute(True, ("ponytail-help",), mode, "explicit-help")

    extensions = {value.casefold() for value in file_extensions}
    terms = {value.casefold() for value in semantic_terms}
    code_signalled = bool(extensions & _CODE_EXTENSIONS or terms & _CODE_TERMS)
    enabled = (
        operation_type in _CODE_OPERATIONS
        or operation_type in _SIGNALLED_OPERATIONS and code_signalled
    )
    if not enabled:
        return PonytailRoute(False, (), mode, "no-code-signal")

    skills = ["ponytail"]
    if explicit_skill in {"ponytail-review", "ponytail-audit"}:
        skills.append(explicit_skill)
    return PonytailRoute(True, tuple(skills), mode, "explicit" if explicit_skill else "code-task")
