"""Explicit Provider configuration, validated registry, and visible fallback."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
from typing import Any, Iterable, Mapping

from selfworkflow.v3.catalog import (
    CatalogError,
    _load_yaml_bytes,
    _metadata_is_reparse,
    _read_bytes,
)
from selfworkflow.v3.contracts import (
    ContractError,
    load_contract,
    validate_provider_descriptor,
)
from selfworkflow.v3.provider_binding import (
    ProviderBindingError,
    ValidatedProviderBinding,
    ValidatedSourceIdentity,
    create_provider_binding,
)
from selfworkflow.v3.support_matrix import (
    ValidatedSupportEntry,
    ValidatedSupportMatrix,
)


_MAX_CONFIG_BYTES = 1024 * 1024
_REGISTRY_SEAL = object()
_FALLBACK_SEAL = object()
_LAYERS = (
    "project", "user-machine", "pinned-public", "reportable-builtin",
)
_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")


class ProviderConfigError(ValueError):
    """Stable configuration failure without echoing paths or sensitive values."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ProviderSelection:
    provider_id: str
    layer: str
    requirement_mode: str
    binding: ValidatedProviderBinding
    fallback_receipt: ProviderFallbackReceipt | None = None


class ProviderFallbackReceipt:
    """Content-addressed fallback record issued by the resolver."""

    __slots__ = ("_document", "__seal")

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("ProviderFallbackReceipt is issued by resolve_provider")

    @property
    def document(self) -> dict[str, Any]:
        return _copy(self._document)

    @property
    def receipt_hash(self) -> str:
        return self._document["receiptHash"]

    def _is_valid(self) -> bool:
        return getattr(self, "_ProviderFallbackReceipt__seal", None) is _FALLBACK_SEAL


class ValidatedProviderRegistry:
    """Sealed cross-binding of catalog, descriptors, sources and matrices."""

    __slots__ = ("_records", "_registry_hash", "__seal")

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("ValidatedProviderRegistry is issued by build_provider_registry")

    @property
    def registry_hash(self) -> str:
        return self._registry_hash

    def _is_valid(self) -> bool:
        return getattr(self, "_ValidatedProviderRegistry__seal", None) is _REGISTRY_SEAL

    def resolve_support_entry(
        self,
        matrix_hash: str,
        entry_hash: str,
    ) -> ValidatedSupportEntry | None:
        """Resolve an entry only from this sealed, cross-bound registry."""

        if not self._is_valid():
            raise ProviderConfigError("provider-registry-required")
        for record in self._records.values():
            if record.matrix.matrix_hash != matrix_hash:
                continue
            for entry_document in record.matrix.document["entries"]:
                if entry_document["entryHash"] == entry_hash:
                    return record.matrix.entry(entry_document["entryId"])
        return None


@dataclass(frozen=True)
class _RegistryRecord:
    provider_id: str
    lifecycle: str
    descriptor: dict[str, Any]
    descriptor_hash: str
    matrix: ValidatedSupportMatrix
    source: ValidatedSourceIdentity


@dataclass(frozen=True)
class _CandidateEvaluation:
    provider_id: str
    layer: str
    binding: ValidatedProviderBinding | None
    source_identity_hash: str | None
    support_matrix_hash: str | None
    support_entry_hash: str | None
    binding_hash: str | None
    rejection_reason: str | None

    @property
    def selectable(self) -> bool:
        return self.binding is not None and self.rejection_reason is None


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ProviderConfigError("provider-config-canonical-invalid") from None


def _copy(value: Any) -> Any:
    return json.loads(_canonical(value))


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def provider_config_path(*, root: str | Path | None = None) -> Path:
    """Return exactly one configured path; this function never searches."""

    if root is not None:
        return Path(root) / "SelfWorkFlow" / "config" / "providers.local.yaml"
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "SelfWorkFlow" / "config" / "providers.local.yaml"
    return Path.home() / "AppData" / "Local" / "SelfWorkFlow" / "config" / "providers.local.yaml"


def load_provider_config(
    *, root: str | Path | None = None, path: str | Path | None = None,
) -> dict[str, Any]:
    """Load one explicit machine config through a bounded immutable snapshot."""

    target = Path(path) if path is not None else provider_config_path(root=root)
    trusted_root = Path(root) if root is not None else target.parent
    try:
        _validate_trusted_config_location(target, trusted_root)
        if not os.path.lexists(target):
            return {"schemaVersion": 3, "providers": []}
        document = _load_yaml_bytes(
            _read_bytes(target, _MAX_CONFIG_BYTES, trusted_root),
        )
        if not isinstance(document, dict):
            raise ValueError
        validated = load_contract(
            "provider-local-config.schema.json",
            json.dumps(document, separators=(",", ":")),
        )
        for provider in validated["providers"]:
            _validate_explicit_windows_path(provider["sourcePath"], require_existing=True)
        return validated
    except CatalogError as error:
        if error.reason == "v3-yaml-resource-limit":
            raise ProviderConfigError("provider-config-resource-limit") from None
        if error.reason in {
            "v3-yaml-path-changed", "v3-catalog-ref-reparse",
            "v3-catalog-ref-unresolved",
        }:
            raise ProviderConfigError("provider-config-path-changed") from None
        raise ProviderConfigError("provider-config-invalid") from None
    except ProviderConfigError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError, ContractError):
        raise ProviderConfigError("provider-config-invalid") from None


def _validate_trusted_config_location(target: Path, trusted_root: Path) -> None:
    try:
        if not trusted_root.is_absolute() or not trusted_root.is_dir():
            raise ProviderConfigError("provider-config-path-invalid")
        relative = target.relative_to(trusted_root)
        current = trusted_root
        for candidate in (trusted_root, *(trusted_root.joinpath(*relative.parts[:index]) for index in range(1, len(relative.parts) + 1))):
            current = candidate
            if not os.path.lexists(current):
                break
            if _metadata_is_reparse(current.lstat()):
                raise ProviderConfigError("provider-config-path-changed")
    except ProviderConfigError:
        raise
    except (OSError, ValueError):
        raise ProviderConfigError("provider-config-path-invalid") from None


def _validate_explicit_windows_path(
    value: object, *, require_existing: bool = False,
) -> None:
    if not isinstance(value, str) or not value:
        raise ProviderConfigError("provider-config-path-invalid")
    windows = PureWindowsPath(value)
    remainder = value[2:] if len(value) >= 2 and value[1] == ":" else value
    if (
        not windows.is_absolute() or (windows.drive and not windows.root)
        or value.startswith(("\\\\?\\", "\\\\.\\"))
        or any(part in {".", ".."} or part.endswith((".", " ")) for part in windows.parts)
        or ":" in remainder
    ):
        raise ProviderConfigError("provider-config-path-invalid")
    if require_existing:
        try:
            native = Path(value)
            resolved = native.resolve(strict=True)
            if (
                os.path.normcase(str(native)) != os.path.normcase(value)
                or os.path.normcase(str(resolved)) != os.path.normcase(value)
            ):
                raise ProviderConfigError("provider-config-path-invalid")
            current = Path(native.anchor)
            for part in native.parts[1:]:
                current /= part
                if _metadata_is_reparse(current.lstat()):
                    raise ProviderConfigError("provider-config-path-invalid")
            mode = native.lstat().st_mode
            if not stat.S_ISDIR(mode) and not stat.S_ISREG(mode):
                raise ProviderConfigError("provider-config-path-invalid")
        except ProviderConfigError:
            raise
        except (OSError, ValueError):
            raise ProviderConfigError("provider-config-path-invalid") from None


def validate_provider_source_path(value: object) -> str:
    """Validate one explicitly selected Provider path without searching for it."""

    _validate_explicit_windows_path(value, require_existing=True)
    return str(value)


def configured_machine_candidates(config: Mapping[str, Any]) -> list[str]:
    """Return enabled IDs from already-loaded config without path discovery."""

    providers = config.get("providers") if isinstance(config, Mapping) else None
    if not isinstance(providers, list):
        raise ProviderConfigError("provider-config-invalid")
    result: list[str] = []
    for provider in providers:
        if not isinstance(provider, Mapping):
            raise ProviderConfigError("provider-config-invalid")
        _validate_explicit_windows_path(provider.get("sourcePath"), require_existing=True)
        if provider.get("enabled"):
            result.append(str(provider.get("providerId")))
    return result


def build_provider_registry(
    catalog: Mapping[str, Any],
    descriptors: Mapping[str, Mapping[str, Any]],
    support_matrices: Mapping[str, ValidatedSupportMatrix],
    source_identities: Mapping[str, ValidatedSourceIdentity],
) -> ValidatedProviderRegistry:
    """Cross-bind every Provider identity before it can enter resolution."""

    if not isinstance(catalog, Mapping) or set(catalog) != {"schemaVersion", "providers"} or catalog.get("schemaVersion") != 3:
        raise ProviderConfigError("provider-catalog-invalid")
    declarations = catalog.get("providers")
    if not isinstance(declarations, list):
        raise ProviderConfigError("provider-catalog-invalid")
    records: dict[str, _RegistryRecord] = {}
    registry_material: list[dict[str, Any]] = []
    for declaration in declarations:
        if not isinstance(declaration, Mapping) or set(declaration) != {"providerId", "descriptorRef", "lifecycle"}:
            raise ProviderConfigError("provider-catalog-invalid")
        provider_id = declaration.get("providerId")
        lifecycle = declaration.get("lifecycle")
        if (
            not isinstance(provider_id, str) or _ID.fullmatch(provider_id) is None
            or lifecycle not in {"supported", "unverified", "candidate"}
            or provider_id in records
        ):
            raise ProviderConfigError("provider-catalog-invalid")
        descriptor = descriptors.get(provider_id)
        matrix = support_matrices.get(provider_id)
        if not isinstance(descriptor, Mapping):
            raise ProviderConfigError("provider-descriptor-missing")
        try:
            validate_provider_descriptor(dict(descriptor))
        except ContractError:
            raise ProviderConfigError("provider-descriptor-invalid") from None
        if descriptor["providerId"] != provider_id:
            raise ProviderConfigError("provider-descriptor-mismatch")
        if not isinstance(matrix, ValidatedSupportMatrix) or not matrix._is_valid() or matrix.provider_id != provider_id:
            raise ProviderConfigError("provider-support-matrix-not-validated")
        source = source_identities.get(descriptor["sourceIdentityRef"])
        if not isinstance(source, ValidatedSourceIdentity) or not source._is_valid():
            raise ProviderConfigError("provider-source-not-validated")
        operation_ids = [operation["operationId"] for operation in descriptor["operations"]]
        if len(operation_ids) != len(set(operation_ids)):
            raise ProviderConfigError("provider-descriptor-operation-conflict")
        for entry in matrix.document["entries"]:
            if (
                entry["capabilityId"] not in descriptor["capabilities"]
                or entry["operationId"] not in operation_ids
                or entry["adapterHash"] != descriptor["adapterHash"]
                or entry["sourceIdentityRef"] != descriptor["sourceIdentityRef"]
                or entry["sourceIdentityHash"] != source.identity_hash
            ):
                raise ProviderConfigError("provider-registry-cross-binding-invalid")
        descriptor_copy = _copy(dict(descriptor))
        descriptor_hash = _hash(descriptor_copy)
        records[provider_id] = _RegistryRecord(
            provider_id, lifecycle, descriptor_copy, descriptor_hash, matrix, source,
        )
        registry_material.append({
            "providerId": provider_id, "lifecycle": lifecycle,
            "descriptorHash": descriptor_hash, "sourceIdentityHash": source.identity_hash,
            "supportMatrixHash": matrix.matrix_hash,
        })
    artifact = object.__new__(ValidatedProviderRegistry)
    object.__setattr__(artifact, "_records", records)
    object.__setattr__(artifact, "_registry_hash", _hash({
        "schemaVersion": 3, "providers": sorted(registry_material, key=lambda item: item["providerId"]),
    }))
    object.__setattr__(artifact, "_ValidatedProviderRegistry__seal", _REGISTRY_SEAL)
    return artifact


def _as_provider_refs(value: object, layer: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, Mapping)):
        value = [value]
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise ProviderConfigError("provider-config-layer-invalid")
    result: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            provider_id = item.get("providerId")
        else:
            provider_id = item
        if not isinstance(provider_id, str) or _ID.fullmatch(provider_id) is None:
            raise ProviderConfigError("provider-config-candidate-invalid")
        if provider_id in result:
            raise ProviderConfigError("provider-config-conflict")
        result.append(provider_id)
    return result


def _support_reason(state: str) -> str | None:
    return {
        "supported": None,
        "unverified": "support-unverified",
        "unsupported": "support-unsupported",
        "needs-revalidation": "support-needs-revalidation",
    }[state]


def _evaluate_candidate(
    registry: ValidatedProviderRegistry,
    provider_id: str,
    capability_id: str,
    operation_id: str,
    layer: str,
    requirement_mode: str,
) -> _CandidateEvaluation:
    record = registry._records.get(provider_id)
    if record is None:
        return _CandidateEvaluation(provider_id, layer, None, None, None, None, None, "provider-not-found")
    descriptor = record.descriptor
    if capability_id not in descriptor["capabilities"]:
        reason = "capability-mismatch"
        return _CandidateEvaluation(provider_id, layer, None, record.source.identity_hash, record.matrix.matrix_hash, None, None, reason)
    if operation_id not in {item["operationId"] for item in descriptor["operations"]}:
        reason = "operation-mismatch"
        return _CandidateEvaluation(provider_id, layer, None, record.source.identity_hash, record.matrix.matrix_hash, None, None, reason)
    entries = [
        item for item in record.matrix.document["entries"]
        if item["capabilityId"] == capability_id
        and item["operationId"] == operation_id
        and item["platform"] == "windows"
    ]
    if len(entries) != 1:
        reason = "conflict" if len(entries) > 1 else "operation-mismatch"
        return _CandidateEvaluation(provider_id, layer, None, record.source.identity_hash, record.matrix.matrix_hash, None, None, reason)
    entry = record.matrix.entry(entries[0]["entryId"])
    state = entry.document["state"]
    reason = _support_reason(state)
    if record.lifecycle != "supported" and reason is None:
        reason = "support-unverified"
    binding = None
    binding_hash = _hash({
        "providerId": provider_id, "capabilityId": capability_id,
        "operationId": operation_id, "configurationLayer": layer,
        "adapterHash": entries[0]["adapterHash"],
        "sourceIdentityHash": record.source.identity_hash,
        "supportMatrixHash": record.matrix.matrix_hash,
        "supportMatrixEntryHash": entry.entry_hash,
        "requirementMode": requirement_mode,
    })
    if reason is None:
        try:
            binding = create_provider_binding(
                capability_id, layer, requirement_mode, entry, record.source,
            )
            binding_hash = binding.document["bindingHash"]
        except ProviderBindingError:
            raise ProviderConfigError("provider-registry-cross-binding-invalid") from None
    return _CandidateEvaluation(
        provider_id, layer, binding, record.source.identity_hash,
        record.matrix.matrix_hash, entry.entry_hash, binding_hash, reason,
    )


def _candidate_document(
    evaluation: _CandidateEvaluation, selected: _CandidateEvaluation,
    selected_seen: bool,
) -> dict[str, Any]:
    is_selected = evaluation is selected
    reason = evaluation.rejection_reason
    if not is_selected and reason is None and selected_seen:
        reason = "lower-priority"
    document = {
        "providerId": evaluation.provider_id,
        "configurationLayer": evaluation.layer,
        "bindingHash": evaluation.binding_hash,
        "sourceIdentityHash": evaluation.source_identity_hash,
        "supportMatrixHash": evaluation.support_matrix_hash,
        "supportMatrixEntryHash": evaluation.support_entry_hash,
        "outcome": "selected" if is_selected else "rejected",
    }
    if not is_selected:
        document["rejectionReason"] = reason or "conflict"
    return document


def _fallback_input_material(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "registryHash": document["registryHash"],
        "capabilityId": document["capabilityId"],
        "operationId": document["operationId"],
        "candidates": [{
            key: candidate[key] for key in (
                "providerId", "configurationLayer", "bindingHash",
                "sourceIdentityHash", "supportMatrixHash", "supportMatrixEntryHash",
            )
        } for candidate in document["candidates"]],
    }


def _issue_fallback_receipt(document: dict[str, Any]) -> ProviderFallbackReceipt:
    artifact = object.__new__(ProviderFallbackReceipt)
    object.__setattr__(artifact, "_document", _copy(document))
    object.__setattr__(artifact, "_ProviderFallbackReceipt__seal", _FALLBACK_SEAL)
    return artifact


def validate_fallback_receipt(document: Mapping[str, Any]) -> ProviderFallbackReceipt:
    value = _copy(dict(document))
    try:
        load_contract(
            "provider-fallback-receipt.schema.json",
            json.dumps(value, separators=(",", ":")),
        )
    except (ContractError, TypeError, ValueError):
        raise ProviderConfigError("provider-fallback-receipt-invalid") from None
    if value["inputSnapshotHash"] != _hash(_fallback_input_material(value)):
        raise ProviderConfigError("provider-fallback-input-hash-invalid")
    if value["receiptHash"] != _hash({key: value[key] for key in value if key != "receiptHash"}):
        raise ProviderConfigError("provider-fallback-receipt-hash-invalid")
    selected = [item for item in value["candidates"] if item["outcome"] == "selected"]
    if len(selected) != 1 or (
        selected[0]["providerId"] != value["selectedProviderId"]
        or selected[0]["configurationLayer"] != value["selectedLayer"]
        or "rejectionReason" in selected[0]
    ):
        raise ProviderConfigError("provider-fallback-selection-invalid")
    return _issue_fallback_receipt(value)


def resolve_provider(
    capability_id: str,
    operation_id: str,
    *,
    registry: ValidatedProviderRegistry | None = None,
    task_explicit: object = None,
    project: object = None,
    user_machine: object = None,
    public: object = None,
    builtin: object = None,
    user_config: Mapping[str, Any] | None = None,
) -> ProviderSelection:
    """Resolve from immutable evidence; caller-supplied state is ignored."""

    if user_machine is None and user_config is not None:
        user_machine = configured_machine_candidates(user_config)
    if not isinstance(registry, ValidatedProviderRegistry) or not registry._is_valid():
        raise ProviderConfigError("provider-registry-required")
    if task_explicit is not None:
        refs = _as_provider_refs(task_explicit, "task-explicit")
        if len(refs) != 1:
            raise ProviderConfigError("provider-task-explicit-invalid")
        selected = _evaluate_candidate(
            registry, refs[0], capability_id, operation_id,
            "task-explicit", "required",
        )
        if not selected.selectable:
            raise ProviderConfigError("provider-task-explicit-invalid")
        return ProviderSelection(
            selected.provider_id, selected.layer, "required", selected.binding,
        )

    layer_inputs = (
        ("project", project), ("user-machine", user_machine),
        ("pinned-public", public), ("reportable-builtin", builtin),
    )
    evaluations: list[_CandidateEvaluation] = []
    selected: _CandidateEvaluation | None = None
    selected_index = -1
    for layer, raw in layer_inputs:
        refs = _as_provider_refs(raw, layer)
        layer_evaluations = [
            _evaluate_candidate(
                registry, provider_id, capability_id, operation_id,
                layer, "preferred",
            )
            for provider_id in refs
        ]
        selectable = [item for item in layer_evaluations if item.selectable]
        if len(selectable) > 1:
            raise ProviderConfigError("provider-config-conflict")
        evaluations.extend(layer_evaluations)
        if selected is None and selectable:
            selected = selectable[0]
            selected_index = evaluations.index(selected)
    if selected is None:
        raise ProviderConfigError("provider-not-available")
    fallback = None
    if selected_index > 0:
        candidate_documents = []
        selected_seen = False
        for evaluation in evaluations:
            if evaluation is selected:
                selected_seen = True
            candidate_documents.append(
                _candidate_document(evaluation, selected, selected_seen),
            )
        receipt = {
            "schemaVersion": 3, "registryHash": registry.registry_hash,
            "capabilityId": capability_id, "operationId": operation_id,
            "candidates": candidate_documents,
            "selectedProviderId": selected.provider_id,
            "selectedLayer": selected.layer,
        }
        receipt["inputSnapshotHash"] = _hash(_fallback_input_material(receipt))
        receipt["receiptHash"] = _hash(receipt)
        fallback = validate_fallback_receipt(receipt)
    return ProviderSelection(
        selected.provider_id, selected.layer, "preferred", selected.binding, fallback,
    )
