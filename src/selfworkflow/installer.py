"""Hash-bound transactional installer for isolated SelfWorkFlow runtimes."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from uuid import uuid4

from selfworkflow.managed_blocks import ManagedBlockError, render_managed_block
from selfworkflow.transactions import (
    TransactionError,
    exclusive_install_lock,
    recover_transactions,
    write_json_atomic,
)


_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+-]{0,63}")
_REPARSE = 0x400
_MAX_FILES = 20_000
_MAX_FILE_BYTES = 8 * 1024 * 1024
_MAX_TREE_BYTES = 64 * 1024 * 1024


class InstallerError(RuntimeError):
    pass


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _path_hash(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise InstallerError("file-invalid")
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_root(path: str | Path, *, allow_missing: bool = True) -> Path:
    raw = Path(path)
    if not raw.is_absolute():
        raise InstallerError("absolute-path-required")
    current = raw.anchor and Path(raw.anchor)
    for part in raw.parts[1:] if raw.anchor else raw.parts:
        current = current / part if current else Path(part)
        if os.path.lexists(current):
            metadata = current.lstat()
            if current.is_symlink() or (
                getattr(metadata, "st_file_attributes", 0) & _REPARSE
            ):
                raise InstallerError("reparse-path-rejected")
    if not allow_missing and not raw.exists():
        raise InstallerError("path-missing")
    return raw.resolve(strict=False)


def _manifest(root: Path) -> list[dict[str, object]]:
    if not root.exists():
        return []
    if not root.is_dir() or root.is_symlink():
        raise InstallerError("tree-invalid")
    entries: list[dict[str, object]] = []
    total = 0
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        if path.is_symlink() or getattr(metadata, "st_file_attributes", 0) & _REPARSE:
            raise InstallerError("reparse-path-rejected")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        if size > _MAX_FILE_BYTES:
            raise InstallerError("file-too-large")
        total += size
        if len(entries) >= _MAX_FILES or total > _MAX_TREE_BYTES:
            raise InstallerError("tree-too-large")
        entries.append({"path": relative, "size": size, "sha256": _path_hash(path)})
    return entries


def tree_hash(root: str | Path) -> str:
    path = Path(root)
    if not path.exists():
        return "missing"
    return _canonical_hash(_manifest(path))


def _root_report(path: Path) -> dict[str, str]:
    if not path.exists():
        return {"path": str(path), "status": "missing", "treeHash": "missing"}
    return {"path": str(path), "status": "present", "treeHash": tree_hash(path)}


def doctor(
    agents_root: str | Path,
    codex_root: str | Path,
    state_root: str | Path,
) -> dict[str, object]:
    agents = _safe_root(agents_root)
    codex = _safe_root(codex_root)
    state = _safe_root(state_root)
    return {
        "schemaVersion": 1,
        "agentsRoot": _root_report(agents),
        "codexRoot": _root_report(codex),
        "stateRoot": _root_report(state),
        "incompleteTransactions": recover_transactions(state),
        "securityStatus": "unverified",
    }


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    if path.stat().st_size > _MAX_FILE_BYTES or not path.is_file() or path.is_symlink():
        raise InstallerError("managed-file-invalid")
    return path.read_text(encoding="utf-8")


def _load_current_manifest(state: Path) -> dict[str, object] | None:
    current = state / "current-manifest.json"
    if not current.is_file():
        return None
    try:
        value = json.loads(current.read_text(encoding="utf-8"))
        manifest_path = Path(value["manifestPath"])
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, KeyError, TypeError, ValueError):
        return None


def create_install_plan(
    artifact_root: str | Path,
    agents_root: str | Path,
    codex_root: str | Path,
    state_root: str | Path,
    version: str,
) -> dict[str, object]:
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise InstallerError("version-invalid")
    artifact = _safe_root(artifact_root, allow_missing=False)
    agents = _safe_root(agents_root)
    codex = _safe_root(codex_root)
    state = _safe_root(state_root)
    roots = (artifact, agents, codex, state)
    if len({str(path).casefold() for path in roots}) != len(roots):
        raise InstallerError("roots-overlap")
    files = _manifest(artifact)
    if not files or not (artifact / "WORKFLOW.md").is_file():
        raise InstallerError("artifact-invalid")
    issues: list[str] = []
    agents_file = codex / "AGENTS.md"
    snapshot = agents / "selfworkflow" / "versions" / version
    try:
        render_managed_block(
            _read_text(agents_file),
            f"Read the vendor-neutral workflow at `{snapshot / 'WORKFLOW.md'}`.",
        )
    except (ManagedBlockError, UnicodeError):
        issues.append("managed-block-invalid")
    current_manifest = _load_current_manifest(state)
    managed_targets = {
        item["target"] for item in current_manifest.get("operations", [])
    } if current_manifest else set()
    for item in files:
        relative = item["path"]
        snapshot_target = snapshot / relative
        if snapshot_target.exists() and str(snapshot_target) not in managed_targets:
            issues.append(f"unmanaged-snapshot-conflict:{relative}")
        if relative.startswith("skills/"):
            target = agents / relative
            if target.exists() and str(target) not in managed_targets:
                issues.append(f"unmanaged-skill-conflict:{relative}")
    artifact_hash = _canonical_hash(files)
    status = "paused" if issues else "ready"
    if current_manifest and current_manifest.get("artifactHash") == artifact_hash and current_manifest.get("version") == version:
        try:
            if verify_install(Path(current_manifest["manifestPath"]))["status"] == "verified":
                status = "already-installed"
        except (InstallerError, KeyError, TypeError):
            pass
    plan = {
        "schemaVersion": 1,
        "operation": "install",
        "version": version,
        "artifactRoot": str(artifact),
        "agentsRoot": str(agents),
        "codexRoot": str(codex),
        "stateRoot": str(state),
        "artifactHash": artifact_hash,
        "artifactFiles": [item["path"] for item in files],
        "baselineHashes": {
            "agentsRoot": tree_hash(agents),
            "codexRoot": tree_hash(codex),
        },
        "status": status,
        "issues": sorted(set(issues)),
        "securityStatus": "unverified",
    }
    plan["planHash"] = _canonical_hash(plan)
    return plan


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _operation(target: Path, content: bytes, backup_root: Path) -> dict[str, object]:
    before_exists = target.is_file()
    before_hash = _path_hash(target) if before_exists else None
    backup_path = None
    if before_exists:
        backup_path = backup_root / f"{len(list(backup_root.glob('*'))):06d}.bak"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(target, backup_path)
    _atomic_write(target, content)
    return {
        "target": str(target),
        "beforeExists": before_exists,
        "beforeHash": before_hash,
        "afterHash": _path_hash(target),
        "backupPath": str(backup_path) if backup_path else None,
    }


def _validate_plan_hash(plan: dict[str, object], confirmed_hash: str) -> None:
    if not isinstance(plan, dict):
        raise InstallerError("plan-invalid")
    expected = {
        "install": {
            "schemaVersion", "operation", "version", "artifactRoot", "agentsRoot",
            "codexRoot", "stateRoot", "artifactHash", "artifactFiles",
            "baselineHashes", "status", "issues", "securityStatus", "planHash",
        },
        "rollback": {
            "schemaVersion", "operation", "transactionId", "transactionPath",
            "transactionHash", "stateRoot", "targetVersion", "operations",
            "securityStatus", "planHash",
        },
    }.get(plan.get("operation"))
    if expected is None or set(plan) != expected or plan.get("schemaVersion") != 1:
        raise InstallerError("plan-invalid")
    supplied = dict(plan)
    plan_hash = supplied.pop("planHash", None)
    if plan_hash != _canonical_hash(supplied) or confirmed_hash != plan_hash:
        raise InstallerError("plan-confirmation-invalid")


def apply_install_plan(plan: dict[str, object], confirmed_hash: str) -> dict[str, object]:
    _validate_plan_hash(plan, confirmed_hash)
    if plan.get("status") != "ready":
        raise InstallerError("plan-not-ready")
    artifact = _safe_root(plan["artifactRoot"], allow_missing=False)
    agents = _safe_root(plan["agentsRoot"])
    codex = _safe_root(plan["codexRoot"])
    state = _safe_root(plan["stateRoot"])
    if _canonical_hash(_manifest(artifact)) != plan["artifactHash"]:
        raise InstallerError("artifact-drift")
    if tree_hash(agents) != plan["baselineHashes"]["agentsRoot"] or tree_hash(codex) != plan["baselineHashes"]["codexRoot"]:
        raise InstallerError("target-drift")
    transaction_id = uuid4().hex
    transaction_path = state / "transactions" / f"{transaction_id}.json"
    backup_root = state / "backups" / transaction_id
    manifest_path = state / "manifests" / f"{transaction_id}.json"
    operations: list[dict[str, object]] = []
    try:
        with exclusive_install_lock(state):
            transaction = {
                "schemaVersion": 1,
                "transactionId": transaction_id,
                "state": "applying",
                "version": plan["version"],
                "artifactHash": plan["artifactHash"],
                "agentsRoot": str(agents),
                "codexRoot": str(codex),
                "stateRoot": str(state),
                "operations": operations,
            }
            write_json_atomic(transaction_path, transaction)

            def record(target: Path, content: bytes) -> None:
                operations.append(_operation(target, content, backup_root))
                transaction["operations"] = operations
                write_json_atomic(transaction_path, transaction)

            snapshot = agents / "selfworkflow" / "versions" / plan["version"]
            for item in _manifest(artifact):
                source = artifact / Path(*PurePosixPath(item["path"]).parts)
                record(snapshot / item["path"], source.read_bytes())
            for item in _manifest(artifact):
                if item["path"].startswith("skills/"):
                    source = artifact / Path(*PurePosixPath(item["path"]).parts)
                    record(agents / item["path"], source.read_bytes())
            agents_path = codex / "AGENTS.md"
            agents_content = render_managed_block(
                _read_text(agents_path),
                f"Read the vendor-neutral workflow at `{snapshot / 'WORKFLOW.md'}`.",
            ).encode("utf-8")
            record(agents_path, agents_content)
            pointer = (json.dumps(
                {"version": plan["version"], "snapshot": str(snapshot)},
                sort_keys=True,
                separators=(",", ":"),
            ) + "\n").encode("utf-8")
            record(agents / "selfworkflow/current.json", pointer)
            current_manifest_content = (
                json.dumps(
                    {"manifestPath": str(manifest_path)},
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
            record(state / "current-manifest.json", current_manifest_content)
            manifest = {
                "schemaVersion": 1,
                "manifestPath": str(manifest_path),
                "transactionId": transaction_id,
                "transactionPath": str(transaction_path),
                "version": plan["version"],
                "artifactHash": plan["artifactHash"],
                "operations": operations,
                "securityStatus": "unverified",
            }
            write_json_atomic(manifest_path, manifest)
            transaction.update({"state": "completed", "operations": operations, "manifestPath": str(manifest_path)})
            write_json_atomic(transaction_path, transaction)
    except (ManagedBlockError, TransactionError) as error:
        raise InstallerError(str(error)) from None
    return {
        "status": "applied",
        "manifestPath": str(manifest_path),
        "transactionId": transaction_id,
        "transactionPath": str(transaction_path),
    }


def verify_install(manifest_path: str | Path) -> dict[str, object]:
    path = Path(manifest_path)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise InstallerError("manifest-invalid") from None
    for operation in manifest.get("operations", []):
        target = Path(operation["target"])
        if not target.is_file() or _path_hash(target) != operation["afterHash"]:
            raise InstallerError("installed-file-drift")
    return {"status": "verified", "manifestPath": str(path)}


def create_rollback_plan(
    transaction_path: str | Path, output_path: str | Path | None = None
) -> dict[str, object]:
    transaction_file = Path(transaction_path)
    try:
        transaction = json.loads(transaction_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise InstallerError("transaction-invalid") from None
    if transaction.get("state") != "completed":
        raise InstallerError("transaction-not-complete")
    operations = [
        {
            "target": item["target"],
            "expectedHash": item["afterHash"],
            "beforeExists": item["beforeExists"],
            "beforeHash": item["beforeHash"],
            "backupPath": item["backupPath"],
        }
        for item in transaction["operations"]
    ]
    state_root = transaction_file.parents[1]
    plan = {
        "schemaVersion": 1,
        "operation": "rollback",
        "transactionId": transaction["transactionId"],
        "transactionPath": str(transaction_file),
        "transactionHash": _path_hash(transaction_file),
        "stateRoot": str(state_root),
        "targetVersion": transaction["version"],
        "operations": operations,
        "securityStatus": "unverified",
    }
    plan["planHash"] = _canonical_hash(plan)
    if output_path is not None:
        write_json_atomic(Path(output_path), plan)
    return plan


def apply_rollback_plan(plan: dict[str, object], confirmed_hash: str) -> dict[str, object]:
    _validate_plan_hash(plan, confirmed_hash)
    state = _safe_root(plan["stateRoot"], allow_missing=False)
    transaction_path = Path(plan["transactionPath"])
    if not transaction_path.is_file() or _path_hash(transaction_path) != plan["transactionHash"]:
        raise InstallerError("rollback-transaction-drift")
    for item in plan["operations"]:
        target = Path(item["target"])
        if not target.is_file() or _path_hash(target) != item["expectedHash"]:
            raise InstallerError("rollback-target-drift")
    try:
        with exclusive_install_lock(state):
            for item in reversed(plan["operations"]):
                target = Path(item["target"])
                if item["beforeExists"]:
                    backup = Path(item["backupPath"])
                    if not backup.is_file() or _path_hash(backup) != item["beforeHash"]:
                        raise InstallerError("rollback-backup-invalid")
                    _atomic_write(target, backup.read_bytes())
                else:
                    target.unlink()
            transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
            transaction["state"] = "rolled-back"
            write_json_atomic(transaction_path, transaction)
    except TransactionError as error:
        raise InstallerError(str(error)) from None
    return {"status": "rolled-back", "transactionId": plan["transactionId"]}
