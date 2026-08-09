"""Machine-local Provider configuration and maintenance transaction core."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
import uuid

from selfworkflow.v3.providers.codegraph import (
    CodeGraphAdapter,
    CodeGraphAdapterError,
    CommandPort,
)
from selfworkflow.v3.provider_config import (
    ProviderConfigError,
    load_provider_config,
    validate_provider_source_path,
)


_MAX_CONFIG_BYTES = 1024 * 1024
_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_PROVIDER_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")


class ProviderManagerError(ValueError):
    """Stable manager error which never embeds paths, command output, or secrets."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class MachineLocalPaths:
    """Host-selected machine-local locations; constructing this does no discovery."""

    config_file: Path

    def __post_init__(self) -> None:
        value = Path(self.config_file)
        if not value.is_absolute():
            raise ProviderManagerError("provider-machine-path-not-absolute")
        object.__setattr__(self, "config_file", value)

    @property
    def backup_file(self) -> Path:
        return self.config_file.with_suffix(self.config_file.suffix + ".bak")


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
        raise ProviderManagerError("provider-config-invalid") from None


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _clean_text(value: object, reason: str, *, maximum: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise ProviderManagerError(reason)
    return value


def _validate_command_prefix(value: object) -> tuple[str, ...]:
    if (
        not isinstance(value, (tuple, list))
        or not value
        or len(value) > 16
        or any(
            not isinstance(item, str)
            or not item
            or item != item.strip()
            or len(item) > 4096
            or any(ord(character) < 32 for character in item)
            for item in value
        )
    ):
        raise ProviderManagerError("provider-command-prefix-invalid")
    return tuple(value)


class ProviderManager:
    """Manage explicit machine-local Provider overrides without disk scanning."""

    def __init__(
        self,
        *,
        paths: MachineLocalPaths,
        command_port: CommandPort,
        source_identity_resolver: Callable[[str], Mapping[str, Any]],
        logger: Callable[[str, Mapping[str, Any]], None] | None = None,
        replace_operation: Callable[[str | Path, str | Path], object] = os.replace,
    ) -> None:
        if type(paths) is not MachineLocalPaths:
            raise ProviderManagerError("provider-machine-paths-invalid")
        if not callable(getattr(command_port, "run", None)):
            raise ProviderManagerError("provider-command-port-invalid")
        if not callable(source_identity_resolver):
            raise ProviderManagerError("provider-source-identity-resolver-invalid")
        if logger is not None and not callable(logger):
            raise ProviderManagerError("provider-logger-invalid")
        if not callable(replace_operation):
            raise ProviderManagerError("provider-replace-operation-invalid")
        self._paths = paths
        self._command_port = command_port
        self._source_identity_resolver = source_identity_resolver
        self._logger = logger
        self._replace = replace_operation
        self._adapter_cache: dict[str, tuple[str, CodeGraphAdapter]] = {}

    def _log(self, event: str, **fields: object) -> None:
        if self._logger is None:
            return
        safe = {
            key: value
            for key, value in fields.items()
            if key in {
                "providerId", "operation", "status", "reasonCode",
                "planHash", "configurationHash",
            }
            and isinstance(value, (str, int, bool))
        }
        try:
            self._logger(event, safe)
        except Exception:
            return

    @staticmethod
    def _empty_config() -> dict[str, Any]:
        return {"schemaVersion": 3, "providers": []}

    @staticmethod
    def _validate_config(value: object) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) != {"schemaVersion", "providers"}:
            raise ProviderManagerError("provider-config-invalid")
        if value.get("schemaVersion") != 3 or not isinstance(value.get("providers"), list):
            raise ProviderManagerError("provider-config-invalid")
        provider_ids: set[str] = set()
        for provider in value["providers"]:
            provider_id = provider.get("providerId") if isinstance(provider, dict) else None
            if (
                not isinstance(provider_id, str)
                or _PROVIDER_ID.fullmatch(provider_id) is None
                or provider_id in provider_ids
                or not isinstance(provider, dict)
                or not {"providerId", "sourcePath", "enabled"} <= set(provider)
            ):
                raise ProviderManagerError("provider-config-invalid")
            provider_ids.add(provider_id)
            managed_fields = {
                "ownership", "commandPrefix", "commandHash", "source", "bindingHash",
            }
            present = managed_fields & set(provider)
            if present and present != managed_fields:
                raise ProviderManagerError("provider-config-invalid")
            if not present:
                continue
            if provider.get("ownership") not in {"user-local", "selfworkflow-managed"}:
                raise ProviderManagerError("provider-config-invalid")
            prefix = _validate_command_prefix(provider.get("commandPrefix"))
            if provider.get("commandHash") != _hash({"argv": list(prefix)}):
                raise ProviderManagerError("provider-config-command-hash-invalid")
            source = provider.get("source")
            if (
                not isinstance(source, dict)
                or set(source) != {"kind", "version", "commit", "sourceHash", "dirty"}
                or source.get("kind") != "local-override"
                or not isinstance(source.get("version"), str)
                or not source["version"]
                or not isinstance(source.get("commit"), str)
                or re.fullmatch(r"[0-9a-f]{40}", source["commit"]) is None
                or not isinstance(source.get("sourceHash"), str)
                or _HASH.fullmatch(source["sourceHash"]) is None
                or type(source.get("dirty")) is not bool
            ):
                raise ProviderManagerError("provider-config-source-invalid")
            binding_material = {
                key: item for key, item in provider.items() if key != "bindingHash"
            }
            if provider.get("bindingHash") != _hash(binding_material):
                raise ProviderManagerError("provider-config-binding-hash-invalid")
        return json.loads(_canonical_bytes(value))

    def _read_config(self) -> dict[str, Any]:
        path = self._paths.config_file
        if not path.exists():
            return self._empty_config()
        if path.is_symlink() or not path.is_file():
            raise ProviderManagerError("provider-config-path-unsafe")
        try:
            if path.stat().st_size > _MAX_CONFIG_BYTES:
                raise ProviderManagerError("provider-config-too-large")
            value = load_provider_config(path=path, root=path.parent)
        except ProviderManagerError:
            raise
        except (OSError, UnicodeError, ValueError, ProviderConfigError):
            raise ProviderManagerError("provider-config-read-failed") from None
        return self._validate_config(value)

    @staticmethod
    def _write_temp(path: Path, payload: bytes) -> Path:
        temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            return temporary
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise ProviderManagerError("provider-config-write-failed") from None

    def _replace_payload(self, target: Path, payload: bytes) -> None:
        temporary = self._write_temp(target, payload)
        try:
            self._replace(temporary, target)
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _write_config(self, config: Mapping[str, Any]) -> bool:
        path = self._paths.config_file
        payload = _canonical_bytes(config) + b"\n"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_symlink() or path.parent.is_symlink():
                raise ProviderManagerError("provider-config-path-unsafe")
            previous = path.read_bytes() if path.exists() else None
            if previous == payload:
                return False
            if previous is not None:
                self._replace_payload(self._paths.backup_file, previous)
            try:
                self._replace_payload(path, payload)
            except Exception:
                if previous is not None:
                    current = path.read_bytes() if path.exists() else None
                    if current != previous:
                        self._replace_payload(path, previous)
                elif path.exists():
                    path.unlink()
                raise
            return True
        except ProviderManagerError:
            raise
        except Exception:
            raise ProviderManagerError("provider-config-write-failed") from None

    def list_providers(self) -> dict[str, Any]:
        config = self._read_config()
        providers = []
        for item in sorted(config["providers"], key=lambda value: value["providerId"]):
            result = {
                "providerId": item["providerId"],
                "enabled": item["enabled"],
                "managementStatus": (
                    "managed-metadata-available" if "bindingHash" in item
                    else "routing-only"
                ),
            }
            if "bindingHash" in item:
                result.update({
                    "ownership": item["ownership"],
                    "commandHash": item["commandHash"],
                    "source": dict(item["source"]),
                    "bindingHash": item["bindingHash"],
                })
            providers.append(result)
        return {"providers": providers}

    def configure(
        self,
        *,
        provider_id: str,
        source_path: str,
        command_prefix: Sequence[str],
        ownership: str,
        source_version: str,
        source_commit: str,
        source_hash: str,
        dirty: bool,
        replace_existing: bool = False,
    ) -> dict[str, Any]:
        try:
            if provider_id != "codegraph":
                raise ProviderManagerError("provider-not-supported")
            if ownership != "user-local":
                raise ProviderManagerError("provider-local-override-ownership-invalid")
            prefix = _validate_command_prefix(command_prefix)
            version = _clean_text(source_version, "provider-source-version-invalid")
            commit = _clean_text(source_commit, "provider-source-commit-invalid")
            if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
                raise ProviderManagerError("provider-source-commit-invalid")
            if not isinstance(source_hash, str) or _HASH.fullmatch(source_hash) is None:
                raise ProviderManagerError("provider-source-hash-invalid")
            if type(dirty) is not bool:
                raise ProviderManagerError("provider-source-dirty-invalid")
            source = {
                "kind": "local-override",
                "version": version,
                "commit": commit,
                "sourceHash": source_hash,
                "dirty": dirty,
            }
            try:
                validated_source_path = validate_provider_source_path(source_path)
            except ProviderConfigError:
                raise ProviderManagerError("provider-source-path-invalid") from None
            provider = {
                "providerId": provider_id,
                "sourcePath": validated_source_path,
                "enabled": True,
                "ownership": ownership,
                "commandPrefix": list(prefix),
                "commandHash": _hash({"argv": list(prefix)}),
                "source": source,
            }
            provider["bindingHash"] = _hash(provider)
            config = self._read_config()
            existing = next(
                (item for item in config["providers"] if item["providerId"] == provider_id),
                None,
            )
            if (
                existing is not None
                and existing != provider
                and replace_existing is not True
            ):
                raise ProviderManagerError("provider-config-conflict")
            config["providers"] = [
                item for item in config["providers"]
                if item["providerId"] != provider_id
            ] + [provider]
            config["providers"].sort(key=lambda item: item["providerId"])
            self._validate_config(config)
            changed = self._write_config(config)
            if changed:
                self._adapter_cache.pop(provider_id, None)
            status = "configured" if changed else "unchanged"
            self._log(
                "provider.configure.completed",
                providerId=provider_id,
                operation="configure",
                status=status,
                configurationHash=_hash(config),
            )
            return {
                "providerId": provider_id,
                "status": status,
                "configurationHash": _hash(config),
                "bindingHash": provider["bindingHash"],
            }
        except ProviderManagerError as error:
            self._log(
                "provider.configure.failed",
                providerId=provider_id if isinstance(provider_id, str) else "invalid",
                operation="configure",
                status="failed",
                reasonCode=error.reason,
            )
            raise

    def _assert_source_identity(self, provider: Mapping[str, Any]) -> None:
        try:
            observation = self._source_identity_resolver(provider["sourcePath"])
            if not isinstance(observation, Mapping):
                raise ProviderManagerError("provider-source-identity-drift")
            report = observation.get("report")
            observed_source = observation.get("source")
            if not isinstance(report, Mapping) or observed_source is None:
                raise ProviderManagerError("provider-source-identity-drift")
            observed_path = validate_provider_source_path(str(observed_source))
            expected = provider["source"]
            if (
                observed_path != provider["sourcePath"]
                or report.get("commit") != expected["commit"]
                or report.get("sourceHash") != expected["sourceHash"]
                or report.get("dirty") is not expected["dirty"]
            ):
                raise ProviderManagerError("provider-source-identity-drift")
        except ProviderManagerError:
            raise
        except Exception:
            raise ProviderManagerError("provider-source-identity-drift") from None

    def _adapter(self, provider_id: str) -> CodeGraphAdapter:
        if provider_id != "codegraph":
            raise ProviderManagerError("provider-not-supported")
        config = self._read_config()
        provider = next(
            (item for item in config["providers"] if item["providerId"] == provider_id),
            None,
        )
        if provider is None:
            raise ProviderManagerError("provider-not-configured")
        if "bindingHash" not in provider:
            raise ProviderManagerError("provider-adapter-unavailable")
        self._assert_source_identity(provider)
        cached = self._adapter_cache.get(provider_id)
        if cached is not None and cached[0] == provider["bindingHash"]:
            return cached[1]
        try:
            adapter = CodeGraphAdapter(
                command_port=self._command_port,
                command_prefix=tuple(provider["commandPrefix"]),
                ownership=provider["ownership"],
                pre_dispatch_validator=lambda: self._assert_source_identity(provider),
            )
            self._adapter_cache[provider_id] = (provider["bindingHash"], adapter)
            return adapter
        except CodeGraphAdapterError:
            raise ProviderManagerError("provider-adapter-invalid") from None

    def doctor(self, provider_id: str) -> dict[str, Any]:
        try:
            adapter = self._adapter(provider_id)
            version = adapter.version()
            help_result = adapter.help()
            result = {
                "providerId": provider_id,
                "operation": "doctor",
                "status": "healthy",
                "readOnly": True,
                "supportStatus": "unverified",
                "version": version["version"],
                "helpAvailable": bool(help_result["summary"]),
                "commandHash": adapter.command_hash,
            }
            self._log(
                "provider.doctor.completed", providerId=provider_id,
                operation="doctor", status="healthy",
            )
            return result
        except (CodeGraphAdapterError, ProviderManagerError):
            self._log(
                "provider.doctor.failed", providerId=provider_id,
                operation="doctor", status="failed",
                reasonCode="provider-operation-failed",
            )
            raise ProviderManagerError("provider-operation-failed") from None

    def status(self, provider_id: str, project_root: str) -> dict[str, Any]:
        try:
            result = self._adapter(provider_id).status(project_root)
            self._log(
                "provider.status.completed", providerId=provider_id,
                operation="status", status="succeeded",
            )
            return result
        except (CodeGraphAdapterError, ProviderManagerError):
            self._log(
                "provider.status.failed", providerId=provider_id,
                operation="status", status="failed",
                reasonCode="provider-operation-failed",
            )
            raise ProviderManagerError("provider-operation-failed") from None

    def maintain(
        self,
        provider_id: str,
        action: str,
        project_root: str,
        *,
        plan_only: bool,
        confirmed_plan_hash: str | None = None,
    ) -> dict[str, Any]:
        if provider_id != "codegraph":
            raise ProviderManagerError("provider-not-supported")
        if not plan_only:
            raise ProviderManagerError("provider-maintenance-apply-unverified")
        adapter = self._adapter(provider_id)
        if action == "upgrade-managed-install" and adapter.ownership == "user-local":
            raise ProviderManagerError("provider-user-owned-upgrade-forbidden")
        try:
            plan = adapter.plan_maintenance(action, project_root)
        except CodeGraphAdapterError as error:
            reason = (
                "provider-user-owned-upgrade-forbidden"
                if error.reason == "codegraph-user-owned-upgrade-forbidden"
                else "provider-maintenance-plan-invalid"
            )
            raise ProviderManagerError(reason) from None
        self._log(
            "provider.maintain.planned", providerId=provider_id,
            operation="maintain", status="planned", planHash=plan["planHash"],
        )
        return plan
