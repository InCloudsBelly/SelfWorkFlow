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
    "diff-signal-set.schema.json",
    "review-finding.schema.json",
    "review-aggregate.schema.json",
    "test-strategy.schema.json",
    "coverage-result.schema.json",
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


def _validate_artifact_binding(
    document: dict[str, Any],
    diff_signal_set: dict[str, Any],
    artifact_name: str,
) -> None:
    bindings = (
        ("planHash", "plan-mismatch"),
        ("attemptRef", "attempt-mismatch"),
        ("finalDiffHash", "final-diff-mismatch"),
    )
    for field, suffix in bindings:
        if document[field] != diff_signal_set[field]:
            _raise_semantic(
                f"{artifact_name}-{suffix}",
                (field,),
            )
    if "diffSignalSetHash" in document and document["diffSignalSetHash"] != diff_signal_set["signalSetHash"]:
        _raise_semantic(
            f"{artifact_name}-diff-mismatch",
            ("diffSignalSetHash",),
        )


def _validate_diff_signal_set(document: dict[str, Any]) -> None:
    if document["signalSetHash"] != _canonical_hash(document, "signalSetHash"):
        _raise_semantic("diff-signal-set-hash-invalid", ("signalSetHash",))
    paths: set[str] = set()
    languages = set(document["languages"])
    for index, file in enumerate(document["files"]):
        if file["path"] in paths:
            _raise_semantic("diff-signal-set-file-duplicate", ("files", index, "path"))
        paths.add(file["path"])
        if file["language"] not in languages:
            _raise_semantic("diff-signal-set-language-missing", ("files", index, "language"))


def _validate_review_finding(
    document: dict[str, Any],
    diff_signal_set: dict[str, Any] | None = None,
) -> None:
    if document["findingHash"] != _canonical_hash(document, "findingHash"):
        _raise_semantic("review-finding-hash-invalid", ("findingHash",))
    if diff_signal_set is not None:
        _validate_artifact_binding(document, diff_signal_set, "review-finding")


def _validate_review_aggregate(
    document: dict[str, Any],
    diff_signal_set: dict[str, Any] | None = None,
    findings: tuple[dict[str, Any], ...] = (),
) -> None:
    if document["aggregateHash"] != _canonical_hash(document, "aggregateHash"):
        _raise_semantic("review-aggregate-hash-invalid", ("aggregateHash",))
    if diff_signal_set is not None:
        _validate_artifact_binding(document, diff_signal_set, "review-aggregate")
    if document["findingHashes"] and not findings:
        _raise_semantic("review-aggregate-findings-required", ("findingHashes",))
    finding_by_hash: dict[str, dict[str, Any]] = {}
    if findings:
        finding_by_hash = {finding["findingHash"]: finding for finding in findings}
        if len(finding_by_hash) != len(findings):
            _raise_semantic("review-aggregate-finding-hash-duplicate", ("findingHashes",))
        if set(document["findingHashes"]) != set(finding_by_hash):
            _raise_semantic("review-aggregate-finding-set-mismatch", ("findingHashes",))
        for index, finding_hash in enumerate(document["findingHashes"]):
            finding = finding_by_hash[finding_hash]
            for field in ("planHash", "attemptRef", "finalDiffHash", "diffSignalSetHash"):
                if finding[field] != document[field]:
                    _raise_semantic(
                        "review-aggregate-finding-binding-mismatch",
                        ("findingHashes", index),
                    )
            _validate_review_finding(finding, diff_signal_set)
    finding_hashes = set(document["findingHashes"])
    dedup_assignments: set[str] = set()
    dedup_fingerprints: set[str] = set()
    for index, group in enumerate(document["dedupGroups"]):
        group_hashes = set(group["findingHashes"])
        if not group_hashes <= finding_hashes:
            _raise_semantic("review-aggregate-dedup-finding-unknown", ("dedupGroups", index, "findingHashes"))
        if group["representativeFindingHash"] not in group_hashes:
            _raise_semantic("review-aggregate-dedup-representative-invalid", ("dedupGroups", index, "representativeFindingHash"))
        for hash_index, finding_hash in enumerate(group["findingHashes"]):
            if finding_hash in dedup_assignments:
                _raise_semantic("review-aggregate-dedup-overlap", ("dedupGroups", index, "findingHashes", hash_index))
            dedup_assignments.add(finding_hash)
            if findings and finding_by_hash[finding_hash]["fingerprint"] != group["fingerprint"]:
                _raise_semantic("review-aggregate-dedup-fingerprint-mismatch", ("dedupGroups", index, "findingHashes", hash_index))
        if group["fingerprint"] in dedup_fingerprints:
            _raise_semantic("review-aggregate-dedup-fingerprint-duplicate", ("dedupGroups", index, "fingerprint"))
        dedup_fingerprints.add(group["fingerprint"])
    if dedup_assignments != finding_hashes:
        _raise_semantic("review-aggregate-dedup-incomplete", ("dedupGroups",))
    representative_hashes = {
        group["representativeFindingHash"]
        for group in document["dedupGroups"]
    }
    conflict_ids: set[str] = set()
    conflict_assignments: set[str] = set()
    for index, conflict in enumerate(document["conflictAdjudications"]):
        if conflict["conflictId"] in conflict_ids:
            _raise_semantic(
                "review-aggregate-conflict-id-duplicate",
                ("conflictAdjudications", index, "conflictId"),
            )
        conflict_ids.add(conflict["conflictId"])
        if conflict["decision"] == "pending":
            _raise_semantic(
                "review-aggregate-conflict-unadjudicated",
                ("conflictAdjudications", index, "decision"),
            )
        for hash_index, finding_hash in enumerate(conflict["findingHashes"]):
            path = ("conflictAdjudications", index, "findingHashes", hash_index)
            if finding_hash not in representative_hashes:
                _raise_semantic("review-aggregate-conflict-finding-unknown", path)
            if finding_hash in conflict_assignments:
                _raise_semantic("review-aggregate-conflict-overlap", path)
            conflict_assignments.add(finding_hash)
    root_cause_owners: set[str] = set()
    root_cause_assignments: set[str] = set()
    for index, coverage in enumerate(document["rootCauseCoverage"]):
        owner_duplicate = coverage["rootCauseOwner"] in root_cause_owners
        for hash_index, finding_hash in enumerate(coverage["findingHashes"]):
            path = ("rootCauseCoverage", index, "findingHashes", hash_index)
            if finding_hash not in representative_hashes:
                _raise_semantic("review-aggregate-root-cause-finding-unknown", path)
            if finding_hash in root_cause_assignments:
                _raise_semantic("review-aggregate-root-cause-overlap", path)
            if findings and finding_by_hash[finding_hash]["rootCauseOwner"] != coverage["rootCauseOwner"]:
                _raise_semantic(
                    "review-aggregate-root-cause-owner-mismatch",
                    ("rootCauseCoverage", index, "rootCauseOwner"),
                )
            root_cause_assignments.add(finding_hash)
        if owner_duplicate:
            _raise_semantic(
                "review-aggregate-root-cause-owner-duplicate",
                ("rootCauseCoverage", index, "rootCauseOwner"),
            )
        root_cause_owners.add(coverage["rootCauseOwner"])
    if root_cause_assignments != representative_hashes:
        _raise_semantic("review-aggregate-root-cause-incomplete", ("rootCauseCoverage",))


_TEST_LEVEL_ORDER = {"T0": 0, "T1": 1, "T2": 2, "T3": 3}


def _validate_test_strategy(
    document: dict[str, Any],
    diff_signal_set: dict[str, Any] | None = None,
) -> None:
    if document["strategyHash"] != _canonical_hash(document, "strategyHash"):
        _raise_semantic("test-strategy-hash-invalid", ("strategyHash",))
    if diff_signal_set is not None:
        _validate_artifact_binding(document, diff_signal_set, "test-strategy")
    if _TEST_LEVEL_ORDER[document["testLevelFloor"]] > _TEST_LEVEL_ORDER[document["testLevel"]]:
        _raise_semantic("test-strategy-floor-invalid", ("testLevelFloor",))
    if document["grillMeImplementation"] and (
        _TEST_LEVEL_ORDER[document["testLevel"]] < _TEST_LEVEL_ORDER["T2"]
        or _TEST_LEVEL_ORDER[document["testLevelFloor"]] < _TEST_LEVEL_ORDER["T2"]
    ):
        _raise_semantic("test-strategy-grill-me-floor-invalid", ("testLevel",))

    risk_ids = {risk["riskId"] for risk in document["risks"]}
    condition_ids = {condition["conditionId"] for condition in document["acceptanceConditions"]}
    technique_ids = {technique["techniqueId"] for technique in document["techniques"]}
    obligation_ids: set[str] = set()
    for risk_index, risk in enumerate(document["risks"]):
        if len(risk_ids) != len(document["risks"]):
            _raise_semantic("test-strategy-risk-duplicate", ("risks", risk_index, "riskId"))
        if not set(risk["acceptanceConditionIds"]) <= condition_ids:
            _raise_semantic("test-strategy-acceptance-condition-unknown", ("risks", risk_index))
    dimension_ids = {
        dimension: set(values)
        for dimension, values in document["dimensions"].items()
    }
    for obligation_index, obligation in enumerate(document["coverageObligations"]):
        if obligation["obligationId"] in obligation_ids:
            _raise_semantic("test-strategy-obligation-duplicate", ("coverageObligations", obligation_index, "obligationId"))
        obligation_ids.add(obligation["obligationId"])
        if obligation["riskId"] not in risk_ids:
            _raise_semantic("test-strategy-risk-unknown", ("coverageObligations", obligation_index, "riskId"))
        if not set(obligation["techniqueIds"]) <= technique_ids:
            _raise_semantic("test-strategy-technique-unknown", ("coverageObligations", obligation_index))
        if not set(obligation["acceptanceConditionIds"]) <= condition_ids:
            _raise_semantic("test-strategy-acceptance-condition-unknown", ("coverageObligations", obligation_index))
        if obligation["obligationId"] not in dimension_ids[obligation["dimension"]]:
            _raise_semantic("test-strategy-dimension-mismatch", ("coverageObligations", obligation_index, "dimension"))


def _validate_coverage_result(
    document: dict[str, Any],
    diff_signal_set: dict[str, Any] | None = None,
    test_strategy: dict[str, Any] | None = None,
) -> None:
    if document["resultHash"] != _canonical_hash(document, "resultHash"):
        _raise_semantic("coverage-result-hash-invalid", ("resultHash",))
    if diff_signal_set is not None:
        _validate_artifact_binding(document, diff_signal_set, "coverage-result")
    if test_strategy is None:
        _raise_semantic("coverage-strategy-required", ())
    _validate_test_strategy(test_strategy, diff_signal_set)
    for field in ("planHash", "attemptRef", "finalDiffHash", "diffSignalSetHash"):
        if document[field] != test_strategy[field]:
            _raise_semantic("coverage-strategy-binding-mismatch", (field,))
    if document["strategyHash"] != test_strategy["strategyHash"]:
        _raise_semantic("coverage-strategy-mismatch", ("strategyHash",))
    expected = {item["obligationId"] for item in test_strategy["coverageObligations"]}
    actual: list[str] = []
    seen_obligations: set[str] = set()
    for index, item in enumerate(document["obligations"]):
        obligation_id = item["obligationId"]
        if obligation_id in seen_obligations:
            _raise_semantic(
                "coverage-obligation-id-duplicate",
                ("obligations", index, "obligationId"),
            )
        seen_obligations.add(obligation_id)
        actual.append(obligation_id)
    if set(actual) != expected:
        _raise_semantic("coverage-obligations-mismatch", ("obligations",))
    for index, item in enumerate(document["obligations"]):
        if item["status"] != "fulfilled":
            continue
        invocation = item["invocationEvidence"]
        result = item["resultEvidence"]
        if invocation["invocationHash"] != _canonical_hash(invocation, "invocationHash"):
            _raise_semantic(
                "coverage-invocation-hash-invalid",
                ("obligations", index, "invocationEvidence", "invocationHash"),
            )
        if result["resultHash"] != _canonical_hash(result, "resultHash"):
            _raise_semantic(
                "coverage-execution-result-hash-invalid",
                ("obligations", index, "resultEvidence", "resultHash"),
            )
        if result["invocationHash"] != invocation["invocationHash"]:
            _raise_semantic(
                "coverage-result-invocation-mismatch",
                ("obligations", index, "resultEvidence", "invocationHash"),
            )
        if invocation["inputHash"] != test_strategy["strategyHash"]:
            _raise_semantic(
                "coverage-invocation-input-mismatch",
                ("obligations", index, "invocationEvidence", "inputHash"),
            )
        if _utc_datetime(result["completedAt"]) < _utc_datetime(invocation["startedAt"]):
            _raise_semantic(
                "coverage-result-time-invalid",
                ("obligations", index, "resultEvidence", "completedAt"),
            )
        if result["exitCode"] != 0:
            _raise_semantic(
                "coverage-result-exit-unsuccessful",
                ("obligations", index, "resultEvidence", "exitCode"),
            )
    if document["passed"] and any(item["status"] != "fulfilled" for item in document["obligations"]):
        _raise_semantic("coverage-passed-with-unfulfilled", ("passed",))


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
    stage = next(
        (item for item in plan["stages"] if item["stageId"] == document["stageId"]),
        None,
    )
    if stage is None:
        _raise_semantic("selection-receipt-stage-mismatch", ("stageId",))
    slot = next(
        (item for item in stage["slots"] if item["slotId"] == document["slotId"]),
        None,
    )
    if slot is None:
        _raise_semantic("selection-receipt-slot-mismatch", ("slotId",))
    if document["eligibleModuleIds"] != slot["eligibleModules"]:
        _raise_semantic(
            "selection-receipt-eligible-set-mismatch",
            ("eligibleModuleIds",),
        )
    selected = document["selectedModuleIds"]
    if slot["selectionMode"] == "static" and selected != slot["selectedModules"]:
        _raise_semantic(
            "selection-receipt-static-selection-mismatch",
            ("selectedModuleIds",),
        )
    cardinality_valid = {
        "exactly-one": len(selected) == 1,
        "zero-or-one": len(selected) <= 1,
        "zero-or-many": True,
        "gate": len(selected) >= 1,
    }[slot["cardinality"]]
    if not cardinality_valid:
        _raise_semantic(
            "selection-receipt-cardinality-invalid",
            ("selectedModuleIds",),
        )


def _validate_run_ledger(
    document: dict[str, Any],
    plan: dict[str, Any] | None = None,
    receipts: tuple[dict[str, Any], ...] = (),
    expected_successor_plan_hash: str | None = None,
) -> None:
    status = document["status"]
    if status == "superseded":
        successor = document["supersededByPlanHash"]
        if successor == document["planHash"]:
            _raise_semantic("ledger-superseding-plan-invalid", ("supersededByPlanHash",))
        if expected_successor_plan_hash is None:
            _raise_semantic("ledger-successor-plan-required", ("supersededByPlanHash",))
        if successor != expected_successor_plan_hash:
            _raise_semantic("ledger-successor-plan-mismatch", ("supersededByPlanHash",))
    elif expected_successor_plan_hash is not None:
        _raise_semantic("ledger-successor-plan-unexpected", ())

    if plan is not None:
        if document["planHash"] != plan["planHash"]:
            _raise_semantic("ledger-plan-binding-invalid", ("planHash",))
        if document["requestHash"] != plan["requestHash"]:
            _raise_semantic("ledger-request-binding-invalid", ("requestHash",))
        if document["capabilitySnapshotHash"] != plan["capabilitySnapshotHash"]:
            _raise_semantic("ledger-capability-binding-invalid", ("capabilitySnapshotHash",))
    plan_stages = {item["stageId"]: item for item in plan["stages"]} if plan else {}
    if plan is not None:
        expected_stage_ids = [item["stageId"] for item in plan["stages"]]
        actual_stage_ids = [item["stageId"] for item in document["stages"]]
        seen_stage_ids: set[str] = set()
        for stage_index, stage_id in enumerate(actual_stage_ids):
            if stage_id in seen_stage_ids:
                _raise_semantic(
                    "ledger-stage-id-duplicate",
                    ("stages", stage_index, "stageId"),
                )
            seen_stage_ids.add(stage_id)
            if stage_id not in plan_stages:
                _raise_semantic(
                    "ledger-stage-unknown",
                    ("stages", stage_index, "stageId"),
                )
        if len(actual_stage_ids) != len(expected_stage_ids):
            _raise_semantic("ledger-stage-list-mismatch", ("stages",))
        if actual_stage_ids != expected_stage_ids:
            _raise_semantic("ledger-stage-order-mismatch", ("stages",))
    stage_statuses = [stage["status"] for stage in document["stages"]]
    active_count = stage_statuses.count("active")
    if active_count > 1:
        second = [index for index, value in enumerate(stage_statuses) if value == "active"][1]
        _raise_semantic("multiple-active-stages", ("stages", second, "status"))
    prefix_done = {"passed", "skipped"}
    suffix_waiting = {"pending", "skipped"}
    if status == "pending":
        status_valid = all(item in suffix_waiting for item in stage_statuses)
    elif status in {"active", "paused", "failed"}:
        marker = status
        marker_indexes = [
            index for index, value in enumerate(stage_statuses)
            if value == marker
        ]
        status_valid = len(marker_indexes) == 1
        if status_valid:
            marker_index = marker_indexes[0]
            status_valid = (
                all(item in prefix_done for item in stage_statuses[:marker_index])
                and all(item in suffix_waiting for item in stage_statuses[marker_index + 1:])
            )
    elif status == "completed":
        status_valid = all(item in prefix_done for item in stage_statuses)
    else:
        status_valid = active_count == 0
    if not status_valid:
        _raise_semantic(f"ledger-status-{status}-invalid", ("status",))

    all_attempt_refs: set[str] = set()
    receipt_by_hash = {receipt["receiptHash"]: receipt for receipt in receipts}
    for stage_index, stage in enumerate(document["stages"]):
        plan_stage = plan_stages.get(stage["stageId"]) if plan else None
        if plan is not None and plan_stage is None:
            _raise_semantic("ledger-stage-unknown", ("stages", stage_index, "stageId"))
        execution_fields = (
            "attempts", "slotResults", "gateResults", "runtimeSkips",
            "selectionReceiptRefs", "reviewAggregateHashes",
            "coverageResultHashes", "artifactHashes",
        )
        if stage["status"] == "skipped" and any(stage[field] for field in execution_fields):
            _raise_semantic("ledger-skipped-stage-has-execution", ("stages", stage_index))

        attempts = stage["attempts"]
        local_refs: set[str] = set()
        for attempt_index, attempt in enumerate(attempts):
            path = ("stages", stage_index, "attempts", attempt_index)
            ref = attempt["attemptRef"]
            if ref in all_attempt_refs:
                _raise_semantic("ledger-attempt-duplicate", path + ("attemptRef",))
            if attempt["ordinal"] != attempt_index + 1:
                _raise_semantic("ledger-attempt-order-invalid", path + ("ordinal",))
            previous = attempts[attempt_index - 1]["attemptRef"] if attempt_index else None
            if attempt["previousAttemptRef"] != previous:
                _raise_semantic("ledger-attempt-chain-invalid", path + ("previousAttemptRef",))
            if "completedAt" in attempt and _utc_datetime(attempt["completedAt"]) < _utc_datetime(attempt["startedAt"]):
                _raise_semantic("ledger-attempt-time-invalid", path + ("completedAt",))
            is_latest = attempt_index == len(attempts) - 1
            if stage["status"] == "active" and is_latest and "completedAt" in attempt:
                _raise_semantic("ledger-active-attempt-completed", path + ("completedAt",))
            if (stage["status"] != "active" or not is_latest) and "completedAt" not in attempt:
                _raise_semantic("ledger-attempt-incomplete", path + ("completedAt",))
            local_refs.add(ref)
            all_attempt_refs.add(ref)
        if stage["status"] == "active" and not attempts:
            _raise_semantic("ledger-active-attempt-missing", ("stages", stage_index, "attempts"))
        current_ref = attempts[-1]["attemptRef"] if attempts else None

        verified: dict[tuple[str, str], set[str]] = {}
        for ref_index, reference in enumerate(stage["selectionReceiptRefs"]):
            base = ("stages", stage_index, "selectionReceiptRefs", ref_index)
            if reference["attemptRef"] not in local_refs:
                _raise_semantic("ledger-attempt-unknown", base + ("attemptRef",))
            if reference["attemptRef"] != current_ref:
                _raise_semantic("ledger-receipt-attempt-stale", base + ("attemptRef",))
            receipt = receipt_by_hash.get(reference["receiptHash"])
            if receipt is None:
                if plan is not None or receipts:
                    _raise_semantic("ledger-receipt-ref-invalid", base + ("receiptHash",))
                continue
            if receipt["planHash"] != document["planHash"]:
                _raise_semantic("ledger-receipt-plan-mismatch", base + ("receiptHash",))
            if receipt["stageId"] != stage["stageId"]:
                _raise_semantic("ledger-receipt-stage-mismatch", base + ("receiptHash",))
            if receipt["attemptRef"] != reference["attemptRef"]:
                _raise_semantic("ledger-receipt-attempt-mismatch", base + ("attemptRef",))
            if plan is not None:
                if not any(slot["slotId"] == receipt["slotId"] for slot in plan_stage["slots"]):
                    _raise_semantic("ledger-receipt-slot-mismatch", base + ("receiptHash",))
                _validate_selection_receipt(receipt, plan)
            verified[(receipt["attemptRef"], receipt["slotId"])] = set(receipt["selectedModuleIds"])

        slots = {slot["slotId"]: slot for slot in plan_stage["slots"]} if plan_stage else {}
        for collection in ("slotResults", "gateResults", "runtimeSkips"):
            for item_index, item in enumerate(stage[collection]):
                if item["attemptRef"] not in local_refs:
                    _raise_semantic("ledger-attempt-unknown", ("stages", stage_index, collection, item_index, "attemptRef"))
        for item_index, item in enumerate(stage["slotResults"]):
            base = ("stages", stage_index, "slotResults", item_index)
            slot = slots.get(item["slotId"])
            if plan is not None and slot is None:
                _raise_semantic("ledger-slot-unknown", base + ("slotId",))
            if slot is not None:
                allowed = set(slot["selectedModules"]) if slot["selectionMode"] == "static" else verified.get((item["attemptRef"], item["slotId"]), set())
                if item["moduleId"] not in allowed:
                    reason = "ledger-module-not-selected" if slot["selectionMode"] == "static" else "ledger-module-selection-receipt-missing"
                    _raise_semantic(reason, base + ("moduleId",))
        gates = {gate for slot in slots.values() for gate in slot["gates"]}
        for item_index, item in enumerate(stage["gateResults"]):
            if plan is not None and item["gateId"] not in gates:
                _raise_semantic("ledger-gate-unknown", ("stages", stage_index, "gateResults", item_index, "gateId"))
        for item_index, item in enumerate(stage["runtimeSkips"]):
            slot = slots.get(item["slotId"])
            if plan is not None and (slot is None or slot["cardinality"] not in {"zero-or-one", "zero-or-many"}):
                _raise_semantic("ledger-runtime-skip-not-optional", ("stages", stage_index, "runtimeSkips", item_index, "slotId"))

        if plan_stage is not None and stage["status"] == "passed":
            current_results = {item["moduleId"] for item in stage["slotResults"] if item["attemptRef"] == current_ref}
            required = {module for slot in plan_stage["slots"] if slot["selectionMode"] == "static" for module in slot["selectedModules"]}
            if required - current_results:
                _raise_semantic("ledger-current-attempt-incomplete", ("stages", stage_index, "slotResults"))

    if status == "completed" and plan is not None:
        actual = {stage["stageId"]: stage["status"] for stage in document["stages"]}
        if any(actual.get(stage["stageId"]) not in {"passed", "skipped"} for stage in plan["stages"] if stage["applicability"] == "applicable"):
            _raise_semantic("ledger-status-completed-invalid", ("status",))


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
    *,
    expected_successor_plan_hash: str | None = None,
) -> None:
    """Validate a V3 RunLedger, optionally against a plan and receipt set."""

    _validate_schema("run-ledger.schema.json", document)
    _validate_run_ledger(
        document, plan, receipts,
        expected_successor_plan_hash,
    )


def validate_diff_signal_set(document: dict[str, Any]) -> None:
    """Validate a V3 DiffSignalSet and its content hash."""

    _validate_schema("diff-signal-set.schema.json", document)
    _validate_diff_signal_set(document)


def validate_review_finding(
    document: dict[str, Any],
    diff_signal_set: dict[str, Any] | None = None,
) -> None:
    """Validate a V3 ReviewFinding, optionally against its current diff."""

    _validate_schema("review-finding.schema.json", document)
    _validate_review_finding(document, diff_signal_set)


def validate_review_aggregate(
    document: dict[str, Any],
    diff_signal_set: dict[str, Any] | None = None,
    findings: tuple[dict[str, Any], ...] = (),
) -> None:
    """Validate a V3 ReviewAggregate and its finding set."""

    _validate_schema("review-aggregate.schema.json", document)
    _validate_review_aggregate(document, diff_signal_set, findings)


def validate_test_strategy(
    document: dict[str, Any],
    diff_signal_set: dict[str, Any] | None = None,
) -> None:
    """Validate a V3 TestStrategy and its T-level semantics."""

    _validate_schema("test-strategy.schema.json", document)
    _validate_test_strategy(document, diff_signal_set)


def validate_coverage_result(
    document: dict[str, Any],
    diff_signal_set: dict[str, Any] | None = None,
    test_strategy: dict[str, Any] | None = None,
) -> None:
    """Validate a V3 CoverageResult against the exact TestStrategy obligations."""

    _validate_schema("coverage-result.schema.json", document)
    _validate_coverage_result(document, diff_signal_set, test_strategy)


def load_contract(
    schema_name: str,
    text: str,
    *,
    plan_graph: dict[str, Any] | None = None,
    receipts: tuple[dict[str, Any], ...] = (),
    expected_successor_plan_hash: str | None = None,
    diff_signal_set: dict[str, Any] | None = None,
    findings: tuple[dict[str, Any], ...] = (),
    test_strategy: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
        if plan_graph is None:
            _raise_semantic("ledger-plan-required", ())
        _validate_run_ledger(
            document,
            plan_graph,
            receipts,
            expected_successor_plan_hash,
        )
    elif schema_name == "diff-signal-set.schema.json":
        _validate_diff_signal_set(document)
    elif schema_name == "review-finding.schema.json":
        _validate_review_finding(document, diff_signal_set)
    elif schema_name == "review-aggregate.schema.json":
        _validate_review_aggregate(document, diff_signal_set, findings)
    elif schema_name == "test-strategy.schema.json":
        _validate_test_strategy(document, diff_signal_set)
    elif schema_name == "coverage-result.schema.json":
        _validate_coverage_result(document, diff_signal_set, test_strategy)
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
