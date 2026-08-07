"""Load schema-validated SelfWorkFlow YAML configuration."""

import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry
from referencing.exceptions import NoSuchResource, Unresolvable


MAX_YAML_DEPTH = 64
MAX_YAML_NODES = 1024


class ConfigError(ValueError):
    """Stable, redacted configuration loading failure."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class _DuplicateKeyError(ValueError):
    pass


class _YamlResourceError(yaml.YAMLError):
    pass


class _StrictSafeLoader(yaml.SafeLoader):
    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self._compose_depth = 0
        self._compose_nodes = 0

    def compose_node(self, parent: yaml.Node | None, index: object) -> yaml.Node:
        if self.check_event(yaml.events.AliasEvent):
            raise _YamlResourceError
        self._compose_nodes += 1
        if self._compose_nodes > MAX_YAML_NODES:
            raise _YamlResourceError
        self._compose_depth += 1
        try:
            if self._compose_depth > MAX_YAML_DEPTH:
                raise _YamlResourceError
            return super().compose_node(parent, index)
        except RecursionError:
            raise _YamlResourceError from None
        finally:
            self._compose_depth -= 1


def _deny_reference_retrieval(uri: str):
    raise NoSuchResource(ref=uri)


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _construct_unique_yaml_mapping(
    loader: _StrictSafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            if key in result:
                raise _DuplicateKeyError
            value = loader.construct_object(value_node, deep=deep)
            result[key] = value
        except Exception:
            raise _DuplicateKeyError from None
    return result


_StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_yaml_mapping,
)


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
        schema = json.loads(
            schema_text,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (json.JSONDecodeError, UnicodeError, _DuplicateKeyError):
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
        document = yaml.load(document_text, Loader=_StrictSafeLoader)
    except Exception:
        raise ConfigError("document-invalid") from None
    _require_json_data(document)
    try:
        validator = Draft202012Validator(
            schema,
            registry=Registry(retrieve=_deny_reference_retrieval),
        )
        errors = sorted(
            validator.iter_errors(document),
            key=lambda error: (
                tuple(str(item) for item in error.absolute_path),
                error.validator,
            ),
        )
    except Unresolvable:
        raise ConfigError("schema-reference-unavailable") from None
    if errors:
        raise ConfigError("configuration-invalid")
    return _freeze(document)
