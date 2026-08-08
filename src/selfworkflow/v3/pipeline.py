"""Strict, deterministic loading for the independent V3 pipeline."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from selfworkflow.v3.catalog import (
    CatalogError,
    _MAX_DOCUMENT_BYTES,
    _canonical_hash,
    _canonical_json,
    _is_reparse_point,
    _json_text,
    _load_yaml_file,
)
from selfworkflow.v3.contracts import ContractError, load_contract


_STAGE_ORDER = (
    "discovered", "capability-checked", "classified", "designed", "planned",
    "implemented", "reviewed", "verified", "completed",
)


class PipelineError(ValueError):
    """Stable V3 pipeline loading failure."""

    def __init__(self, reason: str = "v3-pipeline-invalid") -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class LoadedPipeline:
    document: dict[str, Any]
    content: bytes
    pipeline_hash: str


def load_pipeline(source: object = None) -> LoadedPipeline:
    path = _v3_pipeline_path(source)
    try:
        document = _load_yaml_file(path, _MAX_DOCUMENT_BYTES)
    except CatalogError as error:
        raise PipelineError(error.reason) from None
    except (OverflowError, RecursionError, TypeError, ValueError):
        raise PipelineError("v3-yaml-invalid") from None
    if not isinstance(document, dict):
        raise PipelineError("v3-pipeline-schema-invalid")
    if document.get("schemaVersion") != 3:
        raise PipelineError("v3-pipeline-version-mismatch")
    try:
        validated = load_contract(
            "pipeline.schema.json",
            _json_text(document),
        )
    except ContractError:
        raise PipelineError("v3-pipeline-schema-invalid") from None
    except CatalogError as error:
        raise PipelineError(error.reason) from None
    stage_ids = [stage["id"] for stage in validated["stages"]]
    if tuple(stage_ids) != _STAGE_ORDER:
        raise PipelineError("v3-pipeline-stage-order-invalid")
    slot_ids: set[str] = set()
    for stage in validated["stages"]:
        for slot in stage["slots"]:
            if slot["id"] in slot_ids:
                raise PipelineError("v3-pipeline-slot-duplicate")
            slot_ids.add(slot["id"])
    try:
        content = _canonical_json(validated)
        pipeline_hash = _canonical_hash(validated)
    except CatalogError as error:
        raise PipelineError(error.reason) from None
    return LoadedPipeline(validated, content, pipeline_hash)


def _v3_pipeline_path(source: object) -> Path:
    if source is None:
        source = Path(__file__).resolve().parents[3] / "workflow" / "v3" / "pipeline.yaml"
    try:
        path = Path(source)
        if (
            path.name != "pipeline.yaml"
            or path.parent.name != "v3"
            or path.parent.parent.name != "workflow"
        ):
            raise PipelineError("v3-pipeline-path-invalid")
        root = path.parent.parent.parent
        for part in (root, root / "workflow", root / "workflow" / "v3", path):
            if _is_reparse_point(part):
                raise PipelineError("v3-pipeline-path-reparse")
        if not path.is_file():
            raise PipelineError("v3-pipeline-path-invalid")
        return path
    except PipelineError:
        raise
    except (OSError, TypeError, ValueError):
        raise PipelineError("v3-pipeline-path-invalid") from None
