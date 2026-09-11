"""Project-local lifecycle records for design, test, plan, review, and knowledge handoff.

This module is deliberately independent from the V3 pipeline and ledger.  It stores
bounded, manager-owned records below ``<project>/selfworkflow`` and exposes only the
transition/reconcile boundary used by the workflow adapters.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unicodedata
from typing import Any, Iterator

import yaml


WDLC_LIMITS_V1 = {
    "maxIdUtf8Bytes": 1024,
    "maxRelativePathChars": 1024,
    "maxPathSegmentChars": 255,
    "maxArtifacts": 16,
    "maxFindings": 512,
    "maxReviewReceipts": 512,
    "maxPublicationReceipts": 512,
    "maxOperationRecords": 2048,
    "maxMetadataBytes": 16 * 1024 * 1024,
    "maxAttentionItems": 64,
    "maxAttentionBytes": 64 * 1024,
    "maxDocumentBytes": 256 * 1024,
    "maxPackageBytes": 768 * 1024,
    "maxRequestBytes": 1024 * 1024,
    "maxSummaryBytes": 64 * 1024,
}

_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_RESERVED_NAMES = {
    "con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_INVALID_PATH_CHARS = set('<>:"/\\|?*')
_SENSITIVE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\b(?:oauth[_-]?token|client[_-]?secret|private[_-]?key)\s*[:=]"),
    re.compile(r"(?i)\b(?:access[_-]?token|refresh[_-]?token)\s*[:=]"),
)
_CRITICAL = {"critical", "blocker"}
_IMPORTANT = {"important", "high", "medium"}
_MINOR = {"minor", "low", "info"}
_FINDING_STATUSES = {"open", "resolved", "accepted", "false-positive", "deferred"}


def lifecycle_hook_required(strength: str, formal_work_document_count: int) -> bool:
    """Return the frozen routing rule without initializing local storage."""
    if strength not in {"Light", "Full", "Deep"} or not isinstance(formal_work_document_count, int):
        raise WorkArtifactError("classification-invalid")
    return strength in {"Full", "Deep"} or formal_work_document_count >= 2


class WorkArtifactError(ValueError):
    """Stable, bounded error returned by both the Python and CLI interfaces."""

    def __init__(self, reason: str, *, details: dict[str, Any] | None = None):
        self.reason = reason
        self.details = details or {}
        super().__init__(reason)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise WorkArtifactError("canonical-value-invalid") from None


def _hash_value(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_hash(value: object, code: str = "hash-invalid") -> str:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise WorkArtifactError(code)
    return value


def _bounded_id(value: object, code: str = "id-invalid") -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > WDLC_LIMITS_V1["maxIdUtf8Bytes"]:
        raise WorkArtifactError(code)
    normalized = unicodedata.normalize("NFC", value)
    if not normalized or any(ord(c) < 32 or ord(c) == 127 for c in normalized):
        raise WorkArtifactError(code)
    return normalized


def _physical_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > WDLC_LIMITS_V1["maxRelativePathChars"]:
        raise WorkArtifactError("path-invalid")
    if value.startswith(("/", "\\")) or ":" in value[:3]:
        raise WorkArtifactError("path-invalid")
    parts = value.replace("\\", "/").split("/")
    if any(
        not part or part in {".", ".."}
        or len(part) > WDLC_LIMITS_V1["maxPathSegmentChars"]
        or part.endswith((".", " "))
        or part.casefold().split(".", 1)[0] in _RESERVED_NAMES
        or any(ord(c) < 32 or ord(c) == 127 or c in _INVALID_PATH_CHARS for c in part)
        for part in parts
    ):
        raise WorkArtifactError("path-invalid")
    return "/".join(parts)


def _document_package_input(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    values = [{"id": item["id"], "kind": item["kind"], "contentHash": item["contentHash"]} for item in artifacts]
    values.sort(key=lambda item: (item["kind"], item["id"]))
    return {"artifacts": values, "schemaVersion": 1}


def canonical_document_package_hash(artifacts: list[dict[str, Any]]) -> str:
    """Return DocumentPackageHashV1 for already content-hashed artifacts."""
    return _hash_value(_document_package_input(artifacts))


def canonical_content_generation_hash(artifacts: list[dict[str, Any]], content_generation: int) -> str:
    value = _document_package_input(artifacts)
    value["contentGeneration"] = content_generation
    return _hash_value(value)


def canonical_publication_receipt_hash(receipt: dict[str, Any]) -> str:
    value = deepcopy(receipt)
    value.pop("receiptHash", None)
    return _hash_value(value)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _text_bytes(value: str) -> int:
    return len(value.encode("utf-8"))


def _secret_check(value: str) -> None:
    if any(pattern.search(value) for pattern in _SENSITIVE_PATTERNS):
        raise WorkArtifactError("sensitive-content")


def _atomic_write(path: Path, content: bytes, *, fail_if_exists: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fail_if_exists and path.exists():
        raise WorkArtifactError("target-exists")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if fail_if_exists and path.exists():
            raise WorkArtifactError("target-exists")
        os.replace(temporary_name, path)
        temporary_name = ""
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def _yaml_bytes(value: object) -> bytes:
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False, default_flow_style=False).encode("utf-8")


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise WorkArtifactError("record-invalid") from None
    if not isinstance(value, dict):
        raise WorkArtifactError("record-invalid")
    return value


@contextmanager
def _os_lock(path: Path) -> Iterator[None]:
    """Use an OS lock that is released by process exit; never guess stale PIDs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except (BlockingIOError, OSError) as error:
        raise WorkArtifactError("locked") from None
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


class WorkArtifactManager:
    """Bounded local manager for a single workflow task."""

    def __init__(self, project_root: str | Path, task_id: str):
        self.project_root = Path(project_root).resolve(strict=True)
        self.task_id = _bounded_id(task_id, "task-id-invalid")
        self.local_root = self.project_root / "selfworkflow"
        self.task_root = self.local_root / "tasks" / _physical_id(self.task_id)
        self.manifest_path = self.task_root / "manifest.yaml"

    @property
    def task_path(self) -> Path:
        return self.task_root

    def _check_no_reparse_chain(self, path: Path) -> None:
        current = path
        chain: list[Path] = []
        while True:
            chain.append(current)
            if current == self.project_root:
                break
            parent = current.parent
            if parent == current:
                raise WorkArtifactError("path-escape")
            current = parent
        for item in chain:
            if item.exists() or item.is_symlink():
                try:
                    metadata = item.lstat()
                except OSError:
                    raise WorkArtifactError("path-invalid") from None
                if item.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & 0x400):
                    raise WorkArtifactError("path-reparse")

    def _git_info_exclude(self) -> Path | None:
        environment = os.environ.copy()
        environment.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_OPTIONAL_LOCKS": "0"})
        try:
            top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=self.project_root, check=False, capture_output=True, env=environment, timeout=30)
            if top.returncode != 0 or Path(top.stdout.decode("utf-8").strip()).resolve() != self.project_root:
                return None
            tracked = subprocess.run(["git", "ls-files", "--cached", "--", "selfworkflow"], cwd=self.project_root, check=False, capture_output=True, env=environment, timeout=30)
            staged = subprocess.run(["git", "diff", "--cached", "--name-only", "--", "selfworkflow"], cwd=self.project_root, check=False, capture_output=True, env=environment, timeout=30)
            if tracked.returncode != 0 or staged.returncode != 0:
                raise WorkArtifactError("git-metadata-invalid")
            if tracked.stdout.strip() or staged.stdout.strip():
                raise WorkArtifactError("selfworkflow-tracked")
            info = subprocess.run(["git", "rev-parse", "--git-path", "info/exclude"], cwd=self.project_root, check=False, capture_output=True, env=environment, timeout=30)
            if info.returncode != 0:
                raise WorkArtifactError("git-metadata-invalid")
            value = Path(info.stdout.decode("utf-8").strip())
            return value if value.is_absolute() else self.project_root / value
        except (OSError, UnicodeError, subprocess.TimeoutExpired):
            raise WorkArtifactError("git-metadata-invalid") from None

    def _ensure_local_root(self) -> None:
        self._check_no_reparse_chain(self.local_root)
        exclude = self._git_info_exclude()
        self.local_root.mkdir(parents=True, exist_ok=True)
        if exclude is not None:
            exclude.parent.mkdir(parents=True, exist_ok=True)
            with _os_lock(exclude.with_name(exclude.name + ".selfworkflow.lock")):
                before = exclude.read_bytes() if exclude.exists() else b""
                lines = before.splitlines(keepends=True)
                has_exact = any(line.rstrip(b"\r\n") == b"/selfworkflow/" for line in lines)
                if not has_exact:
                    suffix = b""
                    if before and not before.endswith((b"\n", b"\r")):
                        suffix += b"\n"
                    suffix += b"/selfworkflow/\n"
                    _atomic_write(exclude, before + suffix)
                # Re-read and require the common exclude to be the actual source.
                after = exclude.read_bytes()
                if not any(line.rstrip(b"\r\n") == b"/selfworkflow/" for line in after.splitlines(keepends=True)):
                    raise WorkArtifactError("git-exclude-invalid")

    def _load_manifest(self) -> dict[str, Any] | None:
        if not self.manifest_path.exists():
            return None
        if self.manifest_path.is_symlink():
            raise WorkArtifactError("path-reparse")
        manifest = _read_yaml(self.manifest_path)
        recorded = manifest.pop("manifestHash", None)
        actual = _hash_value(manifest)
        if recorded != actual:
            raise WorkArtifactError("manifest-hash-invalid")
        manifest["manifestHash"] = recorded
        if manifest.get("taskId") != self.task_id:
            raise WorkArtifactError("manifest-task-mismatch")
        return manifest

    @staticmethod
    def _manifest_hash(manifest: dict[str, Any]) -> str:
        value = deepcopy(manifest)
        value.pop("manifestHash", None)
        return _hash_value(value)

    def _save_manifest(self, manifest: dict[str, Any]) -> str:
        value = deepcopy(manifest)
        value.pop("manifestHash", None)
        value["manifestHash"] = _hash_value(value)
        _atomic_write(self.manifest_path, _yaml_bytes(value))
        manifest.clear()
        manifest.update(deepcopy(value))
        return value["manifestHash"]

    def _load_operation(self, nonce: str, payload_hash: str) -> dict[str, Any] | None:
        operation_path = self.task_root / "operations" / (_physical_id(nonce) + ".json")
        if not operation_path.exists():
            return None
        try:
            record = json.loads(operation_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise WorkArtifactError("operation-record-invalid") from None
        if record.get("payloadHash") != payload_hash:
            raise WorkArtifactError("operation-payload-mismatch")
        result = record.get("result")
        if not isinstance(result, dict):
            raise WorkArtifactError("operation-record-invalid")
        return result

    def _save_operation(self, nonce: str, payload_hash: str, result: dict[str, Any]) -> None:
        path = self.task_root / "operations" / (_physical_id(nonce) + ".json")
        if len(list((self.task_root / "operations").glob("*.json"))) >= WDLC_LIMITS_V1["maxOperationRecords"] and not path.exists():
            raise WorkArtifactError("operation-capacity")
        record = {"schemaVersion": 1, "nonce": nonce, "payloadHash": payload_hash, "result": result, "createdAt": _now()}
        _atomic_write(path, (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"), fail_if_exists=True)

    def _validate_artifacts(self, artifacts: list[dict[str, Any]], *, require_content: bool = True) -> list[dict[str, Any]]:
        if not isinstance(artifacts, list) or not artifacts or len(artifacts) > WDLC_LIMITS_V1["maxArtifacts"]:
            raise WorkArtifactError("artifact-list-invalid")
        seen_ids: set[str] = set()
        seen_pairs: set[tuple[str, str]] = set()
        result: list[dict[str, Any]] = []
        package_bytes = 0
        for source in artifacts:
            if not isinstance(source, dict):
                raise WorkArtifactError("artifact-invalid")
            item = deepcopy(source)
            item["id"] = _bounded_id(item.get("id"), "artifact-id-invalid")
            item["kind"] = _bounded_id(item.get("kind"), "artifact-kind-invalid")
            key = item["id"].casefold()
            pair = (item["kind"].casefold(), key)
            if key in seen_ids or pair in seen_pairs:
                raise WorkArtifactError("artifact-alias-or-duplicate")
            seen_ids.add(key)
            seen_pairs.add(pair)
            if require_content:
                content = item.get("content")
                if not isinstance(content, str):
                    raise WorkArtifactError("artifact-content-invalid")
                if _text_bytes(content) > WDLC_LIMITS_V1["maxDocumentBytes"]:
                    raise WorkArtifactError("document-too-large")
                _secret_check(content)
                item["contentHash"] = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
                package_bytes += _text_bytes(content)
            else:
                _require_hash(item.get("contentHash"))
            source_refs = item.get("sourceRefs", [])
            if not isinstance(source_refs, list):
                raise WorkArtifactError("source-reference-invalid")
            for reference in source_refs:
                if not isinstance(reference, dict) or "path" in reference or "descriptor" in reference:
                    raise WorkArtifactError("source-descriptor-rejected")
                _bounded_id(reference.get("sourceId"), "source-reference-invalid")
                _require_hash(reference.get("contentHash"), "source-reference-invalid")
                if reference.get("verificationStatus") not in {"verified", "unverified", "stale"}:
                    raise WorkArtifactError("source-reference-invalid")
            result.append(item)
        if package_bytes > WDLC_LIMITS_V1["maxPackageBytes"]:
            raise WorkArtifactError("package-too-large")
        return result

    def _write_generation(self, generation: int, artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        target = self.task_root / "generations" / f"{generation:06d}"
        if target.exists():
            raise WorkArtifactError("generation-exists")
        target.mkdir(parents=True, exist_ok=False)
        records: list[dict[str, Any]] = []
        for item in artifacts:
            original = item.get("content")
            if not isinstance(original, str):
                raise WorkArtifactError("artifact-content-invalid")
            filename = item["id"] if _SAFE_FILE_RE.fullmatch(item["id"]) and item["id"].casefold() not in _RESERVED_NAMES else _physical_id(item["id"])
            path = target / f"{filename}.md"
            _atomic_write(path, original.encode("utf-8"), fail_if_exists=True)
            record = deepcopy(item)
            record.pop("content", None)
            record.update({"artifactId": item["id"], "path": path.relative_to(self.task_root).as_posix(), "status": "candidate", "replaces": None})
            records.append(record)
        return records

    def _store_review(self, receipt: dict[str, Any], *, generation: int, package_hash: str, manifest_hash: str) -> str:
        value = deepcopy(receipt)
        receipt_id = _bounded_id(value.get("receiptId"), "receipt-id-invalid")
        if value.get("packageHash") != package_hash:
            raise WorkArtifactError("review-subject-mismatch")
        if value.get("independent") is not True:
            raise WorkArtifactError("review-not-independent")
        findings = value.get("findings", [])
        if not isinstance(findings, list) or len(findings) > WDLC_LIMITS_V1["maxFindings"]:
            raise WorkArtifactError("findings-invalid")
        normalized_findings = []
        for finding in findings:
            if not isinstance(finding, dict):
                raise WorkArtifactError("finding-invalid")
            item = deepcopy(finding)
            item["id"] = _bounded_id(item.get("id"), "finding-invalid")
            severity = str(item.get("severity", "")).casefold()
            if severity in _CRITICAL:
                item["severity"] = "Critical"
            elif severity in _IMPORTANT:
                item["severity"] = "Important"
            elif severity in _MINOR:
                item["severity"] = "Minor"
            else:
                raise WorkArtifactError("finding-invalid")
            item["status"] = item.get("status", "open")
            if item["status"] not in _FINDING_STATUSES:
                raise WorkArtifactError("finding-invalid")
            if item["status"] != "open" and not item.get("disposition"):
                raise WorkArtifactError("finding-disposition-required")
            normalized_findings.append(item)
        value.update({"schemaVersion": 1, "receiptId": receipt_id, "generation": generation, "subjectManifestHash": manifest_hash, "findings": normalized_findings, "recordedAt": _now()})
        summary = value.get("summary", "")
        if not isinstance(summary, str) or _text_bytes(summary) > WDLC_LIMITS_V1["maxSummaryBytes"]:
            raise WorkArtifactError("summary-too-large")
        if any(key in value for key in ("privateReasoning", "credentials", "secret")):
            raise WorkArtifactError("sensitive-content")
        _secret_check(summary)
        try:
            _secret_check(json.dumps(value, ensure_ascii=False, sort_keys=True))
        except UnicodeError:
            raise WorkArtifactError("receipt-invalid") from None
        receipt_hash = _hash_value(value)
        value["receiptHash"] = receipt_hash
        directory = self.task_root / "receipts" / "reviews" / _physical_id(receipt_id)
        _atomic_write(directory / "receipt.json", (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"), fail_if_exists=True)
        _atomic_write(directory / "summary.md", summary.encode("utf-8"), fail_if_exists=True)
        return receipt_hash

    def _review_has_blocking(self, receipt: dict[str, Any]) -> bool:
        return any(str(item.get("severity", "")).casefold() in {"critical", "important"} and item.get("status", "open") == "open" for item in receipt.get("findings", []))

    def _attention(self, manifest: dict[str, Any], code: str, message: str, *, generation: int) -> None:
        entries = manifest.setdefault("attention", [])
        if any(item.get("code") == code and item.get("generation") == generation for item in entries):
            return
        candidate = {"code": code, "message": message[:4096], "generation": generation, "createdAt": _now()}
        if len(entries) >= WDLC_LIMITS_V1["maxAttentionItems"] or _text_bytes(json.dumps(entries + [candidate], ensure_ascii=False)) > WDLC_LIMITS_V1["maxAttentionBytes"]:
            raise WorkArtifactError("attention-capacity")
        entries.append(candidate)

    def _clear_attention(self, manifest: dict[str, Any], code: str, generation: int) -> None:
        manifest["attention"] = [item for item in manifest.get("attention", []) if not (item.get("code") == code and item.get("generation") == generation)]

    def _response(self, manifest: dict[str, Any], *, receipt_hash: str | None = None) -> dict[str, Any]:
        return {
            "status": "applied",
            "taskId": self.task_id,
            "taskState": manifest["status"],
            "artifactStatus": next((item["status"] for item in manifest["artifacts"] if item["status"] in {"local-final", "published", "current", "candidate", "invalidated", "rejected"}), "candidate"),
            "contentGeneration": manifest["contentGeneration"],
            "stateRevision": manifest["stateRevision"],
            "manifestHash": manifest["manifestHash"],
            "packageHash": manifest.get("packageHash"),
            "receiptHash": receipt_hash,
        }

    def _update_index(self, manifest: dict[str, Any]) -> None:
        index_path = self.local_root / "index.yaml"
        lock_path = self.local_root / "index.lock"
        with _os_lock(lock_path):
            current = {}
            if index_path.exists():
                try:
                    loaded = yaml.safe_load(index_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        current = loaded
                except (OSError, UnicodeError, yaml.YAMLError):
                    current = {}
            tasks = current.get("tasks", {}) if isinstance(current.get("tasks", {}), dict) else {}
            tasks[self.task_id] = {"taskPath": self.task_root.relative_to(self.local_root).as_posix(), "manifestHash": manifest["manifestHash"], "status": manifest["status"], "updatedAt": _now()}
            _atomic_write(index_path, _yaml_bytes({"schemaVersion": 1, "tasks": tasks}))

    def transition(
        self,
        expected_content_generation: int,
        expected_state_revision: int,
        expected_manifest_hash: str | None,
        event: str,
        artifacts: list[dict[str, Any]] | None = None,
        *,
        operation_nonce: str,
        review: dict[str, Any] | None = None,
        verification: dict[str, Any] | None = None,
        publication: dict[str, Any] | None = None,
        confirmed_by_user: bool = False,
    ) -> dict[str, Any]:
        event = _bounded_id(event, "event-invalid")
        nonce = _bounded_id(operation_nonce, "operation-nonce-invalid")
        payload = {"event": event, "expectedContentGeneration": expected_content_generation, "expectedStateRevision": expected_state_revision, "expectedManifestHash": expected_manifest_hash, "artifacts": artifacts, "review": review, "verification": verification, "publication": publication, "confirmedByUser": confirmed_by_user}
        if _text_bytes(json.dumps(payload, ensure_ascii=False, default=str)) > WDLC_LIMITS_V1["maxRequestBytes"]:
            raise WorkArtifactError("request-too-large")
        payload_hash = _hash_value(payload)
        self._ensure_local_root()
        self.task_root.mkdir(parents=True, exist_ok=True)
        with _os_lock(self.task_root / ".task.lock"):
            replay = self._load_operation(nonce, payload_hash)
            if replay is not None:
                return replay
            manifest = self._load_manifest()
            if manifest is None:
                if event != "documents-captured" or (expected_content_generation, expected_state_revision, expected_manifest_hash) != (0, 0, None):
                    raise WorkArtifactError("cas-conflict")
            else:
                if (manifest["contentGeneration"], manifest["stateRevision"], manifest["manifestHash"]) != (expected_content_generation, expected_state_revision, expected_manifest_hash):
                    raise WorkArtifactError("cas-conflict")

            receipt_hash = None
            if event in {"documents-captured", "documents-revised"}:
                if artifacts is None:
                    raise WorkArtifactError("artifact-list-invalid")
                if manifest is not None and manifest["status"] != "active":
                    raise WorkArtifactError("revision-not-allowed")
                validated = self._validate_artifacts(artifacts)
                generation = 1 if manifest is None else manifest["contentGeneration"] + 1
                records = self._write_generation(generation, validated)
                package_hash = canonical_document_package_hash(records)
                if manifest is not None:
                    for old in manifest["artifacts"]:
                        if old["status"] not in {"published", "rejected"}:
                            old["status"] = "superseded"
                            old["replaces"] = generation
                manifest = {
                    "schemaVersion": 1,
                    "taskId": self.task_id,
                    "projectIdentityHash": _hash_value(str(self.project_root)),
                    "contentGeneration": generation,
                    "stateRevision": 1 if manifest is None else manifest["stateRevision"] + 1,
                    "status": "active",
                    "packageHash": package_hash,
                    "artifacts": records,
                    "review": {"packageHash": package_hash, "receiptHashes": [], "findings": []},
                    "knowledge": {"status": "not-requested", "packageHash": None, "receiptHash": None},
                    "attention": [],
                }
                self._save_manifest(manifest)
            elif manifest is None:
                raise WorkArtifactError("manifest-missing")
            elif event == "review-recorded":
                if review is None:
                    raise WorkArtifactError("review-missing")
                if not any(item["status"] == "candidate" for item in manifest["artifacts"]):
                    raise WorkArtifactError("review-not-allowed")
                receipt_hash = self._store_review(review, generation=manifest["contentGeneration"], package_hash=manifest["packageHash"], manifest_hash=manifest["manifestHash"])
                manifest["stateRevision"] += 1
                manifest["review"]["receiptHashes"].append(receipt_hash)
                manifest["review"]["findings"] = deepcopy(review.get("findings", []))
                if self._review_has_blocking(review):
                    self._attention(manifest, "review-open", "Review has unresolved Critical/Important findings.", generation=manifest["contentGeneration"])
                    for item in manifest["artifacts"]:
                        if item["status"] == "candidate":
                            item["status"] = "candidate"
                else:
                    self._clear_attention(manifest, "review-open", manifest["contentGeneration"])
                    for item in manifest["artifacts"]:
                        if item["status"] == "candidate":
                            item["status"] = "current"
                self._save_manifest(manifest)
            elif event == "post-review-recorded":
                if review is None:
                    raise WorkArtifactError("review-missing")
                if not any(item["status"] == "current" for item in manifest["artifacts"]):
                    raise WorkArtifactError("post-review-not-allowed")
                if any(item.get("event") == "post-review-recorded" and item.get("generation") == manifest["contentGeneration"] and item.get("success") for item in manifest["review"].get("postReviews", [])):
                    raise WorkArtifactError("review-conflict")
                receipt_hash = self._store_review(review, generation=manifest["contentGeneration"], package_hash=manifest["packageHash"], manifest_hash=manifest["manifestHash"])
                manifest["stateRevision"] += 1
                manifest["review"].setdefault("postReviews", []).append({"event": "post-review-recorded", "generation": manifest["contentGeneration"], "receiptHash": receipt_hash, "success": not self._review_has_blocking(review)})
                if self._review_has_blocking(review):
                    self._attention(manifest, "review-open", "Post-landing Review has unresolved findings.", generation=manifest["contentGeneration"])
                else:
                    self._clear_attention(manifest, "review-open", manifest["contentGeneration"])
                self._save_manifest(manifest)
            elif event == "verification-recorded":
                if verification is None or verification.get("passed") is not True or verification.get("fresh") is not True:
                    raise WorkArtifactError("verification-invalid")
                if not any(item["status"] == "current" for item in manifest["artifacts"]):
                    raise WorkArtifactError("verification-not-allowed")
                if verification.get("packageHash") != manifest["packageHash"]:
                    raise WorkArtifactError("verification-subject-mismatch")
                if not any(item.get("generation") == manifest["contentGeneration"] and item.get("success") for item in manifest["review"].get("postReviews", [])):
                    raise WorkArtifactError("verification-blocked")
                if any(item.get("code") == "review-open" and item.get("generation") == manifest["contentGeneration"] for item in manifest.get("attention", [])):
                    raise WorkArtifactError("verification-blocked")
                manifest["stateRevision"] += 1
                manifest["review"].setdefault("verificationReceipts", []).append({"receiptId": _bounded_id(verification.get("receiptId"), "receipt-id-invalid"), "generation": manifest["contentGeneration"], "packageHash": manifest["packageHash"], "passed": True, "fresh": True})
                for item in manifest["artifacts"]:
                    if item["status"] == "current":
                        item["status"] = "local-final"
                self._save_manifest(manifest)
            elif event == "knowledge-published":
                if publication is None or publication.get("decision") != "published":
                    raise WorkArtifactError("publication-invalid")
                _bounded_id(publication.get("backend"), "publication-invalid")
                _bounded_id(publication.get("receiptId"), "publication-invalid")
                _require_hash(publication.get("publishedContentHash"), "publication-invalid")
                if not isinstance(publication.get("publishedAt"), str) or not publication["publishedAt"]:
                    raise WorkArtifactError("publication-invalid")
                if manifest["status"] != "active" or not any(item["status"] == "local-final" for item in manifest["artifacts"]):
                    raise WorkArtifactError("publication-not-ready")
                if publication.get("subjectManifestHash") != manifest["manifestHash"] or publication.get("subjectPackageHash") != manifest["packageHash"] or publication.get("subjectContentGenerationHash") != canonical_content_generation_hash(manifest["artifacts"], manifest["contentGeneration"]):
                    raise WorkArtifactError("publication-subject-mismatch")
                expected = canonical_publication_receipt_hash(publication)
                if publication.get("receiptHash") != expected:
                    raise WorkArtifactError("publication-receipt-hash-invalid")
                receipt_hash = expected
                _atomic_write(self.task_root / "receipts" / "publications" / f"{_physical_id(str(publication.get('receiptId')))}.json", (json.dumps(publication, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"), fail_if_exists=True)
                manifest["stateRevision"] += 1
                manifest["status"] = "knowledge-published"
                manifest["knowledge"] = {"status": "published", "packageHash": manifest["packageHash"], "receiptHash": receipt_hash}
                for item in manifest["artifacts"]:
                    if item["status"] == "local-final":
                        item["status"] = "published"
                self._save_manifest(manifest)
            elif event == "task-completed":
                if manifest["status"] not in {"local-final", "knowledge-published"} and not any(item["status"] == "local-final" for item in manifest["artifacts"]):
                    raise WorkArtifactError("completion-not-ready")
                manifest["stateRevision"] += 1
                manifest["status"] = "completed"
                self._save_manifest(manifest)
            elif event == "task-aborted":
                if not confirmed_by_user:
                    raise WorkArtifactError("confirmation-required")
                if manifest["status"] not in {"active", "local-final"}:
                    raise WorkArtifactError("abort-invalid")
                manifest["stateRevision"] += 1
                manifest["status"] = "aborted"
                for item in manifest["artifacts"]:
                    if item["status"] in {"candidate", "current", "invalidated"}:
                        item["status"] = "rejected"
                self._save_manifest(manifest)
            elif event == "contract-invalidated":
                manifest["stateRevision"] += 1
                for item in manifest["artifacts"]:
                    if item["status"] in {"candidate", "current"}:
                        item["status"] = "invalidated"
                self._attention(manifest, "contract-invalidated", "Implementation contract requires re-planning.", generation=manifest["contentGeneration"])
                self._save_manifest(manifest)
            else:
                raise WorkArtifactError("event-invalid")
            result = self._response(manifest, receipt_hash=receipt_hash)
            self._save_operation(nonce, payload_hash, result)
            self._update_index(manifest)
            return deepcopy(result)

    def reconcile(
        self,
        mode: str,
        expected_content_generation: int,
        expected_state_revision: int,
        expected_manifest_hash: str,
        plan_hash: str | None = None,
    ) -> dict[str, Any]:
        if mode not in {"dry-run", "apply"}:
            raise WorkArtifactError("reconcile-mode-invalid")
        manifest = self._load_manifest()
        if manifest is None:
            raise WorkArtifactError("manifest-missing")
        if (manifest["contentGeneration"], manifest["stateRevision"], manifest["manifestHash"]) != (expected_content_generation, expected_state_revision, expected_manifest_hash):
            raise WorkArtifactError("cas-conflict")
        targets: list[dict[str, Any]] = []
        generation_root = self.task_root / "generations"
        current_generation = manifest["contentGeneration"]
        if generation_root.exists():
            for child in sorted(generation_root.iterdir()):
                if child.is_dir() and child.name.isdigit() and int(child.name) < max(1, current_generation - 1):
                    for file in child.rglob("*"):
                        if file.is_file() and not file.is_symlink():
                            data = file.read_bytes()
                            targets.append({"path": file.relative_to(self.task_root).as_posix(), "contentHash": "sha256:" + hashlib.sha256(data).hexdigest(), "size": len(data)})
        plan = {"schemaVersion": 1, "taskId": self.task_id, "contentGeneration": expected_content_generation, "stateRevision": expected_state_revision, "manifestHash": expected_manifest_hash, "targets": targets, "platformApply": os.name == "nt"}
        computed_plan_hash = _hash_value(plan)
        report = {"status": "dry-run", "taskId": self.task_id, "planHash": computed_plan_hash, "targets": targets, "recovery": {"action": "none"}, "taskState": manifest["status"]}
        if mode == "dry-run":
            return report
        if plan_hash != computed_plan_hash:
            raise WorkArtifactError("reconcile-plan-mismatch")
        if os.name != "nt":
            raise WorkArtifactError("platform-apply-unsupported")
        # First release is intentionally conservative: only manager-owned old generations
        # are eligible.  The preflight hash is rechecked immediately before quarantine.
        for item in targets:
            path = self.task_root / Path(item["path"])
            if not path.exists() or path.is_symlink():
                raise WorkArtifactError("reconcile-target-drift")
            first_read = path.read_bytes()
            current_hash = "sha256:" + hashlib.sha256(first_read).hexdigest()
            if current_hash != item["contentHash"]:
                raise WorkArtifactError("reconcile-target-drift")
            if path.read_bytes() != first_read:
                raise WorkArtifactError("reconcile-target-drift")
            path.unlink()
        return {**report, "status": "applied"}

    def knowledge_package(self) -> dict[str, Any]:
        manifest = self._load_manifest()
        if manifest is None:
            raise WorkArtifactError("manifest-missing")
        if not any(item["status"] in {"local-final", "published"} for item in manifest["artifacts"]):
            raise WorkArtifactError("knowledge-not-ready")
        documents = []
        for item in manifest["artifacts"]:
            if item["status"] not in {"local-final", "published"}:
                continue
            path = self.task_root / item["path"]
            content = path.read_text(encoding="utf-8")
            documents.append({"id": item["artifactId"], "kind": item["kind"], "content": content, "contentHash": item["contentHash"], "sourceRefs": item.get("sourceRefs", [])})
        package = {"schemaVersion": 1, "taskId": self.task_id, "manifestHash": manifest["manifestHash"], "contentGeneration": manifest["contentGeneration"], "documents": documents, "residualRisks": manifest.get("attention", [])}
        package["packageHash"] = _hash_value({key: value for key, value in package.items() if key != "packageHash"})
        return package
