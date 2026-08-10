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


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _same_volume(left: Path, right: Path) -> bool:
    left_drive = os.path.splitdrive(str(left))[0].casefold()
    right_drive = os.path.splitdrive(str(right))[0].casefold()
    return left_drive == right_drive


def _write_json_atomic(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _load_migration_journal(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise SourceSelectionError("migration-journal-invalid") from None
    required = {
        "schemaVersion", "stateRoot", "sourceRoot", "sourceSkills", "targetRoot",
        "target", "backup", "protectedRoots", "inventoryHash", "phase",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("schemaVersion") != 1
        or value.get("phase") not in {"prepared", "link-moved", "staged", "restored", "committed"}
        or any(
            not isinstance(value.get(key), str)
            for key in required - {"schemaVersion", "protectedRoots"}
        )
        or not isinstance(value.get("protectedRoots"), list)
        or any(not isinstance(item, str) for item in value["protectedRoots"])
    ):
        raise SourceSelectionError("migration-journal-invalid")
    return value


def _validated_migration_paths(
    journal: Path, intent: dict[str, object]
) -> tuple[Path, Path, Path]:
    state = Path(intent["stateRoot"])
    source_root = Path(intent["sourceRoot"])
    source_skills = Path(intent["sourceSkills"])
    target_root = Path(intent["targetRoot"])
    target = Path(intent["target"])
    backup = Path(intent["backup"])
    protected = tuple(Path(item) for item in intent["protectedRoots"])
    paths = (state, source_root, source_skills, target_root, target, backup, *protected)
    if any(not path.is_absolute() for path in paths):
        raise SourceSelectionError("migration-journal-invalid")
    expected_journal = state / "source-migrations" / "superpowers.json"
    expected_backup_root = state / "source-migrations" / "backups"
    if (
        journal != expected_journal
        or source_skills != source_root / "skills"
        or target != target_root / "skills" / "superpowers"
        or not _is_within(backup, expected_backup_root)
        or backup == expected_backup_root
        or not _same_volume(target, backup)
        or _is_within(state, source_root)
        or _is_within(source_root, state)
        or _is_within(backup, target_root)
        or any(_is_within(backup, item) for item in (source_root, *protected))
    ):
        raise SourceSelectionError("migration-journal-invalid")
    _reject_reparse_chain(state)
    _reject_reparse_chain(journal)
    _reject_reparse_chain(backup.parent)
    _reject_reparse_chain(source_root)
    _reject_reparse_chain(source_skills)
    _reject_reparse_chain(target_root)
    _reject_reparse_chain(target.parent)
    for item in protected:
        _reject_reparse_chain(item)
    return target, backup, source_skills


def _verify_source_link(path: Path, expected: Path) -> bool:
    return (
        os.path.lexists(path)
        and _is_reparse(path)
        and path.is_dir()
        and path.resolve(strict=True) == expected
    )


def recover_superpowers_migration(
    migration_journal: str | Path, *, if_exists: bool = False
) -> dict[str, object]:
    """Restore a non-committed compatible-link migration without guessing."""

    journal = Path(migration_journal)
    if not journal.is_absolute():
        raise SourceSelectionError("absolute-migration-path-required")
    if not journal.exists():
        if if_exists:
            return {"status": "not-required", "journal": str(journal)}
        raise SourceSelectionError("migration-journal-missing")
    _reject_reparse_chain(journal)
    journal = journal.absolute()
    intent = _load_migration_journal(journal)
    target, backup, source_skills = _validated_migration_paths(journal, intent)
    if intent["phase"] in {"committed", "restored"}:
        return {"status": intent["phase"], "journal": str(journal)}
    inventory_hash = intent["inventoryHash"]
    if _verify_source_link(target, source_skills):
        if os.path.lexists(backup):
            raise SourceSelectionError("migration-backup-drift")
        intent["phase"] = "restored"
        _write_json_atomic(journal, intent)
        return {"status": "restored", "journal": str(journal)}
    if not _verify_source_link(backup, source_skills):
        raise SourceSelectionError("migration-backup-drift")
    if os.path.lexists(target) and _verify_staged_target(target, inventory_hash):
        shutil.rmtree(target)
    elif os.path.lexists(target):
        if not _verify_source_link(target, source_skills):
            raise SourceSelectionError("migration-target-drift")
        intent["phase"] = "restored"
        _write_json_atomic(journal, intent)
        return {"status": "restored", "journal": str(journal)}
    os.replace(backup, target)
    intent["phase"] = "restored"
    _write_json_atomic(journal, intent)
    return {"status": "restored", "journal": str(journal)}


def commit_superpowers_migration(migration_journal: str | Path) -> dict[str, object]:
    """Close a staged migration only after the caller's final verification."""

    journal = Path(migration_journal)
    if not journal.is_absolute() or not journal.exists():
        raise SourceSelectionError("migration-journal-missing")
    _reject_reparse_chain(journal)
    journal = journal.absolute()
    intent = _load_migration_journal(journal)
    target, backup, source_skills = _validated_migration_paths(journal, intent)
    if intent["phase"] == "committed":
        return {"status": "committed", "journal": str(journal)}
    if intent["phase"] != "staged" or not _verify_staged_target(
        target, intent["inventoryHash"]
    ):
        raise SourceSelectionError("migration-not-staged")
    if not _verify_source_link(backup, source_skills):
        raise SourceSelectionError("migration-backup-drift")
    intent["phase"] = "committed"
    _write_json_atomic(journal, intent)
    return {
        "status": "committed",
        "journal": str(journal),
        "backup": intent["backup"],
    }


def remove_staged_superpowers_source(
    target: str | Path, expected_inventory_hash: str
) -> dict[str, object]:
    """Remove only an exact staged snapshot; refuse user or concurrent drift."""

    destination = Path(target)
    if not destination.is_absolute():
        raise SourceSelectionError("absolute-target-required")
    _reject_reparse_chain(destination.parent)
    if not os.path.lexists(destination):
        return {"status": "not-present", "target": str(destination)}
    if _is_reparse(destination) or not _verify_staged_target(
        destination, expected_inventory_hash
    ):
        raise SourceSelectionError("staged-target-drift")
    shutil.rmtree(destination)
    return {
        "status": "removed",
        "target": str(destination),
        "inventoryHash": expected_inventory_hash,
    }


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
    *,
    allow_compatible_link: bool = False,
    state_root: str | Path | None = None,
    migration_journal: str | Path | None = None,
    migration_backup: str | Path | None = None,
    protected_roots: tuple[str | Path, ...] = (),
) -> dict[str, object]:
    """Atomically stage only Git-tracked Superpowers Skill files."""

    source_path = Path(source)
    destination_path = Path(target)
    if not destination_path.is_absolute():
        raise SourceSelectionError("absolute-target-required")
    _reject_reparse_chain(source_path.absolute())
    _reject_reparse_chain(destination_path.parent)
    root = source_path.resolve(strict=True)
    destination = destination_path.absolute()
    if destination == root or destination in root.parents or root in destination.parents:
        raise SourceSelectionError("source-target-overlap")
    report = inspect_superpowers_source(root)
    if (
        report.get("supportStatus") != "supported"
        or report.get("inventoryHash") != expected_inventory_hash
    ):
        raise SourceSelectionError("source-drift")
    migration: dict[str, object] | None = None
    if os.path.lexists(destination_path) and _is_reparse(destination_path):
        if not allow_compatible_link:
            raise SourceSelectionError("target-conflict")
        if state_root is None or migration_journal is None or migration_backup is None:
            raise SourceSelectionError("migration-path-required")
        state = Path(state_root)
        journal = Path(migration_journal)
        backup = Path(migration_backup)
        if not all(path.is_absolute() for path in (state, journal, backup)):
            raise SourceSelectionError("absolute-migration-path-required")
        _reject_reparse_chain(state)
        _reject_reparse_chain(journal)
        _reject_reparse_chain(backup)
        protected_values = tuple(Path(path) for path in protected_roots)
        for item in protected_values:
            if not item.is_absolute():
                raise SourceSelectionError("absolute-migration-path-required")
            _reject_reparse_chain(item)
        state = state.absolute()
        journal = journal.absolute()
        backup = backup.absolute()
        protected = tuple(path.absolute() for path in protected_values)
        if (
            not _is_within(journal, state)
            or not _is_within(backup, state)
            or backup == state
            or not _same_volume(destination_path, backup)
            or _is_within(state, root)
            or _is_within(root, state)
            or any(_is_within(backup, item) for item in (root, *protected))
            or os.path.lexists(backup)
        ):
            raise SourceSelectionError("migration-path-invalid")
        _reject_reparse_chain(state)
        _reject_reparse_chain(journal.parent)
        _reject_reparse_chain(backup.parent)
        source_skills = (root / "skills").resolve(strict=True)
        if not _verify_source_link(destination_path, source_skills):
            raise SourceSelectionError("target-conflict")
        migration = {
            "schemaVersion": 1,
            "stateRoot": str(state),
            "sourceRoot": str(root),
            "sourceSkills": str(source_skills),
            "targetRoot": str(destination_path.parent.parent),
            "target": str(destination_path),
            "backup": str(backup),
            "protectedRoots": [str(item) for item in protected],
            "inventoryHash": expected_inventory_hash,
            "phase": "prepared",
        }
        _validated_migration_paths(journal, migration)
    elif destination.exists() or destination.is_symlink():
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
        if migration is not None:
            journal = Path(migration_journal)
            backup = Path(migration_backup)
            _write_json_atomic(journal, migration)
            backup.parent.mkdir(parents=True, exist_ok=True)
            os.replace(destination_path, backup)
            migration["phase"] = "link-moved"
            _write_json_atomic(journal, migration)
        os.replace(temporary, destination)
        if migration is not None:
            migration["phase"] = "staged"
            _write_json_atomic(Path(migration_journal), migration)
    except BaseException:
        if migration is not None and Path(migration_journal).exists():
            recover_superpowers_migration(Path(migration_journal))
        raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
    result = {
        "status": "staged",
        "target": str(destination),
        "inventoryHash": expected_inventory_hash,
    }
    if migration is not None:
        result.update({
            "migrationStatus": "staged",
            "migrationJournal": str(Path(migration_journal)),
            "migrationBackup": str(Path(migration_backup)),
        })
    return result
