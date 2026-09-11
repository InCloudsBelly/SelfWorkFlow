"""Verify the pinned Graft submodule without executing its source."""

from __future__ import annotations

import hashlib
import json
import argparse
from pathlib import Path
import subprocess
from typing import Any

import yaml


_LOCK = "dependencies/locks/graft.lock.yaml"
_SOURCE = "dependencies/upstream/graft"


class GraftSourceError(ValueError):
    """Stable source/lock failure without paths or command output."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _hash_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _hash(value: object) -> str:
    try:
        payload = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise GraftSourceError("graft-source-identity-invalid") from None
    return _hash_bytes(payload)


def _git(source: Path, *arguments: str, limit: int = 1024 * 1024) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments], cwd=source, capture_output=True,
            text=True, encoding="utf-8", errors="strict", check=False,
            timeout=60,
        )
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError):
        raise GraftSourceError("graft-source-identity-invalid") from None
    if result.returncode != 0 or len(result.stdout.encode("utf-8")) > limit:
        raise GraftSourceError("graft-source-identity-invalid")
    return result.stdout.strip()


def _load_lock(path: Path) -> dict[str, Any]:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise GraftSourceError("graft-lock-invalid") from None
    if (
        not isinstance(document, dict)
        or set(document) != {
            "schemaVersion", "canonicalUrl", "path", "gitlinkCommit",
            "gitTree", "package", "entry", "license",
        }
        or document.get("schemaVersion") != 1
        or document.get("canonicalUrl") != "https://github.com/trailhq/Graft.git"
        or document.get("path") != _SOURCE
        or not isinstance(document.get("gitlinkCommit"), str)
        or len(document["gitlinkCommit"]) != 40
        or any(character not in "0123456789abcdef" for character in document["gitlinkCommit"])
        or not isinstance(document.get("gitTree"), str)
        or len(document["gitTree"]) != 40
        or any(character not in "0123456789abcdef" for character in document["gitTree"])
    ):
        raise GraftSourceError("graft-lock-invalid")
    package = document["package"]
    license_document = document["license"]
    if (
        not isinstance(package, dict)
        or set(package) != {"name", "version", "node", "packageJsonHash", "packageLockHash"}
        or package.get("name") != "@nanonets/graft"
        or package.get("version") != "0.18.0"
        or package.get("node") != ">=20"
        or not isinstance(package.get("packageJsonHash"), str)
        or not isinstance(package.get("packageLockHash"), str)
        or not isinstance(document.get("entry"), str)
        or document["entry"] != "dist/cli.js"
        or not isinstance(license_document, dict)
        or set(license_document) != {"path", "spdx", "hash"}
        or license_document.get("path") != "LICENSE"
        or license_document.get("spdx") != "MIT"
        or not isinstance(license_document.get("hash"), str)
    ):
        raise GraftSourceError("graft-lock-invalid")
    return document


def verify_graft_source(repository: str | Path) -> dict[str, Any]:
    """Verify the Gitlink, clean tree, package identity, and built entrypoint."""

    root = Path(repository).resolve(strict=True)
    lock = _load_lock(root / _LOCK)
    listing = _git(root, "ls-files", "--stage", "--", _SOURCE)
    fields = listing.split()
    if len(fields) < 2 or fields[0] != "160000" or fields[1] != lock["gitlinkCommit"]:
        raise GraftSourceError("graft-gitlink-lock-mismatch")
    source = root / _SOURCE
    if source.is_symlink() or not source.is_dir():
        raise GraftSourceError("graft-source-identity-invalid")
    commit = _git(source, "rev-parse", "HEAD")
    tree = _git(source, "rev-parse", "HEAD^{tree}")
    dirty = _git(source, "status", "--porcelain=v1", "--untracked-files=all")
    if commit != lock["gitlinkCommit"] or tree != lock["gitTree"] or dirty:
        raise GraftSourceError("graft-source-drift")

    package_path = source / "package.json"
    package_lock_path = source / "package-lock.json"
    license_path = source / "LICENSE"
    entry_path = source / lock["entry"]
    if any(
        path.is_symlink() or not path.is_file()
        for path in (package_path, package_lock_path, license_path, entry_path)
    ):
        raise GraftSourceError("graft-build-missing")
    package_bytes = package_path.read_bytes()
    package_lock_bytes = package_lock_path.read_bytes()
    license_bytes = license_path.read_bytes()
    package_hash = _hash_bytes(package_bytes)
    package_lock_hash = _hash_bytes(package_lock_bytes)
    license_hash = _hash_bytes(license_bytes)
    if (
        package_hash != lock["package"]["packageJsonHash"]
        or package_lock_hash != lock["package"]["packageLockHash"]
        or license_hash != lock["license"]["hash"]
    ):
        raise GraftSourceError("graft-source-drift")
    try:
        package = json.loads(package_bytes)
    except (UnicodeError, ValueError):
        raise GraftSourceError("graft-package-invalid") from None
    package_bin = package.get("bin") if isinstance(package, dict) else None
    if (
        not isinstance(package, dict)
        or not isinstance(package_bin, dict)
        or package.get("name") != lock["package"]["name"]
        or package.get("version") != lock["package"]["version"]
        or package_bin.get("graft") != "dist/cli.js"
    ):
        raise GraftSourceError("graft-package-invalid")
    entry_hash = _hash_bytes(entry_path.read_bytes())
    source_hash = _hash({
        "commit": commit,
        "tree": tree,
        "packageJsonHash": package_hash,
        "packageLockHash": package_lock_hash,
        "licenseHash": license_hash,
        "entryHash": entry_hash,
    })
    return {
        "providerId": "graft",
        "status": "ready",
        "commit": commit,
        "tree": tree,
        "version": package["version"],
        "entryHash": entry_hash,
        "sourceHash": source_hash,
    }


def inspect_graft_source_path(source_value: str | Path) -> dict[str, Any]:
    """Return the same identity fields for a configured Graft checkout."""

    source = Path(source_value)
    if not source.is_absolute() or source.is_symlink() or not source.is_dir():
        raise GraftSourceError("graft-source-identity-invalid")
    package_path = source / "package.json"
    package_lock_path = source / "package-lock.json"
    license_path = source / "LICENSE"
    entry_path = source / "dist" / "cli.js"
    if any(
        path.is_symlink() or not path.is_file()
        for path in (package_path, package_lock_path, license_path, entry_path)
    ):
        raise GraftSourceError("graft-build-missing")
    try:
        package_bytes = package_path.read_bytes()
        package_lock_bytes = package_lock_path.read_bytes()
        license_bytes = license_path.read_bytes()
        package = json.loads(package_bytes)
    except (OSError, UnicodeError, ValueError):
        raise GraftSourceError("graft-package-invalid") from None
    if (
        not isinstance(package, dict)
        or package.get("name") != "@nanonets/graft"
        or package.get("version") != "0.18.0"
        or not isinstance(package.get("bin"), dict)
        or package["bin"].get("graft") != "dist/cli.js"
    ):
        raise GraftSourceError("graft-package-invalid")
    commit = _git(source, "rev-parse", "HEAD")
    tree = _git(source, "rev-parse", "HEAD^{tree}")
    dirty = _git(source, "status", "--porcelain=v1", "--untracked-files=all")
    package_hash = _hash_bytes(package_bytes)
    package_lock_hash = _hash_bytes(package_lock_bytes)
    license_hash = _hash_bytes(license_bytes)
    entry_hash = _hash_bytes(entry_path.read_bytes())
    source_hash = _hash({
        "commit": commit,
        "tree": tree,
        "packageJsonHash": package_hash,
        "packageLockHash": package_lock_hash,
        "licenseHash": license_hash,
        "entryHash": entry_hash,
    })
    return {
        "source": source,
        "report": {
            "version": package["version"],
            "commit": commit,
            "sourceHash": source_hash,
            "dirty": bool(dirty),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    arguments = parser.parse_args(argv)
    try:
        result = verify_graft_source(arguments.repository)
    except GraftSourceError as error:
        print(json.dumps({"status": "failed", "reason": error.reason}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
