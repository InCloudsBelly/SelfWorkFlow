"""Inspect and lock a user-selected Superpowers source without installing it."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import shutil
import subprocess
import tempfile


_REPARSE_POINT = 0x400


class SourceSelectionError(RuntimeError):
    pass


def _git_environment() -> dict[str, str]:
    """Return a Git environment that cannot inherit executable or URL config."""

    blocked_exact = {
        "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_SYSTEM", "GIT_CONFIG_GLOBAL",
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in blocked_exact
        and not key.upper().startswith("GIT_CONFIG_KEY_")
        and not key.upper().startswith("GIT_CONFIG_VALUE_")
    }
    environment.update({
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    })
    return environment


def _run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "-c", f"core.hooksPath={os.devnull}",
            "-c", "core.fsmonitor=false",
            *arguments,
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        env=_git_environment(),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_reparse(path: Path) -> bool:
    metadata = path.lstat()
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _reject_reparse_chain(path: Path) -> None:
    current = path
    while True:
        if os.path.lexists(current) and _is_reparse(current):
            raise SourceSelectionError("reparse-path-rejected")
        if current.parent == current:
            break
        current = current.parent


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
    _reject_reparse_chain(root.absolute())
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
    status = _run(root, "status", "--porcelain=v1", "-z")
    if any(result.returncode for result in (commit, status)):
        return {
            "sourceType": "local-git",
            "supportStatus": "unsupported",
            "reproducibilityStatus": "unavailable",
            "reason": "git-inspection-failed",
        }
    inventory = _tracked_inventory(root)
    tracked_skill_ids = sorted(
        PurePosixPath(item["path"]).parts[1]
        for item in inventory
        if len(PurePosixPath(item["path"]).parts) == 3
        and PurePosixPath(item["path"]).parts[0] == "skills"
        and PurePosixPath(item["path"]).parts[2] == "SKILL.md"
    )
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
        "trackedSkillIds": tracked_skill_ids,
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


def _tracked_inventory(root: Path) -> list[dict[str, str]]:
    tracked = _run(root, "ls-files", "-z")
    if tracked.returncode != 0:
        raise SourceSelectionError("git-inspection-failed")
    files: list[dict[str, str]] = []
    total_bytes = 0
    for relative in sorted(path for path in tracked.stdout.split("\0") if path):
        pure = PurePosixPath(relative.replace("\\", "/"))
        if (
            pure.is_absolute()
            or not pure.parts
            or ".." in pure.parts
        ):
            raise SourceSelectionError("source-file-invalid")
        source = root / Path(*pure.parts)
        if not source.is_file() or _is_reparse(source):
            raise SourceSelectionError("source-file-invalid")
        size = source.stat().st_size
        total_bytes += size
        if len(files) >= 20_000 or size > 8 * 1024 * 1024 or total_bytes > 64 * 1024 * 1024:
            raise SourceSelectionError("source-resource-limit")
        files.append(
            {
                "path": pure.as_posix(),
                "sha256": _sha256(source),
            }
        )
    if not files:
        raise SourceSelectionError("source-skills-missing")
    return files


def _tracked_skill_files(
    inventory: list[dict[str, str]],
) -> list[dict[str, str]]:
    files = []
    for item in inventory:
        pure = PurePosixPath(item["path"])
        if not pure.parts or pure.parts[0] != "skills" or len(pure.parts) == 1:
            continue
        files.append(
            {
                "path": PurePosixPath(*pure.parts[1:]).as_posix(),
                "sourcePath": pure.as_posix(),
                "sha256": item["sha256"],
            }
        )
    if not files:
        raise SourceSelectionError("source-skills-missing")
    return files


def _verify_staged_target(
    target: Path, expected_inventory_hash: str
) -> bool:
    lock_path = target / ".selfworkflow-source.json"
    if not lock_path.is_file() or _is_reparse(lock_path):
        return False
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return False
    if (
        not isinstance(lock, dict)
        or lock.get("schemaVersion") != 1
        or lock.get("inventoryHash") != expected_inventory_hash
        or not isinstance(lock.get("stagedFiles"), list)
    ):
        return False
    expected: dict[str, str] = {}
    for item in lock["stagedFiles"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256"}
            or not isinstance(item["path"], str)
            or not isinstance(item["sha256"], str)
            or item["path"] in expected
        ):
            return False
        expected[item["path"]] = item["sha256"]
    actual: dict[str, str] = {}
    for path in sorted(target.rglob("*")):
        if _is_reparse(path):
            return False
        if not path.is_file() or path == lock_path:
            continue
        relative = path.relative_to(target).as_posix()
        actual[relative] = _sha256(path)
    return actual == expected


def stage_superpowers_source(
    source: str | Path,
    target: str | Path,
    expected_inventory_hash: str,
) -> dict[str, object]:
    """Atomically stage only Git-tracked Superpowers Skill files."""

    source_path = Path(source)
    destination_path = Path(target)
    if not destination_path.is_absolute():
        raise SourceSelectionError("absolute-target-required")
    _reject_reparse_chain(source_path.absolute())
    _reject_reparse_chain(destination_path)
    root = source_path.resolve(strict=True)
    destination = destination_path.resolve(strict=False)
    if destination == root or destination in root.parents or root in destination.parents:
        raise SourceSelectionError("source-target-overlap")
    report = inspect_superpowers_source(root)
    if (
        report.get("supportStatus") != "supported"
        or report.get("inventoryHash") != expected_inventory_hash
    ):
        raise SourceSelectionError("source-drift")
    if destination.exists() or destination.is_symlink():
        if destination.is_dir() and _verify_staged_target(
            destination, expected_inventory_hash
        ):
            return {
                "status": "already-staged",
                "target": str(destination),
                "inventoryHash": expected_inventory_hash,
            }
        raise SourceSelectionError("target-conflict")

    inventory = _tracked_inventory(root)
    if _inventory_hash(inventory) != expected_inventory_hash:
        raise SourceSelectionError("source-drift")
    files = _tracked_skill_files(inventory)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=".superpowers-stage-", dir=destination.parent)
    )
    try:
        staged_files: list[dict[str, str]] = []
        for item in files:
            source_file = root / Path(*PurePosixPath(item["sourcePath"]).parts)
            target_file = temporary / Path(*PurePosixPath(item["path"]).parts)
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file, target_file)
            if _sha256(target_file) != item["sha256"]:
                raise SourceSelectionError("stage-copy-drift")
            staged_files.append({"path": item["path"], "sha256": item["sha256"]})
        lock = {
            "schemaVersion": 1,
            "sourceType": report["sourceType"],
            "sourceLocator": report["sourceLocator"],
            "commit": report["commit"],
            "dirty": report["dirty"],
            "inventoryHash": report["inventoryHash"],
            "stagedFiles": staged_files,
        }
        (temporary / ".selfworkflow-source.json").write_text(
            json.dumps(lock, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if inspect_superpowers_source(root).get("inventoryHash") != expected_inventory_hash:
            raise SourceSelectionError("source-drift")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
    return {
        "status": "staged",
        "target": str(destination),
        "inventoryHash": expected_inventory_hash,
    }
