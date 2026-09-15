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
    "ponytail-help",
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
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith("GIT_CONFIG") or key in {
            "GIT_ATTR_NOSYSTEM", "GIT_EXTERNAL_DIFF", "GIT_DIFF_OPTS",
            "GIT_SSH_COMMAND", "GIT_SSH", "GIT_ASKPASS", "GIT_EXEC_PATH",
            "GIT_PROXY_COMMAND", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
            "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CEILING_DIRECTORIES",
            "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_PREFIX",
        }:
            environment.pop(key, None)
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
        }
    )
    result = subprocess.run(
        [
            "git", "-c", "core.hooksPath=NUL", "-c", "core.fsmonitor=false",
            "-c", "core.autocrlf=true",
            "-C", str(repository), *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        env=environment,
        timeout=120,
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
            or set(item) != {"id", "path", "hash", "runtimeHash"}
            or item.get("id") != expected_id
            or item.get("path") != f"skills/{expected_id}"
            or not isinstance(item.get("hash"), str)
            or not item["hash"].startswith(_SHA256)
            or len(item["hash"]) != len(_SHA256) + 64
            or not isinstance(item.get("runtimeHash"), str)
            or not item["runtimeHash"].startswith(_SHA256)
            or len(item["runtimeHash"]) != len(_SHA256) + 64
        ):
            raise PonytailSourceError("ponytail-lock-invalid")
        ids.append(item["id"])
    if len(set(ids)) != len(ids):
        raise PonytailSourceError("ponytail-lock-invalid")
    return lock


def load_ponytail_lock(repository_root: str | Path) -> dict[str, object]:
    root = Path(repository_root).resolve(strict=True)
    lock_path = root / "dependencies/locks/ponytail.lock.yaml"
    _reject_reparse_chain(lock_path)
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
    configured_url = _git(
        root, "config", "--file", ".gitmodules",
        "--get", f"submodule.{PONYTAIL_PATH}.url",
    )
    if configured_url != PONYTAIL_URL:
        raise PonytailSourceError("ponytail-submodule-url-mismatch")
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


def _adapt_ponytail_skill(content: bytes, skill_id: str) -> bytes:
    """Apply only local scope boundaries; upstream source remains untouched."""

    try:
        text = content.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError:
        raise PonytailSourceError("ponytail-source-invalid") from None
    if skill_id == "ponytail-help":
        marker_start = "## Configure Default Mode\n"
        marker_end = "## More\n"
        if marker_start not in text or marker_end not in text:
            raise PonytailSourceError("ponytail-source-adaptation-invalid")
        start = text.index(marker_start)
        end = text.index(marker_end, start)
        local_help = (
            "## Task-scoped mode\n\n"
            "SelfWorkFlow supplies `lite`, `full`, `ultra`, or `off` for the\n"
            "current task. This local adapter does not read or write environment\n"
            "variables, host config files, plugin state, or global mode files.\n\n"
            "Full/Deep tasks may route the selected Ponytail specialist; no mode\n"
            "or skill is persisted outside the current task.\n\n"
        )
        text = text[:start] + local_help + text[end:]
        return text.encode("utf-8")
    if skill_id != "ponytail":
        return content
    old_persistence = (
        "## Persistence\n\n"
        "ACTIVE EVERY RESPONSE. No drift back to over-building. Still active if\n"
        "unsure. Off only: \"stop ponytail\" / \"normal mode\". Default: **full**.\n"
        "Switch: `/ponytail lite|full|ultra`."
    )
    new_persistence = (
        "## Scope\n\n"
        "Active only for a SelfWorkFlow-routed code task. The mode is scoped to the\n"
        "current task and is not persisted in host or global configuration. Outside\n"
        "code tasks this Skill is inactive. Default: **full**. Switch:\n"
        "`/ponytail lite|full|ultra`."
    )
    old_boundary = (
        "Ponytail governs what you build, not how you talk (pair with Caveman for\n"
        "terse prose). \"stop ponytail\" / \"normal mode\": revert. Level persists until\n"
        "changed or session end."
    )
    new_boundary = (
        "Ponytail governs code decisions, not response style. SelfWorkFlow controls\n"
        "scope, output language, Review, verification, and authorization.\n"
        "`stop ponytail` / `normal mode` ends this task-scoped enhancement."
    )
    if old_persistence not in text or old_boundary not in text:
        raise PonytailSourceError("ponytail-source-adaptation-invalid")
    text = text.replace(old_persistence, new_persistence).replace(old_boundary, new_boundary)
    old_complex = (
        "- Complex request? Ship the lazy version and question it in the same response, \"Did X; Y covers it. Need full X? Say so.\" Never stall on an answer you can default."
    )
    new_complex = (
        "- Complex request? Keep the approved SelfWorkFlow scope. Record adjacent improvements instead of implementing them; revise the plan before any out-of-scope change. Do not stall when the approved path is sufficient."
    )
    if old_complex not in text:
        raise PonytailSourceError("ponytail-source-adaptation-invalid")
    text = text.replace(old_complex, new_complex)
    return text.encode("utf-8")


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
                if path.name == "SKILL.md" and item["id"] in {"ponytail", "ponytail-help"}:
                    output.write_bytes(
                        _adapt_ponytail_skill(path.read_bytes(), item["id"])
                    )
                else:
                    shutil.copyfile(path, output)
            else:
                raise PonytailSourceError("ponytail-source-invalid")
        runtime_entry = target / "SKILL.md"
        if _hash_file(runtime_entry) != item["runtimeHash"]:
            raise PonytailSourceError("ponytail-runtime-hash-mismatch")
    license_path = upstream / str(report["license"]["path"])
    target_license = destination / "skills" / "ponytail" / "LICENSE"
    if target_license.exists() or os.path.lexists(target_license):
        raise PonytailSourceError("ponytail-runtime-target-invalid")
    target_license.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(license_path, target_license)
    if _hash_file(target_license) != report["license"]["hash"]:
        raise PonytailSourceError("ponytail-runtime-hash-mismatch")
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
