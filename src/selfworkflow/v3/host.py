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
    )

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("PostGrillReviewEvidence is issued by Host")

    @property
    def receipt(self) -> dict[str, Any]:
        return copy.deepcopy(self._receipt)

    @property
    def receipt_hash(self) -> str:
        return self._receipt["receiptHash"]

    @property
    def design_hash(self) -> str:
        return self._design_hash

    @classmethod
    def _issue(
        cls, *, plan_hash: str, attempt_ref: str, design_hash: str,
        summary_hash: str, receipt: dict[str, Any], decision: object,
    ) -> "PostGrillReviewEvidence":
        artifact = object.__new__(cls)
        artifact._plan_hash = plan_hash
        artifact._attempt_ref = attempt_ref
        artifact._design_hash = design_hash
        artifact._summary_hash = summary_hash
        artifact._receipt = copy.deepcopy(receipt)
        artifact._decision = decision
        artifact._PostGrillReviewEvidence__token = _POST_GRILL_EVIDENCE_TOKEN
        return artifact

    def _is_valid(self) -> bool:
        return getattr(self, "_PostGrillReviewEvidence__token", None) is _POST_GRILL_EVIDENCE_TOKEN


class Host:
    """A pure Host facade over one compiled V3 plan.

    The object keeps only immutable copies of caller-provided values.  It never
    reads or writes files and never invokes a module, process, MCP, or agent.
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
    ) -> None:
        if type(plan) is not PlanGraphArtifact:
            raise HostError("v3-host-plan-not-typed")
        if type(compiled_catalog) is not CompiledCatalog:
            raise HostError("v3-host-catalog-not-typed")
        if type(pipeline) is not LoadedPipeline:
            raise HostError("v3-host-pipeline-not-typed")
        try:
            plan._trusted_snapshot()
        except Exception as error:
            raise HostError(getattr(error, "reason", "v3-host-plan-invalid")) from None
        self._plan = plan
        self._request = copy.deepcopy(dict(request))
        self._catalog = compiled_catalog
        self._pipeline = pipeline
        if snapshot_resolver is not None and not callable(snapshot_resolver):
            raise HostError("v3-fresh-snapshot-resolver-invalid")
        self._snapshot_resolver = snapshot_resolver

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
            return apply_stage_result(ledger, self._plan, stage_result, receipts)
        except Exception as error:
            raise HostError(getattr(error, "reason", "v3-host-stage-result-failed")) from None

    def dispatch_post_grill_review(
        self,
        ledger: Mapping[str, Any],
        summary: Mapping[str, Any],
        *,
        implementation_agent_identity: str,
        implementation_context_identity: str,
        port: object,
        independent_context_available: bool,
        now: object,
        host_attestation_resolver: object = None,
        fallback_authorization_ref: str | None = None,
        fallback_authorization_resolver: object = None,
        fallback_authorization_consumer: object = None,
    ) -> PostGrillReviewEvidence:
        """Dispatch and evaluate the mandatory review through Host-owned ports."""

        if not self._requires_post_grill_review():
            raise HostError("post-grill-independent-review-not-required")
        try:
            from selfworkflow.v3.ledger import assert_valid_ledger
            from selfworkflow.v3.review_dispatch import (
                _load_summary,
                dispatch_independent_review,
                dispatch_same_agent_fallback_review,
            )
            from selfworkflow.v3.review_gate import evaluate_post_grill_review

            assert_valid_ledger(ledger, self._plan)
            active = [item for item in ledger["stages"] if item["status"] == "active"]
            if len(active) != 1 or active[0]["stageId"] != "designed":
                raise HostError("post-grill-review-stage-not-active")
            attempt_ref = active[0]["attempts"][-1]["attemptRef"]
            normalized_summary = _load_summary(dict(summary))
            if independent_context_available:
                receipt = dispatch_independent_review(
                    normalized_summary,
                    implementation_agent_identity=implementation_agent_identity,
                    implementation_context_identity=implementation_context_identity,
                    port=port,
                    fallback_authorization_ref=fallback_authorization_ref,
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
                    fallback_authorization_resolver=fallback_authorization_resolver,
                    fallback_authorization_consumer=fallback_authorization_consumer,
                )
                if preflight.status != "review-required":
                    raise HostError(
                        preflight.reason_code
                        or "post-grill-review-user-authorization-required"
                    )
                receipt = dispatch_same_agent_fallback_review(
                    normalized_summary,
                    implementation_agent_identity=implementation_agent_identity,
                    implementation_context_identity=implementation_context_identity,
                    port=port,
                    fallback_authorization_ref=fallback_authorization_ref,
                )
            decision = evaluate_post_grill_review(
                independent_context_available=independent_context_available,
                receipt=receipt,
                fallback_authorization_ref=fallback_authorization_ref,
                design_hash=receipt["designHash"],
                reviewer_policy_hash=receipt["reviewerPolicyHash"],
                input_summary_hash=receipt["inputSummaryHash"],
                now=now,
                host_attestation_resolver=host_attestation_resolver,
                fallback_authorization_resolver=fallback_authorization_resolver,
                fallback_authorization_consumer=fallback_authorization_consumer,
            )
            if decision.status != "proceed":
                raise HostError(
                    decision.reason_code or "post-grill-independent-review-required"
                )
            return PostGrillReviewEvidence._issue(
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
        return any(
            "design-grill-me" in slot["selectedModules"]
            for stage in document["stages"]
            for slot in stage["slots"]
        )

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
