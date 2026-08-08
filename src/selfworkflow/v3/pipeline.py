"""Strict, deterministic loading for the independent V3 pipeline."""

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


class LoadedPipeline:
    """Artifact issued only after the V3 pipeline loader succeeds."""

    __slots__ = ("_document", "_content", "_pipeline_hash", "__seal")

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("LoadedPipeline is issued by load_pipeline")

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("LoadedPipeline is immutable")

    @property
    def document(self) -> dict[str, Any]:
        return self._document

    @property
    def content(self) -> bytes:
        return self._content

    @property
    def pipeline_hash(self) -> str:
        return self._pipeline_hash

    def _has_valid_seal(self) -> bool:
        return getattr(self, "_LoadedPipeline__seal", None) is _PIPELINE_SEAL


_PIPELINE_SEAL = object()


def _issue_loaded_pipeline(
    document: dict[str, Any], content: bytes, pipeline_hash: str,
) -> LoadedPipeline:
    artifact = object.__new__(LoadedPipeline)
    object.__setattr__(artifact, "_document", document)
    object.__setattr__(artifact, "_content", content)
    object.__setattr__(artifact, "_pipeline_hash", pipeline_hash)
    object.__setattr__(artifact, "_LoadedPipeline__seal", _PIPELINE_SEAL)
    return artifact


def load_pipeline(source: object = None) -> LoadedPipeline:
    path = _v3_pipeline_path(source)
    try:
        document = _load_yaml_file(path, _MAX_DOCUMENT_BYTES, path.parents[2])
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
    _validate_pipeline_semantics(validated)
    try:
        content = _canonical_json(validated)
        pipeline_hash = _canonical_hash(validated)
    except CatalogError as error:
        raise PipelineError(error.reason) from None
    return _issue_loaded_pipeline(validated, content, pipeline_hash)


def _validate_pipeline_semantics(document: dict[str, Any]) -> None:
    stage_ids = [stage["id"] for stage in document["stages"]]
    if tuple(stage_ids) != _STAGE_ORDER:
        raise PipelineError("v3-pipeline-stage-order-invalid")
    slot_ids: set[str] = set()
    for stage in document["stages"]:
        for slot in stage["slots"]:
            if slot["id"] in slot_ids:
                raise PipelineError("v3-pipeline-slot-duplicate")
            slot_ids.add(slot["id"])


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
