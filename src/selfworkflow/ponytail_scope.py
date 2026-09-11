"""Small, stateless route selector for the code-scoped Ponytail skills."""

from __future__ import annotations

from dataclasses import dataclass


_CODE_OPERATIONS = {"implement", "debug"}
_SIGNALLED_OPERATIONS = {"analyze", "design", "plan", "review", "verify"}
_CODE_EXTENSIONS = {
    ".c", ".cc", ".cpp", ".cs", ".go", ".h", ".hpp", ".inl", ".java",
    ".js", ".jsx", ".py", ".rs", ".shader", ".ts", ".tsx", ".ush", ".usf",
}
_CODE_TERMS = {
    "api", "abi", "bug", "build", "code", "compiler", "concurrency", "debug",
    "implementation", "interface", "module", "refactor", "repository", "source",
    "test", "unreal", "ue5",
}
_MODES = {"lite", "full", "deep"}
_EXPLICIT_SKILLS = {"ponytail", "ponytail-review", "ponytail-audit"}


@dataclass(frozen=True)
class PonytailRoute:
    """Immutable route decision; it does not persist or mutate host state."""

    enabled: bool
    skill_ids: tuple[str, ...]
    mode: str
    reason: str


def select_ponytail_route(
    operation_type: str,
    *,
    file_extensions: tuple[str, ...] = (),
    semantic_terms: tuple[str, ...] = (),
    explicit_skill: str | None = None,
    mode: str = "full",
) -> PonytailRoute:
    """Select Ponytail only for code work or an explicit Ponytail request."""

    if operation_type not in _CODE_OPERATIONS | _SIGNALLED_OPERATIONS:
        if explicit_skill is not None:
            raise ValueError("ponytail-explicit-operation-invalid")
        return PonytailRoute(False, (), mode, "non-code-operation")
    if mode not in _MODES:
        raise ValueError("ponytail-mode-invalid")
    if explicit_skill is not None and explicit_skill not in _EXPLICIT_SKILLS:
        raise ValueError("ponytail-skill-invalid")

    extensions = {value.casefold() for value in file_extensions}
    terms = {value.casefold() for value in semantic_terms}
    code_signalled = bool(extensions & _CODE_EXTENSIONS or terms & _CODE_TERMS)
    enabled = (
        explicit_skill is not None
        or operation_type in _CODE_OPERATIONS
        or operation_type in _SIGNALLED_OPERATIONS and code_signalled
    )
    if not enabled:
        return PonytailRoute(False, (), mode, "no-code-signal")

    skills = ["ponytail"]
    if explicit_skill in {"ponytail-review", "ponytail-audit"}:
        skills.append(explicit_skill)
    return PonytailRoute(True, tuple(skills), mode, "explicit" if explicit_skill else "code-task")
