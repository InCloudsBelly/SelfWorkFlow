"""Deterministic, effect-free V3 Host orchestration boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import copy
import hashlib
import json
from typing import Any

from selfworkflow.v3.catalog import CompiledCatalog
from selfworkflow.v3.ledger import (
    apply_stage_result,
    new_ledger,
    start_stage,
    supersede_ledger,
)
from selfworkflow.v3.pipeline import LoadedPipeline
from selfworkflow.v3.plan_graph import PlanGraphArtifact, build_plan_graph
from selfworkflow.v3.selector import SelectionResult


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


@dataclass(frozen=True)
class PlanExtension:
    """Immutable result of a typed out-of-plan request."""

    old_ledger: dict[str, Any]
    new_request: dict[str, Any]
    plan: PlanGraphArtifact

    @property
    def new_request_hash(self) -> str:
        return _value_hash(self.new_request)


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
        capability_snapshot: Mapping[str, Any] | None = None,
        provider_preference_snapshot: Mapping[str, Any] | None = None,
        provider_binding_snapshot: Mapping[str, Any] | None = None,
        execution_policy_snapshot: Mapping[str, Any] | None = None,
        policy_snapshot: Mapping[str, Any] | None = None,
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
        self._snapshots = {
            "capability_snapshot": copy.deepcopy(capability_snapshot),
            "provider_preference_snapshot": copy.deepcopy(provider_preference_snapshot),
            "provider_binding_snapshot": copy.deepcopy(provider_binding_snapshot),
            "execution_policy_snapshot": copy.deepcopy(execution_policy_snapshot),
            "policy_snapshot": copy.deepcopy(policy_snapshot),
        }

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
    ) -> dict[str, Any]:
        try:
            return start_stage(
                ledger, self._plan, stage_id, attempt_ref, started_at, receipts,
            )
        except Exception as error:
            raise HostError(getattr(error, "reason", "v3-host-stage-start-failed")) from None

    def apply_stage_result(
        self,
        ledger: Mapping[str, Any],
        stage_result: Mapping[str, Any],
        receipts: tuple[Any, ...] = (),
    ) -> dict[str, Any]:
        try:
            return apply_stage_result(ledger, self._plan, stage_result, receipts)
        except Exception as error:
            raise HostError(getattr(error, "reason", "v3-host-stage-result-failed")) from None

    def extend_from_next_stage_request(
        self,
        ledger: Mapping[str, Any],
        selection_result: SelectionResult,
        *,
        superseded_at: str = "2026-08-09T00:00:00Z",
        receipts: tuple[Any, ...] = (),
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
            new_request = copy.deepcopy(self._request)
            explicit = set(new_request.get("explicitModuleIds", []))
            explicit.update(requested)
            new_request["explicitModuleIds"] = sorted(explicit)
            new_plan = build_plan_graph(
                new_request,
                self._catalog,
                self._pipeline,
                capability_snapshot=self._snapshots["capability_snapshot"],
                provider_preference_snapshot=self._snapshots["provider_preference_snapshot"],
                provider_binding_snapshot=self._snapshots["provider_binding_snapshot"],
                execution_policy_snapshot=self._snapshots["execution_policy_snapshot"],
                policy_snapshot=self._snapshots["policy_snapshot"],
            )
            old_ledger = supersede_ledger(
                ledger, self._plan, new_plan.plan_hash, superseded_at, receipts,
            )
        except HostError:
            raise
        except Exception as error:
            raise HostError(getattr(error, "reason", "v3-next-stage-request-invalid")) from None
        return PlanExtension(old_ledger, new_request, new_plan)


# Functional aliases are useful to hosts that do not retain a Host instance.
def create_host(*args: Any, **kwargs: Any) -> Host:
    return Host(*args, **kwargs)


def handoff_stage(
    host: Host, ledger: Mapping[str, Any], stage_result: Mapping[str, Any],
    receipts: tuple[Any, ...] = (),
) -> dict[str, Any]:
    return host.apply_stage_result(ledger, stage_result, receipts)
