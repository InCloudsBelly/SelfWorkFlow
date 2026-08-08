"""Vendor-neutral policy overlay for a user-selected Superpowers source."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil


_SKILL_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_STAGE_MAP = {
    ("designed", "design"): ("brainstorming",),
    ("planned", "plan"): ("writing-plans",),
    ("implemented", "implement"): ("test-driven-development",),
    ("implemented", "debug"): ("systematic-debugging",),
    ("reviewed", "review"): (
        "requesting-code-review",
        "receiving-code-review",
    ),
    ("verified", "verify"): ("verification-before-completion",),
}


class SuperpowersOverlayError(RuntimeError):
    pass


def decide_overlay(
    *,
    stage: str,
    operation: str,
    complexity: int,
    risk: int,
    explicit_grill: bool,
    source_status: str,
    write_task: bool,
    grill_available: bool = True,
) -> dict[str, object]:
    """Select only current-stage Skills and fail closed for modifying work."""

    if complexity not in range(4) or risk not in range(4):
        raise SuperpowersOverlayError("classification-invalid")
    grill_recommended = max(complexity, risk) >= 3 or (
        complexity >= 2 and risk >= 2
    )
    if source_status != "supported":
        if write_task or explicit_grill:
            return {
                "status": "paused",
                "allowedMode": "none",
                "selectedSkills": (),
                "grillRecommended": grill_recommended,
                "postGrillReview": None,
                "issues": ("superpowers",),
            }
        return {
            "status": "active",
            "allowedMode": "read-only-analysis",
            "selectedSkills": (),
            "grillRecommended": grill_recommended,
            "postGrillReview": None,
            "issues": ("superpowers",),
        }
    if explicit_grill and not grill_available:
        return {
            "status": "paused",
            "allowedMode": "none",
            "selectedSkills": (),
            "grillRecommended": grill_recommended,
            "postGrillReview": None,
            "issues": ("grill-me-unavailable",),
        }
    selected = list(_STAGE_MAP.get((stage, operation), ()))
    post_review = None
    if explicit_grill:
        selected = ["grill-me", *[item for item in selected if item != "brainstorming"]]
        if "brainstorming" not in selected:
            selected.append("brainstorming")
        post_review = {
            "skill": "brainstorming",
            "independentContextRequired": True,
        }
    return {
        "status": "active",
        "allowedMode": "modify" if write_task else "read-only-analysis",
        "selectedSkills": tuple(selected),
        "grillRecommended": grill_recommended,
        "postGrillReview": post_review,
        "issues": (),
    }


def stage_selected_skills(
    upstream_root: str | Path,
    runtime_skills_root: str | Path,
    selected_skills: tuple[str, ...] | list[str],
) -> dict[str, object]:
    """Copy only selected Skill directories into a new runtime root."""

    source_root = Path(upstream_root).resolve(strict=True)
    destination = Path(runtime_skills_root)
    if destination.exists() or len(selected_skills) != len(set(selected_skills)):
        raise SuperpowersOverlayError("runtime-target-invalid")
    inventory: list[dict[str, str]] = []
    destination.mkdir(parents=True)
    try:
        for skill_id in selected_skills:
            if not isinstance(skill_id, str) or not _SKILL_ID.fullmatch(skill_id):
                raise SuperpowersOverlayError("skill-id-invalid")
            source = source_root / "skills" / skill_id
            if not source.is_dir() or source.is_symlink():
                raise SuperpowersOverlayError("skill-source-invalid")
            target = destination / skill_id
            shutil.copytree(source, target)
            for path in sorted(target.rglob("*")):
                if path.is_file():
                    inventory.append(
                        {
                            "path": path.relative_to(destination).as_posix(),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        }
                    )
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return {"selectedSkills": tuple(selected_skills), "inventory": inventory}
