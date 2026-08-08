"""Governed, deterministic absorption of selected external Skill sources."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile


_SOURCE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_PRINCIPLE_ID = _SOURCE_ID
_SENSITIVE_PATTERNS = (
    re.compile(r"[A-Za-z]:\\"),
    re.compile(r"(?i)(?:^|[/\\])\.env(?:$|[/\\])"),
    re.compile(r"(?i)private[ -]?key"),
    re.compile(r"(?i)(?:oauth|access|refresh)[ _-]?token"),
    re.compile(r"(?i)(?:aws|cloud)[ _-]?(?:secret|credential)"),
)
_REQUIRED_EVIDENCE = (
    "failureBaseline",
    "positiveTrigger",
    "negativeTrigger",
    "conflict",
    "independentReview",
)


class ImportGovernanceError(RuntimeError):
    """Raised when an import cannot satisfy the governance boundary."""


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ImportGovernanceError("git-source-invalid")
    return result.stdout


def _selected_path(root: Path, relative: str) -> Path:
    if not relative or "\\" in relative:
        raise ImportGovernanceError("source-path-invalid")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ImportGovernanceError("source-path-invalid")
    path = (root / Path(*pure.parts)).resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError:
        raise ImportGovernanceError("source-path-invalid") from None
    if not path.is_file() or path.is_symlink():
        raise ImportGovernanceError("source-path-invalid")
    return path


def inspect_git_source(
    repository_root: str | Path,
    source_id: str,
    selected_paths: list[str] | tuple[str, ...],
) -> dict[str, object]:
    """Return provenance for only the explicitly selected tracked files."""

    if not _SOURCE_ID.fullmatch(source_id) or not selected_paths:
        raise ImportGovernanceError("source-input-invalid")
    root = Path(repository_root).resolve(strict=True)
    if Path(_git(root, "rev-parse", "--show-toplevel").strip()).resolve() != root:
        raise ImportGovernanceError("git-root-mismatch")
    revision = _git(root, "rev-parse", "HEAD").strip()
    repository_dirty = bool(_git(root, "status", "--porcelain=v1"))
    selected: list[dict[str, object]] = []
    seen: set[str] = set()
    selected_files_dirty = False
    for relative in selected_paths:
        if relative in seen:
            raise ImportGovernanceError("duplicate-source-path")
        seen.add(relative)
        path = _selected_path(root, relative)
        if not _git(root, "ls-files", "--error-unmatch", "--", relative).strip():
            raise ImportGovernanceError("source-not-tracked")
        dirty = bool(_git(root, "status", "--porcelain=v1", "--", relative))
        selected_files_dirty = selected_files_dirty or dirty
        selected.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "dirty": dirty,
            }
        )
    return {
        "sourceId": source_id,
        "revision": revision,
        "repositoryDirty": repository_dirty,
        "selectedFilesDirty": selected_files_dirty,
        "selectedFiles": selected,
    }


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_subject(snapshot: dict[str, object]) -> dict[str, object]:
    return {
        "sourceId": snapshot.get("sourceId"),
        "revision": snapshot.get("revision"),
        "repositoryDirty": snapshot.get("repositoryDirty"),
        "selectedFilesDirty": snapshot.get("selectedFilesDirty"),
        "selectedFiles": snapshot.get("selectedFiles"),
    }


def build_extraction_candidate(
    snapshot: dict[str, object],
    principles: list[dict[str, str]],
    *,
    quarantine_terms: list[str] | tuple[str, ...] = (),
) -> dict[str, object]:
    """Build a non-publishable candidate while retaining no quarantined plaintext."""

    source_hash = _canonical_hash(_snapshot_subject(snapshot))
    accepted: list[dict[str, str]] = []
    quarantined: list[dict[str, str]] = []
    normalized_terms = tuple(term.casefold() for term in quarantine_terms if term)
    for principle in principles:
        stable_id = principle.get("stableId")
        content = principle.get("content")
        if (
            not isinstance(stable_id, str)
            or not _PRINCIPLE_ID.fullmatch(stable_id)
            or not isinstance(content, str)
            or not content.strip()
            or len(content.encode("utf-8")) > 64 * 1024
        ):
            raise ImportGovernanceError("principle-invalid")
        reasons = [
            "sensitive-or-local-pattern"
            for pattern in _SENSITIVE_PATTERNS
            if pattern.search(content)
        ]
        if any(term in content.casefold() for term in normalized_terms):
            reasons.append("project-specific-term")
        if reasons:
            quarantined.append(
                {
                    "stableId": stable_id,
                    "contentHash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "reason": sorted(set(reasons))[0],
                }
            )
        else:
            accepted.append({"stableId": stable_id, "content": content.strip()})
    return {
        "schemaVersion": 1,
        "sourceEvidenceHash": source_hash,
        "acceptedPrinciples": accepted,
        "quarantined": quarantined,
        "evidence": {},
        "publicationStatus": "candidate",
    }


def validate_candidate(
    candidate: dict[str, object], current_snapshot: dict[str, object]
) -> tuple[str, ...]:
    """Return deterministic governance violations for an extraction candidate."""

    errors: set[str] = set()
    if candidate.get("publicationStatus") != "candidate":
        errors.add("candidate-status-invalid")
    if candidate.get("sourceEvidenceHash") != _canonical_hash(
        _snapshot_subject(current_snapshot)
    ):
        errors.add("source-evidence-stale")
    principles = candidate.get("acceptedPrinciples")
    if not isinstance(principles, list) or not principles:
        errors.add("principles-missing")
    else:
        stable_ids = [
            item.get("stableId") for item in principles if isinstance(item, dict)
        ]
        if len(stable_ids) != len(principles) or len(stable_ids) != len(set(stable_ids)):
            errors.add("duplicate-principle")
    evidence = candidate.get("evidence")
    if not isinstance(evidence, dict) or any(
        evidence.get(key) != "passed" for key in _REQUIRED_EVIDENCE
    ):
        errors.add("evidence-incomplete")
    return tuple(sorted(errors))


def publish_candidate(
    candidate: dict[str, object],
    current_snapshot: dict[str, object],
    output_path: str | Path,
    *,
    confirmed_by_user: bool,
) -> dict[str, object]:
    """Publish only a confirmed, current, reviewed candidate."""

    if confirmed_by_user is not True:
        raise ImportGovernanceError("confirmation-required")
    errors = validate_candidate(candidate, current_snapshot)
    if errors:
        raise ImportGovernanceError(",".join(errors))
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    content = "\n\n".join(
        item["content"] for item in candidate["acceptedPrinciples"]
    ) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, output)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return {
        "publicationStatus": "published",
        "sourceEvidenceHash": candidate["sourceEvidenceHash"],
        "outputHash": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
