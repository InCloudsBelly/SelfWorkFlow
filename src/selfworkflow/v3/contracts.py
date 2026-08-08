"""Strict loading and semantic validation for V3 orchestration contracts."""

from datetime import datetime
from functools import lru_cache
import hashlib
import json
from pathlib import Path, PureWindowsPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource


_SCHEMA_NAMES = (
    "catalog.schema.json",
    "module.schema.json",
    "pipeline.schema.json",
    "resolve-request.schema.json",
    "resolve-result.schema.json",
    "plan-graph.schema.json",
    "selection-receipt.schema.json",
    "run-ledger.schema.json",
)
_SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "schemas" / "v3"
_FORMAT_CHECKER = FormatChecker()
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


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


def _canonical_hash(document: dict[str, Any], field: str) -> str:
    material = dict(document)
    material.pop(field, None)
    payload = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _raise_semantic(reason: str, path: tuple[str | int, ...]) -> None:
    raise ContractError(reason, path, "semantic")


def _validate_plan_graph(document: dict[str, Any]) -> None:
    if document["planHash"] != _canonical_hash(document, "planHash"):
        _raise_semantic("plan-hash-invalid", ("planHash",))

    stage_ids: set[str] = set()
    for stage_index, stage in enumerate(document["stages"]):
        if stage["stageId"] in stage_ids:
            _raise_semantic("plan-stage-id-duplicate", ("stages", stage_index, "stageId"))
        stage_ids.add(stage["stageId"])
        if stage["ordinal"] != stage_index + 1:
            _raise_semantic("plan-stage-order-invalid", ("stages", stage_index, "ordinal"))

        slot_ids: set[str] = set()
        for slot_index, slot in enumerate(stage["slots"]):
            if slot["slotId"] in slot_ids:
                _raise_semantic(
                    "plan-slot-id-duplicate",
                    ("stages", stage_index, "slots", slot_index, "slotId"),
                )
            slot_ids.add(slot["slotId"])
            if slot["ordinal"] != slot_index + 1:
                _raise_semantic(
                    "plan-slot-order-invalid",
                    ("stages", stage_index, "slots", slot_index, "ordinal"),
                )
            selected = slot["selectedModules"]
            eligible = set(slot["eligibleModules"])
            for module_index, module_id in enumerate(selected):
                if module_id not in eligible:
                    _raise_semantic(
                        "plan-selected-module-ineligible",
                        (
                            "stages", stage_index, "slots", slot_index,
                            "selectedModules", module_index,
                        ),
                    )
            if slot["applicability"] == "not-applicable" and (selected or eligible):
                _raise_semantic(
                    "plan-inapplicable-slot-not-empty",
                    ("stages", stage_index, "slots", slot_index),
                )
            if slot["selectionMode"] == "static":
                cardinality = slot["cardinality"]
                valid = {
                    "exactly-one": len(selected) == 1,
                    "zero-or-one": len(selected) <= 1,
                    "zero-or-many": True,
                    "gate": len(selected) >= 1,
                }[cardinality]
                if not valid:
                    _raise_semantic(
                        "plan-static-cardinality-invalid",
                        (
                            "stages", stage_index, "slots", slot_index,
                            "selectedModules",
                        ),
                    )
            else:
                if slot["cardinality"] in {"exactly-one", "gate"} and not eligible:
                    _raise_semantic(
                        "plan-runtime-cardinality-invalid",
                        (
                            "stages", stage_index, "slots", slot_index,
                            "eligibleModules",
                        ),
                    )
                if slot["cardinality"] in {"exactly-one", "zero-or-one"} and len(selected) > 1:
                    _raise_semantic(
                        "plan-runtime-cardinality-invalid",
                        (
                            "stages", stage_index, "slots", slot_index,
                            "selectedModules",
                        ),
                    )


def _plan_is_executable(plan: dict[str, Any]) -> bool:
    return any(
        stage["applicability"] == "applicable"
        and any(
            slot["applicability"] == "applicable"
            and bool(slot["selectedModules"] or slot["eligibleModules"])
            for slot in stage["slots"]
        )
        for stage in plan["stages"]
    )


def _validate_resolve_result(document: dict[str, Any]) -> None:
    if document["status"] == "active":
        plan = document["planGraph"]
        if plan is None:
            _raise_semantic("resolve-active-plan-missing", ("planGraph",))
        _validate_plan_graph(plan)
        if not _plan_is_executable(plan):
            _raise_semantic("resolve-active-plan-not-executable", ("planGraph",))


def _validate_selection_receipt(
    document: dict[str, Any],
    plan: dict[str, Any] | None = None,
) -> None:
    if document["receiptHash"] != _canonical_hash(document, "receiptHash"):
        _raise_semantic("selection-receipt-hash-invalid", ("receiptHash",))
    eligible = set(document["eligibleModuleIds"])
    for index, module_id in enumerate(document["selectedModuleIds"]):
        if module_id not in eligible:
            _raise_semantic(
                "selection-receipt-selected-module-ineligible",
                ("selectedModuleIds", index),
            )
    if plan is None:
        return
    if document["planHash"] != plan["planHash"]:
        _raise_semantic("selection-receipt-plan-mismatch", ("planHash",))
    for stage_index, stage in enumerate(plan["stages"]):
        for slot_index, slot in enumerate(stage["slots"]):
            if stage["stageId"] == document["stageId"] and slot["slotId"] == document["slotId"]:
                if document["eligibleModuleIds"] != slot["eligibleModules"]:
                    _raise_semantic(
                        "selection-receipt-eligible-set-mismatch",
                        ("eligibleModuleIds",),
                    )
                return
    _raise_semantic("selection-receipt-slot-mismatch", ("slotId",))


def _validate_run_ledger(
    document: dict[str, Any],
    plan: dict[str, Any] | None = None,
    receipts: tuple[dict[str, Any], ...] = (),
) -> None:
    if document["status"] == "superseded" and document["supersededByPlanHash"] == document["planHash"]:
        _raise_semantic("ledger-superseding-plan-invalid", ("supersededByPlanHash",))

    active_stage_count = sum(stage["status"] == "active" for stage in document["stages"])
    if active_stage_count > 1:
        active_index = next(index for index, stage in enumerate(document["stages"]) if stage["status"] == "active")
        second_index = next(
            index for index, stage in enumerate(document["stages"])
            if index > active_index and stage["status"] == "active"
        )
        _raise_semantic("multiple-active-stages", ("stages", second_index, "status"))

    all_attempt_refs: set[str] = set()
    receipt_by_hash = {receipt["receiptHash"]: receipt for receipt in receipts}
    for stage_index, stage in enumerate(document["stages"]):
        attempts = stage["attempts"]
        local_refs: set[str] = set()
        for attempt_index, attempt in enumerate(attempts):
            ref = attempt["attemptRef"]
            if ref in all_attempt_refs or ref in local_refs:
                _raise_semantic(
                    "ledger-attempt-duplicate",
                    ("stages", stage_index, "attempts", attempt_index, "attemptRef"),
                )
            if attempt["ordinal"] != attempt_index + 1:
                _raise_semantic(
                    "ledger-attempt-order-invalid",
                    ("stages", stage_index, "attempts", attempt_index, "ordinal"),
                )
            expected_previous = attempts[attempt_index - 1]["attemptRef"] if attempt_index else None
            if attempt["previousAttemptRef"] != expected_previous:
                _raise_semantic(
                    "ledger-attempt-chain-invalid",
                    (
                        "stages", stage_index, "attempts", attempt_index,
                        "previousAttemptRef",
                    ),
                )
            local_refs.add(ref)
            all_attempt_refs.add(ref)
        if stage["status"] == "active" and not attempts:
            _raise_semantic("ledger-active-attempt-missing", ("stages", stage_index, "attempts"))
        current_ref = attempts[-1]["attemptRef"] if attempts else None
        for collection in ("slotResults", "gateResults", "runtimeSkips"):
            for item_index, item in enumerate(stage[collection]):
                if item["attemptRef"] not in local_refs:
                    _raise_semantic(
                        "ledger-attempt-unknown",
                        ("stages", stage_index, collection, item_index, "attemptRef"),
                    )
        for ref_index, reference in enumerate(stage["selectionReceiptRefs"]):
            attempt_path = (
                "stages", stage_index, "selectionReceiptRefs", ref_index, "attemptRef"
            )
            if reference["attemptRef"] not in local_refs:
                _raise_semantic("ledger-attempt-unknown", attempt_path)
            if current_ref is not None and reference["attemptRef"] != current_ref:
                _raise_semantic("ledger-receipt-attempt-stale", attempt_path)
            receipt = receipt_by_hash.get(reference["receiptHash"])
            if receipts and receipt is None:
                _raise_semantic("ledger-receipt-ref-invalid", ("stages", stage_index, "selectionReceiptRefs", ref_index, "receiptHash"))
            if receipt is not None:
                if receipt["attemptRef"] != reference["attemptRef"]:
                    _raise_semantic("ledger-receipt-attempt-mismatch", attempt_path)
                if plan is not None:
                    _validate_selection_receipt(receipt, plan)

        if plan is not None and stage["status"] == "passed":
            plan_stage = next(
                (item for item in plan["stages"] if item["stageId"] == stage["stageId"]),
                None,
            )
            if plan_stage is None:
                _raise_semantic("ledger-stage-unknown", ("stages", stage_index, "stageId"))
            current_results = {
                item["moduleId"]
                for item in stage["slotResults"]
                if item["attemptRef"] == current_ref
            }
            required_modules = {
                module_id
                for slot in plan_stage["slots"]
                if slot["applicability"] == "applicable"
                and slot["selectionMode"] == "static"
                for module_id in slot["selectedModules"]
            }
            missing = sorted(required_modules - current_results)
            if missing:
                _raise_semantic(
                    "ledger-current-attempt-incomplete",
                    ("stages", stage_index, "slotResults"),
                )

    if plan is not None:
        if document["planHash"] != plan["planHash"]:
            _raise_semantic("ledger-plan-binding-invalid", ("planHash",))
        if document["requestHash"] != plan["requestHash"]:
            _raise_semantic("ledger-request-binding-invalid", ("requestHash",))
        if document["capabilitySnapshotHash"] != plan["capabilitySnapshotHash"]:
            _raise_semantic("ledger-capability-binding-invalid", ("capabilitySnapshotHash",))


def validate_plan_graph(document: dict[str, Any]) -> None:
    """Validate a V3 PlanGraph schema and its immutable/selection semantics."""

    _validate_schema("plan-graph.schema.json", document)
    _validate_plan_graph(document)


def validate_selection_receipt(
    document: dict[str, Any], plan: dict[str, Any] | None = None
) -> None:
    """Validate a V3 SelectionReceipt, optionally against its PlanGraph."""

    _validate_schema("selection-receipt.schema.json", document)
    _validate_selection_receipt(document, plan)


def validate_run_ledger(
    document: dict[str, Any],
    plan: dict[str, Any] | None = None,
    receipts: tuple[dict[str, Any], ...] = (),
) -> None:
    """Validate a V3 RunLedger, optionally against a plan and receipt set."""

    _validate_schema("run-ledger.schema.json", document)
    _validate_run_ledger(document, plan, receipts)


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
    elif schema_name == "resolve-result.schema.json":
        _validate_resolve_result(document)
    elif schema_name == "plan-graph.schema.json":
        _validate_plan_graph(document)
    elif schema_name == "selection-receipt.schema.json":
        _validate_selection_receipt(document)
    elif schema_name == "run-ledger.schema.json":
        _validate_run_ledger(document)
    return document


def _is_reparse_point(path: Path) -> bool:
    metadata = path.lstat()
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0)
        & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def _module_ref_target(
    module_root: str | Path,
    reference: str,
    module_index: int,
) -> Path:
    error_path = ("modules", module_index, "ref")
    windows_path = PureWindowsPath(reference)
    if (
        windows_path.is_absolute()
        or windows_path.drive
        or windows_path.root
        or not windows_path.parts
        or any(part in {"", ".", ".."} for part in windows_path.parts)
        or ":" in reference
    ):
        raise ContractError(
            "catalog-module-ref-path-invalid",
            error_path,
            "semantic",
        )

    root = Path(module_root)
    try:
        if not root.is_dir():
            raise OSError
        if _is_reparse_point(root):
            raise ContractError(
                "catalog-module-ref-reparse",
                error_path,
                "semantic",
            )
        current = root
        for part in windows_path.parts:
            current /= part
            if _is_reparse_point(current):
                raise ContractError(
                    "catalog-module-ref-reparse",
                    error_path,
                    "semantic",
                )
        if not current.is_file():
            raise OSError
        resolved_root = root.resolve(strict=True)
        resolved_target = current.resolve(strict=True)
        resolved_target.relative_to(resolved_root)
    except ContractError:
        raise
    except (OSError, ValueError):
        raise ContractError(
            "catalog-module-ref-unresolved",
            error_path,
            "semantic",
        ) from None
    return current


def _load_module_ref(
    declaration: dict[str, Any],
    module_root: str | Path,
    module_index: int,
) -> dict[str, Any]:
    target = _module_ref_target(module_root, declaration["ref"], module_index)
    try:
        content = target.read_bytes()
    except OSError:
        raise ContractError(
            "catalog-module-ref-unresolved",
            ("modules", module_index, "ref"),
            "semantic",
        ) from None
    content_hash = "sha256:" + hashlib.sha256(content).hexdigest()
    if content_hash != declaration["hash"]:
        raise ContractError(
            "catalog-module-ref-hash-mismatch",
            ("modules", module_index, "hash"),
            "semantic",
        )
    try:
        module_text = content.decode("utf-8")
    except UnicodeError:
        raise ContractError("contract-json-invalid", validator="json") from None
    module = load_contract("module.schema.json", module_text)
    if module["id"] != declaration["id"]:
        raise ContractError(
            "catalog-module-ref-id-mismatch",
            ("modules", module_index, "id"),
            "semantic",
        )
    return module


def validate_catalog_pipeline(
    catalog: dict[str, Any],
    pipeline: dict[str, Any],
    module_root: str | Path,
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

    resolved_modules = [
        module
        if "stage" in module
        else _load_module_ref(module, module_root, module_index)
        for module_index, module in enumerate(catalog["modules"])
    ]

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

    for module_index, module in enumerate(resolved_modules):
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
