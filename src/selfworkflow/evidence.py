"""Protected-rule merging and completion evidence gates."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import PurePosixPath
import re
from types import MappingProxyType

from .model import Complexity, Risk


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
        "completion-policy-invalid": "The completion policy is invalid.",
        "artifact-store-invalid": "The evidence artifact store is invalid.",
        "manifest-invalid": "A completion file manifest is invalid.",
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
        "completion-policy-mismatch": (
            "The evidence does not match the governing completion policy."
        ),
        "required-capability-missing": (
            "A required capability is missing from the evidence."
        ),
        "capability-set-mismatch": (
            "The capability evidence does not exactly match the required list."
        ),
        "required-capability-unsupported": (
            "A required capability is unsupported."
        ),
        "required-capability-unverified": (
            "A required capability is unverified."
        ),
        "review-level-insufficient": (
            "The completed review level is below the policy minimum."
        ),
        "review-independence-required": (
            "The required review is not independent of implementation."
        ),
        "review-unverified": "The required review is not verified as passed.",
        "artifact-unresolved": "A referenced evidence artifact is unresolved.",
        "artifact-hash-mismatch": (
            "An artifact store key does not match its canonical content hash."
        ),
        "artifact-identity-duplicate": (
            "The artifact store contains a duplicate artifact identity."
        ),
        "artifact-binding-mismatch": (
            "An evidence record does not match its resolved artifact."
        ),
        "changes-manifest-mismatch": (
            "The declared changes do not match the canonical file manifests."
        ),
        "required-item-skipped": (
            "A policy-required completion item cannot be skipped."
        ),
        "verification-required": (
            "A policy-required verification record is missing."
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


@dataclass(frozen=True, init=False)
class CompletionPolicy:
    """Trusted immutable inputs governing one completion decision."""

    task_kind: str
    complexity: Complexity
    risk: Risk
    required_capabilities: tuple[str, ...]
    required_criterion_ids: tuple[str, ...]
    required_verification_ids: tuple[str, ...]
    implementation_actor: str
    implementation_context: str

    def __init__(
        self,
        *,
        task_kind: str,
        complexity: Complexity,
        risk: Risk,
        required_capabilities: tuple[str, ...],
        required_criterion_ids: tuple[str, ...],
        required_verification_ids: tuple[str, ...],
        implementation_actor: str,
        implementation_context: str,
    ) -> None:
        name_groups = (
            required_capabilities,
            required_criterion_ids,
            required_verification_ids,
        )
        if (
            type(task_kind) is not str
            or task_kind not in {"modification", "read-only"}
            or type(complexity) is not Complexity
            or type(risk) is not Risk
            or any(
                type(group) is not tuple
                or not group
                or any(type(item) is not str or not item for item in group)
                or len(set(group)) != len(group)
                for group in name_groups
            )
            or type(implementation_actor) is not str
            or not implementation_actor
            or type(implementation_context) is not str
            or not implementation_context
            or (
                task_kind == "modification"
                and (complexity is Complexity.C0 or risk is Risk.R0)
            )
        ):
            _fail("completion-policy-invalid")
        object.__setattr__(self, "task_kind", task_kind)
        object.__setattr__(self, "complexity", complexity)
        object.__setattr__(self, "risk", risk)
        object.__setattr__(self, "required_capabilities", required_capabilities)
        object.__setattr__(self, "required_criterion_ids", required_criterion_ids)
        object.__setattr__(self, "required_verification_ids", required_verification_ids)
        object.__setattr__(self, "implementation_actor", implementation_actor)
        object.__setattr__(self, "implementation_context", implementation_context)

    @property
    def policy_hash(self) -> str:
        return canonical_content_hash(
            {
                "taskKind": self.task_kind,
                "complexity": self.complexity.value,
                "risk": self.risk.value,
                "requiredCapabilities": self.required_capabilities,
                "requiredCriterionIds": self.required_criterion_ids,
                "requiredVerificationIds": self.required_verification_ids,
                "implementationActor": self.implementation_actor,
                "implementationContext": self.implementation_context,
            }
        )


@dataclass(frozen=True, init=False)
class OwnerChangeRequest:
    """Immutable owner request; merge recomputes and binds every claim."""

    base_rules_hash: str
    proposed_rules_hash: str
    previous_version: str
    new_version: str
    owner_actor: str
    implementation_actor: str
    implementation_context: str
    confirmation_artifact_hash: str
    review_artifact_hash: str
    behavioral_test_artifact_hash: str

    def __init__(self, **values: object) -> None:
        fields = tuple(self.__dataclass_fields__)
        if set(values) != set(fields) or any(
            type(values[field]) is not str or not values[field] for field in fields
        ):
            _fail("protected-rule-owner-authorization-required")
        hash_fields = (
            "base_rules_hash",
            "proposed_rules_hash",
            "confirmation_artifact_hash",
            "review_artifact_hash",
            "behavioral_test_artifact_hash",
        )
        if any(not _is_sha256(values[field]) for field in hash_fields):
            _fail("protected-rule-owner-authorization-required")
        for field in fields:
            object.__setattr__(self, field, values[field])


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
    operation: str
    statement: str
    source_kind: str
    source_name: str
    protected: bool


@dataclass(frozen=True)
class MergedRules:
    """A frozen, deterministic merged rule collection."""

    rules: tuple[MergedRule, ...]
    policy_version: str

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


_ARTIFACT_ATTRIBUTE_KEYS = MappingProxyType(
    {
        "capability": ("name", "state", "policyHash"),
        "review": ("level", "implementationActor", "implementationContext"),
        "verification": ("verificationId", "validForSeconds"),
        "owner-confirmation": ("scope",),
        "owner-review": ("level", "implementationActor", "implementationContext"),
        "behavioral-test": ("suite",),
    }
)
_ARTIFACT_STATUSES = {"passed", "failed", "not-run", "partial", "not-applicable"}


def _parse_timestamp(value: object, code: str) -> datetime:
    if type(value) is not str or re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
        value,
    ) is None:
        _fail(code)
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        _fail(code)


def _parse_artifact(value: object, code: str) -> dict[str, object]:
    record = _closed_mapping(
        value,
        (
            "kind",
            "status",
            "subjectId",
            "subjectHash",
            "actorId",
            "contextId",
            "relatedIds",
            "recordedAt",
            "attributes",
        ),
        code,
    )
    kind = record["kind"]
    if type(kind) is not str or kind not in _ARTIFACT_ATTRIBUTE_KEYS:
        _fail(code)
    attributes = _closed_mapping(
        record["attributes"],
        _ARTIFACT_ATTRIBUTE_KEYS[kind],
        code,
    )
    related = _ordered_sequence(record["relatedIds"], code)
    if (
        type(record["status"]) is not str
        or record["status"] not in _ARTIFACT_STATUSES
        or any(
            type(record[field]) is not str or not record[field]
            for field in ("subjectId", "actorId", "contextId")
        )
        or not _is_sha256(record["subjectHash"])
        or any(type(item) is not str or not item for item in related)
        or len(set(related)) != len(related)
    ):
        _fail(code)
    _parse_timestamp(record["recordedAt"], code)
    if kind == "verification":
        if (
            type(attributes["verificationId"]) is not str
            or not attributes["verificationId"]
            or type(attributes["validForSeconds"]) is not int
            or not 1 <= attributes["validForSeconds"] <= 86400
        ):
            _fail(code)
    elif any(type(item) is not str or not item for item in attributes.values()):
        _fail(code)
    record["relatedIds"] = related
    record["attributes"] = attributes
    return record


def _prepare_artifacts(
    store: object,
) -> tuple[dict[str, dict[str, object]], str | None]:
    entries = _mapping_entries(store, "artifact-store-invalid")
    parsed: dict[str, dict[str, object]] = {}
    identities: set[tuple[object, object]] = set()
    for artifact_hash, value in entries:
        if not _is_sha256(artifact_hash):
            _fail("artifact-store-invalid")
        artifact = _parse_artifact(value, "artifact-store-invalid")
        if canonical_content_hash(value) != artifact_hash:
            return {}, "artifact-hash-mismatch"
        identity = (artifact["kind"], artifact["subjectId"])
        if identity in identities:
            return {}, "artifact-identity-duplicate"
        identities.add(identity)
        parsed[artifact_hash] = artifact
    return parsed, None


def _manifest_hashes(value: object) -> dict[str, str]:
    entries = _mapping_entries(value, "manifest-invalid")
    result: dict[str, str] = {}
    for path, content in entries:
        normalized = str(PurePosixPath(path)) if type(path) is str else ""
        if (
            type(path) is not str
            or not path
            or path != normalized
            or path.startswith("/")
            or "\\" in path
            or ".." in PurePosixPath(path).parts
            or type(content) is not str
            or path in result
        ):
            _fail("manifest-invalid")
        result[path] = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
    return dict(sorted(result.items()))


def _derived_changes(
    base: dict[str, str], final: dict[str, str]
) -> tuple[dict[str, str], ...]:
    changes = []
    for path in sorted(set(base) | set(final)):
        if path not in base:
            operation, content_hash = "added", final[path]
        elif path not in final:
            operation, content_hash = "deleted", base[path]
        elif base[path] != final[path]:
            operation, content_hash = "modified", final[path]
        else:
            continue
        changes.append(
            {"path": path, "operation": operation, "contentHash": content_hash}
        )
    return tuple(changes)


def evaluate_completion(
    policy: object,
    evidence: object,
    result_content: object,
    *,
    artifact_store: object,
    base_manifest: object,
    final_manifest: object,
    now: object,
    previous_observed_at: object | None = None,
) -> CompletionDecision:
    """Evaluate trusted policy and resolved evidence at a redacted boundary."""

    try:
        return _evaluate_completion(
            policy,
            evidence,
            result_content,
            artifact_store=artifact_store,
            base_manifest=base_manifest,
            final_manifest=final_manifest,
            now=now,
            previous_observed_at=previous_observed_at,
        )
    except WorkflowEvidenceError:
        raise
    except Exception:
        _fail("evidence-invalid")


def _evaluate_completion(
    policy: object,
    evidence: object,
    result_content: object,
    *,
    artifact_store: object,
    base_manifest: object,
    final_manifest: object,
    now: object,
    previous_observed_at: object | None,
) -> CompletionDecision:
    if type(policy) is not CompletionPolicy:
        _fail("completion-policy-invalid")
    previous = _as_utc(previous_observed_at) if previous_observed_at is not None else None
    observed_at = _as_utc(now)
    content_hash = canonical_content_hash(result_content)

    def decision(code: str, eligible: bool = False) -> CompletionDecision:
        return _completion_decision(eligible, code, content_hash, observed_at)

    if previous is not None and observed_at < previous:
        return decision("clock-rollback-detected")
    artifacts, artifact_failure = _prepare_artifacts(artifact_store)
    if artifact_failure is not None:
        return decision(artifact_failure)
    base_hashes = _manifest_hashes(base_manifest)
    final_hashes = _manifest_hashes(final_manifest)

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
        ("taskKind", "complexity", "risk", "policyHash"),
        "evidence-invalid",
    )
    expected_classification = {
        "taskKind": policy.task_kind,
        "complexity": policy.complexity.value,
        "risk": policy.risk.value,
        "policyHash": policy.policy_hash,
    }
    if classification != expected_classification:
        return decision("completion-policy-mismatch")

    selected_skills = _ordered_sequence(document["selectedSkills"], "evidence-invalid")
    if (
        any(type(skill) is not str or not skill for skill in selected_skills)
        or len(set(selected_skills)) != len(selected_skills)
    ):
        _fail("evidence-invalid")

    capability_values = _ordered_sequence(document["capabilities"], "evidence-invalid")
    capabilities = []
    for value in capability_values:
        capability = _closed_mapping(
            value, ("name", "state", "artifactHash"), "evidence-invalid"
        )
        if (
            type(capability["name"]) is not str
            or not capability["name"]
            or type(capability["state"]) is not str
            or capability["state"] not in {"supported", "unsupported", "unverified"}
            or not _is_sha256(capability["artifactHash"])
        ):
            _fail("evidence-invalid")
        capabilities.append(capability)
    names = tuple(item["name"] for item in capabilities)
    if any(name not in names for name in policy.required_capabilities):
        return decision("required-capability-missing")
    if names != policy.required_capabilities or len(set(names)) != len(names):
        return decision("capability-set-mismatch")
    for capability in capabilities:
        artifact = artifacts.get(capability["artifactHash"])
        if artifact is None:
            return decision("artifact-unresolved")
        attributes = artifact["attributes"]
        if (
            artifact["kind"] != "capability"
            or artifact["status"] != "passed"
            or artifact["subjectId"] != capability["name"]
            or artifact["subjectHash"] != policy.policy_hash
            or artifact["relatedIds"]
            or attributes
            != {
                "name": capability["name"],
                "state": capability["state"],
                "policyHash": policy.policy_hash,
            }
        ):
            return decision("artifact-binding-mismatch")
        if capability["state"] == "unsupported":
            return decision("required-capability-unsupported")
        if capability["state"] == "unverified":
            return decision("required-capability-unverified")

    changes = _closed_mapping(
        document["changes"],
        (
            "taskKind",
            "resultContentHash",
            "baseManifestHash",
            "finalManifestHash",
            "items",
        ),
        "evidence-invalid",
    )
    if changes["taskKind"] != policy.task_kind:
        return decision("completion-policy-mismatch")
    if not all(
        _is_sha256(changes[field])
        for field in ("resultContentHash", "baseManifestHash", "finalManifestHash")
    ):
        _fail("evidence-invalid")
    if changes["resultContentHash"] != content_hash:
        return decision("result-content-hash-mismatch")
    declared_changes = []
    for value in _ordered_sequence(changes["items"], "evidence-invalid"):
        item = _closed_mapping(
            value, ("path", "operation", "contentHash"), "evidence-invalid"
        )
        if (
            type(item["path"]) is not str
            or not item["path"]
            or type(item["operation"]) is not str
            or item["operation"] not in {"added", "modified", "deleted"}
            or not _is_sha256(item["contentHash"])
        ):
            _fail("evidence-invalid")
        declared_changes.append(item)
    derived_changes = _derived_changes(base_hashes, final_hashes)
    if (
        changes["baseManifestHash"] != canonical_content_hash(base_hashes)
        or changes["finalManifestHash"] != canonical_content_hash(final_hashes)
        or tuple(declared_changes) != derived_changes
        or (policy.task_kind == "modification" and not derived_changes)
        or (policy.task_kind == "read-only" and bool(derived_changes))
    ):
        return decision("changes-manifest-mismatch")

    skipped_values = _ordered_sequence(document["skipped"], "evidence-invalid")
    for value in skipped_values:
        skipped = _closed_mapping(
            value,
            ("targetType", "targetId", "applicability", "reason"),
            "evidence-invalid",
        )
        if (
            type(skipped["targetType"]) is not str
            or skipped["targetType"] not in {"review", "verification", "criterion", "skill"}
            or type(skipped["targetId"]) is not str
            or not skipped["targetId"]
            or type(skipped["applicability"]) is not str
            or skipped["applicability"] not in {"optional", "not-applicable"}
            or type(skipped["reason"]) is not str
            or not skipped["reason"].strip()
        ):
            _fail("evidence-invalid")
        required = (
            skipped["targetType"] == "review"
            and policy.task_kind == "modification"
        ) or (
            skipped["targetType"] == "verification"
            and skipped["targetId"] in policy.required_verification_ids
        ) or (
            skipped["targetType"] == "criterion"
            and skipped["targetId"] in policy.required_criterion_ids
        )
        if required:
            return decision("required-item-skipped")

    review = _closed_mapping(
        document["review"],
        ("id", "status", "level", "artifactHash", "reason"),
        "evidence-invalid",
    )
    if (
        type(review["id"]) is not str
        or not review["id"]
        or type(review["reason"]) is not str
    ):
        _fail("evidence-invalid")
    if policy.task_kind == "read-only":
        if review != {
            "id": review["id"],
            "status": "not-applicable",
            "level": "not-applicable",
            "artifactHash": None,
            "reason": review["reason"],
        } or not review["reason"].strip():
            _fail("evidence-invalid")
    else:
        if (
            review["status"] != "passed"
            or type(review["level"]) is not str
            or review["level"] not in {"L0", "L1", "L2", "L3"}
            or not _is_sha256(review["artifactHash"])
        ):
            return decision("review-unverified")
        artifact = artifacts.get(review["artifactHash"])
        if artifact is None:
            return decision("artifact-unresolved")
        expected_attributes = {
            "level": review["level"],
            "implementationActor": policy.implementation_actor,
            "implementationContext": policy.implementation_context,
        }
        if (
            artifact["kind"] != "review"
            or artifact["status"] != review["status"]
            or artifact["subjectId"] != review["id"]
            or artifact["subjectHash"] != content_hash
            or artifact["relatedIds"]
            or artifact["attributes"] != expected_attributes
        ):
            return decision("artifact-binding-mismatch")
        review_number = int(review["level"][1])
        required_number = (
            2
            if max(int(policy.complexity.value[1]), int(policy.risk.value[1])) >= 2
            else 0
        )
        if review_number < required_number:
            return decision("review-level-insufficient")
        if review_number >= 2 and (
            artifact["actorId"] == policy.implementation_actor
            or artifact["contextId"] == policy.implementation_context
        ):
            return decision("review-independence-required")

    criterion_values = _ordered_sequence(
        document["acceptanceCriteria"], "evidence-invalid"
    )
    criteria = []
    for value in criterion_values:
        criterion = _closed_mapping(
            value,
            ("id", "description", "applicability", "reason", "verificationIds"),
            "evidence-invalid",
        )
        references = _ordered_sequence(criterion["verificationIds"], "evidence-invalid")
        if (
            type(criterion["id"]) is not str
            or not criterion["id"]
            or type(criterion["description"]) is not str
            or not criterion["description"].strip()
            or type(criterion["applicability"]) is not str
            or criterion["applicability"] not in {"applicable", "not-applicable"}
            or type(criterion["reason"]) is not str
            or not references
            or any(type(item) is not str or not item for item in references)
            or len(set(references)) != len(references)
        ):
            _fail("evidence-invalid")
        criterion["verificationIds"] = references
        criteria.append(criterion)
    if tuple(item["id"] for item in criteria) != policy.required_criterion_ids:
        return decision("acceptance-criterion-unverified")

    verification_values = _ordered_sequence(document["verification"], "evidence-invalid")
    verifications = []
    for value in verification_values:
        verification = _closed_mapping(
            value,
            ("id", "status", "artifactHash", "verifiedAt", "validForSeconds", "reason"),
            "evidence-invalid",
        )
        if (
            type(verification["id"]) is not str
            or not verification["id"]
            or type(verification["status"]) is not str
            or verification["status"] not in _ARTIFACT_STATUSES
            or not _is_sha256(verification["artifactHash"])
            or type(verification["validForSeconds"]) is not int
            or not 1 <= verification["validForSeconds"] <= 86400
            or type(verification["reason"]) is not str
        ):
            _fail("evidence-invalid")
        verification["parsedAt"] = _parse_timestamp(
            verification["verifiedAt"], "evidence-time-invalid"
        )
        verifications.append(verification)
    verification_ids = tuple(item["id"] for item in verifications)
    if not verifications or any(
        required not in verification_ids for required in policy.required_verification_ids
    ):
        return decision("verification-required")
    if verification_ids != policy.required_verification_ids:
        return decision("verification-required")

    reverse_links = {
        verification_id: tuple(
            criterion["id"]
            for criterion in criteria
            if verification_id in criterion["verificationIds"]
        )
        for verification_id in verification_ids
    }
    for verification in verifications:
        artifact = artifacts.get(verification["artifactHash"])
        if artifact is None:
            return decision("artifact-unresolved")
        if artifact["subjectHash"] != content_hash:
            return decision("verification-content-hash-mismatch")
        if (
            artifact["kind"] != "verification"
            or artifact["status"] != verification["status"]
            or artifact["subjectId"] != verification["id"]
            or artifact["recordedAt"] != verification["verifiedAt"]
            or artifact["attributes"]
            != {
                "verificationId": verification["id"],
                "validForSeconds": verification["validForSeconds"],
            }
        ):
            return decision("artifact-binding-mismatch")
        if artifact["relatedIds"] != reverse_links[verification["id"]]:
            return decision("acceptance-criterion-unverified")
        if verification["parsedAt"] > observed_at:
            return decision("verification-time-in-future")
        if observed_at > verification["parsedAt"] + timedelta(
            seconds=verification["validForSeconds"]
        ):
            return decision("verification-stale")
        failure = _VERIFICATION_FAILURE_CODES.get(verification["status"])
        if failure is not None:
            return decision(failure)
        if verification["status"] == "not-applicable":
            if not verification["reason"].strip():
                _fail("evidence-invalid")
            if policy.task_kind != "read-only":
                return decision("verification-not-applicable-for-modification")
        elif verification["status"] != "passed":
            _fail("evidence-invalid")

    statuses = {item["id"]: item["status"] for item in verifications}
    for criterion in criteria:
        expected = (
            "not-applicable"
            if criterion["applicability"] == "not-applicable"
            else "passed"
        )
        if criterion["applicability"] == "not-applicable" and not criterion["reason"].strip():
            _fail("evidence-invalid")
        if any(statuses.get(item) != expected for item in criterion["verificationIds"]):
            return decision("acceptance-criterion-unverified")

    for value in _ordered_sequence(document["residualRisks"], "evidence-invalid"):
        risk = _closed_mapping(value, ("risk", "disposition"), "evidence-invalid")
        if any(type(item) is not str or not item.strip() for item in risk.values()):
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
        operation="protected",
        statement="",
        source_kind=source_kind,
        source_name=source_name,
        protected=protected,
    )


def _is_sha256(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def _parse_semver(value: object) -> tuple[int, int, int] | None:
    if type(value) is not str:
        return None
    match = re.fullmatch(
        r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)",
        value,
    )
    return tuple(map(int, match.groups())) if match is not None else None


def _parse_lower_operation(
    value: object, *, source_kind: str, source_name: str
) -> MergedRule:
    operation = _closed_mapping(
        value,
        ("operation", "id", "statement"),
        "protected-rule-layer-invalid",
    )
    if (
        type(operation["operation"]) is not str
        or operation["operation"] not in {"add-requirement", "advisory"}
        or type(operation["id"]) is not str
        or not operation["id"]
        or type(operation["statement"]) is not str
        or not operation["statement"].strip()
    ):
        _fail("protected-rule-layer-invalid")
    return MergedRule(
        id=operation["id"],
        strength=(
            "enforced" if operation["operation"] == "add-requirement" else "agent-policy"
        ),
        operation=operation["operation"],
        statement=operation["statement"],
        source_kind=source_kind,
        source_name=source_name,
        protected=False,
    )


def _validate_owner_change(
    document: dict[str, object],
    selected_rules: object,
    request: object,
    artifact_store: object,
) -> str:
    code = "protected-rule-owner-authorization-required"
    if type(request) is not OwnerChangeRequest:
        _fail(code)
    base_hash = canonical_content_hash(document["rules"])
    proposed_hash = canonical_content_hash(selected_rules)
    previous = _parse_semver(request.previous_version)
    new = _parse_semver(request.new_version)
    if (
        request.base_rules_hash != base_hash
        or request.proposed_rules_hash != proposed_hash
        or request.previous_version != document["policyVersion"]
        or previous is None
        or new is None
        or new[0] <= previous[0]
        or len(
            {
                request.confirmation_artifact_hash,
                request.review_artifact_hash,
                request.behavioral_test_artifact_hash,
            }
        )
        != 3
    ):
        _fail(code)
    try:
        artifacts, failure = _prepare_artifacts(artifact_store)
    except WorkflowEvidenceError:
        _fail(code)
    if failure is not None:
        _fail(code)
    confirmation = artifacts.get(request.confirmation_artifact_hash)
    review = artifacts.get(request.review_artifact_hash)
    tests = artifacts.get(request.behavioral_test_artifact_hash)
    if confirmation is None or review is None or tests is None:
        _fail(code)
    if (
        confirmation["kind"] != "owner-confirmation"
        or confirmation["status"] != "passed"
        or confirmation["subjectId"] != "protected-rules-change"
        or confirmation["subjectHash"] != proposed_hash
        or confirmation["actorId"] != request.owner_actor
        or confirmation["relatedIds"]
        or confirmation["attributes"] != {"scope": "replace-protected-rules"}
        or review["kind"] != "owner-review"
        or review["status"] != "passed"
        or review["subjectId"] != "protected-rules-change"
        or review["subjectHash"] != proposed_hash
        or review["relatedIds"]
        or review["actorId"] == request.implementation_actor
        or review["contextId"] == request.implementation_context
        or review["attributes"]
        != {
            "level": "L2",
            "implementationActor": request.implementation_actor,
            "implementationContext": request.implementation_context,
        }
        or tests["kind"] != "behavioral-test"
        or tests["status"] != "passed"
        or tests["subjectId"] != "protected-rules-change"
        or tests["subjectHash"] != proposed_hash
        or tests["relatedIds"]
        or tests["attributes"] != {"suite": "protected-rules"}
    ):
        _fail(code)
    return request.new_version


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
            "versionChange",
            "confirmationArtifactKind",
            "reviewArtifactKind",
            "behavioralTestArtifactKind",
        ),
        "protected-rules-invalid",
    )
    if gate != {
        "versionChange": "semver-major",
        "confirmationArtifactKind": "owner-confirmation",
        "reviewArtifactKind": "owner-review",
        "behavioralTestArtifactKind": "behavioral-test",
    }:
        _fail("protected-rules-invalid")


def merge_protected_rules(
    protected_rules: object,
    lower_priority_layers: object = (),
    *,
    owner_rules: object | None = None,
    owner_change: object | None = None,
    artifact_store: object | None = None,
) -> MergedRules:
    """Merge rules in fixed priority order without allowing protected overrides."""

    document = _closed_mapping(
        protected_rules,
        (
            "schemaVersion",
            "policyVersion",
            "mergeOrder",
            "ownerModificationGate",
            "rules",
        ),
        "protected-rules-invalid",
    )
    if (
        type(document["schemaVersion"]) is not int
        or document["schemaVersion"] != 1
        or _parse_semver(document["policyVersion"]) is None
    ):
        _fail("protected-rules-invalid")
    _validate_protected_document_contract(document)
    selected_rules = document["rules"]
    source_name = "repository"
    policy_version = document["policyVersion"]
    if owner_rules is not None:
        selected_rules = owner_rules
        policy_version = _validate_owner_change(
            document,
            selected_rules,
            owner_change,
            artifact_store,
        )
        source_name = "repository-owner"
    elif owner_change is not None or artifact_store is not None:
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
            ("kind", "name", "operations"),
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
            _parse_lower_operation(
                rule_value,
                source_kind=kind,
                source_name=name,
            )
            for rule_value in _ordered_sequence(
                layer["operations"],
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
    return MergedRules(
        tuple(merged[rule_id] for rule_id in sorted(merged)),
        policy_version,
    )
