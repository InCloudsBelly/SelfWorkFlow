"""Machine-local per-Agent Review model selection."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import tempfile
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

import yaml

from selfworkflow.config import ConfigError, load_config


MAX_CONFIG_BYTES = 64 * 1024
_AGENT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max", "ultra"})
_CONFIG_FILENAME = "review-models.local.yaml"


class ReviewModelConfigError(ValueError):
    """Stable, redacted configuration error."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ReviewModelSelection:
    agent_id: str
    model: str
    reasoning_effort: str

    def as_dict(self, *, selection_mode: str = "default") -> dict[str, str]:
        if selection_mode not in {"default", "one-time"}:
            raise ReviewModelConfigError("review-model-selection-mode-invalid")
        return {
            "agentId": self.agent_id,
            "model": self.model,
            "reasoningEffort": self.reasoning_effort,
            "selectionMode": selection_mode,
        }


@dataclass(frozen=True)
class ReviewModelResolution:
    status: str
    agent_id: str
    config_path: str
    selection: ReviewModelSelection | None

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "status": self.status,
            "agentId": self.agent_id,
            "configPath": self.config_path,
            "review": None,
        }
        if self.selection is not None:
            result["review"] = self.selection.as_dict()
        return result


def review_model_config_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "SelfWorkFlow" / "config" / _CONFIG_FILENAME
    return Path.home() / "AppData" / "Local" / "SelfWorkFlow" / "config" / _CONFIG_FILENAME


def _validate_agent_id(agent_id: object) -> str:
    if not isinstance(agent_id, str) or _AGENT_ID.fullmatch(agent_id) is None:
        raise ReviewModelConfigError("review-agent-id-invalid")
    return agent_id


def _validate_model(model: object) -> str:
    if not isinstance(model, str) or not 1 <= len(model) <= 256:
        raise ReviewModelConfigError("review-model-invalid")
    if model != model.strip() or "\x00" in model:
        raise ReviewModelConfigError("review-model-invalid")
    return model


def _validate_reasoning_effort(value: object) -> str:
    if not isinstance(value, str) or value not in _REASONING_EFFORTS:
        raise ReviewModelConfigError("review-reasoning-effort-invalid")
    return value


def _selection(agent_id: object, model: object, reasoning_effort: object) -> ReviewModelSelection:
    return ReviewModelSelection(
        _validate_agent_id(agent_id),
        _validate_model(model),
        _validate_reasoning_effort(reasoning_effort),
    )


def _config_document(path: Path) -> Any:
    try:
        if path.is_symlink() or (path.exists() and path.stat().st_size > MAX_CONFIG_BYTES):
            raise ReviewModelConfigError("review-model-config-invalid")
        return load_config(path, _schema_path())
    except ReviewModelConfigError:
        raise
    except (ConfigError, OSError, UnicodeError, RecursionError):
        raise ReviewModelConfigError("review-model-config-invalid") from None


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas" / "review-model-config.schema.json"


def _config_path(path: str | Path | None) -> Path:
    candidate = Path(path) if path is not None else review_model_config_path()
    if candidate.is_symlink():
        raise ReviewModelConfigError("review-model-config-invalid")
    return candidate.resolve(strict=False)


def resolve_review_model(
    agent_id: str, path: str | Path | None = None,
) -> ReviewModelResolution:
    """Resolve a configured model, without selecting a fallback."""

    normalized_agent = _validate_agent_id(agent_id)
    config_path = _config_path(path)
    if not config_path.exists():
        return ReviewModelResolution(
            "needs_user_configuration", normalized_agent, str(config_path), None,
        )
    document = _config_document(config_path)
    agents = document["agents"]
    if normalized_agent not in agents:
        return ReviewModelResolution(
            "needs_user_configuration", normalized_agent, str(config_path), None,
        )
    review = agents[normalized_agent]["review"]
    if review is None:
        return ReviewModelResolution(
            "needs_user_configuration", normalized_agent, str(config_path), None,
        )
    selected = _selection(
        normalized_agent, review["model"], review["reasoningEffort"],
    )
    return ReviewModelResolution(
        "configured", normalized_agent, str(config_path), selected,
    )


def save_review_model(
    path: str | Path | None,
    agent_id: str,
    model: str,
    reasoning_effort: str,
    *,
    confirmed: bool,
) -> ReviewModelResolution:
    """Atomically save one default selection after explicit user confirmation."""

    if confirmed is not True:
        raise ReviewModelConfigError("review-model-confirmation-required")
    normalized_agent = _validate_agent_id(agent_id)
    selected = _selection(normalized_agent, model, reasoning_effort)
    config_path = _config_path(path)
    if config_path.exists():
        document = _config_document(config_path)
        agents = {
            str(key): {
                "review": None
                if value["review"] is None
                else {
                    "model": value["review"]["model"],
                    "reasoningEffort": value["review"]["reasoningEffort"],
                },
            }
            for key, value in document["agents"].items()
        }
    else:
        agents = {}
    agents[normalized_agent] = {
        "review": {
            "model": selected.model,
            "reasoningEffort": selected.reasoning_effort,
        }
    }
    payload = {"schemaVersion": 1, "agents": dict(sorted(agents.items()))}
    temporary: Path | None = None
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", delete=False,
            dir=config_path.parent, prefix=f".{config_path.name}.", suffix=".tmp",
        ) as handle:
            temporary = Path(handle.name)
            yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, config_path)
    except (OSError, yaml.YAMLError):
        raise ReviewModelConfigError("review-model-config-write-failed") from None
    finally:
        if temporary is not None and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass
    return ReviewModelResolution(
        "configured", normalized_agent, str(config_path), selected,
    )


def one_time_review_model(
    agent_id: str, model: str, reasoning_effort: str,
) -> MappingProxyType:
    """Create a validated, non-persistent per-call override."""

    return MappingProxyType(
        _selection(agent_id, model, reasoning_effort).as_dict(selection_mode="one-time")
    )


def normalize_review_model_payload(value: object) -> MappingProxyType:
    """Validate the exact model selection embedded in a Review dispatch."""

    if not isinstance(value, Mapping) or set(value) != {
        "agentId", "model", "reasoningEffort", "selectionMode",
    }:
        raise ReviewModelConfigError("review-model-payload-invalid")
    selected = _selection(
        value["agentId"], value["model"], value["reasoningEffort"],
    )
    if value["selectionMode"] not in {"default", "one-time"}:
        raise ReviewModelConfigError("review-model-selection-mode-invalid")
    return MappingProxyType(selected.as_dict(selection_mode=value["selectionMode"]))
