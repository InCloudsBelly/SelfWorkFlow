"""Fail-closed CodeGraph CLI adapter using an injected command port only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import ntpath
from typing import Any, Callable, Protocol


_MAX_OUTPUT_BYTES = 1024 * 1024
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


class CodeGraphAdapter:
    """Render fixed CodeGraph commands and delegate execution to the Host."""

    def __init__(
        self,
        *,
        command_port: CommandPort,
        command_prefix: Sequence[str],
        ownership: str,
        pre_dispatch_validator: Callable[[], None] | None = None,
    ) -> None:
        if not callable(getattr(command_port, "run", None)):
            raise CodeGraphAdapterError("codegraph-command-port-invalid")
        if ownership not in {"user-local", "selfworkflow-managed"}:
            raise CodeGraphAdapterError("codegraph-ownership-invalid")
        if pre_dispatch_validator is not None and not callable(pre_dispatch_validator):
            raise CodeGraphAdapterError("codegraph-source-validator-invalid")
        self._port = command_port
        self._prefix = _validate_prefix(command_prefix)
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
            raise CodeGraphAdapterError("codegraph-command-failed")
        return result

    def status(self, project_root: str) -> dict[str, Any]:
        root = _validate_project_root(project_root)
        output = self._run(("status", root, "--json")).stdout
        try:
            value = json.loads(output)
        except (TypeError, ValueError):
            raise CodeGraphAdapterError("codegraph-status-invalid") from None
        if not isinstance(value, dict) or type(value.get("initialized")) is not bool:
            raise CodeGraphAdapterError("codegraph-status-invalid")
        result = {
            "providerId": "codegraph",
            "operation": "status",
            "readOnly": True,
            "supportStatus": "unverified",
            "initialized": value["initialized"],
            "projectRootHash": _hash({"projectRoot": root.casefold()}),
        }
        if isinstance(value.get("revision"), str) and value["revision"]:
            result["revision"] = value["revision"]
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
        plan = _with_hash({
            "schemaVersion": 1,
            "providerId": "codegraph",
            "operation": "query",
            "ownership": self._ownership,
            "projectRootHash": status["projectRootHash"],
            "queryHash": _hash({"query": query_text}),
            "adapterCommandHash": self.command_hash,
            "indexRevision": status.get("revision", "unknown"),
            "readOnly": False,
            "sideEffectClass": "potential-local-write",
            "supportStatus": "unverified",
            "reasonCode": "codegraph-query-no-no-sync",
        })
        return plan

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
            arguments = command[:1] + (root,) + command[1:] + ("--json",)
        else:
            arguments = command + (root, "--json")
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
