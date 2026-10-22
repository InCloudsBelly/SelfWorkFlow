"""Build the pinned personal CodeGraph fork without touching any project index."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
from typing import Callable, Sequence

import yaml

from selfworkflow.v3.submodule_profiles import _native


SOURCE_PATH = "extensions/codegraph/codegraph_ue"
SOURCE_URL = "https://github.com/InCloudsBelly/codegraph_ue.git"
LOCK_PATH = "dependencies/locks/codegraph-ue.lock.yaml"
RECEIPT_PATH = "extensions/codegraph/.build/codegraph-ue.json"
_NODE_PROBE = """
if (Number(process.versions.node.split('.')[0]) === 25) process.exit(25);
const { DatabaseSync } = require('node:sqlite');
const db = new DatabaseSync(':memory:');
try {
  if (db.prepare('SELECT 1 AS healthy').get().healthy !== 1) throw new Error('sqlite');
} finally { db.close(); }
process.stdout.write(JSON.stringify({ version: process.versions.node, sqlite: true }));
"""


def _hash(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _reject_links(path: Path, root: Path) -> None:
    for candidate in (path, *path.parents):
        if candidate.exists() or candidate.is_symlink():
            metadata = candidate.lstat()
            if candidate.is_symlink() or getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError("codegraph-ue-path-invalid")
        if candidate == root:
            break


def _git(root: Path, *arguments: str) -> str:
    result = _native(("git", *arguments), root)
    if result.returncode:
        raise ValueError("codegraph-ue-git-failed")
    return result.stdout.strip()


def _node_runtime_probe(node: Path) -> dict[str, object]:
    try:
        result = subprocess.run([str(node), "-e", _NODE_PROBE], check=False, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=15)
        value = json.loads(result.stdout) if result.returncode == 0 else None
        if (
            not isinstance(value, dict) or set(value) != {"version", "sqlite"}
            or value["sqlite"] is not True or not isinstance(value["version"], str)
            or re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][a-zA-Z0-9.-]+)?", value["version"]) is None
            or int(value["version"].split(".")[0]) < 22
            or value["version"].split(".")[0] == "25"
        ):
            raise ValueError
    except (OSError, ValueError, subprocess.SubprocessError):
        raise ValueError("codegraph-ue-node-runtime-unsupported") from None
    return value


def _pin(repository: Path) -> dict[str, object]:
    lock_path = repository / LOCK_PATH
    _reject_links(lock_path, repository)
    _reject_links(repository / ".gitmodules", repository)
    if lock_path.is_symlink() or not lock_path.is_file():
        raise ValueError("codegraph-ue-lock-missing")
    try:
        lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
        package = lock["package"]
        valid = (
            lock["schemaVersion"] == 1 and lock["sourceId"] == "codegraph-ue"
            and lock["canonicalUrl"] == SOURCE_URL and lock["path"] == SOURCE_PATH
            and re.fullmatch(r"[0-9a-f]{40}", lock["gitlinkCommit"]) is not None
            and re.fullmatch(r"[0-9a-f]{40}", lock["sourceTree"]) is not None
            and package["name"] == "@colbymchenry/codegraph"
            and isinstance(package["version"], str) and bool(package["version"])
            and all(re.fullmatch(r"sha256:[0-9a-f]{64}", package[key]) is not None
                    for key in ("packageJsonHash", "packageLockHash"))
        )
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        raise ValueError("codegraph-ue-lock-invalid") from None
    if not valid:
        raise ValueError("codegraph-ue-lock-invalid")
    listing = _git(repository, "ls-files", "--stage", "--", SOURCE_PATH).split()
    if listing != ["160000", lock["gitlinkCommit"], "0", SOURCE_PATH]:
        raise ValueError("codegraph-ue-gitlink-mismatch")
    url = _git(repository, "config", "--file", ".gitmodules", "--get", f"submodule.{SOURCE_PATH}.url")
    if url != SOURCE_URL:
        raise ValueError("codegraph-ue-url-mismatch")
    paths = _git(repository, "config", "--file", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$").splitlines()
    matching = [line.split(maxsplit=1)[0] for line in paths if line.split(maxsplit=1)[-1] == SOURCE_PATH]
    if matching != [f"submodule.{SOURCE_PATH}.path"]:
        raise ValueError("codegraph-ue-submodule-path-invalid")
    return lock


def verify_codegraph_ue_checkout(repository: str | Path) -> dict[str, object]:
    root = Path(repository).resolve(strict=True)
    lock = _pin(root)
    source = root / SOURCE_PATH
    _reject_links(source, root)
    if not (source / ".git").exists():
        raise ValueError("codegraph-ue-submodule-missing")
    if Path(_git(source, "rev-parse", "--show-toplevel")).resolve() != source:
        raise ValueError("codegraph-ue-source-invalid")
    if _git(source, "rev-parse", "HEAD") != lock["gitlinkCommit"] or _git(source, "rev-parse", "HEAD^{tree}") != lock["sourceTree"]:
        raise ValueError("codegraph-ue-source-mismatch")
    if _git(source, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("codegraph-ue-source-dirty")
    if _git(source, "remote", "get-url", "origin") != SOURCE_URL:
        raise ValueError("codegraph-ue-url-mismatch")
    package = lock["package"]
    for name, key in (("package.json", "packageJsonHash"), ("package-lock.json", "packageLockHash")):
        path = source / name
        if path.is_symlink() or not path.is_file() or _hash(path.read_bytes()) != package[key]:
            raise ValueError("codegraph-ue-package-mismatch")
    value = json.loads((source / "package.json").read_text(encoding="utf-8"))
    if value.get("name") != package["name"] or value.get("version") != package["version"]:
        raise ValueError("codegraph-ue-package-mismatch")
    return lock


def verify_codegraph_ue_build(source: Path, runtime: dict[str, object]) -> dict[str, object]:
    root = source.parents[2]
    lock = verify_codegraph_ue_checkout(root)
    receipt_path = root / RECEIPT_PATH
    _reject_links(receipt_path, root)
    try:
        if receipt_path.is_symlink():
            raise ValueError
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (
            receipt["schemaVersion"] != 1
            or receipt["status"] != "built-and-verified"
            or receipt["backend"] != "codegraph-ue"
            or receipt["canonicalUrl"] != SOURCE_URL
            or receipt["sourcePath"] != str(source)
            or receipt["version"] != lock["package"]["version"]
            or receipt["commands"] != [["npm", "ci"], ["npm", "run", "build"]]
            or not isinstance(receipt["nodeRuntime"], dict)
            or receipt["nodeRuntime"].get("sqlite") is not True
            or receipt["commit"] != lock["gitlinkCommit"]
            or receipt["tree"] != lock["sourceTree"]
            or receipt["lockHash"] != _hash((root / LOCK_PATH).read_bytes())
            or receipt["runtimeHash"] != _hash(_json_bytes(runtime))
            or ("nodePath" in receipt and receipt["nodePath"] != runtime["nodePath"])
        ):
            raise ValueError
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        raise ValueError("codegraph-ue-build-unverified") from None
    return receipt


def codegraph_ue_node(source: Path) -> Path | None:
    """Read the pinned executable; the caller must verify its runtime hash."""
    root = source.parents[2]
    receipt_path = root / RECEIPT_PATH
    _reject_links(receipt_path, root)
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if "nodePath" not in receipt:
            return None  # Legacy receipts are upgraded only after full verification.
        value = receipt["nodePath"]
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError
        node = Path(value)
        _reject_links(node, Path(node.anchor))
        if not node.is_file():
            raise ValueError
        return node
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        raise ValueError("codegraph-ue-build-unverified") from None


def _npm(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(command), cwd=cwd, check=False, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=1800)


def codegraph_ue_runtime_trees(source: Path) -> tuple[Path, ...]:
    # npm links the committed ui workspace from node_modules.
    return (source / "dist", source / "node_modules", source / "ui")


def prepare_codegraph_ue(
    repository: str | Path, *,
    npm_runner: Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]] = _npm,
) -> dict[str, object]:
    root = Path(repository).resolve(strict=True)
    _pin(root)
    source = root / SOURCE_PATH
    _reject_links(source, root)
    if not (source / ".git").exists():
        _git(root, "-c", "protocol.file.allow=never", "-c", f"submodule.{SOURCE_PATH}.url={SOURCE_URL}", "submodule", "update", "--init", "--", SOURCE_PATH)
    lock = verify_codegraph_ue_checkout(root)
    lock_hash = _hash((root / LOCK_PATH).read_bytes())
    receipt_path = root / RECEIPT_PATH
    _reject_links(receipt_path, root)
    try:
        pinned_node = codegraph_ue_node(source) if receipt_path.exists() else None
    except ValueError:
        raise ValueError("codegraph-ue-build-identity-drift") from None
    node_value = pinned_node or shutil.which("node.exe") or shutil.which("node")
    npm_value = shutil.which("npm.cmd") if os.name == "nt" else shutil.which("npm")
    if not node_value or not npm_value:
        raise ValueError("codegraph-ue-node-npm-required")
    node = Path(node_value).resolve(strict=True)
    node_runtime = None if receipt_path.exists() else _node_runtime_probe(node)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    gate = receipt_path.with_suffix(".lock")
    try:
        descriptor = os.open(gate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError("codegraph-ue-build-busy") from None
    os.close(descriptor)
    receipt: dict[str, object] = {"status": "building", "commit": lock["gitlinkCommit"]}
    started_build = False
    try:
        from selfworkflow.cli import _codegraph_runtime_material

        if receipt_path.exists():
            try:
                runtime = _codegraph_runtime_material(source, node, codegraph_ue_runtime_trees(source))
                runtime["commandPrefix"] = (str(node), str(source / "dist/bin/codegraph.js"))
                verified = verify_codegraph_ue_build(source, runtime)
                node_runtime = _node_runtime_probe(node)
                if verified["nodeRuntime"] != node_runtime:
                    raise ValueError
            except (OSError, ValueError):
                raise ValueError("codegraph-ue-build-identity-drift") from None
            if "nodePath" not in verified:
                verified = dict(verified, nodePath=str(node))
                receipt_path.write_bytes(_json_bytes(verified) + b"\n")
            return dict(verified, reused=True)
        started_build = True
        receipt_path.write_bytes(_json_bytes(receipt) + b"\n")
        for arguments in (["ci"], ["run", "build"]):
            result = npm_runner([npm_value, *arguments], source)
            if result.returncode:
                raise ValueError("codegraph-ue-build-failed")
        if verify_codegraph_ue_checkout(root) != lock or _hash((root / LOCK_PATH).read_bytes()) != lock_hash:
            raise ValueError("codegraph-ue-source-drift")
        if not (source / "dist/bin/codegraph.js").is_file():
            raise ValueError("codegraph-ue-entry-missing")
        runtime = _codegraph_runtime_material(source, node, codegraph_ue_runtime_trees(source))
        runtime["commandPrefix"] = (str(node), str(source / "dist/bin/codegraph.js"))
        receipt = {
            "schemaVersion": 1, "status": "built-and-verified", "backend": "codegraph-ue",
            "sourcePath": str(source), "canonicalUrl": SOURCE_URL,
            "commit": lock["gitlinkCommit"], "tree": lock["sourceTree"],
            "version": lock["package"]["version"], "lockHash": lock_hash,
            "runtimeHash": _hash(_json_bytes(runtime)),
            "nodeRuntime": node_runtime,
            "nodePath": str(node),
            "commands": [["npm", "ci"], ["npm", "run", "build"]],
        }
        receipt_path.write_bytes(_json_bytes(receipt) + b"\n")
        return receipt
    except Exception:
        if started_build:
            receipt_path.write_bytes(_json_bytes({"status": "failed", "commit": lock["gitlinkCommit"]}) + b"\n")
        raise
    finally:
        gate.unlink()
