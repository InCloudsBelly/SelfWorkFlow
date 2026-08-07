"""Protected-rule merging and completion evidence gates."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
from types import MappingProxyType


_MAPPING_PROXY_TYPE = type(MappingProxyType({}))
_LAYER_ORDER = {"skill": 1, "project": 2, "overlay": 3}
_ERROR_MESSAGES = MappingProxyType(
    {
        "protected-rules-invalid": "The protected-rule document is invalid.",
        "protected-rule-layer-invalid": "A lower-priority rule layer is invalid.",
        "protected-rule-override-denied": (
            "A lower-priority rule cannot replace a protected rule."
        ),
        "protected-rule-owner-authorization-required": (
            "A protected-rule change requires the complete breaking-change gate."
        ),
        "evidence-json-invalid": "The evidence JSON document is invalid.",
        "evidence-invalid": "The completion evidence structure is invalid.",
        "result-content-invalid": "The completion result content is invalid.",
        "evidence-time-invalid": "The completion evidence time is invalid.",
    }
)
_DECISION_MESSAGES = MappingProxyType(
    {
        "completion-eligible": "The evidence satisfies the completion gate.",
        "verification-failed": (
            "A failed verification cannot satisfy the completion gate."
        ),
        "verification-not-run": (
            "A verification that was not run cannot satisfy the completion gate."
        ),
        "verification-partial": (
            "A partial verification cannot satisfy the completion gate."
        ),
        "verification-stale": (
            "Verification evidence outside its validity window is stale."
        ),
        "result-content-hash-mismatch": (
            "The evidence is not bound to the current completion result."
        ),
        "verification-content-hash-mismatch": (
            "A verification is not bound to the current completion result."
        ),
        "verification-not-applicable-for-modification": (
            "Not-applicable verification is limited to read-only tasks."
        ),
        "acceptance-criterion-unverified": (
            "Every acceptance criterion must reference recorded verification evidence."
        ),
        "clock-rollback-detected": (
            "The current observation time is earlier than a prior observation."
        ),
        "verification-time-in-future": (
            "Verification evidence cannot be newer than the observation time."
        ),
    }
)
_VERIFICATION_FAILURE_CODES = MappingProxyType(
    {
        "failed": "verification-failed",
        "not-run": "verification-not-run",
        "partial": "verification-partial",
    }
)


class WorkflowEvidenceError(ValueError):
    """Stable workflow failure that does not include rejected input values."""

    def __init__(self, code: str):
        self.code = code
        self.message = _ERROR_MESSAGES[code]
        super().__init__(self.message)


class _DuplicateJsonKeyError(ValueError):
    pass


@dataclass(frozen=True)
class CompletionDecision:
    """A frozen completion-gate decision with no rejected input values."""

    eligible: bool
    code: str
    message: str
    content_hash: str
    observed_at: str


@dataclass(frozen=True)
class MergedRule:
    """A deeply immutable rule in deterministic merge order."""

    id: str
    strength: str
    source_kind: str
    source_name: str
    protected: bool


@dataclass(frozen=True)
class MergedRules:
    """A frozen, deterministic merged rule collection."""

    rules: tuple[MergedRule, ...]

    def rule_for(self, rule_id: str) -> MergedRule | None:
        if type(rule_id) is not str or not rule_id:
            _fail("protected-rules-invalid")
        return next((rule for rule in self.rules if rule.id == rule_id), None)


def _fail(code: str) -> None:
    raise WorkflowEvidenceError(code) from None


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError


def _freeze_json(
    value: object,
    *,
    depth: int = 0,
    state: list[int] | None = None,
) -> object:
    if depth > 64:
        _fail("evidence-json-invalid")
    counters = state if state is not None else [0]
    counters[0] += 1
    if counters[0] > 10000:
        _fail("evidence-json-invalid")
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            _fail("evidence-json-invalid")
        return value
    if type(value) is list:
        return tuple(
            _freeze_json(item, depth=depth + 1, state=counters) for item in value
        )
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            _fail("evidence-json-invalid")
        return MappingProxyType(
            {
                key: _freeze_json(item, depth=depth + 1, state=counters)
                for key, item in value.items()
            }
        )
    _fail("evidence-json-invalid")


def parse_evidence_json(document: object) -> MappingProxyType:
    """Parse duplicate-free finite JSON into a deeply immutable structure."""

    if type(document) is not str:
        _fail("evidence-json-invalid")
    try:
        loaded = json.loads(
            document,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        frozen = _freeze_json(loaded)
    except WorkflowEvidenceError:
        raise
    except Exception:
        _fail("evidence-json-invalid")
    if type(frozen) is not _MAPPING_PROXY_TYPE:
        _fail("evidence-json-invalid")
    return frozen


def _normalize_content(
    value: object,
    *,
    depth: int,
    counters: list[int],
    active: set[int],
) -> object:
    if depth > 64:
        _fail("result-content-invalid")
    counters[0] += 1
    if counters[0] > 10000:
        _fail("result-content-invalid")
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            _fail("result-content-invalid")
        if value.is_integer():
            return int(value)
        return value
    if type(value) in (list, tuple):
        identity = id(value)
        if identity in active:
            _fail("result-content-invalid")
        active.add(identity)
        try:
            return [
                _normalize_content(
                    item,
                    depth=depth + 1,
                    counters=counters,
                    active=active,
                )
                for item in value
            ]
        finally:
            active.remove(identity)
    if type(value) in (dict, _MAPPING_PROXY_TYPE):
        entries = _mapping_entries(value, "result-content-invalid")
        identity = id(value)
        if identity in active:
            _fail("result-content-invalid")
        active.add(identity)
        try:
            return {
                key: _normalize_content(
                    item,
                    depth=depth + 1,
                    counters=counters,
                    active=active,
                )
                for key, item in entries
            }
        finally:
            active.remove(identity)
    _fail("result-content-invalid")


def canonical_content_hash(content: object) -> str:
    """Hash normalized finite JSON content with deterministic object ordering."""

    try:
        normalized = _normalize_content(
            content,
            depth=0,
            counters=[0],
            active=set(),
        )
        payload = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except WorkflowEvidenceError:
        raise
    except Exception:
        _fail("result-content-invalid")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _as_utc(value: object) -> datetime:
    if type(value) is not datetime:
        _fail("evidence-time-invalid")
    try:
        if value.utcoffset() is None:
            _fail("evidence-time-invalid")
        return value.astimezone(timezone.utc)
    except WorkflowEvidenceError:
        raise
    except Exception:
        _fail("evidence-time-invalid")


def _format_utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_verified_at(value: object) -> datetime:
    if type(value) is not str or re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
        value,
    ) is None:
        _fail("evidence-time-invalid")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        _fail("evidence-time-invalid")


def _completion_decision(
    eligible: bool,
    code: str,
    content_hash: str,
    observed_at: datetime,
) -> CompletionDecision:
    return CompletionDecision(
        eligible=eligible,
        code=code,
        message=_DECISION_MESSAGES[code],
        content_hash=content_hash,
        observed_at=_format_utc(observed_at),
    )


def evaluate_completion(
    evidence: object,
    result_content: object,
    *,
    now: object,
    previous_observed_at: object | None = None,
) -> CompletionDecision:
    """Evaluate completion and redact unexpected failures at the public boundary."""

    try:
        return _evaluate_completion(
            evidence,
            result_content,
            now=now,
            previous_observed_at=previous_observed_at,
        )
    except WorkflowEvidenceError:
        raise
    except Exception:
        _fail("evidence-invalid")


def _evaluate_completion(
    evidence: object,
    result_content: object,
    *,
    now: object,
    previous_observed_at: object | None = None,
) -> CompletionDecision:
    previous = None
    if previous_observed_at is not None:
        previous = _as_utc(previous_observed_at)
    observed_at = _as_utc(now)
    content_hash = canonical_content_hash(result_content)

    def decision(code: str, eligible: bool = False) -> CompletionDecision:
        return _completion_decision(eligible, code, content_hash, observed_at)

    if previous is not None and observed_at < previous:
        return decision("clock-rollback-detected")
    document = _closed_mapping(
        evidence,
        (
            "classification",
            "capabilities",
            "selectedSkills",
            "acceptanceCriteria",
            "changes",
            "review",
            "verification",
            "skipped",
            "residualRisks",
        ),
        "evidence-invalid",
    )
    classification = _closed_mapping(
        document["classification"],
        ("taskKind", "complexity", "risk"),
        "evidence-invalid",
    )
    if (
        type(classification["complexity"]) is not str
        or classification["complexity"] not in {"C0", "C1", "C2", "C3"}
        or type(classification["risk"]) is not str
        or classification["risk"] not in {"R0", "R1", "R2", "R3"}
    ):
        _fail("evidence-invalid")
    capabilities = _ordered_sequence(document["capabilities"], "evidence-invalid")
    if not capabilities:
        _fail("evidence-invalid")
    capability_names: set[str] = set()
    for value in capabilities:
        capability = _closed_mapping(
            value,
            ("name", "state", "evidenceHash"),
            "evidence-invalid",
        )
        name = capability["name"]
        if (
            type(name) is not str
            or not name.strip()
            or name in capability_names
            or type(capability["state"]) is not str
            or capability["state"]
            not in {"supported", "unsupported", "unverified"}
            or not _is_sha256(capability["evidenceHash"])
        ):
            _fail("evidence-invalid")
        capability_names.add(name)
    selected_skills = _ordered_sequence(
        document["selectedSkills"],
        "evidence-invalid",
    )
    if (
        any(type(skill) is not str or not skill.strip() for skill in selected_skills)
        or len(set(selected_skills)) != len(selected_skills)
    ):
        _fail("evidence-invalid")
    changes = _closed_mapping(
        document["changes"],
        ("taskKind", "resultContentHash", "items"),
        "evidence-invalid",
    )
    review = _closed_mapping(
        document["review"],
        ("status", "level", "evidenceHash", "reason"),
        "evidence-invalid",
    )
    task_kind = classification["taskKind"]
    change_items = _ordered_sequence(changes["items"], "evidence-invalid")
    if (
        type(task_kind) is not str
        or task_kind not in {"modification", "read-only"}
        or changes["taskKind"] != task_kind
        or not _is_sha256(changes["resultContentHash"])
        or not _is_sha256(review["evidenceHash"])
        or type(review["reason"]) is not str
    ):
        _fail("evidence-invalid")
    if task_kind == "modification":
        if (
            not change_items
            or review["status"] != "passed"
            or type(review["level"]) is not str
            or review["level"] not in {"L0", "L1", "L2", "L3"}
        ):
            _fail("evidence-invalid")
    elif (
        change_items
        or review["status"] != "not-applicable"
        or review["level"] != "not-applicable"
        or type(review["reason"]) is not str
        or not review["reason"].strip()
    ):
        _fail("evidence-invalid")
    change_paths: set[str] = set()
    for value in change_items:
        change = _closed_mapping(
            value,
            ("path", "operation", "contentHash"),
            "evidence-invalid",
        )
        path = change["path"]
        if (
            type(path) is not str
            or not path.strip()
            or path in change_paths
            or type(change["operation"]) is not str
            or change["operation"] not in {"added", "modified", "deleted"}
            or not _is_sha256(change["contentHash"])
        ):
            _fail("evidence-invalid")
        change_paths.add(path)
    if changes["resultContentHash"] != content_hash:
        return decision("result-content-hash-mismatch")
    verifications = _ordered_sequence(document["verification"], "evidence-invalid")
    if not verifications:
        _fail("evidence-invalid")
    verification_statuses: dict[str, str] = {}
    for value in verifications:
        verification = _closed_mapping(
            value,
            (
                "id",
                "status",
                "contentHash",
                "evidenceHash",
                "verifiedAt",
                "validForSeconds",
                "reason",
            ),
            "evidence-invalid",
        )
        valid_for = verification["validForSeconds"]
        verified_at = _parse_verified_at(verification["verifiedAt"])
        verification_id = verification["id"]
        if (
            type(verification_id) is not str
            or not verification_id
            or verification_id in verification_statuses
            or type(verification["status"]) is not str
            or verification["status"]
            not in {"not-applicable", "not-run", "partial", "passed", "failed"}
            or not _is_sha256(verification["contentHash"])
            or not _is_sha256(verification["evidenceHash"])
            or type(verification["reason"]) is not str
            or type(valid_for) is not int
            or not 1 <= valid_for <= 86400
        ):
            _fail("evidence-invalid")
        if verified_at > observed_at:
            return decision("verification-time-in-future")
        verification_statuses[verification_id] = verification["status"]
        if verification["contentHash"] != content_hash:
            return decision("verification-content-hash-mismatch")
        if observed_at > verified_at + timedelta(seconds=valid_for):
            return decision("verification-stale")
        failure_code = _VERIFICATION_FAILURE_CODES.get(verification["status"])
        if failure_code is not None:
            return decision(failure_code)
        if verification["status"] == "not-applicable":
            if (
                type(verification["reason"]) is not str
                or not verification["reason"].strip()
            ):
                _fail("evidence-invalid")
            if task_kind == "read-only":
                continue
            return decision("verification-not-applicable-for-modification")
        if verification["status"] != "passed":
            _fail("evidence-invalid")
    criteria = _ordered_sequence(document["acceptanceCriteria"], "evidence-invalid")
    if not criteria:
        _fail("evidence-invalid")
    criterion_ids: set[str] = set()
    for value in criteria:
        criterion = _closed_mapping(
            value,
            (
                "id",
                "description",
                "applicability",
                "reason",
                "verificationIds",
            ),
            "evidence-invalid",
        )
        criterion_id = criterion["id"]
        references = _ordered_sequence(
            criterion["verificationIds"],
            "evidence-invalid",
        )
        if (
            type(criterion_id) is not str
            or not criterion_id
            or criterion_id in criterion_ids
            or type(criterion["description"]) is not str
            or not criterion["description"].strip()
            or type(criterion["applicability"]) is not str
            or criterion["applicability"] not in {"applicable", "not-applicable"}
            or type(criterion["reason"]) is not str
            or not references
            or any(type(reference) is not str or not reference for reference in references)
            or len(set(references)) != len(references)
        ):
            _fail("evidence-invalid")
        criterion_ids.add(criterion_id)
        if criterion["applicability"] == "not-applicable":
            if not criterion["reason"].strip():
                _fail("evidence-invalid")
            expected_status = "not-applicable"
        else:
            expected_status = "passed"
        if any(
            verification_statuses.get(reference) != expected_status
            for reference in references
        ):
            return decision("acceptance-criterion-unverified")
    skipped = _ordered_sequence(document["skipped"], "evidence-invalid")
    for value in skipped:
        skipped_item = _closed_mapping(
            value,
            ("item", "reason"),
            "evidence-invalid",
        )
        if (
            type(skipped_item["item"]) is not str
            or not skipped_item["item"].strip()
            or type(skipped_item["reason"]) is not str
            or not skipped_item["reason"].strip()
        ):
            _fail("evidence-invalid")
    residual_risks = _ordered_sequence(
        document["residualRisks"],
        "evidence-invalid",
    )
    for value in residual_risks:
        residual_risk = _closed_mapping(
            value,
            ("risk", "disposition"),
            "evidence-invalid",
        )
        if (
            type(residual_risk["risk"]) is not str
            or not residual_risk["risk"].strip()
            or type(residual_risk["disposition"]) is not str
            or not residual_risk["disposition"].strip()
        ):
            _fail("evidence-invalid")
    return decision("completion-eligible", True)


def _mapping_entries(value: object, code: str) -> tuple[tuple[str, object], ...]:
    if type(value) not in (dict, _MAPPING_PROXY_TYPE):
        _fail(code)
    try:
        entries = tuple(value.items())
    except Exception:
        _fail(code)
    if any(type(key) is not str for key, _ in entries):
        _fail(code)
    return entries


def _closed_mapping(
    value: object,
    keys: tuple[str, ...],
    code: str,
) -> dict[str, object]:
    entries = _mapping_entries(value, code)
    if len(entries) != len(keys) or {key for key, _ in entries} != set(keys):
        _fail(code)
    return {key: item for key, item in entries}


def _ordered_sequence(value: object, code: str) -> tuple[object, ...]:
    if type(value) not in (list, tuple):
        _fail(code)
    return tuple(value)


def _parse_rule(
    value: object,
    code: str,
    *,
    source_kind: str,
    source_name: str,
    protected: bool,
) -> MergedRule:
    rule = _closed_mapping(value, ("id", "strength"), code)
    rule_id = rule["id"]
    strength = rule["strength"]
    if (
        type(rule_id) is not str
        or not rule_id
        or type(strength) is not str
        or strength not in {"enforced", "agent-policy"}
    ):
        _fail(code)
    return MergedRule(
        id=rule_id,
        strength=strength,
        source_kind=source_kind,
        source_name=source_name,
        protected=protected,
    )


def _is_sha256(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def _validate_owner_authorization(value: object) -> None:
    authorization = _closed_mapping(
        value,
        (
            "destructiveChangeConfirmed",
            "versionBump",
            "independentReview",
            "behavioralTests",
        ),
        "protected-rule-owner-authorization-required",
    )
    review = _closed_mapping(
        authorization["independentReview"],
        ("status", "evidenceHash"),
        "protected-rule-owner-authorization-required",
    )
    tests = _closed_mapping(
        authorization["behavioralTests"],
        ("status", "evidenceHash"),
        "protected-rule-owner-authorization-required",
    )
    if (
        type(authorization["destructiveChangeConfirmed"]) is not bool
        or authorization["destructiveChangeConfirmed"] is not True
        or type(authorization["versionBump"]) is not str
        or authorization["versionBump"] != "major"
        or type(review["status"]) is not str
        or review["status"] != "passed"
        or not _is_sha256(review["evidenceHash"])
        or type(tests["status"]) is not str
        or tests["status"] != "passed"
        or not _is_sha256(tests["evidenceHash"])
    ):
        _fail("protected-rule-owner-authorization-required")


def _validate_protected_document_contract(document: dict[str, object]) -> None:
    merge_order = _ordered_sequence(
        document["mergeOrder"],
        "protected-rules-invalid",
    )
    if merge_order != ("protected", "skill", "project", "overlay"):
        _fail("protected-rules-invalid")
    gate = _closed_mapping(
        document["ownerModificationGate"],
        (
            "destructiveChangeConfirmed",
            "versionBump",
            "independentReview",
            "behavioralTests",
        ),
        "protected-rules-invalid",
    )
    review = _closed_mapping(
        gate["independentReview"],
        ("status", "requiresEvidenceHash"),
        "protected-rules-invalid",
    )
    tests = _closed_mapping(
        gate["behavioralTests"],
        ("status", "requiresEvidenceHash"),
        "protected-rules-invalid",
    )
    if (
        type(gate["destructiveChangeConfirmed"]) is not bool
        or gate["destructiveChangeConfirmed"] is not True
        or type(gate["versionBump"]) is not str
        or gate["versionBump"] != "major"
        or type(review["status"]) is not str
        or review["status"] != "passed"
        or type(review["requiresEvidenceHash"]) is not bool
        or review["requiresEvidenceHash"] is not True
        or type(tests["status"]) is not str
        or tests["status"] != "passed"
        or type(tests["requiresEvidenceHash"]) is not bool
        or tests["requiresEvidenceHash"] is not True
    ):
        _fail("protected-rules-invalid")


def merge_protected_rules(
    protected_rules: object,
    lower_priority_layers: object = (),
    *,
    owner_rules: object | None = None,
    owner_authorization: object | None = None,
) -> MergedRules:
    """Merge rules in fixed priority order without allowing protected overrides."""

    document = _closed_mapping(
        protected_rules,
        ("schemaVersion", "mergeOrder", "ownerModificationGate", "rules"),
        "protected-rules-invalid",
    )
    if type(document["schemaVersion"]) is not int or document["schemaVersion"] != 1:
        _fail("protected-rules-invalid")
    _validate_protected_document_contract(document)
    selected_rules = document["rules"]
    source_name = "repository"
    if owner_rules is not None:
        _validate_owner_authorization(owner_authorization)
        selected_rules = owner_rules
        source_name = "repository-owner"
    elif owner_authorization is not None:
        _fail("protected-rule-owner-authorization-required")
    protected = tuple(
        _parse_rule(
            rule,
            "protected-rules-invalid",
            source_kind="protected",
            source_name=source_name,
            protected=True,
        )
        for rule in _ordered_sequence(selected_rules, "protected-rules-invalid")
    )
    protected_ids = {rule.id for rule in protected}
    if len(protected_ids) != len(protected):
        _fail("protected-rules-invalid")

    layer_values = _ordered_sequence(
        lower_priority_layers,
        "protected-rule-layer-invalid",
    )
    parsed_layers: list[tuple[int, str, tuple[MergedRule, ...]]] = []
    seen_layers: set[tuple[str, str]] = set()
    for layer_value in layer_values:
        layer = _closed_mapping(
            layer_value,
            ("kind", "name", "rules"),
            "protected-rule-layer-invalid",
        )
        kind = layer["kind"]
        name = layer["name"]
        if (
            type(kind) is not str
            or kind not in _LAYER_ORDER
            or type(name) is not str
            or not name
        ):
            _fail("protected-rule-layer-invalid")
        layer_identity = (kind, name)
        if layer_identity in seen_layers:
            _fail("protected-rule-layer-invalid")
        seen_layers.add(layer_identity)
        parsed_rules = tuple(
            _parse_rule(
                rule_value,
                "protected-rule-layer-invalid",
                source_kind=kind,
                source_name=name,
                protected=False,
            )
            for rule_value in _ordered_sequence(
                layer["rules"],
                "protected-rule-layer-invalid",
            )
        )
        if len({rule.id for rule in parsed_rules}) != len(parsed_rules):
            _fail("protected-rule-layer-invalid")
        if any(rule.id in protected_ids for rule in parsed_rules):
            _fail("protected-rule-override-denied")
        parsed_layers.append((_LAYER_ORDER[kind], name, parsed_rules))

    merged = {rule.id: rule for rule in protected}
    for _, _, rules in sorted(parsed_layers, key=lambda item: (item[0], item[1])):
        for rule in sorted(rules, key=lambda item: item.id):
            merged[rule.id] = rule
    return MergedRules(tuple(merged[rule_id] for rule_id in sorted(merged)))
