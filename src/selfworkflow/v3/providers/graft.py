"""Fail-closed adapter for the pinned Graft CLI.

The adapter exposes only the deterministic CLI surfaces used by SelfWorkFlow.
Queries always use Graft's ``--no-refresh`` flag; graph maintenance is a
separate, explicitly confirmed plan and never runs implicitly during a query.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import ntpath
from typing import Any, Callable

from selfworkflow.v3.providers.codegraph import CommandPort, CommandResult


_MAX_OUTPUT_BYTES = 1024 * 1024
# ``graft check --json`` legitimately includes the full drift set.  Large
# repositories can therefore exceed the normal command-result budget even
# though the adapter returns only the bounded freshness summary below.
# Keep this operation-specific and finite; query/help/version remain on the
# tighter default limit.
_STATUS_OUTPUT_BYTES = 64 * 1024 * 1024
_QUERY_KINDS = frozenset({"ask", "map", "grep", "callers", "skeleton"})
_REQUIRED_COMMANDS = frozenset({
    "build", "check", "ask", "map", "grep", "callers", "skeleton",
})
_MAINTENANCE_ACTIONS = frozenset({"initialize", "sync", "rebuild"})


class GraftAdapterError(ValueError):
    """Stable adapter error without command output, paths, or credentials."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (OverflowError, RecursionError, TypeError, ValueError):
        raise GraftAdapterError("graft-plan-invalid") from None


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _with_hash(document: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(document)
    result["planHash"] = _hash(result)
    return result


def _text(value: object, reason: str, *, maximum: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise GraftAdapterError(reason)
    return value


def _project_root(value: object) -> str:
    root = _text(value, "graft-project-root-invalid")
    if not ntpath.isabs(root):
        raise GraftAdapterError("graft-project-root-invalid")
    normalized = ntpath.normpath(root).replace("\\", "/")
    if ".." in normalized.split("/"):
        raise GraftAdapterError("graft-project-root-invalid")
    return normalized


def _context_dir(root: str, value: object) -> str | None:
    """Validate an optional topic context without allowing root ``graft/``."""

    if value is None:
        return None
    context = _project_root(value)
    try:
        relative = ntpath.relpath(context, root).replace("\\", "/")
    except (OSError, ValueError):
        raise GraftAdapterError("graft-context-dir-invalid") from None
    parts = relative.split("/")
    if (
        len(parts) != 4
        or parts[0].casefold() != ".selfworkflow"
        or parts[1].casefold() != "graft-deep"
        or parts[3].casefold() != "graft"
        or not parts[2]
        or parts[2] in {".", ".."}
    ):
        raise GraftAdapterError("graft-context-dir-invalid")
    return context


def _prefix(value: Sequence[str]) -> tuple[str, ...]:
    if (
        not isinstance(value, (tuple, list))
        or not value
        or len(value) > 16
        or any(
            not isinstance(item, str)
            or not item
            or item != item.strip()
            or any(ord(character) < 32 for character in item)
            for item in value
        )
    ):
        raise GraftAdapterError("graft-command-prefix-invalid")
    return tuple(value)


class GraftAdapter:
    """Render bounded Graft commands and delegate execution to the Host."""

    def __init__(
        self,
        *,
        command_port: CommandPort,
        command_prefix: Sequence[str],
        ownership: str,
        pre_dispatch_validator: Callable[[], None] | None = None,
    ) -> None:
        if not callable(getattr(command_port, "run", None)):
            raise GraftAdapterError("graft-command-port-invalid")
        if ownership not in {"user-local", "selfworkflow-managed"}:
            raise GraftAdapterError("graft-ownership-invalid")
        if pre_dispatch_validator is not None and not callable(pre_dispatch_validator):
            raise GraftAdapterError("graft-source-validator-invalid")
        self._port = command_port
        self._prefix = _prefix(command_prefix)
        self._ownership = ownership
        self._pre_dispatch_validator = pre_dispatch_validator
        self._issued_maintenance_plans: set[str] = set()
        self._consumed_maintenance_plans: set[str] = set()

    @property
    def ownership(self) -> str:
        return self._ownership

    @property
    def command_hash(self) -> str:
        return _hash({"argv": list(self._prefix)})

    @property
    def command_prefix(self) -> tuple[str, ...]:
        """Return the already source-bound official Graft launcher."""

        return self._prefix

    def _run(
        self,
        arguments: Sequence[str],
        *,
        context_dir: str | None = None,
        allow_exit_codes: frozenset[int] = frozenset({0}),
        output_limit_bytes: int = _MAX_OUTPUT_BYTES,
    ) -> CommandResult:
        try:
            if self._pre_dispatch_validator is not None:
                self._pre_dispatch_validator()
            prefix = self._prefix
            if context_dir is not None:
                prefix += ("--dir", context_dir)
            result = self._port.run(prefix + tuple(arguments), cwd=None)
        except GraftAdapterError:
            raise
        except Exception:
            raise GraftAdapterError("graft-command-port-failed") from None
        if (
            type(result) is not CommandResult
            or type(result.exit_code) is not int
            or not isinstance(result.stdout, str)
            or not isinstance(result.stderr, str)
        ):
            raise GraftAdapterError("graft-command-result-invalid")
        if (
            len(result.stdout.encode("utf-8")) > output_limit_bytes
            or len(result.stderr.encode("utf-8")) > _MAX_OUTPUT_BYTES
        ):
            raise GraftAdapterError("graft-command-output-too-large")
        if result.exit_code not in allow_exit_codes:
            raise GraftAdapterError("graft-command-failed")
        return result

    @staticmethod
    def _parse_json(output: str, reason: str) -> dict[str, Any]:
        try:
            value = json.loads(output)
        except (TypeError, ValueError):
            raise GraftAdapterError(reason) from None
        if not isinstance(value, dict):
            raise GraftAdapterError(reason)
        return value

    def status(
        self, project_root: str, *, context_dir: str | None = None,
    ) -> dict[str, Any]:
        root = _project_root(project_root)
        context = _context_dir(root, context_dir)
        result = self._run(
            ("check", root, "--json"),
            context_dir=context,
            allow_exit_codes=frozenset({0, 1}),
            output_limit_bytes=_STATUS_OUTPUT_BYTES,
        )
        value = self._parse_json(result.stdout, "graft-status-invalid")
        context = value.get("context")
        graph = value.get("graph")
        if (
            not isinstance(context, Mapping)
            or (graph is not None and not isinstance(graph, Mapping))
        ):
            raise GraftAdapterError("graft-status-invalid")
        context_missing = context.get("missing") is True
        graph_missing = graph is None or graph.get("missing") is True
        if context_missing and graph_missing:
            freshness = "missing"
        elif (
            result.exit_code == 0
            and isinstance(graph, Mapping)
            and graph.get("ok") is True
        ):
            freshness = "fresh"
        else:
            freshness = "stale"
        return {
            "providerId": "graft",
            "operation": "status",
            "readOnly": True,
            "supportStatus": "unverified",
            "freshness": freshness,
            "initialized": freshness != "missing",
            "projectRootHash": _hash({"projectRoot": root.casefold()}),
        }

    def version(self) -> dict[str, Any]:
        result = self._run(("--version",))
        value = result.stdout.strip()
        if not value or any(
            ord(character) < 32 and character not in "\r\n\t"
            for character in value
        ):
            raise GraftAdapterError("graft-version-invalid")
        return {
            "providerId": "graft",
            "operation": "version",
            "readOnly": True,
            "supportStatus": "unverified",
            "version": value.splitlines()[0][:256],
        }

    def provider_preflight(self) -> dict[str, Any]:
        """Verify that the configured runtime exposes the query surface."""

        version = self.version()["version"]
        help_result = self._run(("--help",))
        commands = {
            line.strip().split(maxsplit=1)[0]
            for line in help_result.stdout.splitlines()
            if line.strip()
        }
        if not _REQUIRED_COMMANDS <= commands:
            raise GraftAdapterError("graft-provider-capability-missing")
        return {
            "providerId": "graft",
            "operation": "provider-preflight",
            "readOnly": True,
            "providerStatus": "verified",
            "version": version,
            "queryCapabilities": sorted(_REQUIRED_COMMANDS),
        }

    def query(
        self,
        project_root: str,
        query: str,
        *,
        query_kind: str = "ask",
        context_dir: str | None = None,
    ) -> dict[str, Any]:
        root = _project_root(project_root)
        context = _context_dir(root, context_dir)
        query_text = _text(query, "graft-query-invalid")
        if query_kind not in _QUERY_KINDS:
            raise GraftAdapterError("graft-query-kind-invalid")
        status = self.status(root, context_dir=context)
        if not status["initialized"]:
            raise GraftAdapterError("graft-graph-not-ready")
        if query_kind == "map":
            arguments = (query_kind, root, "--json", "--no-refresh")
        else:
            arguments = (query_kind, query_text, root, "--json", "--no-refresh")
        result = self._run(arguments, context_dir=context)
        return {
            "providerId": "graft",
            "operation": "query",
            "queryKind": query_kind,
            "readOnly": True,
            "sideEffectClass": "none",
            "supportStatus": "unverified",
            "freshness": status["freshness"],
            "data": self._parse_json(result.stdout, "graft-query-invalid"),
        }

    def plan_query(
        self,
        project_root: str,
        query: str,
        *,
        query_kind: str = "ask",
    ) -> dict[str, Any]:
        root = _project_root(project_root)
        query_text = _text(query, "graft-query-invalid")
        if query_kind not in _QUERY_KINDS:
            raise GraftAdapterError("graft-query-kind-invalid")
        status = self.status(root)
        if not status["initialized"]:
            raise GraftAdapterError("graft-graph-not-ready")
        return _with_hash({
            "schemaVersion": 1,
            "providerId": "graft",
            "operation": "query",
            "queryKind": query_kind,
            "ownership": self._ownership,
            "projectRootHash": status["projectRootHash"],
            "queryHash": _hash({"query": query_text}),
            "adapterCommandHash": self.command_hash,
            "graphFreshness": status["freshness"],
            "readOnly": True,
            "sideEffectClass": "none",
            "supportStatus": "unverified",
            "reasonCode": "graft-query-no-refresh",
        })

    def plan_maintenance(self, action: str, project_root: str) -> dict[str, Any]:
        action_value = _text(action, "graft-maintenance-action-invalid")
        root = _project_root(project_root)
        if action_value not in _MAINTENANCE_ACTIONS:
            raise GraftAdapterError("graft-maintenance-action-invalid")
        plan = _with_hash({
            "schemaVersion": 1,
            "providerId": "graft",
            "operation": "maintain",
            "action": action_value,
            "ownership": self._ownership,
            "adapterCommandHash": self.command_hash,
            "projectRootHash": _hash({"projectRoot": root.casefold()}),
            "readOnly": False,
            "sideEffectClass": "local-write",
            "supportStatus": "unverified",
            "reasonCode": "graft-build-explicit-only",
        })
        self._issued_maintenance_plans.add(plan["planHash"])
        return plan

    def build_structural(self, project_root: str) -> dict[str, Any]:
        """Run the host-owned structural build used by preflight and Worker."""

        root = _project_root(project_root)
        # SelfWorkFlow owns the project cache boundary and its anchored ignore
        # rule.  Graft must not modify ignore files behind that boundary.
        self._run(("build", root, "--no-gitignore", "--no-ignore"))
        return {
            "providerId": "graft",
            "operation": "build",
            "status": "succeeded",
            "deep": False,
            "readOnly": False,
            "sideEffectClass": "project-local-cache",
        }

    def execute_maintenance(
        self,
        plan: Mapping[str, Any],
        project_root: str,
        *,
        confirmed_plan_hash: str,
    ) -> dict[str, Any]:
        if not isinstance(plan, Mapping):
            raise GraftAdapterError("graft-maintenance-plan-invalid")
        supplied = dict(plan)
        plan_hash = supplied.get("planHash")
        if not isinstance(plan_hash, str) or confirmed_plan_hash != plan_hash:
            raise GraftAdapterError("graft-maintenance-confirmation-mismatch")
        material = {key: value for key, value in supplied.items() if key != "planHash"}
        if plan_hash != _hash(material):
            raise GraftAdapterError("graft-maintenance-plan-tampered")
        if plan_hash in self._consumed_maintenance_plans:
            raise GraftAdapterError("graft-maintenance-plan-replayed")
        if plan_hash not in self._issued_maintenance_plans:
            raise GraftAdapterError("graft-maintenance-plan-not-issued")
        root = _project_root(project_root)
        expected = {
            "schemaVersion": 1,
            "providerId": "graft",
            "operation": "maintain",
            "action": supplied.get("action"),
            "ownership": self._ownership,
            "adapterCommandHash": self.command_hash,
            "projectRootHash": _hash({"projectRoot": root.casefold()}),
            "readOnly": False,
            "sideEffectClass": "local-write",
            "supportStatus": "unverified",
            "reasonCode": "graft-build-explicit-only",
        }
        if supplied != _with_hash(expected):
            raise GraftAdapterError("graft-maintenance-plan-tampered")
        self.build_structural(root)
        self._issued_maintenance_plans.discard(plan_hash)
        self._consumed_maintenance_plans.add(plan_hash)
        return {
            "providerId": "graft",
            "operation": "maintain",
            "action": supplied["action"],
            "status": "succeeded",
            "planHash": plan_hash,
            "supportStatus": "unverified",
        }
