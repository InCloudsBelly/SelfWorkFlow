"""Project-scoped CodeGraph lifecycle with non-destructive incremental sync."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import os
from pathlib import Path
from typing import Any, TypeVar

from selfworkflow.v3.providers.codegraph import (
    CodeGraphAdapter,
    CodeGraphAdapterError,
)


class CodeGraphProjectError(ValueError):
    """Stable lifecycle error which never exposes command output or paths."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _safe_project_root(project_root: object) -> Path:
    if not isinstance(project_root, str) or not project_root.strip():
        raise CodeGraphProjectError("codegraph-project-root-invalid")
    try:
        root = Path(project_root)
        if not root.is_absolute():
            raise CodeGraphProjectError("codegraph-project-root-invalid")
        resolved = root.resolve(strict=True)
        if not resolved.is_dir() or resolved.is_symlink():
            raise CodeGraphProjectError("codegraph-project-root-invalid")
        return resolved
    except CodeGraphProjectError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise CodeGraphProjectError("codegraph-project-root-invalid") from None


def _checked_changed_paths(changed_paths: Sequence[str] | None) -> tuple[str, ...]:
    if changed_paths is None:
        return ()
    if isinstance(changed_paths, (str, bytes)):
        raise CodeGraphProjectError("codegraph-changed-paths-invalid")
    values: dict[str, None] = {}
    try:
        for value in changed_paths:
            if (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
                or any(ord(character) < 32 for character in value)
            ):
                raise CodeGraphProjectError("codegraph-changed-paths-invalid")
            values[value] = None
    except TypeError:
        raise CodeGraphProjectError("codegraph-changed-paths-invalid") from None
    return tuple(values)


def _index_dir_names() -> tuple[str, ...]:
    name = os.environ.get("CODEGRAPH_DIR", "").strip()
    # Without an override the provider may choose either platform default.
    names = (name,) if name else (".codegraph", ".codegraph-wsl")
    if name == "." or ".." in name or "/" in name or "\\" in name or Path(name).is_absolute():
        names = (".codegraph",)
    return names


def _assert_no_pending_publication(root: Path) -> None:
    for selected in _index_dir_names():
        for suffix in (".publication.json", ".publication.lock"):
            try:
                (root / f"{selected}{suffix}").lstat()
            except FileNotFoundError:
                continue
            except OSError:
                raise CodeGraphProjectError("codegraph-publication-state-unknown") from None
            raise CodeGraphProjectError("codegraph-publication-recovery-required")

_T = TypeVar('_T')


class CodeGraphProjectLifecycle:
    """Execute one automatic boundary; CodeGraph owns process/DB locking."""

    def __init__(self, adapter: CodeGraphAdapter) -> None:
        if not isinstance(adapter, CodeGraphAdapter):
            raise CodeGraphProjectError("codegraph-adapter-invalid")
        self._adapter = adapter

    def _guarded_call(self, root: Path, operation: Callable[[], _T]) -> _T:
        _assert_no_pending_publication(root)

        def validate_dispatch() -> None:
            try:
                _assert_no_pending_publication(root)
            except CodeGraphProjectError as error:
                raise CodeGraphAdapterError(error.reason) from None

        try:
            with self._adapter._guarded_dispatch(validate_dispatch):
                result = operation()
        except CodeGraphAdapterError as error:
            raise CodeGraphProjectError(error.reason) from None
        _assert_no_pending_publication(root)
        return result

    def status(self, project_root: str) -> dict[str, Any]:
        root = _safe_project_root(project_root)
        return self._guarded_call(root, lambda: self._adapter.status(str(root)))

    def _maintain(self, action: str, root: Path) -> dict[str, Any]:
        def maintain() -> dict[str, Any]:
            plan = self._adapter.plan_maintenance(action, str(root))
            return self._adapter.execute_maintenance(
                plan, str(root), confirmed_plan_hash=plan["planHash"],
            )

        return self._guarded_call(root, maintain)

    def _initial_status(self, root: Path) -> dict[str, Any]:
        return self._guarded_call(root, lambda: self._adapter.maintenance_status(str(root)))

    def _automatic_route(self, root: Path, **options: Any) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        def native() -> dict[str, Any] | None:
            return self._guarded_call(root, lambda: self._adapter.reconcile_ue(str(root), **options))

        if self._adapter.allow_ue_reconcile:
            _assert_no_pending_publication(root)
            # This is a startup hint, not the authority for the active profile.
            # On Windows a dormant WSL config cannot select the native route.
            names = _index_dir_names()
            for name in names[:1] if os.name == "nt" else names:
                try:
                    with (root / name / "indexing.json").open("rb") as stream:
                        data = stream.read(1024 * 1024 + 1)
                    config = json.loads(data) if len(data) <= 1024 * 1024 else None
                except (OSError, ValueError, RecursionError):
                    continue
                if isinstance(config, dict) and "ueEngine" in config:
                    result = native()
                    if result is not None:
                        return result, {}
                    break

        initial = self._initial_status(root)
        if (self._adapter.allow_ue_reconcile and initial.get("ueProfile") is True
                and initial.get("indexingConfigInvalid") is not True):
            result = native()
            if result is None:
                raise CodeGraphProjectError("codegraph-ue-profile-changed")
            return result, initial
        return None, initial

    def _ensure_from_status(
        self, root: Path, initial: Mapping[str, Any],
    ) -> dict[str, Any]:
        actions: list[str] = []
        current = dict(initial)
        if current.get("indexingConfigInvalid") is True:
            raise CodeGraphProjectError("codegraph-indexing-config-invalid")
        if current.get("ueProfile") is True and self._adapter.allow_ue_reconcile:
            # A UE generation without a declared native route needs explicit
            # diagnosis. Do not fall through to the permissive legacy writer.
            raise CodeGraphProjectError("codegraph-ue-profile-changed")
        if current.get("indexState") == "indexing":
            raise CodeGraphProjectError("codegraph-project-busy")
        if current.get("initialized") is not True:
            raise CodeGraphProjectError("codegraph-explicit-initialization-required")
        # Missing/unknown state can be an interrupted publication or partial bake.
        if current.get("storedIndexState", current.get("indexState")) != "complete":
            raise CodeGraphProjectError("codegraph-index-state-not-complete")
        files, nodes = current.get("fileCount"), current.get("nodeCount")
        if current.get("dataConsistent") is False or (
            type(files) is int and type(nodes) is int and (files == 0) != (nodes == 0)
        ):
            raise CodeGraphProjectError("codegraph-index-data-inconsistent")
        # An extraction-version upgrade needs a separately verified candidate.
        if current.get("reindexRecommended") is True:
            raise CodeGraphProjectError("codegraph-rebuild-required-preserving-existing-index")
        # Git status can be clean after checkout while the index is stale.
        # The official sync reconciles disk and skips unchanged source files.
        _assert_no_pending_publication(root)
        self._maintain("sync", root)
        actions.append("sync")
        current = self.status(str(root))

        if current.get("indexState") == "indexing":
            raise CodeGraphProjectError("codegraph-project-busy")
        if current.get("initialized") is not True:
            raise CodeGraphProjectError("codegraph-index-not-initialized")
        if current.get("freshness") != "fresh":
            raise CodeGraphProjectError("codegraph-index-not-fresh")
        return {
            "providerId": "codegraph",
            "status": "succeeded",
            "freshness": "fresh",
            "updated": bool(actions),
            "actions": actions,
            "index": current,
        }

    def ensure(self, project_root: str) -> dict[str, Any]:
        root = _safe_project_root(project_root)
        result, initial = self._automatic_route(root)
        return result if result is not None else self._ensure_from_status(root, initial)

    def sync(
        self, project_root: str, changed_paths: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        root = _safe_project_root(project_root)
        paths = _checked_changed_paths(changed_paths)
        result, initial = self._automatic_route(root, changed_paths=paths)
        if result is None:
            result = self._ensure_from_status(root, initial)
        result["changedPathCount"] = len(paths)
        return result

    def query(
        self, project_root: str, query: str, *, query_kind: str = "ask",
    ) -> dict[str, Any]:
        root = _safe_project_root(project_root)
        native, initial = self._automatic_route(root, query=query, query_kind=query_kind)
        if native is not None:
            return native
        ensured = self._ensure_from_status(root, initial)
        result = self._guarded_call(root, lambda: self._adapter.query(
            str(root), query, query_kind=query_kind,
        ))
        result["updated"] = ensured["updated"]
        result["maintenanceActions"] = ensured["actions"]
        return result

    def preflight(self, project_root: str) -> dict[str, Any]:
        return self.ensure(project_root)
