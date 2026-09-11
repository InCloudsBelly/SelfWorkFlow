"""Fail-closed verification and selective packaging of the Ponytail source."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess

import yaml


PONYTAIL_PATH = "dependencies/upstream/ponytail"
PONYTAIL_URL = "https://github.com/DietrichGebert/ponytail.git"
PONYTAIL_SKILLS = (
    "ponytail",
    "ponytail-review",
    "ponytail-audit",
)
_SHA256 = "sha256:"
_REPARSE_POINT = 0x400


class PonytailSourceError(RuntimeError):
    """Raised when the locked Ponytail source cannot be trusted."""


def _is_reparse(path: Path) -> bool:
    metadata = path.lstat()
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _reject_reparse_chain(path: Path) -> None:
    current = path
    while True:
        if os.path.lexists(current) and _is_reparse(current):
            raise PonytailSourceError("ponytail-source-reparse")
        if current.parent == current:
            return
        current = current.parent


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    if result.returncode != 0:
        raise PonytailSourceError("ponytail-source-invalid")
    return result.stdout.strip()


def _hash_bytes(content: bytes) -> str:
    return _SHA256 + hashlib.sha256(content).hexdigest()


def _hash_file(path: Path) -> str:
    try:
        return _hash_bytes(path.read_bytes())
    except (OSError, UnicodeError):
        raise PonytailSourceError("ponytail-source-invalid") from None


def _relative_file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise PonytailSourceError("ponytail-lock-invalid")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise PonytailSourceError("ponytail-lock-invalid")
    candidate = root.joinpath(*pure.parts)
    _reject_reparse_chain(candidate)
    if not candidate.is_file() or _is_reparse(candidate):
        raise PonytailSourceError("ponytail-source-invalid")
    return candidate


def validate_ponytail_lock(lock: object) -> dict[str, object]:
    if not isinstance(lock, dict):
        raise PonytailSourceError("ponytail-lock-invalid")
    allowed = {
        "schemaVersion", "sourceId", "canonicalUrl", "path", "gitlinkCommit",
        "gitTree", "upstreamVersion", "license", "selectedSkills",
    }
    if set(lock) - allowed or set(lock) - {"upstreamVersion"} < (allowed - {"upstreamVersion"}):
        raise PonytailSourceError("ponytail-lock-invalid")
    if (
        lock.get("schemaVersion") != 1
        or lock.get("sourceId") != "ponytail"
        or lock.get("canonicalUrl") != PONYTAIL_URL
        or lock.get("path") != PONYTAIL_PATH
        or not isinstance(lock.get("gitlinkCommit"), str)
        or len(lock["gitlinkCommit"]) != 40
        or any(character not in "0123456789abcdef" for character in lock["gitlinkCommit"])
        or not isinstance(lock.get("gitTree"), str)
        or len(lock["gitTree"]) != 40
        or any(character not in "0123456789abcdef" for character in lock["gitTree"])
        or ("upstreamVersion" in lock and not isinstance(lock["upstreamVersion"], str))
    ):
        raise PonytailSourceError("ponytail-lock-invalid")
    license_value = lock.get("license")
    if (
        not isinstance(license_value, dict)
        or set(license_value) != {"path", "spdx", "hash"}
        or license_value.get("path") != "LICENSE"
        or license_value.get("spdx") != "MIT"
        or not isinstance(license_value.get("hash"), str)
        or not license_value["hash"].startswith(_SHA256)
        or len(license_value["hash"]) != len(_SHA256) + 64
    ):
        raise PonytailSourceError("ponytail-lock-invalid")
    selected = lock.get("selectedSkills")
    if not isinstance(selected, list) or len(selected) != len(PONYTAIL_SKILLS):
        raise PonytailSourceError("ponytail-lock-invalid")
    ids: list[str] = []
    for item, expected_id in zip(selected, PONYTAIL_SKILLS, strict=True):
        if (
            not isinstance(item, dict)
            or set(item) != {"id", "path", "hash"}
            or item.get("id") != expected_id
            or item.get("path") != f"skills/{expected_id}"
            or not isinstance(item.get("hash"), str)
            or not item["hash"].startswith(_SHA256)
            or len(item["hash"]) != len(_SHA256) + 64
        ):
            raise PonytailSourceError("ponytail-lock-invalid")
        ids.append(item["id"])
    if len(set(ids)) != len(ids):
        raise PonytailSourceError("ponytail-lock-invalid")
    return lock


def load_ponytail_lock(repository_root: str | Path) -> dict[str, object]:
    root = Path(repository_root).resolve(strict=True)
    lock_path = root / "dependencies/locks/ponytail.lock.yaml"
    if not lock_path.is_file() or _is_reparse(lock_path):
        raise PonytailSourceError("ponytail-lock-missing")
    try:
        lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise PonytailSourceError("ponytail-lock-invalid") from None
    return validate_ponytail_lock(lock)


def verify_ponytail_source(repository_root: str | Path) -> dict[str, object]:
    root = Path(repository_root).resolve(strict=True)
    lock = load_ponytail_lock(root)
    gitlink = _git(root, "ls-files", "--stage", "--", PONYTAIL_PATH).split()
    if len(gitlink) < 2 or gitlink[0] != "160000" or gitlink[1] != lock["gitlinkCommit"]:
        raise PonytailSourceError("ponytail-gitlink-mismatch")
    upstream = root / PONYTAIL_PATH
    if not upstream.is_dir() or _is_reparse(upstream):
        raise PonytailSourceError("ponytail-source-invalid")
    _reject_reparse_chain(upstream)
    try:
        commit = _git(root, "-C", PONYTAIL_PATH, "rev-parse", "HEAD")
        tree = _git(root, "-C", PONYTAIL_PATH, "rev-parse", "HEAD^{tree}")
        dirty = _git(root, "-C", PONYTAIL_PATH, "status", "--porcelain=v1", "--untracked-files=all")
    except PonytailSourceError:
        raise
    if commit != lock["gitlinkCommit"] or tree != lock["gitTree"] or dirty:
        raise PonytailSourceError("ponytail-source-drift")
    license_path = _relative_file(upstream, lock["license"]["path"])
    if _hash_file(license_path) != lock["license"]["hash"]:
        raise PonytailSourceError("ponytail-source-drift")
    for item in lock["selectedSkills"]:
        skill_root = upstream / item["path"]
        _reject_reparse_chain(skill_root)
        if not skill_root.is_dir() or _is_reparse(skill_root):
            raise PonytailSourceError("ponytail-source-invalid")
        entry = _relative_file(skill_root, "SKILL.md")
        if _hash_file(entry) != item["hash"]:
            raise PonytailSourceError("ponytail-source-drift")
        for path in skill_root.rglob("*"):
            if _is_reparse(path):
                raise PonytailSourceError("ponytail-source-reparse")
    lock_hash = _hash_file(root / "dependencies/locks/ponytail.lock.yaml")
    return {
        "sourceId": lock["sourceId"],
        "canonicalUrl": lock["canonicalUrl"],
        "path": lock["path"],
        "gitlinkCommit": commit,
        "gitTree": tree,
        "upstreamVersion": lock.get("upstreamVersion"),
        "license": lock["license"],
        "selectedSkills": lock["selectedSkills"],
        "lockHash": lock_hash,
    }


def copy_ponytail_skills(
    repository_root: str | Path, destination_root: str | Path
) -> dict[str, object]:
    root = Path(repository_root).resolve(strict=True)
    destination = Path(destination_root)
    report = verify_ponytail_source(root)
    upstream = root / PONYTAIL_PATH
    for item in report["selectedSkills"]:
        source = upstream / item["path"]
        target = destination / "skills" / item["id"]
        if target.exists() or os.path.lexists(target):
            raise PonytailSourceError("ponytail-runtime-target-invalid")
        target.mkdir(parents=True, exist_ok=True)
        for path in sorted(source.rglob("*")):
            if _is_reparse(path):
                raise PonytailSourceError("ponytail-source-reparse")
            relative = path.relative_to(source)
            output = target / relative
            if path.is_dir():
                output.mkdir(parents=True, exist_ok=True)
            elif path.is_file():
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, output)
            else:
                raise PonytailSourceError("ponytail-source-invalid")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    arguments = parser.parse_args(argv)
    try:
        report = verify_ponytail_source(arguments.repository)
    except PonytailSourceError as error:
        print(json.dumps({"status": "failed", "reason": str(error)}, sort_keys=True))
        return 1
    print(json.dumps({"status": "ready", "report": report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
