"""Fail-closed CodeGraph CLI adapter using an injected command port only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import ntpath
import re
from typing import Any, Callable, Protocol


_MAX_OUTPUT_BYTES = 1024 * 1024
_SYNC_LOCK_ERROR = re.compile(
    r"(?:✗|\[ERR\]) Failed to sync: "
    r"(?:Sync could not acquire the file lock; retry when the index is available\. )?"
    r"CodeGraph database is locked by another process"
    r"(?: \(PID [0-9]+\))?\. If this is stale, run 'codegraph unlock' or delete .+"
)
_MAINTENANCE_COMMANDS = {
    "initialize": ("init",),
    "sync": ("sync",),
    "rebuild": ("index", "--force"),
}


class CodeGraphAdapterError(ValueError):
    """Stable adapter error which never includes Provider output or local paths."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    failure_kind: str | None = None
    duration_ms: int | None = None
    timeout_ms: int | None = None
    exception_type: str | None = None


class CommandPort(Protocol):
    def run(
        self, argv: Sequence[str], *, cwd: str | None = None,
    ) -> CommandResult: ...


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (OverflowError, RecursionError, TypeError, ValueError):
        raise CodeGraphAdapterError("codegraph-plan-invalid") from None


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _with_hash(document: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(document)
    result["planHash"] = _hash(result)
    return result


def _validate_text(value: object, reason: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or any(ord(character) < 32 for character in value)
    ):
        raise CodeGraphAdapterError(reason)
    return value


def _validate_project_root(value: object) -> str:
    root = _validate_text(value, "codegraph-project-root-invalid")
    if not ntpath.isabs(root):
        raise CodeGraphAdapterError("codegraph-project-root-invalid")
    return ntpath.normpath(root).replace("\\", "/")


def _validate_prefix(value: object) -> tuple[str, ...]:
    if (
        not isinstance(value, (tuple, list))
        or not value
        or any(
            not isinstance(item, str)
            or not item
            or item != item.strip()
            or any(ord(character) < 32 for character in item)
            for item in value
        )
    ):
        raise CodeGraphAdapterError("codegraph-command-prefix-invalid")
    return tuple(value)


def _status_freshness(value: Mapping[str, Any]) -> str:
    if value.get("workingTreeChecked") is False:
        return "unknown"
    if value.get("initialized") is not True:
        return "missing"
    indexing_config = value.get("indexingConfig")
    if isinstance(indexing_config, Mapping) and indexing_config.get("error") is not None:
        return "stale"
    index = value.get("index")
    if isinstance(index, Mapping):
        if index.get("state") in {"indexing", "partial", "failed"}:
            return "stale"
        if index.get("reindexRecommended") is True:
            return "stale"
        if type(index.get("pendingRefs")) is int and index["pendingRefs"] > 0:
            return "stale"
    environment = value.get("cppIncludeEnvironment")
    if "cppIncludeEnvironment" in value:
        if not isinstance(environment, Mapping) or environment.get("observed") is not True or environment.get("complete") is not True:
            return "unknown"
        if environment.get("changed") is not False:
            return "stale"
    pending = value.get("pendingChanges")
    if "pendingChanges" in value and pending is None:
        return "unknown"
    if isinstance(pending, Mapping) and any(
        type(pending.get(key)) is int and pending[key] > 0
        for key in ("added", "modified", "removed")
    ):
        return "stale"
    if value.get("worktreeMismatch") is not None:
        return "stale"
    return "fresh"


class CodeGraphAdapter:
    """Render fixed CodeGraph commands and delegate execution to the Host."""

    def __init__(
        self,
        *,
        command_port: CommandPort,
        command_prefix: Sequence[str],
        ownership: str,
        pre_dispatch_validator: Callable[[], None] | None = None,
        allow_metadata_only_status: bool = False,
    ) -> None:
        if not callable(getattr(command_port, "run", None)):
            raise CodeGraphAdapterError("codegraph-command-port-invalid")
        if ownership not in {"user-local", "selfworkflow-managed"}:
            raise CodeGraphAdapterError("codegraph-ownership-invalid")
        if pre_dispatch_validator is not None and not callable(pre_dispatch_validator):
            raise CodeGraphAdapterError("codegraph-source-validator-invalid")
        if type(allow_metadata_only_status) is not bool:
            raise CodeGraphAdapterError("codegraph-metadata-capability-invalid")
        self._port = command_port
        self._prefix = _validate_prefix(command_prefix)
        self._ownership = ownership
        self._pre_dispatch_validator = pre_dispatch_validator
        self._allow_metadata_only_status = allow_metadata_only_status
        self._issued_maintenance_plans: set[str] = set()
        self._consumed_maintenance_plans: set[str] = set()

    @property
    def ownership(self) -> str:
        return self._ownership

    @property
    def command_hash(self) -> str:
        return _hash({"argv": list(self._prefix)})

    def _run(self, arguments: Sequence[str]) -> CommandResult:
        try:
            if self._pre_dispatch_validator is not None:
                self._pre_dispatch_validator()
            result = self._port.run(self._prefix + tuple(arguments), cwd=None)
        except CodeGraphAdapterError:
            raise
        except Exception:
            raise CodeGraphAdapterError("codegraph-command-port-failed") from None
        if (
            type(result) is not CommandResult
            or type(result.exit_code) is not int
            or not isinstance(result.stdout, str)
            or not isinstance(result.stderr, str)
        ):
            raise CodeGraphAdapterError("codegraph-command-result-invalid")
        if (
            len(result.stdout.encode("utf-8")) > _MAX_OUTPUT_BYTES
            or len(result.stderr.encode("utf-8")) > _MAX_OUTPUT_BYTES
        ):
            raise CodeGraphAdapterError("codegraph-command-output-too-large")
        if result.exit_code != 0:
            if arguments and arguments[0] == "sync":
                stderr = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", result.stderr)
                if any(_SYNC_LOCK_ERROR.fullmatch(line) for line in stderr.splitlines()):
                    raise CodeGraphAdapterError("codegraph-project-busy")
            raise CodeGraphAdapterError("codegraph-command-failed")
        return result

    def status(self, project_root: str) -> dict[str, Any]:
        return self._status(project_root, metadata_only=False)

    def maintenance_status(self, project_root: str) -> dict[str, Any]:
        root = _validate_project_root(project_root)
        if not self._allow_metadata_only_status:
            return self.status(root)
        declaration = self._run(("status", "--help")).stdout
        if not declaration.strip():
            raise CodeGraphAdapterError("codegraph-metadata-capability-invalid")
        supported = re.search(r"^\s+--metadata-only(?:\s|$)", declaration, re.MULTILINE) is not None
        return self._status(root, metadata_only=supported)

    def _status(self, project_root: str, *, metadata_only: bool) -> dict[str, Any]:
        root = _validate_project_root(project_root)
        arguments = ("status", root, "--json") + (("--metadata-only",) if metadata_only else ())
        output = self._run(arguments).stdout
        try:
            value = json.loads(output)
        except (TypeError, ValueError):
            raise CodeGraphAdapterError("codegraph-status-invalid") from None
        if not isinstance(value, dict) or type(value.get("initialized")) is not bool:
            raise CodeGraphAdapterError("codegraph-status-invalid")
        if metadata_only and (
            value.get("workingTreeChecked") is not False
            or "pendingChanges" not in value or value["pendingChanges"] is not None
        ):
            raise CodeGraphAdapterError("codegraph-metadata-status-invalid")
        environment = value.get("cppIncludeEnvironment")
        if environment is not None and (
            not isinstance(environment, Mapping)
            or any(type(environment.get(key)) is not bool for key in ("observed", "complete", "changed"))
            or ("affectedFileCount" in environment and not (
                type(environment["affectedFileCount"]) is int and environment["affectedFileCount"] >= 0
            ))
            or not (
                type(environment.get("affectedFileCount")) is int and environment["affectedFileCount"] >= 0
                or isinstance(environment.get("affectedFiles"), list)
            )
        ):
            raise CodeGraphAdapterError("codegraph-status-invalid")
        result = {
            "providerId": "codegraph",
            "operation": "status",
            "readOnly": True,
            "supportStatus": "unverified",
            "initialized": value["initialized"],
            "freshness": _status_freshness(value),
            "projectRootHash": _hash({"projectRoot": root.casefold()}),
        }
        if "cppIncludeEnvironment" in value:
            result["cppIncludeEnvironment"] = None if environment is None else {
                key: environment[key] for key in ("observed", "complete", "changed")
            } | {"affectedFileCount": (
                environment["affectedFileCount"] if type(environment.get("affectedFileCount")) is int
                else len(environment["affectedFiles"])
            )}
        indexing_config = value.get("indexingConfig")
        if isinstance(indexing_config, Mapping) and indexing_config.get("error") is not None:
            result["indexingConfigInvalid"] = True
        index = value.get("index")
        if isinstance(index, Mapping):
            if isinstance(index.get("state"), str) and index["state"]:
                result["indexState"] = index["state"]
            if type(index.get("reindexRecommended")) is bool:
                result["reindexRecommended"] = index["reindexRecommended"]
            if type(index.get("pendingRefs")) is int and index["pendingRefs"] >= 0:
                result["pendingRefs"] = index["pendingRefs"]
        pending = value.get("pendingChanges")
        if "pendingChanges" in value and pending is None:
            result["pendingChanges"] = None
        if type(value.get("workingTreeChecked")) is bool:
            result["workingTreeChecked"] = value["workingTreeChecked"]
        if isinstance(pending, Mapping):
            result["pendingChanges"] = {
                key: pending[key]
                for key in ("added", "modified", "removed")
                if type(pending.get(key)) is int and pending[key] >= 0
            }
        result["worktreeMismatch"] = value.get("worktreeMismatch") is not None
        for key in ("fileCount", "nodeCount", "edgeCount", "dbSizeBytes", "walSizeBytes"):
            if type(value.get(key)) is int and value[key] >= 0:
                result[key] = value[key]
        if isinstance(value.get("version"), str) and value["version"]:
            result["version"] = value["version"]
        if isinstance(value.get("lastIndexed"), str) and value["lastIndexed"]:
            result["lastIndexed"] = value["lastIndexed"]
        return result

    def version(self) -> dict[str, Any]:
        value = self._run(("--version",)).stdout.strip()
        if not value or any(ord(character) < 32 and character not in "\r\n\t" for character in value):
            raise CodeGraphAdapterError("codegraph-version-invalid")
        return {
            "providerId": "codegraph",
            "operation": "version",
            "readOnly": True,
            "supportStatus": "unverified",
            "version": value.splitlines()[0][:256],
        }

    def help(self) -> dict[str, Any]:
        value = self._run(("--help",)).stdout.strip()
        if not value:
            raise CodeGraphAdapterError("codegraph-help-invalid")
        return {
            "providerId": "codegraph",
            "operation": "help",
            "readOnly": True,
            "supportStatus": "unverified",
            "summary": value[:4096],
        }

    def plan_query(self, project_root: str, query: str) -> dict[str, Any]:
        root = _validate_project_root(project_root)
        query_text = _validate_text(query, "codegraph-query-invalid")
        status = self.status(root)
        if not status["initialized"]:
            raise CodeGraphAdapterError("codegraph-project-not-initialized")
        if status["freshness"] != "fresh":
            raise CodeGraphAdapterError("codegraph-project-index-stale")
        plan = _with_hash({
            "schemaVersion": 1,
            "providerId": "codegraph",
            "operation": "query",
            "ownership": self._ownership,
            "projectRootHash": status["projectRootHash"],
            "queryHash": _hash({"query": query_text}),
            "adapterCommandHash": self.command_hash,
            "indexRevision": status.get("revision", "unknown"),
            "readOnly": True,
            "sideEffectClass": "none",
            "supportStatus": "unverified",
            "reasonCode": "codegraph-query-after-ensure",
        })
        return plan

    def query(
        self, project_root: str, query: str, *, query_kind: str = "ask",
    ) -> dict[str, Any]:
        root = _validate_project_root(project_root)
        query_text = _validate_text(query, "codegraph-query-invalid")
        kind = _validate_text(query_kind, "codegraph-query-kind-invalid")
        plan = self.plan_query(root, query_text)
        output = self._run(("explore", query_text, "--path", root)).stdout
        return {
            "providerId": "codegraph",
            "operation": "query",
            "readOnly": True,
            "supportStatus": "unverified",
            "freshness": "fresh",
            "queryKind": kind,
            "queryHash": plan["queryHash"],
            "projectRootHash": plan["projectRootHash"],
            "data": output.strip(),
        }

    def plan_maintenance(
        self, action: str, project_root: str,
    ) -> dict[str, Any]:
        action_value = _validate_text(action, "codegraph-maintenance-action-invalid")
        root = _validate_project_root(project_root)
        if action_value == "upgrade-managed-install" and self._ownership == "user-local":
            raise CodeGraphAdapterError("codegraph-user-owned-upgrade-forbidden")
        if action_value not in _MAINTENANCE_COMMANDS:
            raise CodeGraphAdapterError("codegraph-maintenance-action-invalid")
        plan = _with_hash({
            "schemaVersion": 1,
            "providerId": "codegraph",
            "operation": "maintain",
            "action": action_value,
            "ownership": self._ownership,
            "adapterCommandHash": self.command_hash,
            "projectRootHash": _hash({"projectRoot": root.casefold()}),
            "readOnly": False,
            "sideEffectClass": "local-write",
            "supportStatus": "unverified",
            "reasonCode": "codegraph-maintenance-native-unverified",
        })
        self._issued_maintenance_plans.add(plan["planHash"])
        return plan

    def execute_maintenance(
        self,
        plan: Mapping[str, Any],
        project_root: str,
        *,
        confirmed_plan_hash: str,
    ) -> dict[str, Any]:
        if not isinstance(plan, Mapping):
            raise CodeGraphAdapterError("codegraph-maintenance-plan-invalid")
        supplied = dict(plan)
        plan_hash = supplied.get("planHash")
        if not isinstance(plan_hash, str) or confirmed_plan_hash != plan_hash:
            raise CodeGraphAdapterError("codegraph-maintenance-confirmation-mismatch")
        material = {key: value for key, value in supplied.items() if key != "planHash"}
        if plan_hash != _hash(material):
            raise CodeGraphAdapterError("codegraph-maintenance-plan-tampered")
        if plan_hash in self._consumed_maintenance_plans:
            raise CodeGraphAdapterError("codegraph-maintenance-plan-replayed")
        if plan_hash not in self._issued_maintenance_plans:
            raise CodeGraphAdapterError("codegraph-maintenance-plan-not-issued")
        root = _validate_project_root(project_root)
        expected_material = {
            "schemaVersion": 1,
            "providerId": "codegraph",
            "operation": "maintain",
            "action": supplied.get("action"),
            "ownership": self._ownership,
            "adapterCommandHash": self.command_hash,
            "projectRootHash": _hash({"projectRoot": root.casefold()}),
            "readOnly": False,
            "sideEffectClass": "local-write",
            "supportStatus": "unverified",
            "reasonCode": "codegraph-maintenance-native-unverified",
        }
        if supplied != _with_hash(expected_material):
            raise CodeGraphAdapterError("codegraph-maintenance-plan-tampered")

        command = _MAINTENANCE_COMMANDS[supplied["action"]]
        if supplied["action"] == "rebuild":
            arguments = command[:1] + (root,) + command[1:]
        else:
            arguments = command + (root,)
        self._run(arguments)
        self._issued_maintenance_plans.discard(plan_hash)
        self._consumed_maintenance_plans.add(plan_hash)
        return {
            "providerId": "codegraph",
            "operation": "maintain",
            "action": supplied["action"],
            "status": "succeeded",
            "planHash": plan_hash,
            "supportStatus": "unverified",
        }
