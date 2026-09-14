"""Project-local Graft binding and the SelfWorkFlow-owned update worker.

This module is deliberately smaller than a daemon or file watcher.  Hosts emit
one ``agent_write`` event after a code-changing turn; the worker coalesces that
event and performs one structural Graft build.  Query paths only inspect state
and never create the project cache.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import tempfile
from typing import Any


_MAX_CHANGED_PATHS = 2048
_MAX_JSON_BYTES = 256 * 1024
_REPARSE = 0x400
_GRAPH_DIR = "graft"
_STATE_RELATIVE = (".cache", "selfworkflow")


class GraftProjectError(ValueError):
    """Stable project binding/worker error without paths or command output."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _is_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & _REPARSE
    )


def _safe_root(value: object) -> Path:
    if not isinstance(value, (str, Path)):
        raise GraftProjectError("graft-project-root-invalid")
    raw = Path(value)
    if not raw.is_absolute() or not raw.exists() or not raw.is_dir():
        raise GraftProjectError("graft-project-root-invalid")
    try:
        resolved = raw.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise GraftProjectError("graft-project-root-invalid") from None
    current = Path(raw.anchor)
    try:
        for part in raw.parts[1:]:
            current /= part
            if current.exists() and _is_reparse(current):
                raise GraftProjectError("graft-cache-boundary-invalid")
    except GraftProjectError:
        raise
    except OSError:
        raise GraftProjectError("graft-project-root-invalid") from None
    if resolved != raw.resolve(strict=True):
        raise GraftProjectError("graft-project-root-invalid")
    if not ((raw / ".git").is_dir() or (raw / ".git").is_file()):
        raise GraftProjectError("graft-project-root-invalid")
    return resolved


def _binding(root: Path) -> tuple[Path, Path]:
    graph = root / _GRAPH_DIR
    if graph.exists() and (not graph.is_dir() or _is_reparse(graph)):
        raise GraftProjectError("graft-cache-boundary-invalid")
    state = graph.joinpath(*_STATE_RELATIVE)
    for candidate in (graph, graph / ".cache", state):
        if candidate.exists() and _is_reparse(candidate):
            raise GraftProjectError("graft-cache-boundary-invalid")
    try:
        graph.resolve(strict=False).relative_to(root)
    except (OSError, ValueError):
        raise GraftProjectError("graft-cache-boundary-invalid") from None
    return graph, state


def _ignore_has(root: Path) -> bool:
    ignore = root / ".gitignore"
    if not ignore.exists():
        return False
    if ignore.is_symlink() or _is_reparse(ignore) or not ignore.is_file():
        raise GraftProjectError("graft-cache-boundary-invalid")
    try:
        return any(
            line.strip() in {"/graft/", "graft/", "graft"}
            for line in ignore.read_text(encoding="utf-8").splitlines()
        )
    except (OSError, UnicodeError):
        raise GraftProjectError("graft-cache-boundary-invalid") from None


def _ensure_ignore(root: Path) -> None:
    if _ignore_has(root):
        return
    target = root / ".gitignore"
    previous = target.read_bytes() if target.exists() else b""
    suffix = b"" if not previous or previous.endswith(b"\n") else b"\n"
    payload = previous + suffix + b"# SelfWorkFlow local Graft cache\n/graft/\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".selfworkflow-gitignore-", suffix=".tmp",
            dir=root, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = None
    except (OSError, ValueError):
        raise GraftProjectError("graft-cache-ignore-write-failed") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    if len(payload) > _MAX_JSON_BYTES:
        raise GraftProjectError("graft-worker-state-too-large")
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp",
            dir=path.parent, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except (OSError, TypeError, ValueError):
        raise GraftProjectError("graft-worker-state-write-failed") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _read_json(path: Path, default: Mapping[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    if path.is_symlink() or _is_reparse(path) or not path.is_file():
        raise GraftProjectError("graft-worker-state-invalid")
    try:
        if path.stat().st_size > _MAX_JSON_BYTES:
            raise GraftProjectError("graft-worker-state-too-large")
        value = json.loads(path.read_text(encoding="utf-8"))
    except GraftProjectError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError):
        raise GraftProjectError("graft-worker-state-invalid") from None
    if not isinstance(value, dict):
        raise GraftProjectError("graft-worker-state-invalid")
    return value


def _lock_path(state: Path) -> Path:
    return state / "worker.lock"


class _WorkerLock:
    def __init__(self, state: Path) -> None:
        self.path = _lock_path(state)
        self.handle: Any = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.handle = self.path.open("xb")
            self.handle.write(str(os.getpid()).encode("ascii"))
            self.handle.flush()
        except OSError:
            if self.handle is not None:
                self.handle.close()
            raise GraftProjectError("graft-worker-locked") from None
        return self

    def __exit__(self, *_args: object) -> None:
        try:
            if self.handle is not None:
                self.handle.close()
        finally:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass


def _relative_changed_paths(root: Path, values: Sequence[str]) -> list[str]:
    if not isinstance(values, (list, tuple)) or not values or len(values) > _MAX_CHANGED_PATHS:
        raise GraftProjectError("graft-event-invalid")
    result: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise GraftProjectError("graft-event-invalid")
        candidate = Path(value)
        if candidate.is_absolute():
            try:
                candidate = candidate.resolve(strict=False).relative_to(root)
            except (OSError, ValueError):
                raise GraftProjectError("graft-event-path-outside-project") from None
        parts = candidate.parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise GraftProjectError("graft-event-invalid")
        relative = "/".join(parts)
        if relative == _GRAPH_DIR or relative.startswith(f"{_GRAPH_DIR}/"):
            raise GraftProjectError("graft-event-path-invalid")
        result.add(relative)
    return sorted(result)


class GraftProjectLifecycle:
    """Bind one project and run the one-owner structural update worker."""

    def __init__(self, provider: object) -> None:
        if (
            not callable(getattr(provider, "provider_preflight", None))
            or not callable(getattr(provider, "status", None))
            or not callable(getattr(provider, "build_structural", None))
        ):
            raise GraftProjectError("graft-provider-invalid")
        self._provider = provider

    def _provider_preflight(self) -> dict[str, Any]:
        try:
            result = self._provider.provider_preflight()
        except Exception as error:
            reason = getattr(error, "reason", "graft-provider-unavailable")
            raise GraftProjectError(reason) from None
        if (
            not isinstance(result, Mapping)
            or result.get("providerStatus") != "verified"
        ):
            raise GraftProjectError("graft-provider-unavailable")
        return dict(result)

    def _status(
        self, root: Path, provider_report: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            result = self._provider.status(str(root))
        except Exception as error:
            reason = getattr(error, "reason", "graft-provider-failed")
            raise GraftProjectError(reason) from None
        if not isinstance(result, Mapping):
            raise GraftProjectError("graft-status-invalid")
        freshness = result.get("freshness")
        if freshness not in {"fresh", "stale", "missing"}:
            raise GraftProjectError("graft-status-invalid")
        enriched = dict(result)
        enriched["providerStatus"] = "verified"
        enriched["graphStatus"] = freshness
        if isinstance(provider_report.get("version"), str):
            enriched["providerVersion"] = provider_report["version"]
        if isinstance(provider_report.get("queryCapabilities"), list):
            enriched["queryCapabilities"] = list(provider_report["queryCapabilities"])
        return enriched

    def query_status(self, project_root: str) -> dict[str, Any]:
        root = _safe_root(project_root)
        _binding(root)
        try:
            provider_report = self._provider_preflight()
        except Exception as error:
            reason = getattr(error, "reason", "graft-provider-failed")
            return {
                "providerId": "graft", "status": "unverified",
                "providerStatus": "unavailable",
                "graphStatus": "unknown", "reason": reason,
            }
        try:
            result = self._status(root, provider_report)
        except Exception as error:
            reason = getattr(error, "reason", "graft-provider-failed")
            return {
                "providerId": "graft", "status": "unverified",
                "providerStatus": "verified",
                "graphStatus": "unknown", "reason": reason,
            }
        if not isinstance(result, Mapping):
            raise GraftProjectError("graft-status-invalid")
        return dict(result)

    def query(
        self, project_root: str, query: str, *, query_kind: str,
    ) -> dict[str, Any]:
        """Validate the project boundary before a read-only Provider query."""

        root = _safe_root(project_root)
        _binding(root)
        try:
            self._provider_preflight()
            result = self._provider.query(
                str(root), query, query_kind=query_kind,
            )
        except Exception as error:
            reason = getattr(error, "reason", "graft-provider-failed")
            raise GraftProjectError(reason) from None
        if not isinstance(result, Mapping):
            raise GraftProjectError("graft-query-invalid")
        return dict(result)

    def preflight(self, project_root: str) -> dict[str, Any]:
        root = _safe_root(project_root)
        _binding(root)
        try:
            provider_report = self._provider_preflight()
        except Exception as error:
            reason = getattr(error, "reason", "graft-update-failed")
            return {
                "providerId": "graft", "status": "unverified",
                "providerStatus": "unavailable",
                "graphStatus": "unknown", "reason": reason,
            }
        try:
            status = self._status(root, provider_report)
        except Exception as error:
            reason = getattr(error, "reason", "graft-update-failed")
            return {
                "providerId": "graft", "status": "unverified",
                "providerStatus": "verified",
                "graphStatus": "unknown", "reason": reason,
            }
        if status["freshness"] != "missing":
            return {"status": "ready", **status}
        try:
            _ensure_ignore(root)
            build = self._provider.build_structural(str(root))
            final = self._status(root, provider_report)
        except Exception as error:
            reason = getattr(error, "reason", "graft-update-failed")
            return {
                "providerId": "graft", "status": "unverified",
                "providerStatus": "verified",
                "graphStatus": "unknown", "reason": reason,
            }
        return {"status": "initialized", "build": dict(build), **final}

    def enqueue(self, project_root: str, changed_paths: Sequence[str]) -> dict[str, Any]:
        root = _safe_root(project_root)
        graph, state = _binding(root)
        paths = _relative_changed_paths(root, changed_paths)
        try:
            self._provider_preflight()
        except Exception as error:
            reason = getattr(error, "reason", "graft-provider-failed")
            return {
                "providerId": "graft", "status": "unverified",
                "providerStatus": "unavailable", "graphStatus": "unknown",
                "pending": False, "reason": reason,
            }
        _ensure_ignore(root)
        with _WorkerLock(state):
            queue_path = state / "queue.json"
            queue = _read_json(queue_path, {"schemaVersion": 1, "changedPaths": []})
            old = queue.get("changedPaths", [])
            if not isinstance(old, list) or any(not isinstance(item, str) for item in old):
                raise GraftProjectError("graft-worker-state-invalid")
            merged = sorted(set(old).union(paths))
            if len(merged) > _MAX_CHANGED_PATHS:
                raise GraftProjectError("graft-event-too-large")
            _write_json(queue_path, {"schemaVersion": 1, "changedPaths": merged})
        return {
            "providerId": "graft", "status": "queued" if not old else "coalesced",
            "pending": True, "changedPathCount": len(merged),
            "graphRoot": str(graph),
        }

    def run_once(self, project_root: str) -> dict[str, Any]:
        root = _safe_root(project_root)
        graph, state = _binding(root)
        try:
            self._provider_preflight()
        except Exception as error:
            reason = getattr(error, "reason", "graft-provider-failed")
            return {
                "providerId": "graft", "status": "unverified",
                "providerStatus": "unavailable", "graphStatus": "unknown",
                "pending": True, "retryable": True, "reason": reason,
            }
        with _WorkerLock(state):
            queue_path = state / "queue.json"
            queue = _read_json(queue_path, {"schemaVersion": 1, "changedPaths": []})
            paths = queue.get("changedPaths", [])
            if not isinstance(paths, list) or any(not isinstance(item, str) for item in paths):
                raise GraftProjectError("graft-worker-state-invalid")
            if not paths:
                return {"providerId": "graft", "status": "idle", "pending": False}
            _write_json(queue_path, {"schemaVersion": 1, "changedPaths": []})
            active = list(paths)
        try:
            build = self._provider.build_structural(str(root))
        except Exception as error:
            reason = getattr(error, "reason", "graft-update-failed")
            with _WorkerLock(state):
                queue_path = state / "queue.json"
                queue = _read_json(queue_path, {"schemaVersion": 1, "changedPaths": []})
                pending = queue.get("changedPaths", [])
                if not isinstance(pending, list):
                    raise GraftProjectError("graft-worker-state-invalid") from None
                merged = sorted(set(active).union(item for item in pending if isinstance(item, str)))
                _write_json(queue_path, {"schemaVersion": 1, "changedPaths": merged})
                _write_json(state / "state.json", {
                    "schemaVersion": 1, "status": "failed", "retryable": True,
                    "lastChangedPaths": active, "reason": reason,
                })
            return {
                "providerId": "graft", "status": "failed", "retryable": True,
                "pending": True, "reason": reason,
            }
        with _WorkerLock(state):
            queue = _read_json(state / "queue.json", {"schemaVersion": 1, "changedPaths": []})
            pending = queue.get("changedPaths", [])
            if not isinstance(pending, list):
                raise GraftProjectError("graft-worker-state-invalid")
            _write_json(state / "state.json", {
                "schemaVersion": 1, "status": "succeeded", "retryable": False,
                "lastChangedPaths": active,
            })
        return {
            "providerId": "graft", "status": "succeeded", "retryable": False,
            "pending": bool(pending), "changedPathCount": len(active),
            "build": dict(build) if isinstance(build, Mapping) else build,
            "graphRoot": str(graph),
        }


def validate_project_root(project_root: object) -> Path:
    """Validate the same Git/reparse/cache boundary used by the lifecycle."""

    root = _safe_root(project_root)
    _binding(root)
    return root
