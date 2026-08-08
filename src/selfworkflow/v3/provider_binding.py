"""Content-addressed static Provider bindings; no dynamic state is accepted."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from selfworkflow.v3.contracts import ContractError, load_contract


HASH = "sha256:"
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
    return {
        "kind": "git-tree", "remote": remote, "commit": commit, "treeHash": tree_hash,
        "dirty": dirty, "dirtyContentHash": dirty_content_hash,
        "untrackedContentHash": untracked_content_hash,
    }


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


def validate_source_identity(identity: Mapping[str, Any]) -> None:
    """Validate one and only one of the four source identity variants."""

    if not isinstance(identity, Mapping):
        raise ProviderBindingError("provider-source-identity-invalid")
    _validate_source_identity(identity)


def source_identity_hash(identity: Mapping[str, Any]) -> str:
    validate_source_identity(identity)
    return _hash(dict(identity))


def build_binding_snapshot(bindings: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    normalized = []
    for item in bindings:
        if not isinstance(item, Mapping):
            raise ProviderBindingError("provider-binding-invalid")
        value = dict(item)
        _reject_dynamic(value)
        normalized.append(value)
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
