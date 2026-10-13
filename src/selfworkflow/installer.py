"""Hash-bound transactional installer for isolated SelfWorkFlow runtimes."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from uuid import uuid4

from selfworkflow.managed_blocks import ManagedBlockError, render_managed_block
from selfworkflow.host_runtime import legacy_host_launcher, render_host_launcher
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
_RUNTIME_PROFILES = {"core", "knowledge", "maintainer", "custom-unverified"}


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


def _is_reparse(path: Path) -> bool:
    metadata = path.lstat()
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & _REPARSE
    )


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


def _relative_target(value: str) -> PurePosixPath:
    relative = PurePosixPath(value)
    if relative.is_absolute() or not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise InstallerError("managed-target-invalid")
    return relative


def _managed_target_state(root: Path, relative_value: str) -> dict[str, object]:
    relative = _relative_target(relative_value)
    target = root / Path(*relative.parts)
    current = root
    for part in relative.parts:
        current /= part
        if not os.path.lexists(current):
            continue
        metadata = current.lstat()
        if current.is_symlink() or getattr(metadata, "st_file_attributes", 0) & _REPARSE:
            raise InstallerError("reparse-path-rejected")
    if not os.path.lexists(target):
        return {"path": relative.as_posix(), "status": "missing"}
    if not target.is_file():
        raise InstallerError("managed-file-invalid")
    size = target.stat().st_size
    if size > _MAX_FILE_BYTES:
        raise InstallerError("managed-file-invalid")
    return {
        "path": relative.as_posix(),
        "status": "file",
        "size": size,
        "sha256": _path_hash(target),
    }


def _managed_surface_hash(root: Path, relative_values: list[str]) -> str:
    values = sorted(set(relative_values))
    if len(values) > _MAX_FILES:
        raise InstallerError("tree-too-large")
    return _canonical_hash(
        [_managed_target_state(root, relative) for relative in values]
    )


def _path_relative_to(path: Path, root: Path) -> str | None:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return None


def _plan_managed_surfaces(
    *, version: str, artifact_hash: str, artifact_files: list[str],
    retired_skill_files: list[str] | None = None,
) -> dict[str, list[str]]:
    snapshot_prefix = PurePosixPath(
        "selfworkflow", "versions", version, artifact_hash.removeprefix("sha256:")
    )
    agents = [
        (snapshot_prefix / _relative_target(relative)).as_posix()
        for relative in artifact_files
    ]
    agents.extend(
        relative for relative in artifact_files if relative.startswith("skills/")
    )
    agents.extend(retired_skill_files or [])
    agents.append("selfworkflow/current.json")
    return {
        "agentsRoot": agents,
        "codexRoot": ["AGENTS.md"],
        "stateRoot": ["current-manifest.json"],
    }


def _doctor_surfaces(
    agents: Path, codex: Path, state: Path
) -> dict[str, list[str]]:
    surfaces = {
        "agentsRoot": ["selfworkflow/current.json"],
        "codexRoot": ["AGENTS.md"],
        "stateRoot": ["current-manifest.json"],
    }
    manifest = _load_current_manifest(state)
    if not manifest:
        return surfaces
    roots = (("agentsRoot", agents), ("codexRoot", codex), ("stateRoot", state))
    for operation in manifest.get("operations", []):
        if not isinstance(operation, dict) or not isinstance(operation.get("target"), str):
            continue
        target = Path(operation["target"]).resolve(strict=False)
        for key, root in roots:
            relative = _path_relative_to(target, root)
            if relative:
                surfaces[key].append(relative)
                break
    return surfaces


def _root_report(path: Path, managed_targets: list[str]) -> dict[str, str]:
    if not path.exists():
        status = "missing"
    else:
        status = "present"
    return {
        "path": str(path),
        "status": status,
        "treeHash": _managed_surface_hash(path, managed_targets),
    }


def doctor(
    agents_root: str | Path,
    codex_root: str | Path,
    state_root: str | Path,
) -> dict[str, object]:
    agents = _safe_root(agents_root)
    codex = _safe_root(codex_root)
    state = _safe_root(state_root)
    surfaces = _doctor_surfaces(agents, codex, state)
    return {
        "schemaVersion": 1,
        "agentsRoot": _root_report(agents, surfaces["agentsRoot"]),
        "codexRoot": _root_report(codex, surfaces["codexRoot"]),
        "stateRoot": _root_report(state, surfaces["stateRoot"]),
        "incompleteTransactions": recover_transactions(state),
        "securityStatus": "unverified",
    }


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    if path.stat().st_size > _MAX_FILE_BYTES or not path.is_file() or path.is_symlink():
        raise InstallerError("managed-file-invalid")
    return path.read_bytes().decode("utf-8")


def _load_current_manifest(state: Path) -> dict[str, object] | None:
    current = state / "current-manifest.json"
    if not current.is_file():
        return None
    try:
        _managed_target_state(state, "current-manifest.json")
        value = json.loads(current.read_text(encoding="utf-8"))
        manifest_path = Path(value["manifestPath"])
        relative = _path_relative_to(manifest_path.resolve(strict=False), state)
        if relative is None or not relative.startswith("manifests/"):
            return None
        _managed_target_state(state, relative)
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (InstallerError, OSError, KeyError, TypeError, ValueError):
        return None


def _validate_disjoint_roots(roots: tuple[Path, ...]) -> None:
    for index, left in enumerate(roots):
        for right in roots[index + 1:]:
            if (
                left == right
                or _path_relative_to(left, right) is not None
                or _path_relative_to(right, left) is not None
            ):
                raise InstallerError("roots-overlap")


def _artifact_profile(artifact: Path) -> str:
    manifest_path = artifact / "artifact-manifest.json"
    if not manifest_path.exists():
        return "custom-unverified"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise InstallerError("artifact-invalid")
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise InstallerError("artifact-invalid") from None
    profile = value.get("profile") if isinstance(value, dict) else None
    if profile not in _RUNTIME_PROFILES - {"custom-unverified"}:
        raise InstallerError("artifact-invalid")
    return profile


def _managed_instruction(
    snapshot: Path,
    workflow_text: str,
    *,
    profile: str,
    artifact_hash: str,
) -> str:
    return (
        "## SelfWorkflow bootstrap\n\n"
        "SelfWorkflow 已从安装后的 hash-bound artifact 加载。\n\n"
        f"- profile: `{profile}`\n"
        f"- artifact: `{artifact_hash}`\n"
        f"- snapshot: `{snapshot}`\n\n"
        "在任何实质回复或任务操作前应用内嵌的轻量策略。普通任务直接遵循该策略，"
        "不创建 PlanGraph 或 RunLedger。从 snapshot 根目录只读读取选定的 mode 和 task module；"
        "仅在显式 contract-managed task 或 conforming Host 下使用 "
        "resolver、PlanGraph 和 RunLedger。能力不可用时只暂停 contract-managed mode，"
        "不得虚构 resolution evidence。\n\n"
        "任务使用工具、修改文件或产生副作用时，首条进度更新需报告 "
        f"`SelfWorkflow active: {profile}`。\n\n"
        "### 内嵌轻量策略\n\n"
        f"{workflow_text.strip()}"
    )


def _snapshot_root(
    agents: Path,
    version: str,
    artifact_hash: str,
) -> Path:
    return (
        agents
        / "selfworkflow"
        / "versions"
        / version
        / artifact_hash.removeprefix("sha256:")
    )


def _same_install_identity(
    manifest: dict[str, object],
    *,
    version: str,
    profile: str,
    artifact_hash: str,
    agents: Path,
    codex: Path,
    state: Path,
    host_launcher: dict[str, object] | None = None,
) -> bool:
    return all(
        (
            manifest.get("version") == version,
            manifest.get("profile") == profile,
            manifest.get("artifactHash") == artifact_hash,
            manifest.get("agentsRoot") == str(agents),
            manifest.get("codexRoot") == str(codex),
            manifest.get("stateRoot") == str(state),
            manifest.get("hostLauncher") == _host_identity(host_launcher),
        )
    )


def _host_identity(binding: dict[str, object] | None) -> dict[str, object] | None:
    if binding is None:
        return None
    return {key: binding[key] for key in ("path", "pythonExecutable", "pythonHash", "contentHash")}


def _host_launcher_plan(artifact: Path, agents: Path, launcher: str | Path, python: str | Path,
                        current: dict[str, object] | None) -> tuple[dict[str, object], list[str]]:
    raw_target, raw_python = Path(launcher), Path(python)
    target = _safe_root(raw_target.parent) / raw_target.name
    executable = _safe_root(raw_python.parent, allow_missing=False) / raw_python.name
    if target.name.casefold() != "selfworkflow.cmd" or target.is_dir() or (os.path.lexists(target) and _is_reparse(target)):
        raise InstallerError("host-launcher-target-invalid")
    if not executable.is_file() or _is_reparse(executable):
        raise InstallerError("host-python-invalid")
    if _path_relative_to(target, artifact) is not None:
        raise InstallerError("host-launcher-overlaps-artifact")
    try:
        content = render_host_launcher(artifact, agents, executable)
    except (OSError, ValueError) as error:
        raise InstallerError("host-runtime-invalid") from error
    exists = target.is_file()
    before_hash = _path_hash(target) if exists else None
    issues = []
    owned = next((op for op in (current or {}).get("operations", []) if op.get("target") == str(target)), None)
    if owned and before_hash != owned.get("afterHash"):
        issues.append("managed-host-launcher-drift")
    elif (
        exists and owned is None
        and target.read_bytes().replace(b"\r\n", b"\n")
        != legacy_host_launcher(executable).replace(b"\r\n", b"\n")
    ):
        issues.append("unmanaged-host-launcher-conflict")
    return {
        "path": str(target), "pythonExecutable": str(executable), "pythonHash": _path_hash(executable),
        "beforeExists": exists, "beforeHash": before_hash,
        "contentHash": "sha256:" + hashlib.sha256(content).hexdigest(),
    }, issues


def _retired_skill_files(
    manifest: dict[str, object] | None,
    agents: Path,
    desired_skill_files: set[str],
) -> tuple[list[str], list[str]]:
    retired: list[str] = []
    issues: list[str] = []
    managed_skill_hashes: dict[str, str] = {}
    operations = (
        manifest.get("operations", [])
        if manifest is not None and manifest.get("agentsRoot") == str(agents)
        else []
    )
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        target_value = operation.get("target")
        after_hash = operation.get("afterHash")
        if not isinstance(target_value, str) or not isinstance(after_hash, str):
            continue
        target = Path(target_value).resolve(strict=False)
        relative = _path_relative_to(target, agents)
        if (
            relative is None
            or not relative.startswith("skills/")
            or relative in desired_skill_files
        ):
            continue
        managed_skill_hashes[str(target)] = after_hash
        if not target.is_file() or _path_hash(target) != after_hash:
            issues.append(f"managed-skill-drift:{relative}")
        else:
            retired.append(relative)
    legacy_root = agents / "skills" / "caveman"
    if os.path.lexists(legacy_root):
        if not legacy_root.is_dir() or _is_reparse(legacy_root):
            issues.append("legacy-skill-ownership-unknown:skills/caveman")
        else:
            for path in sorted(legacy_root.rglob("*")):
                if _is_reparse(path):
                    issues.append("legacy-skill-ownership-unknown:skills/caveman")
                    continue
                if path.is_file():
                    expected = managed_skill_hashes.get(str(path.resolve(strict=False)))
                    if expected is None or _path_hash(path) != expected:
                        issues.append(
                            f"legacy-skill-ownership-unknown:{_path_relative_to(path, agents)}"
                        )
    return sorted(set(retired)), sorted(set(issues))


def create_install_plan(
    artifact_root: str | Path,
    agents_root: str | Path,
    codex_root: str | Path,
    state_root: str | Path,
    version: str,
    *, host_launcher: str | Path | None = None, host_python: str | Path | None = None,
) -> dict[str, object]:
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise InstallerError("version-invalid")
    artifact = _safe_root(artifact_root, allow_missing=False)
    agents = _safe_root(agents_root)
    codex = _safe_root(codex_root)
    state = _safe_root(state_root)
    roots = (artifact, agents, codex, state)
    _validate_disjoint_roots(roots)
    files = _manifest(artifact)
    if not files or not (artifact / "WORKFLOW.md").is_file():
        raise InstallerError("artifact-invalid")
    artifact_hash = _canonical_hash(files)
    profile = _artifact_profile(artifact)
    current_manifest = _load_current_manifest(state)
    retired_skill_files, retirement_issues = _retired_skill_files(
        current_manifest,
        agents,
        {item["path"] for item in files if item["path"].startswith("skills/")},
    )
    surfaces = _plan_managed_surfaces(
        version=version,
        artifact_hash=artifact_hash,
        artifact_files=[item["path"] for item in files],
        retired_skill_files=retired_skill_files,
    )
    baseline_hashes = {
        "agentsRoot": _managed_surface_hash(agents, surfaces["agentsRoot"]),
        "codexRoot": _managed_surface_hash(codex, surfaces["codexRoot"]),
        "stateRoot": _managed_surface_hash(state, surfaces["stateRoot"]),
    }
    issues: list[str] = list(retirement_issues)
    if (host_launcher is None) != (host_python is None):
        raise InstallerError("host-launcher-options-incomplete")
    host_binding = None
    if host_launcher is not None:
        host_binding, host_issues = _host_launcher_plan(artifact, agents, host_launcher, host_python, current_manifest)
        issues.extend(host_issues)
    agents_file = codex / "AGENTS.md"
    snapshot = _snapshot_root(agents, version, artifact_hash)
    try:
        render_managed_block(
            _read_text(agents_file),
            _managed_instruction(
                snapshot,
                _read_text(artifact / "WORKFLOW.md"),
                profile=profile,
                artifact_hash=artifact_hash,
            ),
        )
    except (ManagedBlockError, UnicodeError):
        issues.append("managed-block-invalid")
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
    status = "paused" if issues else "ready"
    if current_manifest and _same_install_identity(
        current_manifest,
        version=version,
        profile=profile,
        artifact_hash=artifact_hash,
        agents=agents,
        codex=codex,
        state=state,
        host_launcher=host_binding,
    ):
        try:
            if verify_install(Path(current_manifest["manifestPath"]))["status"] == "verified":
                status = "already-installed"
        except (InstallerError, KeyError, TypeError):
            pass
    plan = {
        "schemaVersion": 1,
        "operation": "install",
        "version": version,
        "profile": profile,
        "artifactRoot": str(artifact),
        "agentsRoot": str(agents),
        "codexRoot": str(codex),
        "stateRoot": str(state),
        "artifactHash": artifact_hash,
        "artifactFiles": [item["path"] for item in files],
        "retiredSkillFiles": retired_skill_files,
        "baselineHashes": baseline_hashes,
        "status": status,
        "issues": sorted(set(issues)),
        "securityStatus": "unverified",
    }
    if host_binding is not None:
        plan["hostLauncher"] = host_binding
    plan["planHash"] = _canonical_hash(plan)
    return plan


def _target_matches(path: Path, exists: bool, expected_hash: str | None) -> bool:
    _safe_root(path.parent, allow_missing=False)
    present = os.path.lexists(path)
    if not exists:
        return not present
    if not present:
        return False
    metadata = path.lstat()
    if path.is_symlink() or getattr(metadata, "st_file_attributes", 0) & _REPARSE:
        raise InstallerError("reparse-path-rejected")
    return path.is_file() and _path_hash(path) == expected_hash


def _atomic_write(
    path: Path,
    content: bytes,
    *,
    expected_state: tuple[bool, str | None] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _safe_root(path.parent, allow_missing=False)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if expected_state is not None and not _target_matches(path, *expected_state):
            raise InstallerError("operation-preimage-drift")
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _prepare_operation(
    target: Path, content: bytes, backup_root: Path,
) -> dict[str, object]:
    before_exists = target.is_file()
    before_bytes = target.read_bytes() if before_exists else None
    before_hash = (
        "sha256:" + hashlib.sha256(before_bytes).hexdigest()
        if before_bytes is not None
        else None
    )
    backup_path = None
    if before_exists:
        backup_path = backup_root / f"{len(list(backup_root.glob('*'))):06d}.bak"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(
            backup_path,
            before_bytes,
            expected_state=(False, None),
        )
        if _path_hash(backup_path) != before_hash:
            raise InstallerError("operation-backup-invalid")
    return {
        "target": str(target),
        "beforeExists": before_exists,
        "beforeHash": before_hash,
        "afterHash": "sha256:" + hashlib.sha256(content).hexdigest(),
        "backupPath": str(backup_path) if backup_path else None,
        "phase": "prepared",
    }


def _publish_operation(operation: dict[str, object], content: bytes) -> None:
    expected = "sha256:" + hashlib.sha256(content).hexdigest()
    if operation.get("afterHash") != expected or operation.get("phase") != "prepared":
        raise InstallerError("operation-intent-invalid")
    _atomic_write(
        Path(operation["target"]),
        content,
        expected_state=(operation.get("beforeExists") is True, operation.get("beforeHash")),
    )
    operation["phase"] = "applied"


def _publish_delete(operation: dict[str, object]) -> None:
    target = Path(operation["target"])
    if (
        operation.get("phase") != "prepared"
        or operation.get("beforeExists") is not True
        or operation.get("afterHash") is not None
        or not _target_matches(target, True, operation.get("beforeHash"))
    ):
        raise InstallerError("operation-intent-invalid")
    target.unlink()
    operation["phase"] = "applied"


def _manifest_operation(operation: dict[str, object]) -> dict[str, object]:
    return {
        key: operation[key]
        for key in (
            "target", "beforeExists", "beforeHash", "afterHash", "backupPath",
        )
    }


def _restore_operations(operations: list[dict[str, object]]) -> None:
    for item in reversed(operations):
        target = Path(item["target"])
        current_hash = _path_hash(target) if target.is_file() else None
        if current_hash == item["beforeHash"] and item["beforeExists"]:
            item["phase"] = "rolled-back"
            continue
        if current_hash is None and not item["beforeExists"]:
            item["phase"] = "rolled-back"
            continue
        if current_hash != item["afterHash"]:
            raise InstallerError("automatic-rollback-target-drift")
        if item["beforeExists"]:
            backup = Path(item["backupPath"])
            if not backup.is_file() or _path_hash(backup) != item["beforeHash"]:
                raise InstallerError("automatic-rollback-backup-invalid")
            after_exists = item["afterHash"] is not None
            _atomic_write(
                target,
                backup.read_bytes(),
                expected_state=(after_exists, item["afterHash"]),
            )
        else:
            if not _target_matches(target, True, item["afterHash"]):
                raise InstallerError("automatic-rollback-target-drift")
            target.unlink()
        item["phase"] = "rolled-back"


def _validate_plan_hash(plan: dict[str, object], confirmed_hash: str) -> None:
    if not isinstance(plan, dict):
        raise InstallerError("plan-invalid")
    expected = {
        "install": {
            "schemaVersion", "operation", "version", "profile", "artifactRoot", "agentsRoot",
            "codexRoot", "stateRoot", "artifactHash", "artifactFiles",
            "retiredSkillFiles",
            "baselineHashes", "status", "issues", "securityStatus", "planHash",
        },
        "rollback": {
            "schemaVersion", "operation", "transactionId", "transactionPath",
            "transactionHash", "stateRoot", "targetVersion", "operations",
            "securityStatus", "planHash",
        },
    }.get(plan.get("operation"))
    if expected is not None and plan.get("operation") == "install" and "hostLauncher" in plan:
        expected = expected | {"hostLauncher"}
    if expected is None or set(plan) != expected or plan.get("schemaVersion") != 1:
        raise InstallerError("plan-invalid")
    supplied = dict(plan)
    plan_hash = supplied.pop("planHash", None)
    if plan_hash != _canonical_hash(supplied) or confirmed_hash != plan_hash:
        raise InstallerError("plan-confirmation-invalid")


def _validate_ready_plan_baseline(
    plan: dict[str, object], artifact: Path, agents: Path, codex: Path, state: Path,
) -> None:
    manifest = _manifest(artifact)
    if (
        _canonical_hash(manifest) != plan["artifactHash"]
        or [item["path"] for item in manifest] != plan["artifactFiles"]
    ):
        raise InstallerError("artifact-drift")
    surfaces = _plan_managed_surfaces(
        version=plan["version"],
        artifact_hash=plan["artifactHash"],
        artifact_files=plan["artifactFiles"],
        retired_skill_files=plan["retiredSkillFiles"],
    )
    if (
        _managed_surface_hash(agents, surfaces["agentsRoot"])
        != plan["baselineHashes"]["agentsRoot"]
        or _managed_surface_hash(codex, surfaces["codexRoot"])
        != plan["baselineHashes"]["codexRoot"]
        or _managed_surface_hash(state, surfaces["stateRoot"])
        != plan["baselineHashes"]["stateRoot"]
    ):
        raise InstallerError("target-drift")
    if "hostLauncher" in plan:
        binding = plan["hostLauncher"]
        if not isinstance(binding, dict) or set(binding) != {
            "path", "pythonExecutable", "pythonHash", "beforeExists", "beforeHash", "contentHash",
        } or type(binding["beforeExists"]) is not bool:
            raise InstallerError("host-launcher-plan-invalid")
        current, issues = _host_launcher_plan(artifact, agents, binding["path"], binding["pythonExecutable"], _load_current_manifest(state))
        if issues or current != binding:
            raise InstallerError("host-launcher-drift")


def apply_install_plan(plan: dict[str, object], confirmed_hash: str) -> dict[str, object]:
    _validate_plan_hash(plan, confirmed_hash)
    if plan.get("status") == "already-installed":
        state = _safe_root(plan["stateRoot"], allow_missing=False)
        if os.path.lexists(state / "install.lock"):
            raise InstallerError("installer-locked")
        agents = _safe_root(plan["agentsRoot"], allow_missing=False)
        codex = _safe_root(plan["codexRoot"], allow_missing=False)
        manifest = _load_current_manifest(state)
        if (
            manifest is None
            or not _same_install_identity(
                manifest,
                version=plan["version"],
                profile=plan["profile"],
                artifact_hash=plan["artifactHash"],
                agents=agents,
                codex=codex,
                state=state,
                host_launcher=plan.get("hostLauncher"),
            )
        ):
            raise InstallerError("installed-state-drift")
        verify_install(Path(manifest["manifestPath"]))
        return {
            "status": "already-installed",
            "manifestPath": manifest["manifestPath"],
            "transactionId": manifest["transactionId"],
            "transactionPath": manifest["transactionPath"],
        }
    if plan.get("status") != "ready":
        raise InstallerError("plan-not-ready")
    artifact = _safe_root(plan["artifactRoot"], allow_missing=False)
    agents = _safe_root(plan["agentsRoot"])
    codex = _safe_root(plan["codexRoot"])
    state = _safe_root(plan["stateRoot"])
    _validate_ready_plan_baseline(plan, artifact, agents, codex, state)
    transaction_id = uuid4().hex
    transaction_path = state / "transactions" / f"{transaction_id}.json"
    backup_root = state / "backups" / transaction_id
    manifest_path = state / "manifests" / f"{transaction_id}.json"
    operations: list[dict[str, object]] = []
    committed = False
    cleanup_pending: list[str] = []
    try:
        with exclusive_install_lock(state):
            _validate_ready_plan_baseline(plan, artifact, agents, codex, state)
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
            try:
                write_json_atomic(transaction_path, transaction)

                def record(target: Path, content: bytes, *, expected_before: dict[str, object] | None = None) -> None:
                    operation = _prepare_operation(target, content, backup_root)
                    if expected_before is not None and any(
                        operation[key] != expected_before[key] for key in ("beforeExists", "beforeHash")
                    ):
                        raise InstallerError("host-launcher-drift")
                    operations.append(operation)
                    transaction["operations"] = operations
                    write_json_atomic(transaction_path, transaction)
                    _publish_operation(operation, content)
                    transaction["operations"] = operations
                    write_json_atomic(transaction_path, transaction)

                def record_delete(target: Path) -> None:
                    operation = _prepare_operation(target, b"", backup_root)
                    operation["afterHash"] = None
                    operations.append(operation)
                    transaction["operations"] = operations
                    write_json_atomic(transaction_path, transaction)
                    _publish_delete(operation)
                    transaction["operations"] = operations
                    write_json_atomic(transaction_path, transaction)

                snapshot = _snapshot_root(agents, plan["version"], plan["artifactHash"])
                for item in _manifest(artifact):
                    source = artifact / Path(*PurePosixPath(item["path"]).parts)
                    record(snapshot / item["path"], source.read_bytes())
                for relative in plan["retiredSkillFiles"]:
                    record_delete(agents / Path(*PurePosixPath(relative).parts))
                for item in _manifest(artifact):
                    if item["path"].startswith("skills/"):
                        source = artifact / Path(*PurePosixPath(item["path"]).parts)
                        record(agents / item["path"], source.read_bytes())
                agents_path = codex / "AGENTS.md"
                agents_content = render_managed_block(
                    _read_text(agents_path),
                    _managed_instruction(
                        snapshot,
                        _read_text(artifact / "WORKFLOW.md"),
                        profile=plan["profile"],
                        artifact_hash=plan["artifactHash"],
                    ),
                ).encode("utf-8")
                record(agents_path, agents_content)
                pointer = (json.dumps(
                    {
                        "version": plan["version"],
                        "profile": plan["profile"],
                        "artifactHash": plan["artifactHash"],
                        "snapshot": str(snapshot),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ) + "\n").encode("utf-8")
                record(agents / "selfworkflow/current.json", pointer)
                host_binding = plan.get("hostLauncher")
                if host_binding is not None:
                    content = render_host_launcher(artifact, agents, Path(host_binding["pythonExecutable"]))
                    if "sha256:" + hashlib.sha256(content).hexdigest() != host_binding["contentHash"]:
                        raise InstallerError("host-launcher-content-drift")
                    record(Path(host_binding["path"]), content, expected_before=host_binding)
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
                    "profile": plan["profile"],
                    "artifactHash": plan["artifactHash"],
                    "agentsRoot": str(agents),
                    "codexRoot": str(codex),
                    "stateRoot": str(state),
                    "operations": [_manifest_operation(item) for item in operations],
                    "securityStatus": "unverified",
                }
                if host_binding is not None:
                    manifest["hostLauncher"] = _host_identity(host_binding)
                write_json_atomic(manifest_path, manifest)
                transaction.update({"state": "completed", "operations": operations, "manifestPath": str(manifest_path)})
                write_json_atomic(transaction_path, transaction)
                committed = True
            except BaseException as failure:
                try:
                    _restore_operations(operations)
                    manifest_path.unlink(missing_ok=True)
                    transaction.update({"state": "rolled-back", "operations": operations})
                    write_json_atomic(transaction_path, transaction)
                except Exception:
                    raise InstallerError("automatic-rollback-failed") from None
                if not isinstance(failure, Exception):
                    raise
                raise InstallerError("apply-failed") from None
    except InstallerError:
        raise
    except TransactionError as error:
        if committed and str(error) == "installer-lock-release-failed":
            cleanup_pending.append(str(error))
        else:
            raise InstallerError(str(error)) from None
    except ManagedBlockError as error:
        raise InstallerError(str(error)) from None
    result = {
        "status": "applied",
        "manifestPath": str(manifest_path),
        "transactionId": transaction_id,
        "transactionPath": str(transaction_path),
    }
    if cleanup_pending:
        result["cleanupPending"] = cleanup_pending
    return result


def verify_install(manifest_path: str | Path) -> dict[str, object]:
    path = Path(manifest_path)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise InstallerError("manifest-invalid") from None
    for operation in manifest.get("operations", []):
        target = Path(operation["target"])
        if operation.get("afterHash") is None:
            if target.exists():
                raise InstallerError("installed-file-drift")
        elif not target.is_file() or _path_hash(target) != operation["afterHash"]:
            raise InstallerError("installed-file-drift")
    host = manifest.get("hostLauncher")
    if host is not None:
        raw_python = Path(host["pythonExecutable"])
        python = _safe_root(raw_python.parent, allow_missing=False) / raw_python.name
        if not python.is_file() or _is_reparse(python) or _path_hash(python) != host["pythonHash"]:
            raise InstallerError("installed-host-python-drift")
    return {"status": "verified", "manifestPath": str(path)}


def create_rollback_plan(
    transaction_path: str | Path, output_path: str | Path | None = None
) -> dict[str, object]:
    transaction_file = Path(transaction_path)
    try:
        transaction = json.loads(transaction_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise InstallerError("transaction-invalid") from None
    if transaction.get("state") not in {"completed", "rolling-back"}:
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
        if item.get("phase") != "rolled-back"
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
        if item["expectedHash"] is None:
            drifted = target.exists()
        else:
            drifted = not target.is_file() or _path_hash(target) != item["expectedHash"]
        if drifted:
            raise InstallerError("rollback-target-drift")
    try:
        with exclusive_install_lock(state):
            if (
                not transaction_path.is_file()
                or _path_hash(transaction_path) != plan["transactionHash"]
            ):
                raise InstallerError("rollback-transaction-drift")
            for item in plan["operations"]:
                target = Path(item["target"])
                expected_exists = item["expectedHash"] is not None
                if not _target_matches(target, expected_exists, item["expectedHash"]):
                    raise InstallerError("rollback-target-drift")
            transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
            if transaction.get("state") not in {"completed", "rolling-back"}:
                raise InstallerError("rollback-transaction-drift")
            transaction["state"] = "rolling-back"
            write_json_atomic(transaction_path, transaction)
            for item in reversed(plan["operations"]):
                target = Path(item["target"])
                expected_exists = item["expectedHash"] is not None
                if item["beforeExists"]:
                    backup = Path(item["backupPath"])
                    if not backup.is_file() or _path_hash(backup) != item["beforeHash"]:
                        raise InstallerError("rollback-backup-invalid")
                    _atomic_write(
                        target,
                        backup.read_bytes(),
                        expected_state=(expected_exists, item["expectedHash"]),
                    )
                else:
                    if not _target_matches(target, True, item["expectedHash"]):
                        raise InstallerError("rollback-target-drift")
                    target.unlink()
                matches = [
                    operation
                    for operation in transaction["operations"]
                    if operation.get("target") == item["target"]
                    and operation.get("afterHash") == item["expectedHash"]
                ]
                if len(matches) != 1:
                    raise InstallerError("rollback-transaction-drift")
                matches[0]["phase"] = "rolled-back"
                write_json_atomic(transaction_path, transaction)
            transaction["state"] = "rolled-back"
            write_json_atomic(transaction_path, transaction)
    except TransactionError as error:
        raise InstallerError(str(error)) from None
    return {"status": "rolled-back", "transactionId": plan["transactionId"]}
