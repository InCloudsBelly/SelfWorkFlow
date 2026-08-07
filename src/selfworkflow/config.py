"""Load schema-validated SelfWorkFlow YAML configuration."""

import json
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
    validator = Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(document),
        key=lambda error: (tuple(str(item) for item in error.absolute_path), error.validator),
    )
    if errors:
        raise ConfigError("configuration-invalid")
    return _freeze(document)
