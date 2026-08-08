"""Strict loading and semantic validation for V3 orchestration contracts."""

from datetime import datetime
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource


_SCHEMA_NAMES = (
    "catalog.schema.json",
    "module.schema.json",
    "pipeline.schema.json",
    "resolve-request.schema.json",
)
_SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "schemas" / "v3"
_FORMAT_CHECKER = FormatChecker()


@_FORMAT_CHECKER.checks("date-time", raises=ValueError)
def _is_calendar_datetime(value: object) -> bool:
    if not isinstance(value, str):
        return True
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return True


class ContractError(ValueError):
    """Stable contract validation failure."""

    def __init__(
        self,
        reason: str,
        path: tuple[str | int, ...] = (),
        validator: str | None = None,
    ) -> None:
        self.reason = reason
        self.path = path
        self.validator = validator
        super().__init__(reason)


class _DuplicateKeyError(ValueError):
    pass


class _InvalidJsonConstantError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise _InvalidJsonConstantError


@lru_cache(maxsize=1)
def _schema_bundle() -> tuple[dict[str, dict[str, Any]], Registry]:
    schemas: dict[str, dict[str, Any]] = {}
    resources: list[tuple[str, Resource[Any]]] = []
    try:
        for schema_name in _SCHEMA_NAMES:
            schema = json.loads(
                (_SCHEMA_ROOT / schema_name).read_text(encoding="utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
            Draft202012Validator.check_schema(schema)
            schema_id = schema["$id"]
            if not isinstance(schema_id, str):
                raise SchemaError("missing schema id")
            schemas[schema_name] = schema
            resources.append((schema_id, Resource.from_contents(schema)))
    except Exception:
        raise ContractError(
            "contract-schema-unavailable",
            validator="schema",
        ) from None
    return schemas, Registry().with_resources(resources)


def _validation_error_key(error: Any) -> tuple[tuple[str, ...], str]:
    path = tuple(f"{type(part).__name__}:{part}" for part in error.absolute_path)
    return path, str(error.validator)


def _validation_error_path(error: Any) -> tuple[str | int, ...]:
    path = tuple(error.absolute_path)
    if error.validator == "additionalProperties" and isinstance(error.instance, dict):
        properties = error.schema.get("properties", {})
        unexpected = sorted(set(error.instance) - set(properties))
        if unexpected:
            return path + (unexpected[0],)
    return path


def _validate_schema(schema_name: str, document: dict[str, Any]) -> None:
    schemas, registry = _schema_bundle()
    validator = Draft202012Validator(
        schemas[schema_name],
        registry=registry,
        format_checker=_FORMAT_CHECKER,
    )
    errors = sorted(validator.iter_errors(document), key=_validation_error_key)
    if errors:
        error = errors[0]
        raise ContractError(
            "contract-schema-invalid",
            _validation_error_path(error),
            str(error.validator),
        )


def _utc_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _validate_resolve_request(document: dict[str, Any]) -> None:
    snapshot = document["capabilityEvidenceSnapshot"]
    captured_at = _utc_datetime(snapshot["capturedAt"])
    for index, evidence in enumerate(snapshot["evidence"]):
        observed_at = _utc_datetime(evidence["observedAt"])
        valid_until = _utc_datetime(evidence["validUntil"])
        base_path = ("capabilityEvidenceSnapshot", "evidence", index)
        if observed_at > captured_at:
            raise ContractError(
                "resolve-evidence-observed-after-capture",
                base_path + ("observedAt",),
                "semantic",
            )
        if captured_at > valid_until:
            raise ContractError(
                "resolve-evidence-expired-at-capture",
                base_path + ("validUntil",),
                "semantic",
            )


def load_contract(schema_name: str, text: str) -> dict[str, Any]:
    """Load one registered V3 JSON contract."""

    if schema_name not in _SCHEMA_NAMES:
        raise ContractError(
            "contract-schema-not-registered",
            validator="schemaName",
        )
    try:
        document = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except _DuplicateKeyError:
        raise ContractError(
            "contract-json-duplicate-key",
            validator="uniqueKeys",
        ) from None
    except (json.JSONDecodeError, UnicodeError, _InvalidJsonConstantError, RecursionError):
        raise ContractError("contract-json-invalid", validator="json") from None
    if not isinstance(document, dict):
        raise ContractError("contract-root-not-object", validator="type")
    _validate_schema(schema_name, document)
    if schema_name == "resolve-request.schema.json":
        _validate_resolve_request(document)
    return document


def validate_catalog_pipeline(
    catalog: dict[str, Any],
    pipeline: dict[str, Any],
) -> None:
    """Validate semantic links between a V3 Catalog and Pipeline."""

    _validate_schema("catalog.schema.json", catalog)
    _validate_schema("pipeline.schema.json", pipeline)

    seen_domains: set[str] = set()
    for index, domain in enumerate(catalog["domains"]):
        domain_id = domain["id"]
        if domain_id in seen_domains:
            raise ContractError(
                "catalog-domain-id-duplicate",
                ("domains", index, "id"),
                "semantic",
            )
        seen_domains.add(domain_id)

    seen_modules: set[str] = set()
    for index, module in enumerate(catalog["modules"]):
        module_id = module["id"]
        if module_id in seen_modules:
            raise ContractError(
                "catalog-module-id-duplicate",
                ("modules", index, "id"),
                "semantic",
            )
        seen_modules.add(module_id)

    stages: dict[str, dict[str, Any]] = {}
    seen_slots: set[str] = set()
    for stage_index, stage in enumerate(pipeline["stages"]):
        stage_id = stage["id"]
        if stage_id in stages:
            raise ContractError(
                "pipeline-stage-id-duplicate",
                ("stages", stage_index, "id"),
                "semantic",
            )
        stages[stage_id] = stage
        for slot_index, slot in enumerate(stage["slots"]):
            slot_id = slot["id"]
            if slot_id in seen_slots:
                raise ContractError(
                    "pipeline-slot-id-duplicate",
                    ("stages", stage_index, "slots", slot_index, "id"),
                    "semantic",
                )
            seen_slots.add(slot_id)

    for module_index, module in enumerate(catalog["modules"]):
        if "stage" not in module:
            continue
        stage = stages.get(module["stage"])
        if stage is None:
            raise ContractError(
                "catalog-module-stage-unknown",
                ("modules", module_index, "stage"),
                "semantic",
            )
        slots = {slot["id"]: slot for slot in stage["slots"]}
        slot = slots.get(module["slot"])
        if slot is None:
            raise ContractError(
                "catalog-module-slot-unknown",
                ("modules", module_index, "slot"),
                "semantic",
            )
        if module["invocation"]["kind"] not in slot["allowedInvocationKinds"]:
            raise ContractError(
                "catalog-module-invocation-kind-not-allowed",
                ("modules", module_index, "invocation", "kind"),
                "semantic",
            )
        if module["selectionMode"] != slot["selectionMode"]:
            raise ContractError(
                "catalog-module-selection-mode-mismatch",
                ("modules", module_index, "selectionMode"),
                "semantic",
            )
