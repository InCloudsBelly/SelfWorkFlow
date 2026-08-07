"""Load schema-validated SelfWorkFlow YAML configuration."""

import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


class ConfigError(ValueError):
    """Stable, redacted configuration loading failure."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _require_json_data(value: Any, active_containers: set[int] | None = None) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if math.isfinite(value):
            return
        raise ConfigError("document-data-invalid")
    if not isinstance(value, (dict, list)):
        raise ConfigError("document-data-invalid")

    active = active_containers if active_containers is not None else set()
    identity = id(value)
    if identity in active:
        raise ConfigError("document-data-invalid")
    active.add(identity)
    try:
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ConfigError("document-data-invalid")
            for item in value.values():
                _require_json_data(item, active)
        else:
            for item in value:
                _require_json_data(item, active)
    finally:
        active.remove(identity)


def load_config(document_path: str | Path, schema_path: str | Path) -> Any:
    """Load YAML from explicit paths and validate it as Draft 2020-12 JSON Schema."""

    try:
        schema_text = Path(schema_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise ConfigError("schema-read-failed") from None
    try:
        schema = json.loads(schema_text)
    except (json.JSONDecodeError, UnicodeError):
        raise ConfigError("schema-invalid") from None
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        raise ConfigError("schema-invalid") from None
    try:
        document_text = Path(document_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise ConfigError("document-read-failed") from None
    try:
        document = yaml.safe_load(document_text)
    except yaml.YAMLError:
        raise ConfigError("document-invalid") from None
    _require_json_data(document)
    validator = Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(document),
        key=lambda error: (tuple(str(item) for item in error.absolute_path), error.validator),
    )
    if errors:
        raise ConfigError("configuration-invalid")
    return _freeze(document)
