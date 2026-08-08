"""Read-only, blob-bound Git repository policy inspection."""

from __future__ import annotations

from datetime import date
import re
from pathlib import Path, PurePosixPath
import subprocess
from typing import Mapping

from selfworkflow.config import load_config


class GitPolicyError(ValueError):
    pass


_SECRET_PATTERNS = (
    re.compile(br"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(br"AKIA[0-9A-Z]{16}"),
    re.compile(br"sk-[A-Za-z0-9_-]{20,}"),
)


def load_git_policy(value: str | Path | Mapping[str, object]) -> dict[str, object]:
    if isinstance(value, Mapping):
        result = {key: item[:] if isinstance(item, list) else dict(item) if isinstance(item, Mapping) else item for key, item in value.items()}
        if result["sizeBytes"]["warning"] >= result["sizeBytes"]["failure"]:
            raise GitPolicyError("git-policy-invalid")
        return result
    root = Path(__file__).resolve().parents[2]
    document = load_config(value, root / "schemas/git-policy.schema.json")
    result = _thaw(document)
    if result["sizeBytes"]["warning"] >= result["sizeBytes"]["failure"]:
        raise GitPolicyError("git-policy-invalid")
    return result


def _thaw(value):
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _run(root: Path, *args: str, text: bool = False):
    result = subprocess.run(["git", *args], cwd=root, check=False, capture_output=True, text=text)
    if result.returncode != 0:
        raise GitPolicyError("git-inspection-failed")
    return result.stdout


def _records(root: Path) -> list[tuple[str, str, str, str]]:
    records: list[tuple[str, str, str, str]] = []
    if _run(root, "rev-parse", "--verify", "HEAD", text=True).strip():
        for item in _run(root, "ls-tree", "-r", "-z", "--full-tree", "HEAD").split(b"\0"):
            if not item:
                continue
            metadata, raw_path = item.split(b"\t", 1)
            mode, _, object_hash = metadata.decode().split(" ")
            records.append(("head", raw_path.decode("utf-8"), mode, object_hash))
    index: dict[str, tuple[str, str]] = {}
    for item in _run(root, "ls-files", "-s", "-z").split(b"\0"):
        if not item:
            continue
        metadata, raw_path = item.split(b"\t", 1)
        mode, object_hash, stage = metadata.decode().split(" ")
        if stage == "0":
            path = raw_path.decode("utf-8")
            index[path] = (mode, object_hash)
            records.append(("index", path, mode, object_hash))
    for raw_path in _run(root, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR").split(b"\0"):
        if raw_path:
            path = raw_path.decode("utf-8")
            if path in index:
                records.append(("staged", path, *index[path]))
    return records


def _allowed(policy: Mapping[str, object], path: str, object_hash: str) -> bool:
    today = date.today().isoformat()
    return any(
        item["path"] == path and item["objectHash"] == object_hash
        and item["reason"].strip() and item["owner"].strip() and item["expires"] >= today
        for item in policy["allowlist"]
    )


def check_repository(repository: str | Path, policy_source: str | Path | Mapping[str, object]) -> dict[str, object]:
    root = Path(repository).resolve(strict=True)
    policy = load_git_policy(policy_source)
    findings: dict[tuple[str, str, str], dict[str, object]] = {}
    warning_limit, failure_limit = policy["sizeBytes"]["warning"], policy["sizeBytes"]["failure"]
    allowed_names = {name.casefold() for name in policy["allowedSensitiveNames"]}
    forbidden_roots = {name.casefold() for name in policy["forbiddenRoots"]}
    database_suffixes = tuple(suffix.casefold() for suffix in policy["databaseSuffixes"])

    def add(scope, path, object_hash, code, severity):
        if _allowed(policy, path, object_hash):
            return
        key = (path.casefold(), code, object_hash)
        current = findings.get(key)
        priority = {"head": 0, "index": 1, "staged": 2}
        if current is None or priority[scope] > priority[current["scope"]]:
            findings[key] = {"scope": scope, "path": path, "objectHash": object_hash, "code": code, "severity": severity}

    for scope, path, mode, object_hash in _records(root):
        normalized = PurePosixPath(path.replace("\\", "/")).as_posix()
        folded, name = normalized.casefold(), PurePosixPath(normalized).name.casefold()
        first = PurePosixPath(normalized).parts[0].casefold() if PurePosixPath(normalized).parts else ""
        if mode == "120000":
            add(scope, normalized, object_hash, "symlink", "failure")
            continue
        if mode == "160000":
            add(scope, normalized, object_hash, "submodule", "failure")
            continue
        if first in forbidden_roots or "__pycache__" in (part.casefold() for part in PurePosixPath(normalized).parts):
            add(scope, normalized, object_hash, "runtime-root", "failure")
        if name not in allowed_names and (name == ".env" or name.startswith(".env.") or name in {"oauth-token.json", "credentials.json", "cookies.json", "id_rsa", "id_ed25519"} or name.endswith((".pem", ".key"))):
            add(scope, normalized, object_hash, "sensitive-path", "failure")
        if folded.endswith(database_suffixes):
            add(scope, normalized, object_hash, "database-file", "failure")
        size = int(_run(root, "cat-file", "-s", object_hash, text=True).strip())
        if size > failure_limit:
            add(scope, normalized, object_hash, "large-file-failure", "failure")
            continue
        if size > warning_limit:
            add(scope, normalized, object_hash, "large-file-warning", "warning")
        content = _run(root, "cat-file", "blob", object_hash)
        if b"\0" in content:
            add(scope, normalized, object_hash, "binary-file", "warning")
        if any(pattern.search(content) for pattern in _SECRET_PATTERNS):
            add(scope, normalized, object_hash, "known-secret-pattern", "failure")
    ordered = sorted(findings.values(), key=lambda item: (item["path"].casefold(), item["code"], item["objectHash"]))
    status = "failed" if any(item["severity"] == "failure" for item in ordered) else "warning" if ordered else "passed"
    return {"schemaVersion": 1, "status": status, "secretHeuristic": "known-patterns-only", "findings": ordered}
