"""Bounded loading and identity for the vendor-neutral workflow Pipeline."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from selfworkflow.config import ConfigError, load_config


_STAGE_ORDER = (
    "discovered", "capability-checked", "classified", "designed", "planned",
    "implemented", "reviewed", "verified", "completed",
)


class PipelineError(ValueError):
    def __init__(self, code: str = "pipeline-invalid") -> None:
        self.code = code
        super().__init__(code)


def canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class CompiledPipeline:
    document: Mapping[str, Any]
    pipeline_hash: str

    def mutable_document(self) -> dict[str, Any]:
        return deepcopy(_thaw(self.document))


def _load_schema(schema_path: str | Path) -> dict[str, object]:
    try:
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except Exception:
        raise PipelineError("pipeline-schema-invalid") from None
    return schema


def load_pipeline(
    source: str | Path | Mapping[str, object], schema_path: str | Path
) -> CompiledPipeline:
    """Load, validate, semantically close, and hash a Pipeline document."""

    try:
        if isinstance(source, Mapping):
            document = deepcopy(dict(source))
            errors = list(Draft202012Validator(_load_schema(schema_path)).iter_errors(document))
            if errors:
                raise PipelineError()
        else:
            document = _thaw(load_config(source, schema_path))
    except PipelineError:
        raise
    except ConfigError:
        raise PipelineError() from None
    except Exception:
        raise PipelineError() from None

    stages = document["stages"]
    if tuple(stage["id"] for stage in stages) != _STAGE_ORDER:
        raise PipelineError("pipeline-stage-order-invalid")
    slot_ids: list[str] = []
    for stage in stages:
        slot_ids.extend(slot["id"] for slot in stage["slots"])
    if len(slot_ids) != len(set(slot_ids)):
        raise PipelineError("pipeline-slot-duplicate")
    frozen = _freeze(document)
    return CompiledPipeline(frozen, canonical_hash(document))
