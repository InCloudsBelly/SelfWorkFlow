"""Hash-bound Review packages shared with independent reviewer SubAgents."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from selfworkflow.v3.hashing import HashingError, clone, content_hash, require_hash


class ReviewPackageError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_KINDS = frozenset({"code", "plan"})

# This is the pinned tree hash from matt-pocock-skills.lock.yaml.  It is a
# manifest identity, not a claim that this process executed the Skill.
_GENERIC_CODE_REVIEW_SKILL = {
    "layer": "generic",
    "id": "matt-pocock.code-review",
    "path": "skills/engineering/code-review",
    "contentHash": "sha256:3abbdfe52540f9242e16589fae2cc423b3d98994c37683944462b29bab89495c",
    "required": True,
}


def _valid_id(value: object) -> bool:
    return type(value) is str and _ID.fullmatch(value) is not None


def normalize_review_package(
    value: object,
    *,
    expected_kind: str,
    plan_hash: str,
    stage_id: str | tuple[str, ...],
    attempt_ref: str,
) -> dict[str, Any]:
    """Validate a complete code/plan package and bind it to the live attempt."""

    if expected_kind not in _KINDS:
        raise ReviewPackageError("review-package-kind-invalid")
    try:
        require_hash(plan_hash)
    except HashingError:
        raise ReviewPackageError("review-package-binding-invalid") from None
    allowed_stage_ids = (stage_id,) if isinstance(stage_id, str) else stage_id
    if (
        not allowed_stage_ids
        or not all(_valid_id(item) for item in allowed_stage_ids)
        or not _valid_id(attempt_ref)
    ):
        raise ReviewPackageError("review-package-binding-invalid")
    if not isinstance(value, Mapping) or set(value) != {
        "schemaVersion", "reviewKind", "planHash", "stageId", "attemptRef",
        "content", "packageHash",
    }:
        raise ReviewPackageError("review-package-invalid")
    package = dict(value)
    if (
        package["schemaVersion"] != 1
        or package["reviewKind"] != expected_kind
        or package["planHash"] != plan_hash
        or package["stageId"] not in allowed_stage_ids
        or package["attemptRef"] != attempt_ref
        or not isinstance(package["content"], Mapping)
    ):
        raise ReviewPackageError("review-package-binding-invalid")
    content = package["content"]
    if expected_kind == "code" and not {
        "changes", "baseline", "specification", "verificationPlans",
    } <= set(content):
        raise ReviewPackageError("review-code-package-incomplete")
    if expected_kind == "plan" and not {
        "plan", "acceptanceCriteria", "testDesign",
    } <= set(content):
        raise ReviewPackageError("review-plan-package-incomplete")
    try:
        require_hash(package["packageHash"])
        semantic = {key: item for key, item in package.items() if key != "packageHash"}
        if package["packageHash"] != content_hash(semantic):
            raise ReviewPackageError("review-package-hash-invalid")
        return clone(package)
    except ReviewPackageError:
        raise
    except (HashingError, TypeError, ValueError, OverflowError):
        raise ReviewPackageError("review-package-invalid") from None


def ordered_skill_manifest(project_context: Mapping[str, object] | None) -> list[dict[str, object]]:
    """Return the primary project Review Skill and supplementary generic Skill."""

    project_entries: list[dict[str, object]] = []
    if project_context is not None:
        reviewers = project_context.get("reviewers")
        if isinstance(reviewers, Mapping):
            standards = reviewers.get("standards")
            if isinstance(standards, Mapping):
                manifest = standards.get("manifest")
                if isinstance(manifest, tuple):
                    for item in manifest:
                        if not isinstance(item, Mapping):
                            raise ReviewPackageError("review-skill-manifest-invalid")
                        project_entries.append(
                            {"layer": "project", "role": "primary", **dict(item)}
                        )
    if project_entries:
        result = project_entries
        result.append({
            "layer": "generic", "role": "supplementary",
            **dict(_GENERIC_CODE_REVIEW_SKILL),
        })
    else:
        result = [{
            "layer": "generic", "role": "primary",
            **dict(_GENERIC_CODE_REVIEW_SKILL),
        }]
    return result


def skill_manifest_hash(manifest: list[dict[str, object]]) -> str:
    return content_hash({"schemaVersion": 1, "skills": manifest})
