"""Strict loading and semantic validation for V3 orchestration contracts."""

from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import re
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Protocol

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
    "provider-descriptor.schema.json",
    "provider-local-config.schema.json",
    "provider-binding-snapshot.schema.json",
    "provider-support-matrix.schema.json",
    "provider-source-identity.schema.json",
    "provider-project-state-receipt.schema.json",
    "provider-operation-plan.schema.json",
    "provider-approval-receipt.schema.json",
    "provider-operation-receipt.schema.json",
    "provider-query-plan.schema.json",
    "provider-query-receipt.schema.json",
    "provider-mutation-evidence.schema.json",
    "workspace-fingerprint.schema.json",
    "provider-fallback-receipt.schema.json",
    "provider-project-lease.schema.json",
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


@_FORMAT_CHECKER.checks("utc-date-time", raises=ValueError)
def _is_utc_datetime(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z",
        value,
    ) is None:
        raise ValueError
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError
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


class VerificationReceiptPort(Protocol):
    """Host collector trust boundary for immutable verification receipts.

    Contract validation authenticates receipt structure and bindings; it does not
    independently attest that an operating-system process actually ran.
    """

    def resolve_verification_receipt(
        self, reference: str,
    ) -> dict[str, Any] | None:
        """Return the collector receipt identified by ``reference``."""


VerificationReceiptResolver = (
    VerificationReceiptPort
    | Callable[[str], dict[str, Any] | None]
)


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


def _validate_schema_definition(
    schema_name: str,
    definition_name: str,
    document: dict[str, Any],
    reason: str,
    path: tuple[str | int, ...],
) -> None:
    schemas, registry = _schema_bundle()
    reference = f"{schemas[schema_name]['$id']}#/$defs/{definition_name}"
    validator = Draft202012Validator(
        {"$ref": reference},
        registry=registry,
        format_checker=_FORMAT_CHECKER,
    )
    if next(validator.iter_errors(document), None) is not None:
        _raise_semantic(reason, path)


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


def _canonical_value_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
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


def _validate_diff_signal_set_core(document: dict[str, Any]) -> None:
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


def _current_ledger_attempt(run_ledger: dict[str, Any]) -> str | None:
    current: str | None = None
    for stage in run_ledger["stages"]:
        if stage["attempts"]:
            current = stage["attempts"][-1]["attemptRef"]
    return current


def _validate_quality_run_context(
    document: dict[str, Any],
    run_ledger: dict[str, Any] | None,
    artifact_name: str,
) -> None:
    if run_ledger is None:
        _raise_semantic(f"{artifact_name}-run-ledger-required", ())
    _validate_schema("run-ledger.schema.json", run_ledger)
    _validate_run_ledger(run_ledger)
    if document["planHash"] != run_ledger["planHash"]:
        _raise_semantic(f"{artifact_name}-ledger-plan-mismatch", ("planHash",))
    if document["attemptRef"] != _current_ledger_attempt(run_ledger):
        _raise_semantic(f"{artifact_name}-attempt-not-current", ("attemptRef",))


def _validate_plan_quality_context(
    document: dict[str, Any],
    plan_graph: dict[str, Any] | None,
    run_ledger: dict[str, Any] | None,
    artifact_name: str,
) -> None:
    if plan_graph is None:
        _raise_semantic(f"{artifact_name}-plan-required", ())
    if run_ledger is None:
        _raise_semantic(f"{artifact_name}-run-ledger-required", ())
    _validate_schema("plan-graph.schema.json", plan_graph)
    _validate_plan_graph(plan_graph)
    _validate_schema("run-ledger.schema.json", run_ledger)
    _validate_run_ledger(run_ledger, plan_graph)
    if document["planHash"] != plan_graph["planHash"]:
        _raise_semantic(f"{artifact_name}-plan-mismatch", ("planHash",))
    if document["attemptRef"] != _current_ledger_attempt(run_ledger):
        _raise_semantic(f"{artifact_name}-attempt-not-current", ("attemptRef",))


def _validate_current_diff(
    diff_signal_set: dict[str, Any],
    run_ledger: dict[str, Any] | None,
    artifact_name: str,
) -> None:
    _validate_schema("diff-signal-set.schema.json", diff_signal_set)
    _validate_diff_signal_set_core(diff_signal_set)
    _validate_quality_run_context(diff_signal_set, run_ledger, artifact_name)


def _validate_diff_signal_set(
    document: dict[str, Any],
    plan_graph: dict[str, Any] | None = None,
    run_ledger: dict[str, Any] | None = None,
) -> None:
    _validate_diff_signal_set_core(document)
    _validate_plan_quality_context(
        document, plan_graph, run_ledger, "diff-signal-set",
    )


def _validate_review_finding(
    document: dict[str, Any],
    diff_signal_set: dict[str, Any] | None = None,
    run_ledger: dict[str, Any] | None = None,
) -> None:
    if document["findingHash"] != _canonical_hash(document, "findingHash"):
        _raise_semantic("review-finding-hash-invalid", ("findingHash",))
    if diff_signal_set is None:
        _raise_semantic("review-finding-diff-required", ())
    _validate_artifact_binding(document, diff_signal_set, "review-finding")
    _validate_current_diff(diff_signal_set, run_ledger, "review-finding")


def _validate_review_aggregate(
    document: dict[str, Any],
    diff_signal_set: dict[str, Any] | None = None,
    findings: tuple[dict[str, Any], ...] = (),
    run_ledger: dict[str, Any] | None = None,
) -> None:
    if document["aggregateHash"] != _canonical_hash(document, "aggregateHash"):
        _raise_semantic("review-aggregate-hash-invalid", ("aggregateHash",))
    if diff_signal_set is None:
        _raise_semantic("review-aggregate-diff-required", ())
    _validate_artifact_binding(document, diff_signal_set, "review-aggregate")
    _validate_current_diff(diff_signal_set, run_ledger, "review-aggregate")
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
            _validate_schema("review-finding.schema.json", finding)
            _validate_review_finding(finding, diff_signal_set, run_ledger)
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


def _validate_test_strategy_core(
    document: dict[str, Any],
    diff_signal_set: dict[str, Any] | None = None,
) -> None:
    if document["strategyHash"] != _canonical_hash(document, "strategyHash"):
        _raise_semantic("test-strategy-hash-invalid", ("strategyHash",))
    if document["basisKind"] == "diff" and diff_signal_set is not None:
        _validate_artifact_binding(document, diff_signal_set, "test-strategy")
    if _TEST_LEVEL_ORDER[document["testLevelFloor"]] > _TEST_LEVEL_ORDER[document["testLevel"]]:
        _raise_semantic("test-strategy-floor-invalid", ("testLevelFloor",))
    if document["grillMeImplementation"] and (
        _TEST_LEVEL_ORDER[document["testLevel"]] < _TEST_LEVEL_ORDER["T2"]
        or _TEST_LEVEL_ORDER[document["testLevelFloor"]] < _TEST_LEVEL_ORDER["T2"]
    ):
        _raise_semantic("test-strategy-grill-me-floor-invalid", ("testLevel",))

    risk_ids = {risk["riskId"] for risk in document["risks"]}
    condition_ids: set[str] = set()
    for condition_index, condition in enumerate(document["acceptanceConditions"]):
        condition_id = condition["conditionId"]
        if condition_id in condition_ids:
            _raise_semantic(
                "test-strategy-acceptance-condition-duplicate",
                ("acceptanceConditions", condition_index, "conditionId"),
            )
        condition_ids.add(condition_id)
    technique_ids: set[str] = set()
    for technique_index, technique in enumerate(document["techniques"]):
        technique_id = technique["techniqueId"]
        if technique_id in technique_ids:
            _raise_semantic(
                "test-strategy-technique-duplicate",
                ("techniques", technique_index, "techniqueId"),
            )
        technique_ids.add(technique_id)
    obligation_ids: set[str] = set()
    for risk_index, risk in enumerate(document["risks"]):
        if len(risk_ids) != len(document["risks"]):
            _raise_semantic("test-strategy-risk-duplicate", ("risks", risk_index, "riskId"))
        if not set(risk["acceptanceConditionIds"]) <= condition_ids:
            _raise_semantic("test-strategy-acceptance-condition-unknown", ("risks", risk_index))
    authorization_by_id: dict[str, dict[str, Any]] = {}
    for authorization_index, requirement in enumerate(document["authorizationRequirements"]):
        authorization_id = requirement["authorizationId"]
        if authorization_id in authorization_by_id:
            _raise_semantic(
                "test-strategy-authorization-requirement-duplicate",
                ("authorizationRequirements", authorization_index, "authorizationId"),
            )
        authorization_by_id[authorization_id] = requirement
    used_required_authorization_ids: set[str] = set()
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
        for authorization_index, authorization_id in enumerate(
            obligation.get("authorizationRequirementIds", ())
        ):
            requirement = authorization_by_id.get(authorization_id)
            if requirement is None:
                _raise_semantic(
                    "test-strategy-authorization-requirement-unknown",
                    (
                        "coverageObligations", obligation_index,
                        "authorizationRequirementIds", authorization_index,
                    ),
                )
            if not requirement["required"]:
                _raise_semantic(
                    "test-strategy-authorization-requirement-not-required",
                    (
                        "coverageObligations", obligation_index,
                        "authorizationRequirementIds", authorization_index,
                    ),
                )
            used_required_authorization_ids.add(authorization_id)

    expected_dimensions = {"direct", "failure", "boundary", "state", "nfr"}
    dimensions: dict[str, set[str]] = {}
    for dimension_index, dimension in enumerate(document["dimensions"]):
        dimension_id = dimension["dimensionId"]
        if dimension_id in dimensions:
            _raise_semantic(
                "test-strategy-dimension-id-duplicate",
                ("dimensions", dimension_index, "dimensionId"),
            )
        dimensions[dimension_id] = set(dimension["obligationIds"])
    if set(dimensions) != expected_dimensions:
        _raise_semantic("test-strategy-dimension-set-mismatch", ("dimensions",))

    assignments: set[str] = set()
    for dimension_index, dimension in enumerate(document["dimensions"]):
        for obligation_index, obligation_id in enumerate(dimension["obligationIds"]):
            path = ("dimensions", dimension_index, "obligationIds", obligation_index)
            if obligation_id not in obligation_ids:
                _raise_semantic("test-strategy-dimension-obligation-unknown", path)
            if obligation_id in assignments:
                _raise_semantic("test-strategy-dimension-overlap", path)
            assignments.add(obligation_id)
    if assignments != obligation_ids:
        _raise_semantic("test-strategy-dimension-incomplete", ("dimensions",))

    for obligation_index, obligation in enumerate(document["coverageObligations"]):
        if obligation["obligationId"] not in dimensions[obligation["dimension"]]:
            _raise_semantic("test-strategy-dimension-mismatch", ("coverageObligations", obligation_index, "dimension"))

    for authorization_index, requirement in enumerate(document["authorizationRequirements"]):
        if (
            requirement["required"]
            and requirement["authorizationId"] not in used_required_authorization_ids
        ):
            _raise_semantic(
                "test-strategy-authorization-requirement-unused",
                ("authorizationRequirements", authorization_index, "authorizationId"),
            )


def _validate_test_strategy(
    document: dict[str, Any],
    plan_graph: dict[str, Any] | None = None,
    run_ledger: dict[str, Any] | None = None,
    diff_signal_set: dict[str, Any] | None = None,
) -> None:
    _validate_test_strategy_core(document, diff_signal_set)
    _validate_plan_quality_context(
        document, plan_graph, run_ledger, "test-strategy",
    )
    if document["basisKind"] == "diff":
        if diff_signal_set is None:
            _raise_semantic("test-strategy-diff-required", ())
        _validate_artifact_binding(document, diff_signal_set, "test-strategy")
        _validate_current_diff(diff_signal_set, run_ledger, "test-strategy")


def _resolve_verification_receipt(
    resolver: VerificationReceiptResolver | None,
    reference: str,
    path: tuple[str | int, ...],
) -> dict[str, Any]:
    if resolver is None:
        _raise_semantic("coverage-verification-resolver-required", ())
    try:
        method = getattr(resolver, "resolve_verification_receipt", None)
        receipt = method(reference) if callable(method) else resolver(reference)
    except Exception:
        _raise_semantic("coverage-execution-receipt-unavailable", path)
    if receipt is None:
        _raise_semantic("coverage-execution-receipt-unknown", path)
    if not isinstance(receipt, dict):
        _raise_semantic("coverage-execution-receipt-schema-invalid", path)
    return receipt


def _validate_execution_receipt(
    receipt: dict[str, Any],
    item: dict[str, Any],
    document: dict[str, Any],
    test_strategy: dict[str, Any],
    path: tuple[str | int, ...],
) -> None:
    _validate_schema_definition(
        "coverage-result.schema.json",
        "verificationReceipt",
        receipt,
        "coverage-execution-receipt-schema-invalid",
        path,
    )
    if receipt["receiptHash"] != _canonical_hash(receipt, "receiptHash"):
        _raise_semantic("coverage-execution-receipt-hash-invalid", path)
    if item["executionReceiptHash"] != receipt["receiptHash"]:
        _raise_semantic("coverage-execution-receipt-reference-hash-mismatch", path)
    if receipt["invocationHash"] != _canonical_value_hash(receipt["invocationEnvelope"]):
        _raise_semantic("coverage-execution-receipt-invocation-hash-invalid", path)
    if receipt["resultHash"] != _canonical_value_hash(receipt["resultEnvelope"]):
        _raise_semantic("coverage-execution-receipt-result-hash-invalid", path)
    bindings = (
        ("planHash", document["planHash"], "plan-mismatch"),
        ("attemptRef", document["attemptRef"], "attempt-mismatch"),
        ("strategyHash", test_strategy["strategyHash"], "strategy-mismatch"),
        ("diffSignalSetHash", document["diffSignalSetHash"], "diff-mismatch"),
    )
    for field, expected, suffix in bindings:
        if receipt[field] != expected:
            _raise_semantic(f"coverage-execution-receipt-{suffix}", path)
    if item["obligationId"] not in receipt["obligationIds"]:
        _raise_semantic("coverage-execution-receipt-obligation-mismatch", path)
    invocation = receipt["invocationEnvelope"]
    result = receipt["resultEnvelope"]
    if result["invocationHash"] != receipt["invocationHash"]:
        _raise_semantic("coverage-execution-receipt-invocation-mismatch", path)
    if invocation["inputHash"] != test_strategy["strategyHash"]:
        _raise_semantic("coverage-execution-receipt-input-mismatch", path)
    if _utc_datetime(result["completedAt"]) < _utc_datetime(invocation["startedAt"]):
        _raise_semantic("coverage-execution-receipt-time-invalid", path)
    if result["exitCode"] != 0:
        _raise_semantic("coverage-execution-receipt-exit-unsuccessful", path)
    if result["status"] != "passed":
        _raise_semantic("coverage-execution-receipt-status-unsuccessful", path)
    if "invocationHash" in item and item["invocationHash"] != receipt["invocationHash"]:
        _raise_semantic("coverage-display-invocation-hash-mismatch", path)
    if "resultHash" in item and item["resultHash"] != receipt["resultHash"]:
        _raise_semantic("coverage-display-result-hash-mismatch", path)


def _validate_coverage_result(
    document: dict[str, Any],
    diff_signal_set: dict[str, Any] | None = None,
    test_strategy: dict[str, Any] | None = None,
    run_ledger: dict[str, Any] | None = None,
    verification_receipt_resolver: VerificationReceiptResolver | None = None,
) -> None:
    if document["resultHash"] != _canonical_hash(document, "resultHash"):
        _raise_semantic("coverage-result-hash-invalid", ("resultHash",))
    if test_strategy is None:
        _raise_semantic("coverage-strategy-required", ())
    if diff_signal_set is None:
        _raise_semantic("coverage-diff-required", ())
    _validate_artifact_binding(document, diff_signal_set, "coverage-result")
    _validate_schema("test-strategy.schema.json", test_strategy)
    _validate_test_strategy_core(test_strategy, diff_signal_set)
    if test_strategy["basisKind"] != "diff":
        _raise_semantic("coverage-strategy-basis-invalid", ("basisKind",))
    _validate_current_diff(diff_signal_set, run_ledger, "coverage-result")
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
    receipts_by_ref: dict[str, dict[str, Any]] = {}
    referenced_obligations: dict[str, set[str]] = {}
    first_paths: dict[str, tuple[str | int, ...]] = {}
    for index, item in enumerate(document["obligations"]):
        if item["status"] != "fulfilled":
            continue
        path = ("obligations", index, "executionReceiptRef")
        reference = item["executionReceiptRef"]
        receipt = receipts_by_ref.get(reference)
        if receipt is None:
            receipt = _resolve_verification_receipt(
                verification_receipt_resolver, reference, path,
            )
            receipts_by_ref[reference] = receipt
            first_paths[reference] = path
        _validate_execution_receipt(
            receipt, item, document, test_strategy, path,
        )
        referenced_obligations.setdefault(reference, set()).add(item["obligationId"])
    for reference, receipt in receipts_by_ref.items():
        if set(receipt["obligationIds"]) != referenced_obligations[reference]:
            _raise_semantic(
                "coverage-execution-receipt-obligations-mismatch",
                first_paths[reference],
            )
    if document["passed"] and any(item["status"] != "fulfilled" for item in document["obligations"]):
        _raise_semantic("coverage-passed-with-unfulfilled", ("passed",))


def _plan_constraint_map(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    constraints: dict[str, dict[str, Any]] = {}
    indexes: dict[str, int] = {}
    for index, constraint in enumerate(document["moduleConstraints"]):
        module_id = constraint["moduleId"]
        if module_id in constraints:
            _raise_semantic(
                "plan-module-constraint-duplicate",
                ("moduleConstraints", index, "moduleId"),
            )
        constraints[module_id] = constraint
        indexes[module_id] = index
    for module_id, constraint in constraints.items():
        index = indexes[module_id]
        for field, unknown_reason, self_reason in (
            ("dependencies", "plan-module-dependency-unknown", "plan-module-dependency-self"),
            ("conflicts", "plan-module-conflict-unknown", "plan-module-conflict-self"),
        ):
            for item_index, related_id in enumerate(constraint[field]):
                path = ("moduleConstraints", index, field, item_index)
                if related_id not in constraints:
                    _raise_semantic(unknown_reason, path)
                if related_id == module_id:
                    _raise_semantic(self_reason, path)
        for dependency_id in constraint["dependencies"]:
            dependency = constraints[dependency_id]
            if (
                dependency["stageId"] != constraint["stageId"]
                or dependency["slotId"] != constraint["slotId"]
            ):
                _raise_semantic(
                    "plan-module-dependency-cross-slot",
                    ("moduleConstraints", index, "dependencies"),
                )
        for conflict_id in constraint["conflicts"]:
            if module_id not in constraints[conflict_id]["conflicts"]:
                _raise_semantic(
                    "plan-module-conflict-asymmetric",
                    ("moduleConstraints", index, "conflicts"),
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module_id: str) -> None:
        if module_id in visiting:
            _raise_semantic(
                "plan-module-dependency-cycle",
                ("moduleConstraints", indexes[module_id], "dependencies"),
            )
        if module_id in visited:
            return
        visiting.add(module_id)
        for dependency_id in constraints[module_id]["dependencies"]:
            visit(dependency_id)
        visiting.remove(module_id)
        visited.add(module_id)

    for module_id in constraints:
        visit(module_id)
    return constraints


def _selection_has_bidirectional_conflict(
    selected: set[str], constraints: dict[str, dict[str, Any]],
) -> bool:
    return any(
        right in constraints[left]["conflicts"]
        or left in constraints[right]["conflicts"]
        for left in selected
        for right in selected
        if left != right
    )


def _validate_plan_graph(document: dict[str, Any]) -> None:
    if document["planHash"] != _canonical_hash(document, "planHash"):
        _raise_semantic("plan-hash-invalid", ("planHash",))

    constraints = _plan_constraint_map(document)
    known_slots = {
        (stage["stageId"], slot["slotId"])
        for stage in document["stages"]
        for slot in stage["slots"]
    }
    for index, constraint in enumerate(document["moduleConstraints"]):
        if (constraint["stageId"], constraint["slotId"]) not in known_slots:
            _raise_semantic(
                "plan-module-boundary-unknown",
                ("moduleConstraints", index, "slotId"),
            )

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
            selected_set = set(selected)
            for module_index, module_id in enumerate(slot["eligibleModules"]):
                constraint = constraints.get(module_id)
                path = (
                    "stages", stage_index, "slots", slot_index,
                    "eligibleModules", module_index,
                )
                if constraint is None:
                    _raise_semantic("plan-module-constraint-missing", path)
                if (
                    constraint["stageId"] != stage["stageId"]
                    or constraint["slotId"] != slot["slotId"]
                ):
                    _raise_semantic("plan-module-boundary-mismatch", path)
                if not set(constraint["dependencies"]) <= eligible:
                    _raise_semantic("plan-eligible-dependency-open", path)
            for module_index, module_id in enumerate(selected):
                if module_id not in eligible:
                    _raise_semantic(
                        "plan-selected-module-ineligible",
                        (
                            "stages", stage_index, "slots", slot_index,
                            "selectedModules", module_index,
                        ),
                    )
                if not set(constraints[module_id]["dependencies"]) <= selected_set:
                    _raise_semantic(
                        "plan-selected-dependency-open",
                        (
                            "stages", stage_index, "slots", slot_index,
                            "selectedModules", module_index,
                        ),
                    )
            if _selection_has_bidirectional_conflict(selected_set, constraints):
                _raise_semantic(
                    "plan-selected-conflict",
                    ("stages", stage_index, "slots", slot_index, "selectedModules"),
                )
            if slot["applicability"] == "not-applicable" and (selected or eligible):
                _raise_semantic(
                    "plan-inapplicable-slot-not-empty",
                    ("stages", stage_index, "slots", slot_index),
                )
            # A non-applicable slot is intentionally empty.  Its pipeline
            # cardinality remains the contract for when the condition matches;
            # applying it while the condition is false makes an otherwise
            # schema-valid not-applicable bounded slot impossible to represent.
            if slot["applicability"] != "applicable":
                continue
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


def _validate_receipt_coverage(document: dict[str, Any]) -> set[str]:
    actual_obligations: set[str] = set()
    used_evidence: set[str] = set()
    signal_evidence = set(document["signalEvidenceRefs"])
    for index, decision in enumerate(document["coverageDecisions"]):
        obligation_id = decision["obligationId"]
        if obligation_id in actual_obligations:
            _raise_semantic(
                "selection-receipt-coverage-obligation-duplicate",
                ("coverageDecisions", index, "obligationId"),
            )
        actual_obligations.add(obligation_id)
        evidence = decision.get("evidenceRefs", [])
        if decision["decision"] == "fulfilled" and not evidence:
            _raise_semantic(
                "selection-receipt-coverage-evidence-required",
                ("coverageDecisions", index, "evidenceRefs"),
            )
        if not set(evidence) <= signal_evidence:
            _raise_semantic(
                "selection-receipt-coverage-evidence-invalid",
                ("coverageDecisions", index, "evidenceRefs"),
            )
        if used_evidence & set(evidence):
            _raise_semantic(
                "selection-receipt-coverage-evidence-reused",
                ("coverageDecisions", index, "evidenceRefs"),
            )
        used_evidence.update(evidence)
    return actual_obligations


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
    actual_obligations = _validate_receipt_coverage(document)
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
    if document["selectionPolicyHash"] != slot["selectionPolicyHash"]:
        _raise_semantic(
            "selection-receipt-policy-mismatch",
            ("selectionPolicyHash",),
        )
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
    constraints = _plan_constraint_map(plan)
    eligible = set(document["eligibleModuleIds"])
    selected = set(document["selectedModuleIds"])
    for module_id in eligible:
        constraint = constraints.get(module_id)
        if constraint is None:
            _raise_semantic(
                "selection-receipt-module-metadata-missing",
                ("eligibleModuleIds",),
            )
        if (
            constraint["stageId"] != document["stageId"]
            or constraint["slotId"] != document["slotId"]
        ):
            _raise_semantic(
                "selection-receipt-module-boundary-mismatch",
                ("eligibleModuleIds",),
            )
        dependencies = set(constraint["dependencies"])
        if not dependencies <= eligible:
            _raise_semantic(
                "selection-receipt-eligible-dependency-open",
                ("eligibleModuleIds",),
            )
    for module_id in selected:
        constraint = constraints[module_id]
        dependencies = set(constraint["dependencies"])
        if not dependencies <= selected:
            _raise_semantic(
                "selection-receipt-selected-dependency-open",
                ("selectedModuleIds",),
            )
    if _selection_has_bidirectional_conflict(selected, constraints):
        _raise_semantic(
            "selection-receipt-selected-conflict",
            ("selectedModuleIds",),
        )
    expected_context_cost = sum(
        constraints[module_id]["estimatedContextCost"] for module_id in selected
    )
    expected_execution_cost = sum(
        constraints[module_id]["estimatedExecutionCost"] for module_id in selected
    )
    if document["estimatedContextCost"] != expected_context_cost:
        _raise_semantic(
            "selection-receipt-context-cost-mismatch",
            ("estimatedContextCost",),
        )
    if document["estimatedExecutionCost"] != expected_execution_cost:
        _raise_semantic(
            "selection-receipt-execution-cost-mismatch",
            ("estimatedExecutionCost",),
        )

    if actual_obligations != set(slot["coverageObligations"]):
        _raise_semantic(
            "selection-receipt-coverage-obligations-mismatch",
            ("coverageDecisions",),
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
        # ``pending`` also represents a deterministic handoff point: a
        # completed prefix with no stage activated yet.  An active stage is
        # still rejected, so callers cannot skip the explicit activation
        # transition or create two active stages.
        first_waiting = next(
            (index for index, value in enumerate(stage_statuses)
             if value == "pending"),
            len(stage_statuses),
        )
        status_valid = (
            active_count == 0
            and first_waiting < len(stage_statuses)
            and all(item in prefix_done for item in stage_statuses[:first_waiting])
            and all(item in suffix_waiting for item in stage_statuses[first_waiting:])
            and all(
                "completedAt" in attempt
                for stage in document["stages"]
                if stage["status"] == "passed"
                for attempt in stage["attempts"]
            )
        )
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
        stage_artifact_hashes = set(stage["artifactHashes"])
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
            if not set(attempt.get("inputArtifactHashes", [])) <= stage_artifact_hashes:
                _raise_semantic(
                    "ledger-attempt-input-artifact-unregistered",
                    path + ("inputArtifactHashes",),
                )
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
            receipt_key = (receipt["attemptRef"], receipt["slotId"])
            if receipt_key in verified:
                _raise_semantic(
                    "ledger-receipt-slot-duplicate", base + ("receiptHash",),
                )
            verified[receipt_key] = set(receipt["selectedModuleIds"])

        slots = {slot["slotId"]: slot for slot in plan_stage["slots"]} if plan_stage else {}
        for collection in ("slotResults", "gateResults", "runtimeSkips"):
            for item_index, item in enumerate(stage[collection]):
                if item["attemptRef"] not in local_refs:
                    _raise_semantic("ledger-attempt-unknown", ("stages", stage_index, collection, item_index, "attemptRef"))
        seen_slot_results: set[tuple[str, str, str]] = set()
        for item_index, item in enumerate(stage["slotResults"]):
            base = ("stages", stage_index, "slotResults", item_index)
            result_key = (
                item["attemptRef"], item["slotId"], item["moduleId"],
            )
            if result_key in seen_slot_results:
                _raise_semantic("ledger-slot-result-duplicate", base)
            seen_slot_results.add(result_key)
            slot = slots.get(item["slotId"])
            if plan is not None and slot is None:
                _raise_semantic("ledger-slot-unknown", base + ("slotId",))
            if slot is not None:
                allowed = set(slot["selectedModules"]) if slot["selectionMode"] == "static" else verified.get((item["attemptRef"], item["slotId"]), set())
                if item["moduleId"] not in allowed:
                    reason = "ledger-module-not-selected" if slot["selectionMode"] == "static" else "ledger-module-selection-receipt-missing"
                    _raise_semantic(reason, base + ("moduleId",))
            if item["artifactHash"] not in stage_artifact_hashes:
                _raise_semantic(
                    "ledger-slot-result-artifact-unregistered",
                    base + ("artifactHash",),
                )
        gates = {gate for slot in slots.values() for gate in slot["gates"]}
        seen_gate_results: set[tuple[str, str]] = set()
        for item_index, item in enumerate(stage["gateResults"]):
            gate_key = (item["attemptRef"], item["gateId"])
            if gate_key in seen_gate_results:
                _raise_semantic(
                    "ledger-gate-result-duplicate",
                    ("stages", stage_index, "gateResults", item_index),
                )
            seen_gate_results.add(gate_key)
            if plan is not None and item["gateId"] not in gates:
                _raise_semantic("ledger-gate-unknown", ("stages", stage_index, "gateResults", item_index, "gateId"))
            if item["artifactHash"] not in stage_artifact_hashes:
                _raise_semantic(
                    "ledger-gate-result-artifact-unregistered",
                    ("stages", stage_index, "gateResults", item_index, "artifactHash"),
                )
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
    document: dict[str, Any],
    plan: dict[str, Any] | None = None,
) -> None:
    """Validate a V3 SelectionReceipt, optionally against its PlanGraph."""

    _validate_schema("selection-receipt.schema.json", document)
    if plan is not None:
        _validate_schema("plan-graph.schema.json", plan)
        _validate_plan_graph(plan)
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
    if plan is not None:
        _validate_schema("plan-graph.schema.json", plan)
        _validate_plan_graph(plan)
    _validate_run_ledger(
        document, plan, receipts,
        expected_successor_plan_hash,
    )


def validate_resolve_result(document: dict[str, Any]) -> None:
    """Validate a V3 ResolveResult containing only its immutable PlanGraph."""

    _validate_schema("resolve-result.schema.json", document)
    _validate_resolve_result(document)


def validate_diff_signal_set(
    document: dict[str, Any],
    plan_graph: dict[str, Any] | None = None,
    run_ledger: dict[str, Any] | None = None,
) -> None:
    """Validate a V3 DiffSignalSet against its current plan and ledger."""

    _validate_schema("diff-signal-set.schema.json", document)
    _validate_diff_signal_set(document, plan_graph, run_ledger)


def validate_review_finding(
    document: dict[str, Any],
    diff_signal_set: dict[str, Any] | None = None,
    run_ledger: dict[str, Any] | None = None,
) -> None:
    """Validate a V3 ReviewFinding against its current diff and ledger."""

    _validate_schema("review-finding.schema.json", document)
    _validate_review_finding(document, diff_signal_set, run_ledger)


def validate_review_aggregate(
    document: dict[str, Any],
    diff_signal_set: dict[str, Any] | None = None,
    findings: tuple[dict[str, Any], ...] = (),
    run_ledger: dict[str, Any] | None = None,
) -> None:
    """Validate a V3 ReviewAggregate and its finding set."""

    _validate_schema("review-aggregate.schema.json", document)
    _validate_review_aggregate(document, diff_signal_set, findings, run_ledger)


def validate_test_strategy(
    document: dict[str, Any],
    plan_graph: dict[str, Any] | None = None,
    run_ledger: dict[str, Any] | None = None,
    diff_signal_set: dict[str, Any] | None = None,
) -> None:
    """Validate a V3 TestStrategy and its T-level semantics."""

    _validate_schema("test-strategy.schema.json", document)
    _validate_test_strategy(document, plan_graph, run_ledger, diff_signal_set)


def validate_coverage_result(
    document: dict[str, Any],
    diff_signal_set: dict[str, Any] | None = None,
    test_strategy: dict[str, Any] | None = None,
    run_ledger: dict[str, Any] | None = None,
    verification_receipt_resolver: VerificationReceiptResolver | None = None,
) -> None:
    """Validate coverage using Host-collected receipts as the trust boundary."""

    _validate_schema("coverage-result.schema.json", document)
    _validate_coverage_result(
        document,
        diff_signal_set,
        test_strategy,
        run_ledger,
        verification_receipt_resolver,
    )


def _validate_provider_document(schema_name: str, document: dict[str, Any]) -> None:
    """Validate a Provider envelope through the same closed registry as V3 core."""

    _validate_schema(schema_name, document)
    _validate_provider_time_semantics(schema_name, document)


def _validate_provider_time_semantics(
    schema_name: str,
    document: dict[str, Any],
) -> None:
    ranges = {
        "provider-project-state-receipt.schema.json": (
            "capturedAt", "validUntil", "provider-project-state-time-invalid",
        ),
        "provider-approval-receipt.schema.json": (
            "issuedAt", "expiresAt", "provider-approval-time-invalid",
        ),
        "provider-operation-receipt.schema.json": (
            "startedAt", "completedAt", "provider-operation-time-invalid",
        ),
        "provider-project-lease.schema.json": (
            "issuedAt", "expiresAt", "provider-lease-time-invalid",
        ),
    }
    time_range = ranges.get(schema_name)
    if time_range is None:
        return
    start_field, end_field, reason = time_range
    if _utc_datetime(document[end_field]) < _utc_datetime(document[start_field]):
        _raise_semantic(reason, (end_field,))


def validate_provider_descriptor(document: dict[str, Any]) -> None:
    _validate_provider_document("provider-descriptor.schema.json", document)


def validate_provider_local_config(document: dict[str, Any]) -> None:
    _validate_provider_document("provider-local-config.schema.json", document)


def validate_provider_binding_snapshot(
    document: dict[str, Any],
    *,
    support_registry: object | None = None,
    support_resolver: Callable[[str, str], object | None] | None = None,
) -> None:
    from selfworkflow.v3.provider_binding import validate_binding_snapshot
    validate_binding_snapshot(
        document,
        support_registry=support_registry,
        support_resolver=support_resolver,
    )


def validate_provider_support_matrix(document: dict[str, Any]) -> None:
    from selfworkflow.v3.support_matrix import validate_support_matrix
    validate_support_matrix(document)


def validate_provider_source_identity(document: dict[str, Any]) -> None:
    from selfworkflow.v3.provider_binding import validate_source_identity
    validate_source_identity(document)


def validate_provider_project_state_receipt(document: dict[str, Any]) -> None:
    _validate_provider_document("provider-project-state-receipt.schema.json", document)


def validate_provider_operation_plan(document: dict[str, Any]) -> None:
    _validate_provider_document("provider-operation-plan.schema.json", document)


def validate_provider_approval_receipt(document: dict[str, Any]) -> None:
    _validate_provider_document("provider-approval-receipt.schema.json", document)


def validate_provider_operation_receipt(document: dict[str, Any]) -> None:
    _validate_provider_document("provider-operation-receipt.schema.json", document)


def validate_provider_query_plan(document: dict[str, Any]) -> None:
    _validate_provider_document("provider-query-plan.schema.json", document)


def validate_provider_query_receipt(document: dict[str, Any]) -> None:
    _validate_provider_document("provider-query-receipt.schema.json", document)


def validate_provider_mutation_evidence(document: dict[str, Any]) -> None:
    _validate_provider_document("provider-mutation-evidence.schema.json", document)


def validate_workspace_fingerprint(document: dict[str, Any]) -> None:
    _validate_provider_document("workspace-fingerprint.schema.json", document)


def validate_provider_fallback_receipt(document: dict[str, Any]) -> None:
    from selfworkflow.v3.provider_config import validate_fallback_receipt
    validate_fallback_receipt(document)


def validate_provider_project_lease(document: dict[str, Any]) -> None:
    _validate_provider_document("provider-project-lease.schema.json", document)


def load_contract(
    schema_name: str,
    text: str,
    *,
    plan_graph: dict[str, Any] | None = None,
    receipts: tuple[dict[str, Any], ...] = (),
    expected_successor_plan_hash: str | None = None,
    run_ledger: dict[str, Any] | None = None,
    diff_signal_set: dict[str, Any] | None = None,
    findings: tuple[dict[str, Any], ...] = (),
    test_strategy: dict[str, Any] | None = None,
    verification_receipt_resolver: VerificationReceiptResolver | None = None,
    provider_support_registry: object | None = None,
    provider_support_resolver: Callable[[str, str], object | None] | None = None,
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
    if schema_name == "provider-binding-snapshot.schema.json":
        from selfworkflow.v3.provider_binding import _validate_binding_snapshot_semantics
        _validate_binding_snapshot_semantics(
            document,
            support_registry=provider_support_registry,
            support_resolver=provider_support_resolver,
        )
    elif schema_name == "resolve-request.schema.json":
        _validate_resolve_request(document)
    elif schema_name == "resolve-result.schema.json":
        _validate_resolve_result(document)
    elif schema_name == "plan-graph.schema.json":
        _validate_plan_graph(document)
    elif schema_name == "selection-receipt.schema.json":
        if plan_graph is not None:
            _validate_schema("plan-graph.schema.json", plan_graph)
            _validate_plan_graph(plan_graph)
        _validate_selection_receipt(document, plan_graph)
    elif schema_name == "run-ledger.schema.json":
        if plan_graph is None:
            _raise_semantic("ledger-plan-required", ())
        _validate_schema("plan-graph.schema.json", plan_graph)
        _validate_plan_graph(plan_graph)
        _validate_run_ledger(
            document,
            plan_graph,
            receipts,
            expected_successor_plan_hash,
        )
    elif schema_name == "diff-signal-set.schema.json":
        _validate_diff_signal_set(document, plan_graph, run_ledger)
    elif schema_name == "review-finding.schema.json":
        _validate_review_finding(document, diff_signal_set, run_ledger)
    elif schema_name == "review-aggregate.schema.json":
        _validate_review_aggregate(document, diff_signal_set, findings, run_ledger)
    elif schema_name == "test-strategy.schema.json":
        _validate_test_strategy(document, plan_graph, run_ledger, diff_signal_set)
    elif schema_name == "coverage-result.schema.json":
        _validate_coverage_result(
            document,
            diff_signal_set,
            test_strategy,
            run_ledger,
            verification_receipt_resolver,
        )
    else:
        _validate_provider_time_semantics(schema_name, document)
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
