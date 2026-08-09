"""Protected-rule merging and completion evidence gates."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from types import MappingProxyType

from ._evidence_artifacts import (
    _ARTIFACT_STATUSES,
    _parse_timestamp,
    ArtifactCollector,
    ExecutionInvocation,
    TrustedArtifactStore,
    prepare_artifacts as _prepare_artifacts,
)
from ._evidence_values import (
    MAX_ACCEPTANCE_CRITERIA,
    MAX_CAPABILITIES,
    MAX_CHANGES,
    MAX_IDENTIFIER_UTF8_BYTES,
    MAX_RESIDUAL_RISKS,
    MAX_SELECTED_SKILLS,
    MAX_SKIPPED,
    MAX_TEXT_UTF8_BYTES,
    MAX_VERIFICATIONS,
    bounded_text,
    WorkflowEvidenceError,
    canonical_content_hash,
    fail as _fail,
    manifest_hashes,
    parse_evidence_json,
    repository_path_identity,
    review_level_at_least,
)
from .model import CapabilityState, Complexity, Risk


_MAPPING_PROXY_TYPE = type(MappingProxyType({}))
_LAYER_ORDER = {"skill": 1, "project": 2, "overlay": 3}
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
        "artifact-receipt-duplicate": (
            "The artifact store contains a duplicate provider receipt."
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
        "verification-invocation-mismatch": (
            "A verification used an invocation other than the trusted policy expectation."
        ),
        "verification-invocation-input-mismatch": (
            "A verification invocation is not bound to the current task input."
        ),
        "capability-time-in-future": (
            "Capability evidence cannot be newer than the observation time."
        ),
        "capability-stale": "Capability evidence is outside the trusted freshness window.",
        "review-time-in-future": (
            "Review evidence cannot be newer than the observation time."
        ),
        "review-stale": "Review evidence is outside the trusted freshness window.",
    }
)
_VERIFICATION_FAILURE_CODES = MappingProxyType(
    {
        "failed": "verification-failed",
        "not-run": "verification-not-run",
        "partial": "verification-partial",
    }
)
_OUTPUT_TOKEN = object()


def _valid_policy_group(value: object, maximum: int) -> bool:
    return (
        type(value) is tuple
        and 0 < len(value) <= maximum
        and all(
            bounded_text(item, maximum=MAX_IDENTIFIER_UTF8_BYTES)
            for item in value
        )
        and len(set(value)) == len(value)
    )


def _require_direct_text_budget(
    *values: object,
    maximum: int = MAX_TEXT_UTF8_BYTES,
) -> None:
    if any(
        type(value) is str
        and not bounded_text(value, maximum=maximum, allow_empty=True)
        for value in values
    ):
        _fail("evidence-budget-exceeded")


@dataclass(frozen=True)
class ReviewFallbackAuthorization:
    """Trusted explicit authorization for the L2-unavailable L1 path."""

    capability_name: str
    capability_state: CapabilityState
    user_prompted: bool
    user_authorized: bool
    authorization_id: str

    def __post_init__(self) -> None:
        if (
            not bounded_text(
                self.capability_name, maximum=MAX_IDENTIFIER_UTF8_BYTES
            )
            or self.capability_name != "independent-context"
            or type(self.capability_state) is not CapabilityState
            or self.capability_state
            not in {CapabilityState.UNSUPPORTED, CapabilityState.UNVERIFIED}
            or type(self.user_prompted) is not bool
            or self.user_prompted is not True
            or type(self.user_authorized) is not bool
            or self.user_authorized is not True
            or not bounded_text(
                self.authorization_id, maximum=MAX_IDENTIFIER_UTF8_BYTES
            )
        ):
            _fail("review-fallback-authorization-invalid")


@dataclass(frozen=True, init=False)
class CompletionPolicy:
    """Trusted immutable inputs governing one completion decision."""

    task_kind: str
    complexity: Complexity
    risk: Risk
    required_capabilities: tuple[str, ...]
    required_criterion_ids: tuple[str, ...]
    required_verification_ids: tuple[str, ...]
    expected_verification_invocations: tuple[tuple[str, str], ...]
    implementation_actor: str
    implementation_context: str
    task_nonce: str
    artifact_freshness_seconds: int
    review_fallback: ReviewFallbackAuthorization | None

    def __init__(
        self,
        *,
        task_kind: str,
        complexity: Complexity,
        risk: Risk,
        required_capabilities: tuple[str, ...],
        required_criterion_ids: tuple[str, ...],
        required_verification_ids: tuple[str, ...],
        expected_verification_invocations: tuple[tuple[str, str], ...],
        implementation_actor: str,
        implementation_context: str,
        task_nonce: str,
        artifact_freshness_seconds: int,
        review_fallback: ReviewFallbackAuthorization | None = None,
    ) -> None:
        name_groups = (
            (required_capabilities, MAX_CAPABILITIES),
            (required_criterion_ids, MAX_ACCEPTANCE_CRITERIA),
            (required_verification_ids, MAX_VERIFICATIONS),
        )
        if (
            not bounded_text(task_kind, maximum=MAX_IDENTIFIER_UTF8_BYTES)
            or task_kind not in {"modification", "read-only"}
            or type(complexity) is not Complexity
            or type(risk) is not Risk
            or any(
                not _valid_policy_group(group, maximum)
                for group, maximum in name_groups
            )
            or not bounded_text(
                implementation_actor, maximum=MAX_IDENTIFIER_UTF8_BYTES
            )
            or not bounded_text(
                implementation_context, maximum=MAX_IDENTIFIER_UTF8_BYTES
            )
            or not bounded_text(task_nonce, maximum=256)
            or type(artifact_freshness_seconds) is not int
            or not 1 <= artifact_freshness_seconds <= 86400
            or (
                review_fallback is not None
                and type(review_fallback) is not ReviewFallbackAuthorization
            )
            or (
                task_kind == "modification"
                and (complexity is Complexity.C0 or risk is Risk.R0)
            )
            or type(expected_verification_invocations) is not tuple
            or len(expected_verification_invocations) > MAX_VERIFICATIONS
            or any(
                type(item) is not tuple
                or len(item) != 2
                or not bounded_text(item[0], maximum=MAX_IDENTIFIER_UTF8_BYTES)
                or not bounded_text(item[1], maximum=MAX_IDENTIFIER_UTF8_BYTES)
                or not _is_sha256(item[1])
                for item in expected_verification_invocations
            )
            or tuple(item[0] for item in expected_verification_invocations)
            != required_verification_ids
        ):
            _fail("completion-policy-invalid")
        object.__setattr__(self, "task_kind", task_kind)
        object.__setattr__(self, "complexity", complexity)
        object.__setattr__(self, "risk", risk)
        object.__setattr__(self, "required_capabilities", required_capabilities)
        object.__setattr__(self, "required_criterion_ids", required_criterion_ids)
        object.__setattr__(self, "required_verification_ids", required_verification_ids)
        object.__setattr__(
            self,
            "expected_verification_invocations",
            expected_verification_invocations,
        )
        object.__setattr__(self, "implementation_actor", implementation_actor)
        object.__setattr__(self, "implementation_context", implementation_context)
        object.__setattr__(self, "task_nonce", task_nonce)
        object.__setattr__(
            self, "artifact_freshness_seconds", artifact_freshness_seconds
        )
        object.__setattr__(self, "review_fallback", review_fallback)

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
                "expectedVerificationInvocations": self.expected_verification_invocations,
                "implementationActor": self.implementation_actor,
                "implementationContext": self.implementation_context,
                "taskNonce": self.task_nonce,
                "artifactFreshnessSeconds": self.artifact_freshness_seconds,
                "reviewFallback": (
                    None
                    if self.review_fallback is None
                    else {
                        "capabilityName": self.review_fallback.capability_name,
                        "capabilityState": self.review_fallback.capability_state.value,
                        "userPrompted": self.review_fallback.user_prompted,
                        "userAuthorized": self.review_fallback.user_authorized,
                        "authorizationId": self.review_fallback.authorization_id,
                    }
                ),
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
    operation_nonce: str
    proposed_at: datetime
    valid_for_seconds: int
    behavioral_test_invocation_hash: str
    confirmation_artifact_hash: str
    review_artifact_hash: str
    behavioral_test_artifact_hash: str

    @property
    def pre_test_subject_hash(self) -> str:
        return owner_pre_test_subject_hash(
            base_rules_hash=self.base_rules_hash,
            proposed_rules_hash=self.proposed_rules_hash,
            previous_version=self.previous_version,
            new_version=self.new_version,
            operation_nonce=self.operation_nonce,
            proposed_at=self.proposed_at,
            valid_for_seconds=self.valid_for_seconds,
        )

    @property
    def proposal_hash(self) -> str:
        return owner_change_proposal_hash(
            base_rules_hash=self.base_rules_hash,
            proposed_rules_hash=self.proposed_rules_hash,
            previous_version=self.previous_version,
            new_version=self.new_version,
            operation_nonce=self.operation_nonce,
            proposed_at=self.proposed_at,
            valid_for_seconds=self.valid_for_seconds,
            behavioral_test_invocation_hash=self.behavioral_test_invocation_hash,
        )

    def __init__(self, **values: object) -> None:
        fields = tuple(self.__dataclass_fields__)
        text_fields = tuple(
            field
            for field in fields
            if field not in {"proposed_at", "valid_for_seconds"}
        )
        if set(values) != set(fields) or any(
            not bounded_text(values[field], maximum=MAX_IDENTIFIER_UTF8_BYTES)
            for field in text_fields
        ):
            _fail("protected-rule-owner-authorization-required")
        hash_fields = (
            "base_rules_hash",
            "proposed_rules_hash",
            "confirmation_artifact_hash",
            "review_artifact_hash",
            "behavioral_test_artifact_hash",
            "behavioral_test_invocation_hash",
        )
        try:
            proposed_at = _as_utc(values["proposed_at"])
        except WorkflowEvidenceError:
            _fail("protected-rule-owner-authorization-required")
        if (
            any(not _is_sha256(values[field]) for field in hash_fields)
            or not bounded_text(values["operation_nonce"], maximum=256)
            or type(values["valid_for_seconds"]) is not int
            or not 1 <= values["valid_for_seconds"] <= 86400
        ):
            _fail("protected-rule-owner-authorization-required")
        for field in fields:
            object.__setattr__(
                self,
                field,
                proposed_at if field == "proposed_at" else values[field],
            )


def owner_pre_test_subject_hash(
    *,
    base_rules_hash: str,
    proposed_rules_hash: str,
    previous_version: str,
    new_version: str,
    operation_nonce: str,
    proposed_at: datetime,
    valid_for_seconds: int,
) -> str:
    """Bind a behavioral invocation to one owner-change operation."""

    return canonical_content_hash(
        _owner_change_subject_values(
            base_rules_hash=base_rules_hash,
            proposed_rules_hash=proposed_rules_hash,
            previous_version=previous_version,
            new_version=new_version,
            operation_nonce=operation_nonce,
            proposed_at=proposed_at,
            valid_for_seconds=valid_for_seconds,
        )
    )


def owner_change_proposal_hash(
    *,
    base_rules_hash: str,
    proposed_rules_hash: str,
    previous_version: str,
    new_version: str,
    operation_nonce: str,
    proposed_at: datetime,
    valid_for_seconds: int,
    behavioral_test_invocation_hash: str,
) -> str:
    """Bind all owner attestations to the selected behavioral invocation."""

    if not _is_sha256(behavioral_test_invocation_hash):
        _fail("protected-rule-owner-authorization-required")
    values = _owner_change_subject_values(
        base_rules_hash=base_rules_hash,
        proposed_rules_hash=proposed_rules_hash,
        previous_version=previous_version,
        new_version=new_version,
        operation_nonce=operation_nonce,
        proposed_at=proposed_at,
        valid_for_seconds=valid_for_seconds,
    )
    values["behavioralTestInvocationHash"] = behavioral_test_invocation_hash
    return canonical_content_hash(values)


def _owner_change_subject_values(
    *,
    base_rules_hash: str,
    proposed_rules_hash: str,
    previous_version: str,
    new_version: str,
    operation_nonce: str,
    proposed_at: datetime,
    valid_for_seconds: int,
) -> dict[str, object]:

    code = "protected-rule-owner-authorization-required"
    if (
        not _is_sha256(base_rules_hash)
        or not _is_sha256(proposed_rules_hash)
        or not bounded_text(previous_version, maximum=MAX_IDENTIFIER_UTF8_BYTES)
        or not bounded_text(new_version, maximum=MAX_IDENTIFIER_UTF8_BYTES)
        or not bounded_text(operation_nonce, maximum=256)
        or type(valid_for_seconds) is not int
        or not 1 <= valid_for_seconds <= 86400
    ):
        _fail(code)
    try:
        normalized_proposed_at = _as_utc(proposed_at)
    except WorkflowEvidenceError:
        _fail(code)
    return {
        "baseRulesHash": base_rules_hash,
        "proposedRulesHash": proposed_rules_hash,
        "previousVersion": previous_version,
        "newVersion": new_version,
        "operationNonce": operation_nonce,
        "proposedAt": _format_utc(normalized_proposed_at),
        "validForSeconds": valid_for_seconds,
    }


def _initialize_output(instance: object, values: dict[str, object], token: object) -> None:
    fields = tuple(instance.__dataclass_fields__)
    if token is not _OUTPUT_TOKEN or set(values) != set(fields):
        _fail("output-construction-denied")
    for field in fields:
        object.__setattr__(instance, field, values[field])


@dataclass(frozen=True, init=False)
class CompletionDecision:
    """A frozen completion-gate decision with no rejected input values."""

    eligible: bool
    code: str
    message: str
    content_hash: str
    observed_at: str

    def __init__(self, *args: object, _token: object = None, **values: object):
        if args:
            _fail("output-construction-denied")
        _initialize_output(self, values, _token)


@dataclass(frozen=True, init=False)
class MergedRule:
    """A deeply immutable rule in deterministic merge order."""

    id: str
    strength: str
    operation: str
    statement: str
    constraint: tuple[str, str, str, str]
    source_kind: str
    source_name: str
    protected: bool

    def __init__(self, *args: object, _token: object = None, **values: object):
        if args:
            _fail("output-construction-denied")
        _initialize_output(self, values, _token)


@dataclass(frozen=True, init=False)
class MergedRules:
    """A frozen, deterministic merged rule collection."""

    rules: tuple[MergedRule, ...]
    policy_version: str

    def __init__(self, *args: object, _token: object = None, **values: object):
        if args:
            _fail("output-construction-denied")
        _initialize_output(self, values, _token)

    def rule_for(self, rule_id: str) -> MergedRule | None:
        if type(rule_id) is not str or not rule_id:
            _fail("protected-rules-invalid")
        return next((rule for rule in self.rules if rule.id == rule_id), None)


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
        _token=_OUTPUT_TOKEN,
        eligible=eligible,
        code=code,
        message=_DECISION_MESSAGES[code],
        content_hash=content_hash,
        observed_at=_format_utc(observed_at),
    )


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


def _parse_acceptance_graph(
    value: object, policy: CompletionPolicy
) -> list[dict[str, object]]:
    criteria = []
    values = _ordered_sequence(
        value, "evidence-invalid", maximum=MAX_ACCEPTANCE_CRITERIA
    )
    for item in values:
        criterion = _closed_mapping(
            item,
            ("id", "description", "applicability", "reason", "verificationIds"),
            "evidence-invalid",
        )
        references = _ordered_sequence(
            criterion["verificationIds"],
            "evidence-invalid",
            maximum=MAX_VERIFICATIONS,
        )
        _require_direct_text_budget(
            criterion["id"], *references, maximum=MAX_IDENTIFIER_UTF8_BYTES
        )
        _require_direct_text_budget(
            criterion["description"],
            criterion["applicability"],
            criterion["reason"],
        )
        if (
            type(criterion["id"]) is not str
            or not criterion["id"]
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
        criterion["verificationIds"] = references
        criteria.append(criterion)
    if tuple(item["id"] for item in criteria) != policy.required_criterion_ids:
        return []
    return criteria


def _completion_subject_hash(
    policy: CompletionPolicy,
    content_hash: str,
    base_hashes: dict[str, str],
    final_hashes: dict[str, str],
    changes: tuple[dict[str, str], ...],
    criteria: list[dict[str, object]],
) -> str:
    return canonical_content_hash(
        {
            "policyHash": policy.policy_hash,
            "baseManifestHash": canonical_content_hash(base_hashes),
            "finalManifestHash": canonical_content_hash(final_hashes),
            "derivedChanges": changes,
            "acceptanceGraph": criteria,
            "resultContentHash": content_hash,
        }
    )


def pre_verification_subject_hash(
    *,
    task_nonce: str,
    base_manifest_hash: str,
    final_manifest_hash: str,
    derived_changes: object,
    acceptance_graph: object,
    result_content_hash: str,
) -> str:
    """Hash current verification inputs without policy/invocation cycles."""

    if (
        not bounded_text(task_nonce, maximum=256)
        or not _is_sha256(base_manifest_hash)
        or not _is_sha256(final_manifest_hash)
        or not _is_sha256(result_content_hash)
    ):
        _fail("completion-policy-invalid")
    return canonical_content_hash(
        {
            "taskNonce": task_nonce,
            "baseManifestHash": base_manifest_hash,
            "finalManifestHash": final_manifest_hash,
            "derivedChanges": derived_changes,
            "acceptanceGraph": acceptance_graph,
            "resultContentHash": result_content_hash,
        }
    )


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
    base_hashes, base_identities = manifest_hashes(base_manifest)
    final_hashes, final_identities = manifest_hashes(final_manifest)
    if any(
        base_identities[identity] != final_identities[identity]
        for identity in set(base_identities) & set(final_identities)
    ):
        _fail("manifest-invalid")

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
    _require_direct_text_budget(
        *classification.values(), maximum=MAX_IDENTIFIER_UTF8_BYTES
    )
    expected_classification = {
        "taskKind": policy.task_kind,
        "complexity": policy.complexity.value,
        "risk": policy.risk.value,
        "policyHash": policy.policy_hash,
    }
    if classification != expected_classification:
        return decision("completion-policy-mismatch")

    selected_skills = _ordered_sequence(
        document["selectedSkills"],
        "evidence-invalid",
        maximum=MAX_SELECTED_SKILLS,
    )
    _require_direct_text_budget(
        *selected_skills, maximum=MAX_IDENTIFIER_UTF8_BYTES
    )
    if (
        any(type(skill) is not str or not skill for skill in selected_skills)
        or len(set(selected_skills)) != len(selected_skills)
    ):
        _fail("evidence-invalid")

    capability_values = _ordered_sequence(
        document["capabilities"],
        "evidence-invalid",
        maximum=MAX_CAPABILITIES,
    )
    capabilities = []
    for value in capability_values:
        capability = _closed_mapping(
            value, ("name", "state", "artifactHash"), "evidence-invalid"
        )
        _require_direct_text_budget(
            *capability.values(), maximum=MAX_IDENTIFIER_UTF8_BYTES
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
                "provider": attributes["provider"],
                "receiptId": attributes["receiptId"],
            }
        ):
            return decision("artifact-binding-mismatch")
        capability_time = _parse_timestamp(
            artifact["recordedAt"], "evidence-time-invalid"
        )
        if capability_time > observed_at:
            return decision("capability-time-in-future")
        if observed_at > capability_time + timedelta(
            seconds=policy.artifact_freshness_seconds
        ):
            return decision("capability-stale")
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
    _require_direct_text_budget(
        changes["taskKind"],
        changes["resultContentHash"],
        changes["baseManifestHash"],
        changes["finalManifestHash"],
        maximum=MAX_IDENTIFIER_UTF8_BYTES,
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
    change_values = _ordered_sequence(
        changes["items"], "evidence-invalid", maximum=MAX_CHANGES
    )
    for value in change_values:
        item = _closed_mapping(
            value, ("path", "operation", "contentHash"), "evidence-invalid"
        )
        _require_direct_text_budget(
            *item.values(), maximum=MAX_IDENTIFIER_UTF8_BYTES
        )
        if (
            type(item["path"]) is not str
            or not item["path"]
            or type(item["operation"]) is not str
            or item["operation"] not in {"added", "modified", "deleted"}
            or not _is_sha256(item["contentHash"])
        ):
            _fail("evidence-invalid")
        repository_path_identity(item["path"])
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

    criteria = _parse_acceptance_graph(document["acceptanceCriteria"], policy)
    if not criteria:
        return decision("acceptance-criterion-unverified")
    pre_verification_subject = pre_verification_subject_hash(
        task_nonce=policy.task_nonce,
        base_manifest_hash=changes["baseManifestHash"],
        final_manifest_hash=changes["finalManifestHash"],
        derived_changes=derived_changes,
        acceptance_graph=criteria,
        result_content_hash=content_hash,
    )
    completion_subject = _completion_subject_hash(
        policy,
        content_hash,
        base_hashes,
        final_hashes,
        derived_changes,
        criteria,
    )

    skipped_values = _ordered_sequence(
        document["skipped"], "evidence-invalid", maximum=MAX_SKIPPED
    )
    for value in skipped_values:
        skipped = _closed_mapping(
            value,
            ("targetType", "targetId", "applicability", "reason"),
            "evidence-invalid",
        )
        _require_direct_text_budget(
            skipped["targetType"],
            skipped["targetId"],
            skipped["applicability"],
            maximum=MAX_IDENTIFIER_UTF8_BYTES,
        )
        _require_direct_text_budget(skipped["reason"])
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
    _require_direct_text_budget(
        review["id"],
        review["status"],
        review["level"],
        review["artifactHash"],
        maximum=MAX_IDENTIFIER_UTF8_BYTES,
    )
    _require_direct_text_budget(review["reason"])
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
        attributes = artifact["attributes"]
        if (
            artifact["kind"] != "review"
            or artifact["status"] != review["status"]
            or artifact["subjectId"] != review["id"]
            or artifact["subjectHash"] != completion_subject
            or artifact["relatedIds"]
            or attributes["decision"] != "passed"
            or attributes["level"] != review["level"]
            or attributes["implementationActor"] != policy.implementation_actor
            or attributes["implementationContext"] != policy.implementation_context
        ):
            return decision("artifact-binding-mismatch")
        review_time = _parse_timestamp(artifact["recordedAt"], "evidence-time-invalid")
        if review_time > observed_at:
            return decision("review-time-in-future")
        if observed_at > review_time + timedelta(
            seconds=policy.artifact_freshness_seconds
        ):
            return decision("review-stale")
        review_number = int(review["level"][1])
        governing_level = max(
            int(policy.complexity.value[1]),
            int(policy.risk.value[1]),
        )
        required_number = 2 if governing_level >= 2 else 0
        fallback_allowed = (
            governing_level == 2
            and review_number == 1
            and policy.review_fallback is not None
        )
        required_level = f"L{required_number}"
        if not review_level_at_least(review["level"], required_level) and not fallback_allowed:
            return decision("review-level-insufficient")
        if (
            review_number >= 2
            and artifact["actorId"] == policy.implementation_actor
        ) or (
            (review_number >= 2 or fallback_allowed)
            and artifact["contextId"] == policy.implementation_context
        ):
            return decision("review-independence-required")

    verification_values = _ordered_sequence(
        document["verification"],
        "evidence-invalid",
        maximum=MAX_VERIFICATIONS,
    )
    verifications = []
    for value in verification_values:
        verification = _closed_mapping(
            value,
            ("id", "status", "artifactHash", "verifiedAt", "validForSeconds", "reason"),
            "evidence-invalid",
        )
        _require_direct_text_budget(
            verification["id"],
            verification["status"],
            verification["artifactHash"],
            verification["verifiedAt"],
            maximum=MAX_IDENTIFIER_UTF8_BYTES,
        )
        _require_direct_text_budget(verification["reason"])
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
    expected_invocations = dict(policy.expected_verification_invocations)
    for verification in verifications:
        artifact = artifacts.get(verification["artifactHash"])
        if artifact is None:
            return decision("artifact-unresolved")
        if artifact["subjectHash"] != completion_subject:
            return decision("verification-content-hash-mismatch")
        if (
            artifact["attributes"]["invocation"]["inputHash"]
            != pre_verification_subject
        ):
            return decision("verification-invocation-input-mismatch")
        if (
            artifact["attributes"].get("invocationHash")
            != expected_invocations[verification["id"]]
        ):
            return decision("verification-invocation-mismatch")
        if (
            artifact["kind"] != "verification"
            or artifact["status"] != verification["status"]
            or artifact["subjectId"] != verification["id"]
            or artifact["recordedAt"] != verification["verifiedAt"]
            or artifact["attributes"]["verificationId"] != verification["id"]
            or artifact["attributes"]["validForSeconds"]
            != verification["validForSeconds"]
            or verification["validForSeconds"]
            != policy.artifact_freshness_seconds
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

    residual_risks = _ordered_sequence(
        document["residualRisks"],
        "evidence-invalid",
        maximum=MAX_RESIDUAL_RISKS,
    )
    for value in residual_risks:
        risk = _closed_mapping(value, ("risk", "disposition"), "evidence-invalid")
        _require_direct_text_budget(risk["risk"], risk["disposition"])
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
    if type(value) not in (dict, _MAPPING_PROXY_TYPE) or len(value) != len(keys):
        _fail(code)
    entries = _mapping_entries(value, code)
    if {key for key, _ in entries} != set(keys):
        _fail(code)
    return {key: item for key, item in entries}


def _ordered_sequence(
    value: object,
    code: str,
    *,
    maximum: int | None = None,
) -> tuple[object, ...]:
    if type(value) not in (list, tuple):
        _fail(code)
    if maximum is not None and len(value) > maximum:
        _fail("evidence-budget-exceeded")
    return tuple(value)


def _parse_rule(
    value: object,
    code: str,
    *,
    source_kind: str,
    source_name: str,
    protected: bool,
) -> MergedRule:
    entries = dict(_mapping_entries(value, code))
    if entries.get("id") == "require-independent-post-grill-brainstorming-review":
        rule = _closed_mapping(
            value,
            ("id", "strength", "gate", "evaluator", "reasonCodes"),
            code,
        )
        if (
            rule["strength"] != "enforced"
            or rule["gate"] != "design.post-grill-review"
            or rule["evaluator"] != "post-grill-review-independence-v1"
            or _ordered_sequence(rule["reasonCodes"], code) != (
                "post-grill-independent-review-required",
                "post-grill-review-input-invalid",
                "post-grill-review-attestation-missing",
                "post-grill-review-user-authorization-required",
                "post-grill-review-changes-required",
                "post-grill-review-authorization-replayed",
                "post-grill-review-attestation-replayed",
            )
        ):
            _fail(code)
    else:
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
        _token=_OUTPUT_TOKEN,
        id=rule_id,
        strength=strength,
        operation="protected",
        statement="",
        constraint=("protected-invariant", rule_id, "enforce", strength),
        source_kind=source_kind,
        source_name=source_name,
        protected=protected,
    )


def _is_sha256(value: object) -> bool:
    return (
        bounded_text(value, maximum=71)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None
    )


def _parse_semver(value: object) -> tuple[int, int, int] | None:
    if not bounded_text(value, maximum=MAX_IDENTIFIER_UTF8_BYTES):
        return None
    match = re.fullmatch(
        r"(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})",
        value,
    )
    try:
        return tuple(map(int, match.groups())) if match is not None else None
    except (TypeError, ValueError):
        return None


def _parse_lower_operation(
    value: object, *, source_kind: str, source_name: str
) -> MergedRule:
    operation = _closed_mapping(
        value,
        ("operation", "id", "constraint"),
        "protected-rule-layer-invalid",
    )
    constraint = _closed_mapping(
        operation["constraint"],
        ("kind", "target", "mode", "value"),
        "protected-rule-layer-invalid",
    )
    constraint_values = tuple(constraint[field] for field in ("kind", "target", "mode", "value"))
    identifier = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
    if (
        type(operation["operation"]) is not str
        or operation["operation"] not in {"add-requirement", "advisory"}
        or type(operation["id"]) is not str
        or identifier.fullmatch(operation["id"]) is None
        or any(type(item) is not str for item in constraint_values)
        or identifier.fullmatch(constraint["target"]) is None
    ):
        _fail("protected-rule-layer-invalid")
    valid_constraint = (
        operation["operation"] == "add-requirement"
        and (
            (
                constraint["kind"] == "capability-state"
                and constraint["mode"] == "equals"
                and constraint["value"] == "supported"
            )
            or (
                constraint["kind"] == "verification-status"
                and constraint["mode"] == "equals"
                and constraint["value"] == "passed"
            )
            or (
                constraint["kind"] == "review-level"
                and constraint["mode"] == "at-least"
                and constraint["value"] in {"L0", "L1", "L2", "L3"}
            )
        )
    ) or (
        operation["operation"] == "advisory"
        and constraint["kind"] == "workflow-action"
        and constraint["target"] in {"review", "verification", "documentation"}
        and constraint["mode"] == "recommend"
        and constraint["value"] in {"perform", "record"}
    )
    if not valid_constraint:
        _fail("protected-rule-layer-invalid")
    return MergedRule(
        _token=_OUTPUT_TOKEN,
        id=operation["id"],
        strength=(
            "enforced" if operation["operation"] == "add-requirement" else "agent-policy"
        ),
        operation=operation["operation"],
        statement="",
        constraint=constraint_values,
        source_kind=source_kind,
        source_name=source_name,
        protected=False,
    )


def _validate_owner_change(
    document: dict[str, object],
    selected_rules: object,
    request: object,
    artifact_store: object,
    now: object,
) -> str:
    code = "protected-rule-owner-authorization-required"
    if type(request) is not OwnerChangeRequest:
        _fail(code)
    base_hash = canonical_content_hash(document["rules"])
    proposed_hash = canonical_content_hash(selected_rules)
    proposal_hash = request.proposal_hash
    try:
        observed_at = _as_utc(now)
    except WorkflowEvidenceError:
        _fail(code)
    previous = _parse_semver(request.previous_version)
    new = _parse_semver(request.new_version)
    if (
        request.base_rules_hash != base_hash
        or request.proposed_rules_hash != proposed_hash
        or request.previous_version != document["policyVersion"]
        or previous is None
        or new is None
        or new[0] <= previous[0]
        or request.proposed_at > observed_at
        or observed_at
        > request.proposed_at + timedelta(seconds=request.valid_for_seconds)
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
        or confirmation["subjectHash"] != proposal_hash
        or confirmation["actorId"] != request.owner_actor
        or confirmation["relatedIds"]
        or confirmation["attributes"]["decision"] != "authorized"
        or confirmation["attributes"]["scope"] != "replace-protected-rules"
        or review["kind"] != "owner-review"
        or review["status"] != "passed"
        or review["subjectId"] != "protected-rules-change"
        or review["subjectHash"] != proposal_hash
        or review["relatedIds"]
        or review["actorId"] == request.implementation_actor
        or review["contextId"] == request.implementation_context
        or review["attributes"]["decision"] != "passed"
        or not review_level_at_least(review["attributes"]["level"], "L2")
        or review["attributes"]["implementationActor"]
        != request.implementation_actor
        or review["attributes"]["implementationContext"]
        != request.implementation_context
        or tests["kind"] != "behavioral-test"
        or tests["status"] != "passed"
        or tests["subjectId"] != "protected-rules-change"
        or tests["subjectHash"] != proposal_hash
        or tests["relatedIds"]
        or tests["attributes"]["suite"] != "protected-rules"
        or tests["attributes"]["invocationHash"]
        != request.behavioral_test_invocation_hash
        or tests["attributes"]["invocation"]["inputHash"]
        != request.pre_test_subject_hash
    ):
        _fail(code)
    for artifact in (confirmation, review, tests):
        recorded_at = _parse_timestamp(
            artifact["recordedAt"], "protected-rule-owner-authorization-required"
        )
        if (
            recorded_at < request.proposed_at
            or recorded_at > observed_at
            or recorded_at
            > request.proposed_at + timedelta(seconds=request.valid_for_seconds)
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
    now: object | None = None,
) -> MergedRules:
    """Merge rules in fixed priority order without allowing protected overrides."""

    document = _closed_mapping(
        protected_rules,
        (
            "schemaVersion",
            "policyVersion",
            "mergeOrder",
            "ordinaryLayerContractVersion",
            "ownerModificationGate",
            "rules",
        ),
        "protected-rules-invalid",
    )
    if (
        type(document["schemaVersion"]) is not int
        or document["schemaVersion"] != 1
        or type(document["ordinaryLayerContractVersion"]) is not int
        or document["ordinaryLayerContractVersion"] != 1
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
            now,
        )
        source_name = "repository-owner"
    elif owner_change is not None or artifact_store is not None or now is not None:
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
            ("contractVersion", "kind", "name", "operations"),
            "protected-rule-layer-invalid",
        )
        kind = layer["kind"]
        name = layer["name"]
        if (
            type(layer["contractVersion"]) is not int
            or layer["contractVersion"] != document["ordinaryLayerContractVersion"]
            or type(kind) is not str
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
        if any(rule.id in protected_ids for rule in parsed_rules):
            _fail("protected-rule-override-denied")
        parsed_layers.append((_LAYER_ORDER[kind], name, parsed_rules))

    merged = {rule.id: rule for rule in protected}
    ordinary_ids: set[str] = set()
    for _, _, rules in sorted(parsed_layers, key=lambda item: (item[0], item[1])):
        for rule in sorted(rules, key=lambda item: item.id):
            if rule.id in ordinary_ids:
                _fail("protected-rule-layer-conflict")
            ordinary_ids.add(rule.id)
            merged[rule.id] = rule
    return MergedRules(
        _token=_OUTPUT_TOKEN,
        rules=tuple(merged[rule_id] for rule_id in sorted(merged)),
        policy_version=policy_version,
    )
