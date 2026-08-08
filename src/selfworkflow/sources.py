"""Inspect and lock a user-selected Superpowers source without installing it."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


class SourceSelectionError(RuntimeError):
    pass


def _run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=False, capture_output=True, text=True
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inventory_hash(entries: list[dict[str, str]]) -> str:
    encoded = json.dumps(
        entries, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def inspect_superpowers_source(source: str | Path) -> dict[str, object]:
    """Inspect a local candidate; this function never installs or mutates it."""

    root = Path(source)
    if not root.exists():
        return {
            "sourceType": "missing",
            "supportStatus": "unsupported",
            "reproducibilityStatus": "unavailable",
            "reason": "missing",
        }
    root = root.resolve(strict=True)
    top = _run(root, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root:
        return {
            "sourceType": "non-git",
            "supportStatus": "unsupported",
            "reproducibilityStatus": "unavailable",
            "reason": "not-git",
        }
    commit = _run(root, "rev-parse", "HEAD")
    tracked = _run(root, "ls-files", "-z")
    status = _run(root, "status", "--porcelain=v1", "-z")
    if any(result.returncode for result in (commit, tracked, status)):
        return {
            "sourceType": "local-git",
            "supportStatus": "unsupported",
            "reproducibilityStatus": "unavailable",
            "reason": "git-inspection-failed",
        }
    paths = sorted(path for path in tracked.stdout.split("\0") if path)
    inventory: list[dict[str, str]] = []
    for relative in paths:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise SourceSelectionError("source-file-invalid")
        inventory.append({"path": relative.replace("\\", "/"), "sha256": _sha256(path)})
    dirty_paths: set[str] = set()
    records = [record for record in status.stdout.split("\0") if record]
    for record in records:
        if len(record) >= 4:
            dirty_paths.add(record[3:].replace("\\", "/"))
    inventory_by_path = {entry["path"]: entry["sha256"] for entry in inventory}
    dirty_files = [
        {"path": path, "sha256": inventory_by_path.get(path, "untracked-or-deleted")}
        for path in sorted(dirty_paths)
    ]
    dirty = bool(records)
    return {
        "sourceType": "local-git",
        "sourceLocator": str(root),
        "supportStatus": "supported",
        "reproducibilityStatus": "dirty-snapshot" if dirty else "reproducible",
        "commit": commit.stdout.strip(),
        "dirty": dirty,
        "inventoryHash": _inventory_hash(inventory),
        "dirtyFiles": dirty_files,
    }


def lock_superpowers_source(
    candidate: dict[str, object],
    *,
    selected_by_user: bool,
    allow_dirty: bool,
    readonly_fallback: bool = False,
) -> dict[str, object]:
    """Create an immutable-plan value only after an explicit user selection."""

    if not selected_by_user:
        if readonly_fallback:
            return {
                "selectionStatus": "declined",
                "allowedMode": "read-only-analysis",
                "reason": "superpowers-unavailable-or-declined",
            }
        raise SourceSelectionError("selection-required")
    if candidate.get("supportStatus") != "supported":
        raise SourceSelectionError("source-unsupported")
    dirty = candidate.get("dirty") is True
    if dirty and not allow_dirty:
        raise SourceSelectionError("dirty-authorization-required")
    required = (
        "sourceType",
        "reproducibilityStatus",
        "commit",
        "inventoryHash",
        "dirtyFiles",
    )
    if any(key not in candidate for key in required):
        raise SourceSelectionError("source-candidate-invalid")
    return {
        "selectionStatus": "selected",
        "sourceType": candidate["sourceType"],
        "sourceLocator": candidate.get("sourceLocator"),
        "commit": candidate["commit"],
        "dirty": dirty,
        "dirtyAuthorized": dirty and allow_dirty,
        "dirtyFiles": candidate["dirtyFiles"],
        "inventoryHash": candidate["inventoryHash"],
        "supportStatus": candidate["supportStatus"],
        "reproducibilityStatus": candidate["reproducibilityStatus"],
    }
