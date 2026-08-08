"""Vendor-neutral policy overlay for a user-selected Superpowers source."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil


_SKILL_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
class SuperpowersOverlayError(RuntimeError):
    pass


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
