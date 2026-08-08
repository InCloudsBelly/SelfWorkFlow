"""Fresh, read-only workspace and provider project state artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from selfworkflow.v3.contracts import (
    validate_provider_project_state_receipt,
    validate_workspace_fingerprint,
)
from selfworkflow.v3.hashing import (
    HashingError,
    canonical_project_root,
    canonical_relative_path,
    clone,
    content_hash,
    hash_file_content,
    project_root_hash,
    require_hash,
)


class ProjectStateError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _utc(value: datetime | str) -> str:
    if isinstance(value, str):
        return value
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ProjectStateError("time-must-be-utc")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _file_record(root, item: Mapping[str, Any]) -> dict[str, Any]:
    try:
        path = canonical_relative_path(item["path"])
        status = item["status"]
        if status not in {"tracked", "modified", "deleted", "untracked"}:
            raise ProjectStateError("workspace-file-status-invalid")
        if "content" in item:
            raw = item["content"]
            if not isinstance(raw, (bytes, bytearray)):
                raise ProjectStateError("workspace-file-content-invalid")
            size = len(raw)
            digest = "sha256:" + __import__("hashlib").sha256(bytes(raw)).hexdigest()
        elif status == "deleted":
            size = int(item.get("size", 0))
            digest = require_hash(item["contentHash"])
        elif item.get("readFromRoot"):
            size, digest = hash_file_content(root / path)
        else:
            size = int(item["size"])
            digest = require_hash(item["contentHash"])
        if size < 0:
            raise ProjectStateError("workspace-file-size-invalid")
        record = {"path": path, "status": status, "size": size, "contentHash": digest}
        if "reparseIdentityHash" in item:
            record["reparseIdentityHash"] = require_hash(item["reparseIdentityHash"])
        return record
    except (KeyError, TypeError, ValueError, HashingError, OSError):
        raise ProjectStateError("workspace-file-invalid") from None


def build_workspace_fingerprint(
    project_root: str,
    *,
    git_head_tree_hash: str,
    git_index_hash: str,
    files: Iterable[Mapping[str, Any]],
    indexing_config_hash: str,
    ignored_generated_boundary_hash: str,
    dependency_closure_hash: str | None,
    dependency_closure_proven: bool = True,
) -> dict[str, Any]:
    """Build a content-addressed fingerprint; no git command or write is performed."""

    try:
        root = canonical_project_root(project_root)
        records = [_file_record(root, item) for item in files]
        records.sort(key=lambda item: item["path"])
        if len({item["path"] for item in records}) != len(records):
            raise ProjectStateError("workspace-file-duplicate")
        hashes = [git_head_tree_hash, git_index_hash, indexing_config_hash, ignored_generated_boundary_hash]
        for value in hashes:
            require_hash(value)
        if dependency_closure_proven:
            closure = require_hash(dependency_closure_hash)
        else:
            closure = content_hash({"dependencyClosure": "unknown"})
        body = {
            "schemaVersion": 3,
            "gitHeadTreeHash": git_head_tree_hash,
            "gitIndexHash": git_index_hash,
            "files": records,
            "indexingConfigHash": indexing_config_hash,
            "ignoredGeneratedBoundaryHash": ignored_generated_boundary_hash,
            "dependencyClosureHash": closure,
        }
        body["fingerprintHash"] = content_hash(body)
        validate_workspace_fingerprint(body)
        return clone(body)
    except ProjectStateError:
        raise
    except (HashingError, OSError, TypeError, ValueError):
        raise ProjectStateError("workspace-fingerprint-invalid") from None


def build_project_state_receipt(
    *,
    provider_id: str,
    source_identity_hash: str,
    project_root: str,
    workspace_fingerprint: Mapping[str, Any],
    index_revision: str,
    health: str,
    source_content_fresh: str,
    relationship_fresh: str,
    captured_at: datetime | str,
    valid_until: datetime | str,
    pending_files: Iterable[str] = (),
    parse_failures: Iterable[str] = (),
    state_evidence_ref: str | None = None,
) -> dict[str, Any]:
    try:
        root_hash = project_root_hash(project_root)
        validate_workspace_fingerprint(dict(workspace_fingerprint))
        require_hash(source_identity_hash)
        require_hash(workspace_fingerprint["fingerprintHash"])
        unknown_closure = content_hash({"dependencyClosure": "unknown"})
        if relationship_fresh == "fresh" and workspace_fingerprint.get("dependencyClosureHash") == unknown_closure:
            raise ProjectStateError("relationship-freshness-unproven")
        if relationship_fresh not in {"fresh", "stale", "unknown"}:
            raise ProjectStateError("relationship-freshness-invalid")
        body: dict[str, Any] = {
            "schemaVersion": 3,
            "providerId": provider_id,
            "sourceIdentityHash": source_identity_hash,
            "canonicalProjectRootHash": root_hash,
            "workspaceFingerprintHash": workspace_fingerprint["fingerprintHash"],
            "indexRevision": index_revision,
            "health": health,
            "sourceContentFresh": source_content_fresh,
            "relationshipFresh": relationship_fresh,
            "capturedAt": _utc(captured_at),
            "validUntil": _utc(valid_until),
            "pendingFiles": sorted({canonical_relative_path(item) for item in pending_files}),
            "parseFailures": sorted(set(parse_failures)),
        }
        if state_evidence_ref is not None:
            body["stateEvidenceRef"] = state_evidence_ref
        body["receiptHash"] = content_hash(body)
        validate_provider_project_state_receipt(body)
        return clone(body)
    except ProjectStateError:
        raise
    except (HashingError, KeyError, TypeError, ValueError):
        raise ProjectStateError("project-state-receipt-invalid") from None


@dataclass(frozen=True)
class WorkspaceObservation:
    identity_hash: str
    fingerprint: dict[str, Any]
    changed_paths: tuple[str, ...] = ()

    @property
    def fingerprint_hash(self) -> str:
        return self.fingerprint["fingerprintHash"]
