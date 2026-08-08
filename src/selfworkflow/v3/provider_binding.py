"""Content-addressed static Provider bindings; no dynamic state is accepted."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from selfworkflow.v3.contracts import ContractError, load_contract
from selfworkflow.v3.support_matrix import (
    SupportMatrixError,
    ValidatedSupportEntry,
    is_selectable,
)


HASH = "sha256:"
_EMPTY_HASH = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_SOURCE_SEAL = object()
_BINDING_SEAL = object()
_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_LAYERS = {
    "task-explicit", "project", "user-machine", "pinned-public",
    "reportable-builtin",
}
_DYNAMIC_KEYS = {
    "freshness", "indexrevision", "indexstatus", "query", "queryinput",
    "queryoutput", "returnedfiles", "returnedranges", "workspacefingerprint",
    "projectstatereceipt", "projectstatereceipthash", "pendingfiles",
    "parsefailures", "actualsideeffects", "outputhash", "inputhash",
}


class ProviderBindingError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ValidatedSourceIdentity:
    """Canonical source identity issued by semantic validation."""

    __slots__ = ("_document", "_identity_hash", "__seal")

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("ValidatedSourceIdentity is issued by validate_source_identity")

    @property
    def document(self) -> dict[str, Any]:
        return json.loads(_canonical(self._document))

    @property
    def identity_hash(self) -> str:
        return self._identity_hash

    def _is_valid(self) -> bool:
        return getattr(self, "_ValidatedSourceIdentity__seal", None) is _SOURCE_SEAL


class ValidatedProviderBinding:
    """Binding tuple issued from sealed support and source artifacts."""

    __slots__ = ("_document", "_support_entry", "_source_identity", "__seal")

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("ValidatedProviderBinding is issued by create_provider_binding")

    @property
    def document(self) -> dict[str, Any]:
        return json.loads(_canonical(self._document))

    @property
    def support_entry(self) -> ValidatedSupportEntry:
        return self._support_entry

    @property
    def source_identity(self) -> ValidatedSourceIdentity:
        return self._source_identity

    def _is_valid(self) -> bool:
        return getattr(self, "_ValidatedProviderBinding__seal", None) is _BINDING_SEAL


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise ProviderBindingError("provider-binding-canonical-invalid") from None


def _hash(value: Any) -> str:
    return HASH + hashlib.sha256(_canonical(value)).hexdigest()


def build_git_source_identity(
    remote: str,
    commit: str,
    tree_hash: str,
    dirty: bool,
    dirty_content_hash: str,
    untracked_content_hash: str | None = None,
) -> dict[str, Any]:
    if untracked_content_hash is None:
        untracked_content_hash = dirty_content_hash
    identity = {
        "kind": "git-tree", "remote": _canonicalize_git_remote(remote),
        "commit": commit.lower(), "treeHash": tree_hash,
        "dirty": dirty, "dirtyContentHash": dirty_content_hash,
        "untrackedContentHash": untracked_content_hash,
    }
    validate_source_identity(identity)
    return identity


def build_binary_source_identity(
    package_identity: str, version: str, integrity: str,
    executable_hash: str, build_identity: str,
) -> dict[str, Any]:
    identity = {
        "kind": "binary-or-package-build", "packageIdentity": package_identity,
        "version": version, "integrity": integrity,
        "executableHash": executable_hash, "buildIdentity": build_identity,
    }
    validate_source_identity(identity)
    return identity


def build_service_source_identity(
    endpoint_identity: str, protocol: str, server_attestation: str,
    data_boundary: str,
) -> dict[str, Any]:
    identity = {
        "kind": "service", "endpointIdentity": endpoint_identity,
        "protocol": protocol, "serverAttestation": server_attestation,
        "dataBoundary": data_boundary,
    }
    validate_source_identity(identity)
    return identity


def build_host_native_source_identity(
    host_capability: str, host_version: str, attestation: str,
) -> dict[str, Any]:
    identity = {
        "kind": "host-native", "hostCapability": host_capability,
        "hostVersion": host_version, "attestation": attestation,
    }
    validate_source_identity(identity)
    return identity


def _canonical_repo_path(path: str) -> str:
    if not path or any(ord(character) < 32 for character in path) or "%" in path or "\\" in path:
        raise ProviderBindingError("provider-source-remote-invalid")
    parts: list[str] = []
    for part in path.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise ProviderBindingError("provider-source-remote-invalid")
            parts.pop()
            continue
        parts.append(part)
    if not parts:
        raise ProviderBindingError("provider-source-remote-invalid")
    if parts[-1].lower().endswith(".git"):
        parts[-1] = parts[-1][:-4]
    if not parts[-1]:
        raise ProviderBindingError("provider-source-remote-invalid")
    return "/".join(parts)


def _canonicalize_git_remote(remote: object) -> str:
    if not isinstance(remote, str) or remote != remote.strip():
        raise ProviderBindingError("provider-source-remote-invalid")
    scp = re.fullmatch(
        r"(?P<user>[A-Za-z0-9._-]+)@(?P<host>[A-Za-z0-9.-]+):(?P<path>[^?#]+)",
        remote,
    )
    if scp:
        return (
            f"{scp.group('user').lower()}@{scp.group('host').lower()}:"
            f"{_canonical_repo_path(scp.group('path'))}"
        )
    try:
        parsed = urlsplit(remote)
        scheme = parsed.scheme.lower()
        if scheme not in {"https", "ssh"} or not parsed.hostname:
            raise ValueError
        if parsed.password is not None or parsed.query or parsed.fragment:
            raise ValueError
        if scheme == "https" and parsed.username is not None:
            raise ValueError
        host = parsed.hostname.lower()
        user = parsed.username.lower() if parsed.username else None
        port = parsed.port
        if port == {"https": 443, "ssh": 22}[scheme]:
            port = None
        authority = host + (f":{port}" if port is not None else "")
        if user:
            authority = f"{user}@{authority}"
        return f"{scheme}://{authority}/{_canonical_repo_path(parsed.path)}"
    except (TypeError, ValueError):
        raise ProviderBindingError("provider-source-remote-invalid") from None


def _reject_dynamic(value: Any) -> None:
    if isinstance(value, Mapping):
        if any(str(key).lower() in _DYNAMIC_KEYS for key in value):
            raise ProviderBindingError("provider-binding-dynamic-field")
        for child in value.values():
            _reject_dynamic(child)
    elif isinstance(value, list):
        for child in value:
            _reject_dynamic(child)


def _validate_source_identity(identity: Mapping[str, Any]) -> None:
    try:
        load_contract("provider-source-identity.schema.json", json.dumps(identity, separators=(",", ":")))
    except (ContractError, TypeError, ValueError):
        raise ProviderBindingError("provider-source-identity-invalid") from None


def validate_source_identity(identity: Mapping[str, Any]) -> ValidatedSourceIdentity:
    """Validate one and only one of the four source identity variants."""

    if not isinstance(identity, Mapping):
        raise ProviderBindingError("provider-source-identity-invalid")
    _validate_source_identity(identity)
    value = dict(identity)
    kind = value["kind"]
    if kind == "git-tree":
        if value["remote"] != _canonicalize_git_remote(value["remote"]):
            raise ProviderBindingError("provider-source-remote-not-canonical")
        if type(value["dirty"]) is not bool:
            raise ProviderBindingError("provider-source-identity-invalid")
        if not value["dirty"] and (
            value["dirtyContentHash"] != _EMPTY_HASH
            or value["untrackedContentHash"] != _EMPTY_HASH
        ):
            raise ProviderBindingError("provider-source-clean-inventory-invalid")
    artifact = object.__new__(ValidatedSourceIdentity)
    object.__setattr__(artifact, "_document", json.loads(_canonical(value)))
    object.__setattr__(artifact, "_identity_hash", _hash(value))
    object.__setattr__(artifact, "_ValidatedSourceIdentity__seal", _SOURCE_SEAL)
    return artifact


def source_identity_hash(
    identity: Mapping[str, Any] | ValidatedSourceIdentity,
) -> str:
    if isinstance(identity, ValidatedSourceIdentity) and identity._is_valid():
        return identity.identity_hash
    return validate_source_identity(identity).identity_hash


def create_provider_binding(
    module_id: str,
    configuration_layer: str,
    requirement_mode: str,
    support_entry: ValidatedSupportEntry,
    source_identity: ValidatedSourceIdentity,
) -> ValidatedProviderBinding:
    if (
        not isinstance(module_id, str) or _ID.fullmatch(module_id) is None
        or configuration_layer not in _LAYERS
        or requirement_mode not in {"required", "preferred"}
    ):
        raise ProviderBindingError("provider-binding-invalid")
    try:
        if not is_selectable(support_entry):
            raise ProviderBindingError("provider-binding-support-not-selectable")
    except SupportMatrixError:
        raise ProviderBindingError("provider-binding-support-not-validated") from None
    if not isinstance(source_identity, ValidatedSourceIdentity) or not source_identity._is_valid():
        raise ProviderBindingError("provider-binding-source-not-validated")
    support = support_entry.document
    if support["sourceIdentityHash"] != source_identity.identity_hash:
        raise ProviderBindingError("provider-binding-source-mismatch")
    document = {
        "moduleId": module_id,
        "providerId": support_entry.provider_id,
        "capabilityId": support["capabilityId"],
        "operationId": support["operationId"],
        "configurationLayer": configuration_layer,
        "adapterHash": support["adapterHash"],
        "sourceIdentityHash": source_identity.identity_hash,
        "supportMatrixHash": support_entry.matrix_hash,
        "supportMatrixEntryRef": support["entryId"],
        "supportMatrixEntryHash": support_entry.entry_hash,
        "requirementMode": requirement_mode,
    }
    document["bindingHash"] = _hash(document)
    artifact = object.__new__(ValidatedProviderBinding)
    object.__setattr__(artifact, "_document", json.loads(_canonical(document)))
    object.__setattr__(artifact, "_support_entry", support_entry)
    object.__setattr__(artifact, "_source_identity", source_identity)
    object.__setattr__(artifact, "_ValidatedProviderBinding__seal", _BINDING_SEAL)
    return artifact


def build_binding_snapshot(
    bindings: Iterable[ValidatedProviderBinding],
) -> dict[str, Any]:
    normalized = []
    for item in bindings:
        if not isinstance(item, ValidatedProviderBinding) or not item._is_valid():
            raise ProviderBindingError("provider-binding-not-validated")
        normalized.append(item.document)
    normalized.sort(key=lambda item: tuple(str(item.get(key, "")) for key in (
        "moduleId", "providerId", "capabilityId", "operationId", "adapterHash", "sourceIdentityHash",
    )))
    identities = [(
        item.get("moduleId"), item.get("capabilityId"), item.get("operationId"),
    ) for item in normalized]
    if len(identities) != len(set(identities)):
        raise ProviderBindingError("provider-binding-conflict")
    snapshot = {"schemaVersion": 3, "bindings": normalized}
    snapshot["bindingSnapshotHash"] = _hash(snapshot)
    try:
        load_contract("provider-binding-snapshot.schema.json", json.dumps(snapshot, separators=(",", ":")))
    except (ContractError, TypeError, ValueError):
        raise ProviderBindingError("provider-binding-invalid") from None
    return snapshot


def _validate_binding_set(bindings: object) -> None:
    if not isinstance(bindings, list):
        raise ProviderBindingError("provider-binding-invalid")
    identities = []
    for item in bindings:
        if not isinstance(item, Mapping):
            raise ProviderBindingError("provider-binding-invalid")
        _reject_dynamic(item)
        if item.get("bindingHash") != _hash({
            key: item[key] for key in item if key != "bindingHash"
        }):
            raise ProviderBindingError("provider-binding-tuple-hash-invalid")
        identities.append((item.get("moduleId"), item.get("capabilityId"), item.get("operationId")))
    if len(identities) != len(set(identities)):
        raise ProviderBindingError("provider-binding-conflict")


def validate_binding_snapshot(snapshot: Mapping[str, Any]) -> None:
    if not isinstance(snapshot, Mapping):
        raise ProviderBindingError("provider-binding-invalid")
    value = dict(snapshot)
    _reject_dynamic(value)
    expected = _hash({key: value[key] for key in value if key != "bindingSnapshotHash"})
    if value.get("bindingSnapshotHash") != expected:
        raise ProviderBindingError("provider-binding-hash-invalid")
    _validate_binding_set(value.get("bindings"))
    try:
        load_contract("provider-binding-snapshot.schema.json", json.dumps(value, separators=(",", ":")))
    except (ContractError, TypeError, ValueError):
        raise ProviderBindingError("provider-binding-invalid") from None
