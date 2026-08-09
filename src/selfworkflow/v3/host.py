"""Deterministic, effect-free V3 Host orchestration boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import copy
import hashlib
import json
from typing import Any

from selfworkflow.v3.catalog import CompiledCatalog
from selfworkflow.v3.contracts import ContractError, load_contract
from selfworkflow.v3.ledger import (
    apply_stage_result,
    new_ledger,
    start_stage,
    supersede_ledger,
)
from selfworkflow.v3.pipeline import LoadedPipeline
from selfworkflow.v3.plan_graph import PlanGraphArtifact, build_plan_graph
from selfworkflow.v3.selector import SelectionResult


_MISSING = object()
_POST_GRILL_EVIDENCE_TOKEN = object()
_ISSUED_POST_GRILL_EVIDENCE: set[object] = set()
_SNAPSHOT_KEYS = (
    "capabilitySnapshot",
    "providerPreferenceSnapshot",
    "providerBindingSnapshot",
    "executionPolicySnapshot",
    "policySnapshot",
)


class HostError(ValueError):
    """Stable failure at the V3 Host boundary."""

    def __init__(self, reason: str = "v3-host-invalid") -> None:
        self.reason = reason
        super().__init__(reason)


def _value_hash(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _canonical_mapping(value: object, reason: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise HostError(reason)
    try:
        encoded = json.dumps(
            dict(value), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )
        decoded = json.loads(encoded)
    except (OverflowError, RecursionError, TypeError, ValueError):
        raise HostError(reason) from None
    if type(decoded) is not dict:
        raise HostError(reason)
    return decoded


def _canonical_snapshots(value: object) -> dict[str, Any]:
    source = _canonical_mapping(value, "v3-fresh-snapshots-invalid")
    if set(source) != set(_SNAPSHOT_KEYS):
        raise HostError("v3-fresh-snapshots-invalid")
    return {
        key: _canonical_mapping(source[key], f"v3-{key}-invalid")
        for key in _SNAPSHOT_KEYS
    }


def _validated_request(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        text = json.dumps(
            dict(value), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )
        return load_contract("resolve-request.schema.json", text)
    except ContractError as error:
        raise HostError(error.reason) from None
    except (OverflowError, RecursionError, TypeError, ValueError):
        raise HostError("v3-fresh-capability-snapshot-invalid") from None


@dataclass(frozen=True)
class PlanExtension:
    """Immutable result of a typed out-of-plan request."""

    old_ledger: dict[str, Any]
    new_request: dict[str, Any]
    plan: PlanGraphArtifact

    @property
    def new_request_hash(self) -> str:
        return _value_hash(self.new_request)


class PostGrillReviewEvidence:
    """Sealed Host result that can satisfy the designed-stage gate once."""

    __slots__ = (
        "_plan_hash", "_attempt_ref", "_design_hash", "_summary_hash",
        "_receipt", "_decision", "__token",
        "_service_identity",
    )

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("PostGrillReviewEvidence is issued by Host")

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("PostGrillReviewEvidence is immutable")

    @property
    def receipt(self) -> dict[str, Any]:
        return copy.deepcopy(self._receipt)

    @property
    def receipt_hash(self) -> str:
        return self._receipt["receiptHash"]

    @property
    def design_hash(self) -> str:
        return self._design_hash

    def _is_valid(self) -> bool:
        return (
            getattr(self, "_PostGrillReviewEvidence__token", None)
            is _POST_GRILL_EVIDENCE_TOKEN
            and self in _ISSUED_POST_GRILL_EVIDENCE
        )


def _issue_post_grill_evidence(
    *, services: object, plan_hash: str, attempt_ref: str, design_hash: str,
    summary_hash: str, receipt: dict[str, Any], decision: object,
) -> PostGrillReviewEvidence:
    artifact = object.__new__(PostGrillReviewEvidence)
    object.__setattr__(artifact, "_plan_hash", plan_hash)
    object.__setattr__(artifact, "_attempt_ref", attempt_ref)
    object.__setattr__(artifact, "_design_hash", design_hash)
    object.__setattr__(artifact, "_summary_hash", summary_hash)
    object.__setattr__(artifact, "_receipt", copy.deepcopy(receipt))
    object.__setattr__(artifact, "_decision", decision)
    object.__setattr__(artifact, "_service_identity", id(services))
    object.__setattr__(
        artifact, "_PostGrillReviewEvidence__token", _POST_GRILL_EVIDENCE_TOKEN,
    )
    _ISSUED_POST_GRILL_EVIDENCE.add(artifact)
    return artifact


class Host:
    """A pure Host facade over one compiled V3 plan.

    The object keeps immutable planning inputs. Optional Review Host services
    are bound once at construction; Agent-provided data cannot replace them.
    """

    def __init__(
        self,
        plan: PlanGraphArtifact,
        request: Mapping[str, Any],
        compiled_catalog: CompiledCatalog,
        pipeline: LoadedPipeline,
        *,
        snapshot_resolver: Callable[
            [dict[str, Any], dict[str, Any]], Mapping[str, Any]
        ] | None = None,
        review_services: object = None,
        review_test_mode: bool = False,
    ) -> None:
        if type(plan) is not PlanGraphArtifact:
            raise HostError("v3-host-plan-not-typed")
        if type(compiled_catalog) is not CompiledCatalog:
            raise HostError("v3-host-catalog-not-typed")
        if type(pipeline) is not LoadedPipeline:
            raise HostError("v3-host-pipeline-not-typed")
        try:
            plan_document, _module_specs = plan._trusted_snapshot()
        except Exception as error:
            raise HostError(getattr(error, "reason", "v3-host-plan-invalid")) from None
        normalized_request = _validated_request(request)
        if _value_hash(normalized_request) != plan_document["requestHash"]:
            raise HostError("v3-host-request-plan-mismatch")
        self._plan = plan
        self._request = normalized_request
        self._catalog = compiled_catalog
        self._pipeline = pipeline
        if snapshot_resolver is not None and not callable(snapshot_resolver):
            raise HostError("v3-fresh-snapshot-resolver-invalid")
        self._snapshot_resolver = snapshot_resolver
        if review_services is not None:
            from selfworkflow.v3.review_services import ReviewHostServices
            if (
                not isinstance(review_services, ReviewHostServices)
                or not review_services._is_valid(test_mode=review_test_mode)
            ):
                raise HostError("review-host-services-invalid")
        self._review_services = review_services

    @property
    def plan(self) -> PlanGraphArtifact:
        return self._plan

    @property
    def request(self) -> dict[str, Any]:
        return copy.deepcopy(self._request)

    def new_ledger(self) -> dict[str, Any]:
        return new_ledger(self._plan)

    def start_stage(
        self,
        ledger: Mapping[str, Any],
        stage_id: str,
        attempt_ref: str,
        started_at: str,
        receipts: tuple[Any, ...] = (),
        *,
        input_artifact_hashes: Sequence[str] = (),
    ) -> dict[str, Any]:
        try:
            return start_stage(
                ledger, self._plan, stage_id, attempt_ref, started_at, receipts,
                input_artifact_hashes=input_artifact_hashes,
            )
        except Exception as error:
            raise HostError(getattr(error, "reason", "v3-host-stage-start-failed")) from None

    def apply_stage_result(
        self,
        ledger: Mapping[str, Any],
        stage_result: Mapping[str, Any],
        receipts: tuple[Any, ...] = (),
        *,
        post_grill_review_evidence: PostGrillReviewEvidence | None = None,
    ) -> dict[str, Any]:
        self._validate_post_grill_stage_gate(
            ledger, stage_result, post_grill_review_evidence,
        )
        try:
            result = apply_stage_result(ledger, self._plan, stage_result, receipts)
        except Exception as error:
            raise HostError(getattr(error, "reason", "v3-host-stage-result-failed")) from None
        if post_grill_review_evidence is not None:
            _ISSUED_POST_GRILL_EVIDENCE.discard(post_grill_review_evidence)
        return result

    def dispatch_post_grill_review(
        self,
        ledger: Mapping[str, Any],
        summary_ref: str,
        *,
        implementation_agent_identity: str,
        implementation_context_identity: str,
        independent_context_available: bool,
        now: object,
        grill_completion_ref: str,
        fallback_authorization_ref: str | None = None,
    ) -> PostGrillReviewEvidence:
        """Dispatch and evaluate the mandatory review through Host-owned ports."""

        if not self._requires_post_grill_review():
            raise HostError("post-grill-independent-review-not-required")
        if self._review_services is None:
            raise HostError("post-grill-review-host-services-required")
        try:
            from selfworkflow.v3.ledger import assert_valid_ledger
            from selfworkflow.v3.review_dispatch import (
                dispatch_independent_review,
                dispatch_same_agent_fallback_review,
            )
            from selfworkflow.v3.review_inputs import verify_review_inputs
            from selfworkflow.v3.review_gate import evaluate_post_grill_review
            from selfworkflow.v3.hashing import require_hash

            assert_valid_ledger(ledger, self._plan)
            active = [item for item in ledger["stages"] if item["status"] == "active"]
            if len(active) != 1 or active[0]["stageId"] != "designed":
                raise HostError("post-grill-review-stage-not-active")
            attempt_ref = active[0]["attempts"][-1]["attemptRef"]
            require_hash(summary_ref)
            verified_input = verify_review_inputs(
                self._review_services.summary_resolver(summary_ref),
                summary_attestation_resolver=self._review_services.summary_attestation_resolver,
                grill_completion_ref=grill_completion_ref,
                grill_completion_resolver=self._review_services.grill_completion_resolver,
                reviewer_policy_hash=self._review_services.review_policy_hash,
                plan_hash=self._plan.plan_hash,
                attempt_ref=attempt_ref,
                now=now,
            )
            normalized_summary = verified_input.summary
            if normalized_summary["summaryHash"] != summary_ref:
                raise HostError("post-grill-review-summary-reference-invalid")
            if independent_context_available:
                receipt = dispatch_independent_review(
                    verified_input,
                    implementation_agent_identity=implementation_agent_identity,
                    implementation_context_identity=implementation_context_identity,
                    port=self._review_services.dispatch_port,
                    fallback_authorization_ref=fallback_authorization_ref,
                    plan_hash=self._plan.plan_hash,
                    attempt_ref=attempt_ref,
                )
            else:
                if fallback_authorization_ref is None:
                    raise HostError("post-grill-review-user-authorization-required")
                preflight = evaluate_post_grill_review(
                    independent_context_available=False,
                    receipt=None,
                    fallback_authorization_ref=fallback_authorization_ref,
                    design_hash=normalized_summary["designHash"],
                    reviewer_policy_hash=normalized_summary["reviewerPolicyHash"],
                    input_summary_hash=normalized_summary["summaryHash"],
                    now=now,
                    plan_hash=self._plan.plan_hash,
                    attempt_ref=attempt_ref,
                    fallback_authorization_resolver=self._review_services.fallback_authorization_resolver,
                    fallback_authorization_consumer=self._review_services.fallback_authorization_consumer,
                )
                if preflight.status != "review-required":
                    raise HostError(
                        preflight.reason_code
                        or "post-grill-review-user-authorization-required"
                    )
                receipt = dispatch_same_agent_fallback_review(
                    verified_input,
                    implementation_agent_identity=implementation_agent_identity,
                    implementation_context_identity=implementation_context_identity,
                    port=self._review_services.dispatch_port,
                    fallback_authorization_ref=fallback_authorization_ref,
                    plan_hash=self._plan.plan_hash,
                    attempt_ref=attempt_ref,
                )
            decision = evaluate_post_grill_review(
                independent_context_available=independent_context_available,
                receipt=receipt,
                fallback_authorization_ref=fallback_authorization_ref,
                design_hash=receipt["designHash"],
                reviewer_policy_hash=receipt["reviewerPolicyHash"],
                input_summary_hash=receipt["inputSummaryHash"],
                now=now,
                plan_hash=self._plan.plan_hash,
                attempt_ref=attempt_ref,
                host_attestation_resolver=self._review_services.host_attestation_resolver,
                host_attestation_consumer=self._review_services.host_attestation_consumer,
                fallback_authorization_resolver=self._review_services.fallback_authorization_resolver,
                fallback_authorization_consumer=self._review_services.fallback_authorization_consumer,
            )
            if decision.status != "proceed":
                raise HostError(
                    decision.reason_code or "post-grill-independent-review-required"
                )
            return _issue_post_grill_evidence(
                services=self._review_services,
                plan_hash=self._plan.plan_hash,
                attempt_ref=attempt_ref,
                design_hash=receipt["designHash"],
                summary_hash=receipt["inputSummaryHash"],
                receipt=receipt,
                decision=decision,
            )
        except HostError:
            raise
        except Exception as error:
            raise HostError(
                getattr(error, "reason", "post-grill-review-input-invalid")
            ) from None

    def _requires_post_grill_review(self) -> bool:
        document = self._plan.as_dict()
        selected = any(
            "design-grill-me" in slot["selectedModules"]
            for stage in document["stages"]
            for slot in stage["slots"]
        )
        if selected and "design-grill-me" not in self._request["explicitModuleIds"]:
            raise HostError("post-grill-review-input-invalid")
        return selected

    def _validate_post_grill_stage_gate(
        self,
        ledger: Mapping[str, Any],
        stage_result: Mapping[str, Any],
        evidence: PostGrillReviewEvidence | None,
    ) -> None:
        required = self._requires_post_grill_review()
        is_designed_pass = (
            isinstance(stage_result, Mapping)
            and stage_result.get("stageId") == "designed"
            and stage_result.get("status") == "passed"
        )
        if not required:
            if evidence is not None:
                raise HostError("post-grill-review-evidence-unexpected")
            return
        if not is_designed_pass:
            if evidence is not None:
                raise HostError("post-grill-review-evidence-stage-invalid")
            return
        if not isinstance(evidence, PostGrillReviewEvidence) or not evidence._is_valid():
            raise HostError("post-grill-independent-review-required")
        active = [item for item in ledger.get("stages", []) if item.get("status") == "active"]
        if (
            evidence._plan_hash != self._plan.plan_hash
            or evidence._service_identity != id(self._review_services)
            or len(active) != 1
            or active[0].get("stageId") != "designed"
            or not active[0].get("attempts")
            or active[0]["attempts"][-1].get("attemptRef") != evidence._attempt_ref
        ):
            raise HostError("post-grill-review-evidence-binding-invalid")
        output_hashes = set(stage_result.get("outputArtifactHashes", ()))
        gate_results = stage_result.get("gateResults", ())
        matching = [
            item for item in gate_results
            if isinstance(item, Mapping)
            and item.get("gateId") == "design.post-grill-review"
            and item.get("outcome") == "passed"
            and item.get("artifactHash") == evidence.receipt_hash
        ]
        if (
            evidence.design_hash not in output_hashes
            or evidence.receipt_hash not in output_hashes
            or len(matching) != 1
        ):
            raise HostError("post-grill-review-evidence-binding-invalid")

    def extend_from_next_stage_request(
        self,
        ledger: Mapping[str, Any],
        selection_result: SelectionResult,
        *,
        superseded_at: str = "2026-08-09T00:00:00Z",
        receipts: tuple[Any, ...] = (),
        fresh_snapshots: Mapping[str, Any] | None = None,
        capability_snapshot: object = _MISSING,
        provider_preference_snapshot: object = _MISSING,
        provider_binding_snapshot: object = _MISSING,
        execution_policy_snapshot: object = _MISSING,
        policy_snapshot: object = _MISSING,
    ) -> PlanExtension:
        """Re-plan only from a typed Selector out-of-eligible result."""

        if type(selection_result) is not SelectionResult:
            raise HostError("v3-next-stage-request-not-typed")
        result = selection_result.as_dict()
        if result.get("status") != "next-stage-request":
            raise HostError("v3-next-stage-request-status-invalid")
        if result.get("planHash") != self._plan.plan_hash:
            raise HostError("v3-next-stage-request-plan-binding-invalid")
        requested = result.get("requestedModuleIds")
        if type(requested) is not list or not requested:
            raise HostError("v3-next-stage-request-empty")
        if len(requested) != len(set(requested)):
            raise HostError("v3-next-stage-request-duplicate")
        try:
            # SelectionResult already revalidates its result hash.  Requiring
            # the immutable ledger to be current closes replay and old-plan use.
            from selfworkflow.v3.ledger import assert_valid_ledger
            receipt_documents = tuple(
                item.as_dict() if hasattr(item, "as_dict") else item
                for item in receipts
            )
            assert_valid_ledger(ledger, self._plan, receipt_documents)
            if ledger.get("status") == "superseded":
                raise HostError("v3-ledger-superseded")
            active_stages = [
                stage for stage in ledger["stages"]
                if stage["status"] == "active"
            ]
            if len(active_stages) != 1:
                raise HostError("v3-next-stage-request-active-stage-invalid")
            active_stage = active_stages[0]
            if result.get("stageId") != active_stage["stageId"]:
                raise HostError("v3-next-stage-request-stage-stale")
            attempts = active_stage["attempts"]
            if not attempts or result.get("attemptRef") != attempts[-1]["attemptRef"]:
                raise HostError("v3-next-stage-request-attempt-stale")
            plan_document = self._plan.as_dict()
            plan_stage = next(
                stage for stage in plan_document["stages"]
                if stage["stageId"] == active_stage["stageId"]
            )
            slot = next(
                (item for item in plan_stage["slots"]
                 if item["slotId"] == result.get("slotId")),
                None,
            )
            if slot is None:
                raise HostError("v3-next-stage-request-slot-stale")
            if result.get("selectionPolicyHash") != slot["selectionPolicyHash"]:
                raise HostError("v3-next-stage-request-policy-stale")
            registered_inputs = set(
                attempts[-1].get("inputArtifactHashes", [])
            )
            if result.get("inputArtifactHash") not in registered_inputs:
                raise HostError("v3-next-stage-request-input-unregistered")

            fresh = self._fresh_snapshots(
                fresh_snapshots=fresh_snapshots,
                capability_snapshot=capability_snapshot,
                provider_preference_snapshot=provider_preference_snapshot,
                provider_binding_snapshot=provider_binding_snapshot,
                execution_policy_snapshot=execution_policy_snapshot,
                policy_snapshot=policy_snapshot,
            )
            new_request = copy.deepcopy(self._request)
            explicit = set(new_request.get("explicitModuleIds", []))
            explicit.update(requested)
            new_request["explicitModuleIds"] = sorted(explicit)
            new_request["capabilityEvidenceSnapshot"] = fresh[
                "capabilitySnapshot"
            ]
            new_request = _validated_request(new_request)
            new_plan = build_plan_graph(
                new_request,
                self._catalog,
                self._pipeline,
                capability_snapshot=fresh["capabilitySnapshot"],
                provider_preference_snapshot=fresh["providerPreferenceSnapshot"],
                provider_binding_snapshot=fresh["providerBindingSnapshot"],
                execution_policy_snapshot=fresh["executionPolicySnapshot"],
                policy_snapshot=fresh["policySnapshot"],
            )
            old_ledger = supersede_ledger(
                ledger, self._plan, new_plan.plan_hash, superseded_at, receipts,
            )
        except HostError:
            raise
        except Exception as error:
            raise HostError(getattr(error, "reason", "v3-next-stage-request-invalid")) from None
        return PlanExtension(old_ledger, new_request, new_plan)

    def _fresh_snapshots(
        self,
        *,
        fresh_snapshots: Mapping[str, Any] | None,
        capability_snapshot: object,
        provider_preference_snapshot: object,
        provider_binding_snapshot: object,
        execution_policy_snapshot: object,
        policy_snapshot: object,
    ) -> dict[str, Any]:
        explicit = {
            "capabilitySnapshot": capability_snapshot,
            "providerPreferenceSnapshot": provider_preference_snapshot,
            "providerBindingSnapshot": provider_binding_snapshot,
            "executionPolicySnapshot": execution_policy_snapshot,
            "policySnapshot": policy_snapshot,
        }
        explicit_present = [value is not _MISSING for value in explicit.values()]
        if fresh_snapshots is not None and any(explicit_present):
            raise HostError("v3-fresh-snapshot-source-ambiguous")
        if fresh_snapshots is not None:
            source: object = fresh_snapshots
        elif any(explicit_present):
            if not all(explicit_present):
                raise HostError("v3-fresh-snapshots-incomplete")
            source = explicit
        elif self._snapshot_resolver is not None:
            try:
                source = self._snapshot_resolver(
                    copy.deepcopy(self._request), self._plan.as_dict(),
                )
            except Exception:
                raise HostError("v3-fresh-snapshot-resolution-failed") from None
        else:
            raise HostError("v3-fresh-snapshots-required")
        return _canonical_snapshots(source)


# Functional aliases are useful to hosts that do not retain a Host instance.
def create_host(*args: Any, **kwargs: Any) -> Host:
    return Host(*args, **kwargs)


def handoff_stage(
    host: Host, ledger: Mapping[str, Any], stage_result: Mapping[str, Any],
    receipts: tuple[Any, ...] = (), *,
    post_grill_review_evidence: PostGrillReviewEvidence | None = None,
) -> dict[str, Any]:
    return host.apply_stage_result(
        ledger, stage_result, receipts,
        post_grill_review_evidence=post_grill_review_evidence,
    )
