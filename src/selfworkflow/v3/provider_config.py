"""Explicit, non-discovering Provider configuration and precedence rules."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from pathlib import PureWindowsPath
from typing import Any, Iterable, Mapping

import yaml

from selfworkflow.v3.contracts import ContractError, load_contract


class ProviderConfigError(ValueError):
    """Stable configuration failure without echoing paths or secret values."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ProviderSelection:
    provider_id: str
    layer: str
    requirement_mode: str
    fallback_receipt: dict[str, Any] | None = None


class _StrictLoader(yaml.SafeLoader):
    def compose_node(self, parent: yaml.Node | None, index: object) -> yaml.Node:
        if self.check_event(yaml.events.AliasEvent):
            raise ValueError("alias")
        return super().compose_node(parent, index)


def _mapping(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ValueError("mapping")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _mapping,
)


def provider_config_path(*, root: str | Path | None = None) -> Path:
    """Return exactly one configured path; this function never searches."""

    if root is not None:
        return Path(root) / "SelfWorkFlow" / "config" / "providers.local.yaml"
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "SelfWorkFlow" / "config" / "providers.local.yaml"
    return Path.home() / "AppData" / "Local" / "SelfWorkFlow" / "config" / "providers.local.yaml"


def load_provider_config(
    *, root: str | Path | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load the one explicit machine config, returning an empty default if absent."""

    target = Path(path) if path is not None else provider_config_path(root=root)
    try:
        if not target.is_file():
            return {"schemaVersion": 3, "providers": []}
        raw = target.read_text(encoding="utf-8")
        document = yaml.load(raw, Loader=_StrictLoader)
        if not isinstance(document, dict):
            raise ValueError
        return load_contract(
            "provider-local-config.schema.json",
            json.dumps(document, separators=(",", ":")),
        )
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError, yaml.YAMLError, ContractError):
        raise ProviderConfigError("provider-config-invalid") from None


def _validate_explicit_windows_path(value: object) -> None:
    if not isinstance(value, str) or not value:
        raise ProviderConfigError("provider-config-path-invalid")
    windows = PureWindowsPath(value)
    if not windows.is_absolute() or (windows.drive and not windows.root):
        raise ProviderConfigError("provider-config-path-invalid")
    if value.startswith(("\\\\?\\", "\\\\.\\")):
        raise ProviderConfigError("provider-config-path-invalid")
    if any(part in {".", ".."} or part.endswith((".", " ")) for part in windows.parts):
        raise ProviderConfigError("provider-config-path-invalid")
    remainder = value[2:] if len(value) >= 2 and value[1] == ":" else value
    if ":" in remainder:
        raise ProviderConfigError("provider-config-path-invalid")


def configured_machine_candidates(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Convert the already-loaded machine config; never discover another path."""

    providers = config.get("providers") if isinstance(config, Mapping) else None
    if not isinstance(providers, list):
        raise ProviderConfigError("provider-config-invalid")
    result = []
    for provider in providers:
        if not isinstance(provider, Mapping):
            raise ProviderConfigError("provider-config-invalid")
        _validate_explicit_windows_path(provider.get("sourcePath"))
        result.append({
            "providerId": provider.get("providerId"),
            "state": "supported" if provider.get("enabled") else "unsupported",
        })
    return result


def _as_candidates(value: object, layer: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        value = [value]
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise ProviderConfigError("provider-config-layer-invalid")
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            item = {"providerId": item, "state": "supported"}
        if not isinstance(item, Mapping):
            raise ProviderConfigError("provider-config-candidate-invalid")
        provider_id = item.get("providerId")
        if not isinstance(provider_id, str) or not provider_id:
            raise ProviderConfigError("provider-config-candidate-invalid")
        state = item.get("state", "supported")
        if state not in {"supported", "unverified", "unsupported", "candidate", "needs-revalidation"}:
            raise ProviderConfigError("provider-config-candidate-invalid")
        result.append({"providerId": provider_id, "state": state, "layer": layer})
    return result


def _choose_layer(candidates: list[dict[str, Any]], layer: str) -> tuple[dict[str, Any] | None, bool]:
    supported = [item for item in candidates if item["state"] == "supported"]
    ids = sorted({item["providerId"] for item in supported})
    if len(ids) > 1:
        raise ProviderConfigError("provider-config-conflict")
    return (supported[0] if supported else None), bool(candidates)


def resolve_provider(
    capability_id: str,
    operation_id: str,
    *,
    task_explicit: object = None,
    project: object = None,
    user_machine: object = None,
    public: object = None,
    builtin: object = None,
    user_config: Mapping[str, Any] | None = None,
) -> ProviderSelection:
    """Resolve one provider without discovery, process start, or network access."""

    if task_explicit is not None:
        explicit = _as_candidates(task_explicit, "task-explicit")
        selected, _ = _choose_layer(explicit, "task-explicit")
        if selected is None:
            raise ProviderConfigError("provider-task-explicit-invalid")
        return ProviderSelection(selected["providerId"], "task-explicit", "required")

    if user_machine is None and user_config is not None:
        user_machine = configured_machine_candidates(user_config)
    layers = (
        ("project", project), ("user-machine", user_machine),
        ("pinned-public", public), ("reportable-builtin", builtin),
    )
    rejected: list[str] = []
    for layer, value in layers:
        candidates = _as_candidates(value, layer)
        selected, configured = _choose_layer(candidates, layer)
        if selected is None:
            if configured:
                rejected.append(layer)
            continue
        receipt = None
        if rejected:
            receipt = {
                "schemaVersion": 3,
                "capabilityId": capability_id,
                "operationId": operation_id,
                "fromLayer": rejected[0],
                "selectedLayer": layer,
                "rejectedLayers": list(rejected),
                "reason": "preferred-provider-unavailable",
            }
        return ProviderSelection(selected["providerId"], layer, "preferred", receipt)
    raise ProviderConfigError("provider-not-available")
