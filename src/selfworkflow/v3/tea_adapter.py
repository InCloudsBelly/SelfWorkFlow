"""Fail-closed TEA source verification, bounded routing, and JIT reads."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any, Mapping

from selfworkflow.v3.catalog import CatalogError, _load_yaml_file
from selfworkflow.v3.hashing import content_hash, hash_bytes


_SOURCE = "dependencies/upstream/tea"
_LOCK = "dependencies/locks/tea.lock.yaml"
_ADAPTER = "overlays/tea/adapter.yaml"
_ROUTING = "overlays/tea/routing.yaml"
_URL = "https://github.com/bmad-code-org/bmad-method-test-architecture-enterprise.git"
_LEVELS = {"T0": 0, "T1": 1, "T2": 2, "T3": 3}
_STAGES = {"plan", "implementation", "review", "verify", "release"}
_MAX_CONFIG_BYTES = 1024 * 1024
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_HASH = re.compile(r"sha256:[0-9a-f]{64}")


class TeaAdapterError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _run(command: list[str], cwd: Path, *, allow_missing: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
            errors="strict", check=False,
        )
    except (OSError, UnicodeError, ValueError):
        raise TeaAdapterError("tea-source-identity-invalid") from None
    if result.returncode != 0 and not allow_missing:
        raise TeaAdapterError("tea-source-identity-invalid")
    return result


def _mapping(path: Path, root: Path, fields: set[str]) -> dict[str, Any]:
    try:
        value = _load_yaml_file(path, _MAX_CONFIG_BYTES, root)
    except (CatalogError, OSError, ValueError):
        raise TeaAdapterError("tea-source-identity-invalid") from None
    if not isinstance(value, dict) or set(value) != fields:
        raise TeaAdapterError("tea-source-identity-invalid")
    return value


def _file_hash(path: Path) -> str:
    try:
        if not path.is_file() or path.is_symlink():
            raise OSError
        return hash_bytes(path.read_bytes())
    except (OSError, ValueError):
        raise TeaAdapterError("tea-source-identity-invalid") from None


def verify_tea_source(repository: str | Path) -> dict[str, str]:
    """Recompute every pinned identity dimension; any drift has one stable error."""

    root = Path(repository).resolve()
    tea = root / _SOURCE
    lock = _mapping(
        root / _LOCK,
        root,
        {
            "schemaVersion", "sourceId", "canonicalUrl", "path", "gitlinkCommit",
            "gitTree", "inventoryHash", "license", "adapterFiles", "adapterHash", "status",
        },
    )
    if (
        lock["schemaVersion"] != 3
        or lock["sourceId"] != "tea"
        or lock["canonicalUrl"] != _URL
        or lock["path"] != _SOURCE
        or not tea.is_dir()
    ):
        raise TeaAdapterError("tea-source-identity-invalid")

    url = _run(
        ["git", "config", "--file", ".gitmodules", "--get", "submodule.dependencies/upstream/tea.url"],
        root,
    ).stdout.strip()
    branch = _run(
        ["git", "config", "--file", ".gitmodules", "--get", "submodule.dependencies/upstream/tea.branch"],
        root,
        allow_missing=True,
    )
    if url != _URL or branch.returncode == 0 or branch.stdout.strip():
        raise TeaAdapterError("tea-source-identity-invalid")

    listing = _run(["git", "ls-files", "--stage", "--", _SOURCE], root).stdout.strip().split()
    if len(listing) < 2 or listing[0] != "160000":
        raise TeaAdapterError("tea-source-identity-invalid")
    commit = _run(["git", "rev-parse", "HEAD"], tea).stdout.strip()
    tree = _run(["git", "rev-parse", "HEAD^{tree}"], tea).stdout.strip()
    dirty = _run(["git", "status", "--porcelain=v1", "--untracked-files=all"], tea).stdout
    inventory = _run(["git", "ls-tree", "-r", "--full-tree", "HEAD"], tea).stdout.encode("utf-8")
    if dirty or any(value != lock["gitlinkCommit"] for value in (listing[1], commit)):
        raise TeaAdapterError("tea-source-identity-invalid")
    if tree != lock["gitTree"] or hash_bytes(inventory) != lock["inventoryHash"]:
        raise TeaAdapterError("tea-source-identity-invalid")

    license_info = lock["license"]
    if not isinstance(license_info, dict) or set(license_info) != {"path", "spdx", "hash"}:
        raise TeaAdapterError("tea-source-identity-invalid")
    if license_info["path"] != "LICENSE" or license_info["spdx"] != "MIT":
        raise TeaAdapterError("tea-source-identity-invalid")
    if _file_hash(tea / "LICENSE") != license_info["hash"]:
        raise TeaAdapterError("tea-source-identity-invalid")

    adapter_files = lock["adapterFiles"]
    if not isinstance(adapter_files, list) or len(adapter_files) != 2:
        raise TeaAdapterError("tea-source-identity-invalid")
    identities = []
    seen: set[str] = set()
    for item in adapter_files:
        if not isinstance(item, dict) or set(item) != {"path", "hash"}:
            raise TeaAdapterError("tea-source-identity-invalid")
        path = item["path"]
        if path in seen or path not in {_ADAPTER, _ROUTING} or not _HASH.fullmatch(item["hash"]):
            raise TeaAdapterError("tea-source-identity-invalid")
        seen.add(path)
        actual = _file_hash(root / path)
        if actual != item["hash"]:
            raise TeaAdapterError("tea-source-identity-invalid")
        identities.append({"path": path, "hash": actual})
    if content_hash(identities) != lock["adapterHash"]:
        raise TeaAdapterError("tea-source-identity-invalid")
    status = lock["status"]
    if not isinstance(status, dict) or status.get("sourceIntegrity") != "supported":
        raise TeaAdapterError("tea-source-identity-invalid")
    return {"commit": commit, "tree": tree, "status": "supported"}


def load_workflow_candidates(repository: str | Path) -> tuple[dict[str, Any], ...]:
    root = Path(repository).resolve()
    verify_tea_source(root)
    adapter = _mapping(
        root / _ADAPTER,
        root,
        {"schemaVersion", "sourceId", "sourcePath", "artifactRoot", "workflows"},
    )
    workflows = adapter["workflows"]
    if adapter["schemaVersion"] != 3 or not isinstance(workflows, list) or len(workflows) != 9:
        raise TeaAdapterError("tea-adapter-invalid")
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    for item in workflows:
        if not isinstance(item, dict) or set(item) != {"id", "upstreamId", "root", "support"}:
            raise TeaAdapterError("tea-adapter-invalid")
        if item["id"] in ids:
            raise TeaAdapterError("tea-adapter-invalid")
        ids.add(item["id"])
        support = item["support"]
        if not isinstance(support, dict) or set(support) != {
            "sourceIntegrity", "adapterSupport", "runtimeCapability", "behaviorEvidence"
        }:
            raise TeaAdapterError("tea-adapter-invalid")
        result.append(json.loads(json.dumps(item)))
    return tuple(result)


def eligible_workflows(
    *, stage: str, test_level: str, grill_me_used: bool = False,
    acceptance_red: bool = False,
) -> tuple[str, ...]:
    if stage not in _STAGES or test_level not in _LEVELS or type(grill_me_used) is not bool or type(acceptance_red) is not bool:
        raise TeaAdapterError("tea-route-invalid")
    effective = max(_LEVELS[test_level], 2 if grill_me_used else 0)
    if effective < 2:
        return ()
    if stage == "plan":
        return ("test-design",)
    if stage == "review":
        return ("test-review",)
    if stage == "implementation":
        return ("atdd",) if acceptance_red else ()
    if effective >= 3 and stage in {"verify", "release"}:
        return ("trace", "nfr")
    return ()


def load_jit_artifact(
    repository: str | Path, *, workflow_id: str, kind: str, relative_path: str,
) -> dict[str, Any]:
    root = Path(repository).resolve()
    candidates = {item["id"]: item for item in load_workflow_candidates(root)}
    candidate = candidates.get(workflow_id)
    if candidate is None or candidate["support"]["adapterSupport"] != "supported":
        raise TeaAdapterError("tea-jit-workflow-unavailable")
    if kind not in {"skill", "workflow", "step", "resource"} or not isinstance(relative_path, str):
        raise TeaAdapterError("tea-jit-path-invalid")
    try:
        relative = PurePosixPath(relative_path)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError
        if kind == "skill" and relative.as_posix() != "SKILL.md":
            raise ValueError
        if kind == "workflow" and relative.as_posix() != "workflow.yaml":
            raise ValueError
        if kind == "step" and (not relative.parts or relative.parts[0] != "steps-c"):
            raise ValueError
        if kind == "resource" and (not relative.parts or relative.parts[0] != "resources"):
            raise ValueError
        workflow_root = (root / _SOURCE / candidate["root"]).resolve(strict=True)
        target = (workflow_root / Path(*relative.parts)).resolve(strict=True)
        target.relative_to(workflow_root)
        if not target.is_file() or target.is_symlink() or target.stat().st_size > _MAX_ARTIFACT_BYTES:
            raise ValueError
        content = target.read_bytes()
        text = content.decode("utf-8")
    except (OSError, UnicodeError, ValueError):
        raise TeaAdapterError("tea-jit-path-invalid") from None
    return {
        "workflowId": workflow_id,
        "kind": kind,
        "path": f"{candidate['root']}/{relative.as_posix()}",
        "content": text,
        "contentHash": hash_bytes(content),
    }
