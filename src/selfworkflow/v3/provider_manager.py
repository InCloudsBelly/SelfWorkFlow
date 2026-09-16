"""Machine-local Provider configuration and maintenance transaction core."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import base64
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
from selfworkflow.v3.providers.graft import GraftAdapter, GraftAdapterError
from selfworkflow.v3.provider_config import (
    ProviderConfigError,
    load_provider_config,
    validate_provider_source_path,
)


_MAX_CONFIG_BYTES = 1024 * 1024
_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_PROVIDER_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_HOST_MODEL_ENV = "SELFWORKFLOW_HOST_CURRENT_MODEL"
_HOST_REASONING_ENV = "SELFWORKFLOW_HOST_CURRENT_REASONING_EFFORT"


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

    @property
    def lock_file(self) -> Path:
        return self.config_file.with_suffix(self.config_file.suffix + ".lock")

    @property
    def transaction_directory(self) -> Path:
        return self.config_file.parent / ".provider-transactions"


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


def _payload_hash(value: bytes | None) -> str:
    return "missing" if value is None else "sha256:" + hashlib.sha256(value).hexdigest()


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


def _current_graft_deep_model_context() -> tuple[str, str]:
    """Read the active Host model for this one worker invocation only."""

    model = os.environ.get(_HOST_MODEL_ENV)
    reasoning_effort = os.environ.get(_HOST_REASONING_ENV)
    if (
        not isinstance(model, str) or not model.strip()
        or not isinstance(reasoning_effort, str) or not reasoning_effort.strip()
    ):
        raise ProviderManagerError("graft-deep-current-model-unavailable")
    if (
        model != model.strip() or reasoning_effort != reasoning_effort.strip()
        or any(ord(character) < 32 for character in model + reasoning_effort)
    ):
        raise ProviderManagerError("graft-deep-current-model-context-incomplete")
    return model, reasoning_effort


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
        self._adapter_cache: dict[str, tuple[str, object]] = {}

    @contextmanager
    def _config_lock(self):
        path = self._paths.lock_file
        handle = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(path, "a+b")
            if path.stat().st_size == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            try:
                if handle is not None:
                    handle.close()
            except Exception:
                pass
            raise ProviderManagerError("provider-config-locked") from None
        try:
            yield
        finally:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

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
                or source.get("kind") not in {"local-override", "managed-submodule"}
                or (
                    provider_id == "graft"
                    and source.get("kind") != "managed-submodule"
                )
                or (
                    provider_id != "graft"
                    and source.get("kind") != "local-override"
                )
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

    @staticmethod
    def _validate_rollback_token(value: object) -> str:
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{32}", value) is None:
            raise ProviderManagerError("provider-config-rollback-invalid")
        return value

    def _transaction_path(self, token: str) -> Path:
        return self._paths.transaction_directory / f"{token}.json"

    def _config_path_hash(self) -> str:
        canonical = os.path.normcase(str(self._paths.config_file.resolve(strict=False)))
        return _hash({"configPath": canonical})

    def _restore_config_preimage(self, preimage: bytes | None) -> None:
        try:
            if preimage is None:
                self._paths.config_file.unlink(missing_ok=True)
            else:
                self._replace_payload(self._paths.config_file, preimage)
        except Exception:
            raise ProviderManagerError("provider-config-rollback-failed") from None

    def _write_rollback_transaction(
        self, token: str, preimage: bytes | None, postimage: bytes,
    ) -> None:
        path = self._transaction_path(token)
        if path.exists():
            raise ProviderManagerError("provider-config-rollback-invalid")
        transaction = {
            "schemaVersion": 1,
            "rollbackToken": token,
            "configPathHash": self._config_path_hash(),
            "state": "prepared",
            "preimage": (
                None if preimage is None
                else base64.b64encode(preimage).decode("ascii")
            ),
            "preimageHash": _payload_hash(preimage),
            "postimageHash": _payload_hash(postimage),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.parent.is_symlink() or path.is_symlink():
                raise OSError
            self._replace_payload(path, _canonical_bytes(transaction) + b"\n")
        except Exception:
            raise ProviderManagerError("provider-config-transaction-write-failed") from None

    def _set_rollback_transaction_state(self, token: str, state: str) -> None:
        if state not in {"applied", "rolled-back"}:
            raise ProviderManagerError("provider-config-transaction-write-failed")
        loaded = self._read_rollback_transaction(token)
        if loaded is None:
            raise ProviderManagerError("provider-config-transaction-write-failed")
        path, transaction = loaded
        transaction["state"] = state
        try:
            self._replace_payload(path, _canonical_bytes(transaction) + b"\n")
        except Exception:
            raise ProviderManagerError("provider-config-transaction-write-failed") from None

    def _read_rollback_transaction(
        self, token: str, *, if_issued: bool = False,
        verify_postimage: bool = False,
    ) -> tuple[Path, dict[str, Any]] | None:
        path = self._transaction_path(token)
        if not path.exists():
            if if_issued:
                return None
            raise ProviderManagerError("provider-config-rollback-invalid")
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_CONFIG_BYTES * 2:
                raise ValueError
            transaction = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(transaction, dict)
                or set(transaction) != {
                    "schemaVersion", "rollbackToken", "configPathHash",
                    "state", "preimage", "preimageHash", "postimageHash",
                }
                or transaction["schemaVersion"] != 1
                or transaction["rollbackToken"] != token
                or transaction["configPathHash"] != self._config_path_hash()
                or transaction["state"] not in {"prepared", "applied", "rolled-back"}
                or not isinstance(transaction["preimageHash"], str)
                or not (
                    transaction["preimageHash"] == "missing"
                    or _HASH.fullmatch(transaction["preimageHash"]) is not None
                )
                or not isinstance(transaction["postimageHash"], str)
                or _HASH.fullmatch(transaction["postimageHash"]) is None
                or not (
                    transaction["preimage"] is None
                    or isinstance(transaction["preimage"], str)
                )
            ):
                raise ProviderManagerError("provider-config-rollback-invalid")
            try:
                encoded = transaction["preimage"]
                preimage = None if encoded is None else base64.b64decode(
                    encoded, validate=True,
                )
            except Exception:
                raise ProviderManagerError("provider-config-rollback-invalid") from None
            if transaction["preimageHash"] != _payload_hash(preimage):
                raise ProviderManagerError("provider-config-rollback-invalid")
            if verify_postimage and transaction["postimageHash"] != _payload_hash(
                self._paths.config_file.read_bytes()
                if self._paths.config_file.exists() else None
            ):
                raise ProviderManagerError("provider-config-rollback-state-drift")
            return path, transaction
        except ProviderManagerError:
            raise
        except Exception:
            raise ProviderManagerError("provider-config-rollback-invalid") from None

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
        rollback_token: str | None = None,
    ) -> dict[str, Any]:
        try:
            if provider_id not in {"codegraph", "graft"}:
                raise ProviderManagerError("provider-not-supported")
            expected_ownership = {
                "codegraph": "user-local",
                "graft": "selfworkflow-managed",
            }[provider_id]
            if ownership != expected_ownership:
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
                "kind": "managed-submodule" if provider_id == "graft" else "local-override",
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
            token = (
                self._validate_rollback_token(rollback_token)
                if rollback_token is not None else None
            )
            with self._config_lock():
                preimage = (
                    self._paths.config_file.read_bytes()
                    if self._paths.config_file.exists() else None
                )
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
                if token is not None:
                    postimage = _canonical_bytes(config) + b"\n"
                    self._write_rollback_transaction(token, preimage, postimage)
                try:
                    changed = self._write_config(config)
                    if token is not None:
                        self._set_rollback_transaction_state(token, "applied")
                except BaseException as failure:
                    self._restore_config_preimage(preimage)
                    if token is not None:
                        try:
                            self._set_rollback_transaction_state(
                                token, "rolled-back",
                            )
                        except ProviderManagerError:
                            pass
                    if not isinstance(failure, Exception):
                        raise
                    raise
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
            result = {
                "providerId": provider_id,
                "status": status,
                "configurationHash": _hash(config),
                "bindingHash": provider["bindingHash"],
            }
            if token is not None:
                result["rollbackToken"] = token
            return result
        except ProviderManagerError as error:
            self._log(
                "provider.configure.failed",
                providerId=provider_id if isinstance(provider_id, str) else "invalid",
                operation="configure",
                status="failed",
                reasonCode=error.reason,
            )
            raise

    def rollback_config(
        self, rollback_token: str, *, if_issued: bool = False,
    ) -> dict[str, Any]:
        token = self._validate_rollback_token(rollback_token)
        with self._config_lock():
            loaded = self._read_rollback_transaction(
                token, if_issued=if_issued,
            )
            if loaded is None:
                return {"status": "not-issued"}
            path, transaction = loaded
            if transaction["state"] == "rolled-back" and if_issued:
                return {"status": "already-rolled-back"}
            try:
                encoded = transaction["preimage"]
                preimage = None if encoded is None else base64.b64decode(
                    encoded, validate=True,
                )
                if preimage is not None and len(preimage) > _MAX_CONFIG_BYTES:
                    raise ValueError
            except Exception:
                raise ProviderManagerError("provider-config-rollback-invalid") from None
            current = _payload_hash(
                self._paths.config_file.read_bytes()
                if self._paths.config_file.exists() else None
            )
            if transaction["state"] == "rolled-back":
                raise ProviderManagerError("provider-config-rollback-invalid")
            if current == transaction["postimageHash"]:
                self._restore_config_preimage(preimage)
            elif current != transaction["preimageHash"]:
                raise ProviderManagerError("provider-config-rollback-state-drift")
            try:
                path.unlink()
            except OSError:
                raise ProviderManagerError("provider-config-rollback-failed") from None
        return {"status": "rolled-back"}

    def commit_config(self, rollback_token: str) -> dict[str, Any]:
        token = self._validate_rollback_token(rollback_token)
        with self._config_lock():
            loaded = self._read_rollback_transaction(token)
            if loaded is None:
                raise ProviderManagerError("provider-config-rollback-invalid")
            path, transaction = loaded
            if transaction["state"] != "applied":
                raise ProviderManagerError("provider-config-rollback-invalid")
            try:
                path.unlink()
            except OSError:
                raise ProviderManagerError("provider-config-commit-failed") from None
        return {"status": "committed"}

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

    def _adapter(self, provider_id: str) -> object:
        if provider_id not in {"codegraph", "graft"}:
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
            adapter_type = GraftAdapter if provider_id == "graft" else CodeGraphAdapter
            adapter = adapter_type(
                command_port=self._command_port,
                command_prefix=tuple(provider["commandPrefix"]),
                ownership=provider["ownership"],
                pre_dispatch_validator=lambda: self._assert_source_identity(provider),
            )
            self._adapter_cache[provider_id] = (provider["bindingHash"], adapter)
            return adapter
        except (CodeGraphAdapterError, GraftAdapterError):
            raise ProviderManagerError("provider-adapter-invalid") from None

    def doctor(self, provider_id: str) -> dict[str, Any]:
        self._log(
            "provider.doctor.failed", providerId=provider_id,
            operation="doctor", status="failed",
            reasonCode="provider-operation-unverified",
        )
        raise ProviderManagerError("provider-operation-unverified")

    def status(
        self, provider_id: str, project_root: str, *,
        context_dir: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        if provider_id == "graft":
            try:
                from selfworkflow.v3.graft_lifecycle import (
                    GraftProjectError, GraftProjectLifecycle,
                )
                return GraftProjectLifecycle(self._adapter(provider_id)).query_status(
                    project_root, context_dir=context_dir,
                    conversation_id=conversation_id,
                )
            except (
                GraftAdapterError, GraftProjectError, ProviderManagerError,
            ) as error:
                self._log(
                    "provider.status.failed", providerId=provider_id,
                    operation="status", status="failed", reasonCode=error.reason,
                )
                raise ProviderManagerError(error.reason) from None
        self._log(
            "provider.status.failed", providerId=provider_id,
            operation="status", status="failed",
            reasonCode="provider-operation-unverified",
        )
        raise ProviderManagerError("provider-operation-unverified")

    def query(
        self, provider_id: str, project_root: str, query: str, *, query_kind: str,
        context_dir: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        if provider_id != "graft":
            raise ProviderManagerError("provider-not-supported")
        try:
            from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle
            return GraftProjectLifecycle(self._adapter(provider_id)).query(
                project_root, query, query_kind=query_kind,
                context_dir=context_dir,
                conversation_id=conversation_id,
            )
        except (GraftAdapterError, ProviderManagerError) as error:
            raise ProviderManagerError(error.reason) from None
        except Exception as error:
            reason = getattr(error, "reason", "graft-query-failed")
            raise ProviderManagerError(reason) from None

    def graft_preflight(self, project_root: str) -> dict[str, Any]:
        if "graft" not in {item["providerId"] for item in self._read_config()["providers"]}:
            raise ProviderManagerError("provider-not-configured")
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle
        return GraftProjectLifecycle(self._adapter("graft")).preflight(project_root)

    def graft_topics(
        self, project_root: str, conversation_id: str,
    ) -> dict[str, Any]:
        """List local Deep Topics and the current conversation choice."""

        try:
            from selfworkflow.v3.graft_lifecycle import conversation_topic_options
            return {
                "providerId": "graft",
                **conversation_topic_options(project_root, conversation_id),
            }
        except Exception as error:
            reason = getattr(error, "reason", "graft-topic-discovery-failed")
            raise ProviderManagerError(reason) from None

    def graft_topic_select(
        self, project_root: str, conversation_id: str, *,
        topic_id: str | None = None, disable: bool = False,
    ) -> dict[str, Any]:
        """Persist an explicit user choice without running Graft."""

        if (topic_id is None) == (not disable):
            raise ProviderManagerError("graft-topic-choice-invalid")
        try:
            from selfworkflow.v3.graft_lifecycle import (
                choose_conversation_topic, disable_conversation_graft,
            )
            choice = (
                disable_conversation_graft(project_root, conversation_id)
                if disable else choose_conversation_topic(
                    project_root, conversation_id, topic_id,  # type: ignore[arg-type]
                )
            )
            return {
                "providerId": "graft",
                "status": "disabled" if disable else "bound",
                "conversationId": conversation_id,
                "topicId": None if disable else topic_id,
                "choice": choice,
            }
        except Exception as error:
            reason = getattr(error, "reason", "graft-topic-choice-failed")
            raise ProviderManagerError(reason) from None

    def graft_enqueue(
        self, project_root: str, changed_paths: Sequence[str],
    ) -> dict[str, Any]:
        if "graft" not in {item["providerId"] for item in self._read_config()["providers"]}:
            raise ProviderManagerError("provider-not-configured")
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle
        return GraftProjectLifecycle(self._adapter("graft")).enqueue(
            project_root, changed_paths,
        )

    @staticmethod
    def _topic_refresh_failure(
        result: Mapping[str, Any], reason: str, *, deep: object = None,
    ) -> dict[str, Any]:
        """Keep the global result usable while making Topic freshness explicit."""

        failure = dict(result)
        failure.update({
            "status": "partial",
            "topicUpdated": False,
            "topicFreshness": "unverified",
            "retryable": True,
            "completionEligible": False,
            "nextAction": "retry-topic-deep",
            "reason": reason,
        })
        if deep is not None:
            failure["topicDeep"] = deep
        return failure

    def _refresh_bound_topic_after_worker(
        self, project_root: str, result: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Continue one write-triggered worker run into its bound Topic Deep."""

        output = dict(result)
        if output.get("status") not in {"succeeded", "partial"}:
            return output
        topic_refresh = output.get("topicRefresh")
        if not isinstance(topic_refresh, Mapping):
            return self._topic_refresh_failure(
                output, "graft-topic-refresh-result-missing",
            )
        action = output.get("nextAction")
        if action != "run-graft-deep":
            if action == "stop":
                reason = topic_refresh.get("reason")
                return self._topic_refresh_failure(
                    output,
                    reason if isinstance(reason, str) else "graft-topic-refresh-unverified",
                )
            if action in {"none", "topic-selection-required", "retry-global-map"}:
                output.update({
                    "topicUpdated": topic_refresh.get("status") == "fresh",
                    "completionEligible": action != "retry-global-map",
                })
                return output
            return self._topic_refresh_failure(
                output, "graft-topic-refresh-action-invalid",
            )
        topic_id = topic_refresh.get("topicId")
        if not isinstance(topic_id, str) or not topic_id:
            return self._topic_refresh_failure(
                output, "graft-topic-refresh-topic-invalid",
            )
        try:
            model, reasoning_effort = _current_graft_deep_model_context()
            deep = self.graft_deep(
                project_root, model, reasoning_effort,
                conversation_id=str(output["conversationId"]),
                topic_id=topic_id,
                scope_files=(),
            )
        except ProviderManagerError as error:
            return self._topic_refresh_failure(output, error.reason)
        except Exception:
            return self._topic_refresh_failure(output, "graft-topic-deep-failed")
        if not isinstance(deep, Mapping) or deep.get("status") != "succeeded":
            return self._topic_refresh_failure(
                output, "graft-topic-deep-failed", deep=deep,
            )
        try:
            topic_status = self.status(
                "graft", project_root,
                conversation_id=str(output["conversationId"]),
            )
        except ProviderManagerError as error:
            return self._topic_refresh_failure(
                output, error.reason, deep=deep,
            )
        topic_fresh = (
            isinstance(topic_status, Mapping)
            and topic_status.get("freshness") == "fresh"
            and topic_status.get("graphStatus") == "fresh"
            and topic_status.get("topicFreshness") == "fresh"
        )
        if not topic_fresh:
            return self._topic_refresh_failure(
                output, "graft-freshness-verification-failed", deep=deep,
            )
        global_map_failed = (
            isinstance(output.get("globalMap"), Mapping)
            and output["globalMap"].get("status") == "failed"
        )
        output.update({
            "topicUpdated": True,
            "topicFreshness": "fresh",
            "topicDeep": dict(deep),
            "nextAction": "retry-global-map" if global_map_failed else "none",
            "completionEligible": not global_map_failed,
        })
        return output

    def graft_worker(
        self, project_root: str, *, conversation_id: str,
    ) -> dict[str, Any]:
        if "graft" not in {item["providerId"] for item in self._read_config()["providers"]}:
            raise ProviderManagerError("provider-not-configured")
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle
        result = GraftProjectLifecycle(self._adapter("graft")).run_once(
            project_root, conversation_id=conversation_id,
        )
        if not isinstance(result, Mapping):
            raise ProviderManagerError("graft-worker-result-invalid")
        return self._refresh_bound_topic_after_worker(project_root, result)

    def graft_deep(
        self,
        project_root: str,
        model: str,
        reasoning_effort: str,
        *,
        conversation_id: str,
        topic_id: str | None,
        scope_files: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Run one scoped official Graft Deep build through the current model."""

        if "graft" not in {item["providerId"] for item in self._read_config()["providers"]}:
            raise ProviderManagerError("provider-not-configured")
        try:
            from selfworkflow.v3.graft_codex_bridge import run_codex_graft_deep

            adapter = self._adapter("graft")
            command = getattr(adapter, "command_prefix", None)
            if not isinstance(command, tuple):
                raise ProviderManagerError("provider-adapter-unavailable")
            return run_codex_graft_deep(
                graft_command=command,
                project_root=project_root,
                model=model,
                reasoning_effort=reasoning_effort,
                conversation_id=conversation_id,
                topic_id=topic_id,
                scope_files=scope_files,
            )
        except ProviderManagerError:
            raise
        except Exception as error:
            reason = getattr(error, "reason", "graft-deep-failed")
            raise ProviderManagerError(reason) from None

    def maintain(
        self,
        provider_id: str,
        action: str,
        project_root: str,
        *,
        plan_only: bool,
        confirmed_plan_hash: str | None = None,
    ) -> dict[str, Any]:
        if provider_id not in {"codegraph", "graft"}:
            raise ProviderManagerError("provider-not-supported")
        if provider_id == "codegraph" and not plan_only:
            raise ProviderManagerError("provider-maintenance-apply-unverified")
        adapter = self._adapter(provider_id)
        if action == "upgrade-managed-install" and adapter.ownership == "user-local":  # type: ignore[union-attr]
            raise ProviderManagerError("provider-user-owned-upgrade-forbidden")
        try:
            plan = adapter.plan_maintenance(action, project_root)  # type: ignore[union-attr]
        except (CodeGraphAdapterError, GraftAdapterError) as error:
            reason = (
                "provider-user-owned-upgrade-forbidden"
                if error.reason in {
                    "codegraph-user-owned-upgrade-forbidden",
                    "graft-user-owned-upgrade-forbidden",
                }
                else "provider-maintenance-plan-invalid"
            )
            raise ProviderManagerError(reason) from None
        self._log(
            "provider.maintain.planned", providerId=provider_id,
            operation="maintain", status="planned", planHash=plan["planHash"],
        )
        if plan_only:
            return plan
        try:
            return adapter.execute_maintenance(  # type: ignore[union-attr]
                plan, project_root,
                confirmed_plan_hash=str(confirmed_plan_hash),
            )
        except (CodeGraphAdapterError, GraftAdapterError) as error:
            raise ProviderManagerError(error.reason) from None
