"""Machine-local CodeGraph configuration and lifecycle routing."""

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

from selfworkflow.v3.codegraph_lifecycle import (
    CodeGraphProjectError,
    CodeGraphProjectLifecycle,
)
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
    """Stable manager error which never embeds paths or command output."""

    def __init__(self, reason: str, *, diagnostics: dict[str, Any] | None = None) -> None:
        self.reason = reason
        self.diagnostics = diagnostics
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
    """Manage the one active CodeGraph binding and its project lifecycle."""

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
        self._adapter_cache: tuple[str, CodeGraphAdapter] | None = None

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
                or source.get("kind") not in {
                    "local-override", "managed-runtime", "managed-submodule",
                }
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
            encoded = transaction["preimage"]
            preimage = None if encoded is None else base64.b64decode(encoded, validate=True)
            if transaction["preimageHash"] != _payload_hash(preimage):
                raise ProviderManagerError("provider-config-rollback-invalid")
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
        source_kind: str | None = None,
        replace_existing: bool = False,
        rollback_token: str | None = None,
    ) -> dict[str, Any]:
        if provider_id != "codegraph":
            raise ProviderManagerError("provider-not-supported")
        if ownership not in {"user-local", "selfworkflow-managed"}:
            raise ProviderManagerError("provider-ownership-invalid")
        if source_kind not in {None, "managed-submodule"} or (source_kind == "managed-submodule" and ownership != "selfworkflow-managed"):
            raise ProviderManagerError("provider-source-kind-invalid")
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
            "kind": source_kind or ("managed-runtime" if ownership == "selfworkflow-managed" else "local-override"),
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
            "providerId": "codegraph",
            "sourcePath": validated_source_path,
            "enabled": True,
            "ownership": ownership,
            "commandPrefix": list(prefix),
            "commandHash": _hash({"argv": list(prefix)}),
            "source": source,
        }
        provider["bindingHash"] = _hash(provider)
        token = self._validate_rollback_token(rollback_token) if rollback_token is not None else None
        with self._config_lock():
            preimage = self._paths.config_file.read_bytes() if self._paths.config_file.exists() else None
            config = self._read_config()
            existing = next(
                (item for item in config["providers"] if item["providerId"] == "codegraph"),
                None,
            )
            if existing is not None and existing != provider and not replace_existing:
                raise ProviderManagerError("provider-config-conflict")
            config["providers"] = [
                item for item in config["providers"]
                if item["providerId"] != "codegraph"
            ] + [provider]
            config["providers"].sort(key=lambda item: item["providerId"])
            self._validate_config(config)
            if token is not None:
                self._write_rollback_transaction(token, preimage, _canonical_bytes(config) + b"\n")
            try:
                changed = self._write_config(config)
                if token is not None:
                    self._set_rollback_transaction_state(token, "applied")
            except BaseException as failure:
                self._restore_config_preimage(preimage)
                if token is not None:
                    try:
                        self._set_rollback_transaction_state(token, "rolled-back")
                    except ProviderManagerError:
                        pass
                if not isinstance(failure, Exception):
                    raise
                raise
        if changed:
            self._adapter_cache = None
        status = "configured" if changed else "unchanged"
        self._log(
            "provider.configure.completed", providerId="codegraph",
            operation="configure", status=status,
            configurationHash=_hash(config),
        )
        result = {
            "providerId": "codegraph", "status": status,
            "configurationHash": _hash(config), "bindingHash": provider["bindingHash"],
        }
        if token is not None:
            result["rollbackToken"] = token
        return result

    def retire(self, provider_id: str) -> dict[str, Any]:
        """Remove one obsolete machine-local binding transactionally."""

        if not isinstance(provider_id, str) or _PROVIDER_ID.fullmatch(provider_id) is None:
            raise ProviderManagerError("provider-id-invalid")
        if provider_id == "codegraph":
            raise ProviderManagerError("provider-retire-active-forbidden")
        with self._config_lock():
            config = self._read_config()
            old = len(config["providers"])
            config["providers"] = [
                item for item in config["providers"] if item["providerId"] != provider_id
            ]
            changed = old != len(config["providers"])
            if changed:
                self._write_config(config)
        return {"providerId": provider_id, "status": "retired" if changed else "absent"}

    def rollback_config(self, rollback_token: str, *, if_issued: bool = False) -> dict[str, Any]:
        token = self._validate_rollback_token(rollback_token)
        with self._config_lock():
            loaded = self._read_rollback_transaction(token, if_issued=if_issued)
            if loaded is None:
                return {"status": "not-issued"}
            path, transaction = loaded
            if transaction["state"] == "rolled-back" and if_issued:
                return {"status": "already-rolled-back"}
            encoded = transaction["preimage"]
            preimage = None if encoded is None else base64.b64decode(encoded, validate=True)
            current = _payload_hash(
                self._paths.config_file.read_bytes() if self._paths.config_file.exists() else None
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
        self._adapter_cache = None
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

    def _assert_source_identity(self, provider: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            observation = self._source_identity_resolver(provider["sourcePath"])
            if not isinstance(observation, Mapping):
                raise ValueError
            report = observation.get("report")
            observed_source = observation.get("source")
            if not isinstance(report, Mapping) or observed_source is None:
                raise ValueError
            observed_path = validate_provider_source_path(str(observed_source))
            expected = provider["source"]
            if (
                not isinstance(report.get("commit"), str)
                or re.fullmatch(r"[0-9a-f]{40}", report["commit"]) is None
                or not isinstance(report.get("sourceHash"), str)
                or _HASH.fullmatch(report["sourceHash"]) is None
                or type(report.get("dirty")) is not bool
            ):
                raise ValueError
            changed = [field for field in ("commit", "sourceHash", "dirty") if report[field] != expected[field]]
            if observed_path != provider["sourcePath"]:
                changed.append("sourcePath")
            if changed:
                raise ProviderManagerError("provider-source-identity-drift", diagnostics={
                    "failureStage": "source-identity", "changedFields": changed,
                    "expectedSourceHash": expected["sourceHash"], "observedSourceHash": report["sourceHash"],
                    "recovery": "inspect-and-review-rebinding",
                })
            return report
        except ProviderManagerError:
            raise
        except Exception as error:
            detail = getattr(error, "diagnostics", {})
            diagnostics = {"failureStage": "source-inspection", "cause": "read-failed", "recovery": "retry-inspection"}
            if isinstance(detail, dict):
                if detail.get("cause") in {"timeout", "start-failed", "dubious-ownership", "git-command-failed", "not-a-repository", "output-limit", "read-failed", "invalid-source"}:
                    diagnostics["cause"] = detail["cause"]
                if detail.get("operation") in {"rev-parse", "status", "diff", "metadata"}:
                    diagnostics["operation"] = detail["operation"]
                if type(detail.get("exitCode")) is int:
                    diagnostics["exitCode"] = detail["exitCode"]
            raise ProviderManagerError("provider-source-inspection-failed", diagnostics=diagnostics) from None

    def _adapter(self, *, fresh_session: bool = False) -> CodeGraphAdapter:
        config = self._read_config()
        provider = next(
            (item for item in config["providers"] if item["providerId"] == "codegraph"),
            None,
        )
        if provider is None:
            raise ProviderManagerError("provider-not-configured")
        if provider.get("enabled") is not True:
            raise ProviderManagerError("provider-disabled")
        if "bindingHash" not in provider:
            raise ProviderManagerError("provider-adapter-unavailable")
        source_report = self._assert_source_identity(provider)
        if (
            not fresh_session
            and self._adapter_cache is not None
            and self._adapter_cache[0] == provider["bindingHash"]
        ):
            return self._adapter_cache[1]
        def validate_source() -> None:
            self._assert_source_identity(provider)

        try:
            adapter = CodeGraphAdapter(
                command_port=self._command_port,
                command_prefix=tuple(provider["commandPrefix"]),
                ownership=provider["ownership"],
                pre_dispatch_validator=validate_source,
                allow_metadata_only_status=(
                    provider["ownership"] == "selfworkflow-managed"
                    and provider["source"]["kind"] == "managed-submodule"
                    and source_report.get("sourceType") == "managed-submodule"
                ),
            )
        except CodeGraphAdapterError:
            raise ProviderManagerError("provider-adapter-invalid") from None
        if not fresh_session:
            self._adapter_cache = (provider["bindingHash"], adapter)
        return adapter

    def doctor(self, provider_id: str) -> dict[str, Any]:
        if provider_id != "codegraph":
            raise ProviderManagerError("provider-not-supported")
        try:
            adapter = self._adapter()
            version = adapter.version()
            help_result = adapter.help()
        except CodeGraphAdapterError as error:
            raise ProviderManagerError(error.reason) from None
        return {
            "providerId": "codegraph", "status": "ready",
            "version": version["version"], "helpAvailable": bool(help_result["summary"]),
        }

    @staticmethod
    def _lifecycle(adapter: CodeGraphAdapter) -> CodeGraphProjectLifecycle:
        try:
            return CodeGraphProjectLifecycle(adapter)
        except CodeGraphProjectError as error:
            raise ProviderManagerError(error.reason) from None

    def status(
        self, provider_id: str, project_root: str, *,
        context_dir: str | None = None, conversation_id: str | None = None,
    ) -> dict[str, Any]:
        if provider_id != "codegraph":
            raise ProviderManagerError("provider-not-supported")
        if context_dir is not None or conversation_id is not None:
            raise ProviderManagerError("codegraph-conversation-context-unsupported")
        try:
            return self._lifecycle(self._adapter()).status(project_root)
        except (CodeGraphProjectError, CodeGraphAdapterError) as error:
            raise ProviderManagerError(error.reason) from None

    def ensure(self, project_root: str) -> dict[str, Any]:
        try:
            return self._lifecycle(self._adapter(fresh_session=True)).ensure(project_root)
        except (CodeGraphProjectError, CodeGraphAdapterError) as error:
            raise ProviderManagerError(error.reason) from None

    def sync(self, project_root: str, changed_paths: Sequence[str] = ()) -> dict[str, Any]:
        try:
            return self._lifecycle(self._adapter(fresh_session=True)).sync(project_root, changed_paths)
        except (CodeGraphProjectError, CodeGraphAdapterError) as error:
            raise ProviderManagerError(error.reason) from None

    def query(
        self, provider_id: str, project_root: str, query: str, *, query_kind: str = "ask",
        context_dir: str | None = None, conversation_id: str | None = None,
    ) -> dict[str, Any]:
        if provider_id != "codegraph":
            raise ProviderManagerError("provider-not-supported")
        if context_dir is not None or conversation_id is not None:
            raise ProviderManagerError("codegraph-conversation-context-unsupported")
        try:
            return self._lifecycle(self._adapter(fresh_session=True)).query(
                project_root, query, query_kind=query_kind,
            )
        except (CodeGraphProjectError, CodeGraphAdapterError) as error:
            raise ProviderManagerError(error.reason) from None

    def preflight(self, project_root: str) -> dict[str, Any]:
        return self.ensure(project_root)

    def maintain(
        self, provider_id: str, action: str, project_root: str, *,
        plan_only: bool, confirmed_plan_hash: str | None = None,
    ) -> dict[str, Any]:
        if provider_id != "codegraph":
            raise ProviderManagerError("provider-not-supported")
        adapter = self._adapter()
        try:
            plan = adapter.plan_maintenance(action, project_root)
        except CodeGraphAdapterError as error:
            raise ProviderManagerError(error.reason) from None
        self._log(
            "provider.maintain.planned", providerId="codegraph",
            operation="maintain", status="planned", planHash=plan["planHash"],
        )
        if plan_only:
            return plan
        if not isinstance(confirmed_plan_hash, str):
            raise ProviderManagerError("provider-maintenance-confirmation-required")
        try:
            return adapter.execute_maintenance(
                plan, project_root, confirmed_plan_hash=confirmed_plan_hash,
            )
        except CodeGraphAdapterError as error:
            raise ProviderManagerError(error.reason) from None
