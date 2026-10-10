"""Machine-local Graft Deep model selection."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from typing import Any

import yaml

from selfworkflow.config import ConfigError, load_config

MAX_CONFIG_BYTES = 64 * 1024
DEFAULT_MODEL = "gpt-6-astra"
DEFAULT_REASONING_EFFORT = "medium"
_CONFIG_FILENAME = "graft-model.local.yaml"
_REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max", "ultra"})


class GraftModelConfigError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class GraftModelSelection:
    model: str
    reasoning_effort: str

    def as_dict(self) -> dict[str, str]:
        return {"model": self.model, "reasoningEffort": self.reasoning_effort}


@dataclass(frozen=True)
class GraftModelResolution:
    status: str
    config_path: str
    selection: GraftModelSelection

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "configPath": self.config_path,
            "graftDeep": self.selection.as_dict(),
        }


def graft_model_config_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "SelfWorkFlow" / "config" / _CONFIG_FILENAME
    try:
        home = Path.home()
    except RuntimeError:
        # Test/isolated hosts may deliberately clear environment discovery.
        home = Path.cwd() / ".selfworkflow-machine"
    return home / "AppData" / "Local" / "SelfWorkFlow" / "config" / _CONFIG_FILENAME


def _config_path(path: str | Path | None) -> Path:
    candidate = Path(path) if path is not None else graft_model_config_path()
    if candidate.is_symlink():
        raise GraftModelConfigError("graft-model-config-invalid")
    return candidate.resolve(strict=False)


def _selection(model: object, reasoning_effort: object) -> GraftModelSelection:
    if (
        not isinstance(model, str) or not 1 <= len(model) <= 256
        or model != model.strip() or any(ord(c) < 32 for c in model)
    ):
        raise GraftModelConfigError("graft-model-invalid")
    if not isinstance(reasoning_effort, str) or reasoning_effort not in _REASONING_EFFORTS:
        raise GraftModelConfigError("graft-reasoning-effort-invalid")
    return GraftModelSelection(model, reasoning_effort)


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas" / "graft-model-config.schema.json"


def _config_document(path: Path) -> Any:
    try:
        if path.is_symlink() or (path.exists() and path.stat().st_size > MAX_CONFIG_BYTES):
            raise GraftModelConfigError("graft-model-config-invalid")
        return load_config(path, _schema_path())
    except GraftModelConfigError:
        raise
    except (ConfigError, OSError, UnicodeError, RecursionError):
        raise GraftModelConfigError("graft-model-config-invalid") from None


def resolve_graft_model(path: str | Path | None = None) -> GraftModelResolution:
    config_path = _config_path(path)
    if not config_path.exists():
        return GraftModelResolution(
            "defaulted", str(config_path),
            GraftModelSelection(DEFAULT_MODEL, DEFAULT_REASONING_EFFORT),
        )
    document = _config_document(config_path)
    selected = document["graftDeep"]
    return GraftModelResolution(
        "configured", str(config_path),
        _selection(selected["model"], selected["reasoningEffort"]),
    )


def save_graft_model(
    path: str | Path | None, model: str, reasoning_effort: str, *, confirmed: bool,
) -> GraftModelResolution:
    if confirmed is not True:
        raise GraftModelConfigError("graft-model-confirmation-required")
    selected = _selection(model, reasoning_effort)
    config_path = _config_path(path)
    payload = {"schemaVersion": 1, "graftDeep": selected.as_dict()}
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
        raise GraftModelConfigError("graft-model-config-write-failed") from None
    finally:
        if temporary is not None and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass
    return GraftModelResolution("configured", str(config_path), selected)


def graft_model_context(path: str | Path | None = None) -> tuple[str, str]:
    selected = resolve_graft_model(path).selection
    return selected.model, selected.reasoning_effort
