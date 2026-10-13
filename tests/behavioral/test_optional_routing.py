"""Integration contracts for explicitly selected optional workflow modules."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from selfworkflow.catalog import compile_catalog as compile_v2_catalog
from selfworkflow.pipeline import load_pipeline as load_v2_pipeline
from selfworkflow.router import ModuleRouteRequest, route_modules
from selfworkflow.v3.catalog import compile_catalog as compile_v3_catalog
from selfworkflow.v3.pipeline import load_pipeline as load_v3_pipeline
from selfworkflow.v3.resolver import ResolveError, resolve_plan
from selfworkflow.implement_spec import ticket_dag_hash
from tests.unit.v3 import test_plan_graph


ROOT = Path(__file__).resolve().parents[2]
OPTIONAL = {
    "tea-framework": ("planned", "plan.assessment", "plan"),
    "tea-ci": ("verified", "verify.ci", "verify"),
    "ponytail-debt": ("reviewed", "review.debt", "review"),
    "implement-spec": ("implemented", "implement.spec", "implement"),
}
CAPABILITIES = (
    "filesystem-read", "filesystem-write", "skill-discovery",
    "test-execution", "independent-context", "user-confirmation",
)


def _valid_implement_spec_evidence():
    tickets = [
        {"id": "ticket-a", "dependencies": [], "acceptanceHash": "sha256:" + "a" * 64},
        {"id": "ticket-b", "dependencies": ["ticket-a"], "acceptanceHash": "sha256:" + "b" * 64},
    ]
    return {
        "specHash": "sha256:" + "c" * 64,
        "tickets": tickets,
        "ticketDagHash": ticket_dag_hash(tickets),
        "planReviewHash": "sha256:" + "d" * 64,
        "implementationConfirmationHash": "sha256:" + "e" * 64,
        "independentAgentsHash": "sha256:" + "f" * 64,
        "independentReviewHash": "sha256:" + "1" * 64,
        "gitPermissionsHash": "sha256:" + "2" * 64,
        "planReviewStatus": "passed",
        "implementationConfirmationStatus": "confirmed",
        "independentAgentsStatus": "supported",
        "independentReviewStatus": "supported",
        "gitPermissionsStatus": "confirmed",
    }


def _slots(document):
    return {
        slot["slotId"]: slot
        for stage in document["stages"] for slot in stage["slots"]
    }


def _selected(document):
    return [
        module_id for slot in _slots(document).values()
        for module_id in slot["selectedModules"]
    ]


def _contains_explicit_condition(condition, module_id):
    if not isinstance(condition, dict):
        return False
    if condition.get("contains") == ["explicitModuleIds", module_id]:
        return True
    # A reference under `not` is not an explicit activation requirement.
    return any(
        _contains_explicit_condition(child, module_id)
        for operator in ("all", "any")
        for child in condition.get(operator, [])
    )


class OptionalV2RoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = compile_v2_catalog(ROOT / "catalog").content
        cls.pipeline = load_v2_pipeline(
            ROOT / "workflow/pipeline.yaml", ROOT / "schemas/pipeline.schema.json",
        ).mutable_document()

    def _route(self, module_id, *, explicit=False, project_default=False):
        _, slot_id, operation = OPTIONAL[module_id]
        slot = next(
            slot for stage in self.pipeline["stages"] for slot in stage["slots"]
            if slot["id"] == slot_id
        )
        return route_modules(self.catalog, ModuleRouteRequest(
            slot_id=slot_id,
            cardinality=slot["cardinality"],
            operation_type=operation,
            strength="Full",
            write_task=operation == "implement",
            explicit_module_ids=(module_id,) if explicit else (),
            project_default_module_ids=(module_id,) if project_default else (),
                capability_states={name: "supported" for name in CAPABILITIES},
            implement_spec_evidence=_valid_implement_spec_evidence() if module_id == "implement-spec" else None,
            durable_spec=True if module_id == "implement-spec" else None,
            requirements_maturity="approved" if module_id == "implement-spec" else None,
        ))

    def test_explicit_selection_is_operation_bounded(self):
        wrong_operations = {
            "tea-framework": "review",
            "tea-ci": "plan",
            "ponytail-debt": "verify",
            "implement-spec": "debug",
        }
        for module_id, operation in wrong_operations.items():
            with self.subTest(module=module_id):
                result = route_modules(
                    self.catalog,
                    ModuleRouteRequest(
                        slot_id=OPTIONAL[module_id][1],
                        cardinality="zero-or-one",
                        operation_type=operation,
                        strength="Full",
                        write_task=operation == "implement",
                        explicit_module_ids=(module_id,),
                        capability_states={name: "supported" for name in CAPABILITIES},
                    ),
                )
                self.assertEqual(result.status, "paused")
                self.assertIn("explicit-selection-inapplicable", result.reason_codes)

    def test_real_catalog_modules_match_pipeline_slots_and_explicit_activation(self):
        modules = {
            item["id"]: item
            for item in json.loads(self.catalog)["catalog"]["modules"]
        }
        slots = {
            slot["id"]: stage["id"]
            for stage in self.pipeline["stages"] for slot in stage["slots"]
        }
        for module_id, (stage_id, slot_id, _) in OPTIONAL.items():
            with self.subTest(module=module_id):
                self.assertEqual(modules[module_id]["activation"], "explicit")
                self.assertEqual(modules[module_id]["stage"], stage_id)
                self.assertEqual(modules[module_id]["slot"], slot_id)
                self.assertEqual(slots[slot_id], stage_id)

    def test_default_and_project_default_never_select_optional_modules(self):
        for module_id in OPTIONAL:
            for project_default in (False, True):
                with self.subTest(module=module_id, project_default=project_default):
                    result = self._route(module_id, project_default=project_default)
                    self.assertEqual(result.status, "routed", result.reason_codes)
                    self.assertEqual(result.selected_modules, ())

    def test_explicit_selection_routes_each_optional_module(self):
        for module_id in OPTIONAL:
            with self.subTest(module=module_id):
                result = self._route(module_id, explicit=True)
                self.assertEqual(result.status, "routed", result.reason_codes)
                self.assertEqual(result.selected_modules, (module_id,))

    def test_low_level_implement_spec_route_requires_all_preconditions(self):
        result = route_modules(
            self.catalog,
            ModuleRouteRequest(
                slot_id="implement.spec", cardinality="zero-or-one",
                operation_type="implement", strength="Full", write_task=True,
                explicit_module_ids=("implement-spec",),
                capability_states={name: "supported" for name in CAPABILITIES},
            ),
        )
        self.assertEqual(result.status, "paused")
        self.assertEqual(result.selected_modules, ())
        self.assertIn("implement-spec-precondition-unverified", result.reason_codes)


class OptionalV3RoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = compile_v3_catalog(ROOT / "catalog/v3/index.yaml")
        cls.pipeline = load_v3_pipeline(ROOT / "workflow/v3/pipeline.yaml")

    def _request(self, *, operation="plan", explicit=(), defaults=()):
        request = deepcopy(test_plan_graph.PlanGraphTests.REQUEST)
        request.update({
            "operationType": operation,
            "writeTask": operation == "implement",
            "complexity": "C1", "risk": "R1",
            "projectMinimums": {"strength": "Light"},
            "explicitModuleIds": list(explicit),
            "projectDefaultModuleIds": list(defaults),
            "testLevelFloor": "T2",
        })
        # The real V3 catalog deliberately keeps the core planner unverified;
        # approve that baseline explicitly so this fixture isolates optional
        # module activation instead of failing at plan.primary.
        request["explicitModuleIds"].extend([
            "discover-context", "capability-check", "classify-task", "plan-core",
        ])
        # The legacy orchestrator is itself unverified in the real catalog.
        # Keep its approval explicit in the baseline, without selecting any
        # of the four optional modules under test.
        if operation == "implement" and "implement-spec" not in explicit:
            request["explicitModuleIds"].append("implement-matt")
        if "implement-spec" in explicit:
            request["implementSpecEvidence"] = {
                **_valid_implement_spec_evidence(),
            }
        request["capabilityEvidenceSnapshot"] = {
            "schemaVersion": 1,
            "capturedAt": "2026-08-09T00:00:00Z",
            "evidence": [{
                "name": name, "provider": "test-host",
                "subject": {
                    "kind": "host", "id": "optional-routing-fixture",
                    "version": "1", "build": "1",
                    "sourceLock": "sha256:" + "a" * 64,
                },
                "state": "supported",
                "observedAt": "2026-08-09T00:00:00Z",
                "validUntil": "2099-01-01T00:00:00Z",
                "evidenceRef": "fixture:" + name,
                "evidenceHash": "sha256:" + "b" * 64,
            } for name in CAPABILITIES],
        }
        return request

    def _resolve(self, request):
        # This tests routing, not runtime execution or evidence promotion.
        # Do not mutate catalog supportEvidence to make the fixture pass.
        return resolve_plan(
            request, catalog_source=self.catalog, pipeline_source=self.pipeline,
            capability_snapshot=deepcopy(request["capabilityEvidenceSnapshot"]),
            execution_policy_snapshot={
                "allowUnverifiedModuleIds": request["explicitModuleIds"],
            },
        ).plan.document

    def test_four_real_slots_are_static_and_explicitly_conditioned(self):
        modules = {
            item["id"]: item for item in self.catalog.document["catalog"]["modules"]
        }
        slots = {
            slot["id"]: (stage["id"], slot)
            for stage in self.pipeline.document["stages"] for slot in stage["slots"]
        }
        for module_id, (stage_id, slot_id, _) in OPTIONAL.items():
            with self.subTest(module=module_id):
                actual_stage, slot = slots[slot_id]
                self.assertEqual(actual_stage, stage_id)
                self.assertEqual(slot["selectionMode"], "static")
                self.assertTrue(_contains_explicit_condition(slot.get("condition"), module_id))
                self.assertEqual(modules[module_id]["stage"], stage_id)
                self.assertEqual(modules[module_id]["slot"], slot_id)
                self.assertEqual(modules[module_id]["selectionMode"], "static")

    def test_default_never_selects_optional_modules(self):
        for operation in ("plan", "verify", "review", "implement"):
            with self.subTest(operation=operation):
                plan = self._resolve(self._request(operation=operation))
                self.assertFalse(set(_selected(plan)) & OPTIONAL.keys())
                for _, slot_id, _ in OPTIONAL.values():
                    self.assertEqual(_slots(plan)[slot_id]["applicability"], "not-applicable")

    def test_explicit_selection_is_operation_bounded(self):
        wrong_operations = {
            "tea-framework": "review",
            "tea-ci": "plan",
            "ponytail-debt": "verify",
            "implement-spec": "review",
        }
        for module_id, operation in wrong_operations.items():
            with self.subTest(module=module_id):
                expected = (
                    "ponytail-explicit-operation-invalid"
                    if module_id == "ponytail-debt" else "v3-explicit-module-inapplicable"
                )
                with self.assertRaisesRegex(ResolveError, expected):
                    self._resolve(self._request(operation=operation, explicit=(module_id,)))

    def test_project_default_cannot_authorize_optional_selection(self):
        for module_id, (_, slot_id, operation) in OPTIONAL.items():
            with self.subTest(module=module_id):
                # First prove the same request works without the default.
                self._resolve(self._request(operation=operation))
                request = self._request(operation=operation, defaults=(module_id,))
                try:
                    plan = self._resolve(request)
                except ResolveError as error:
                    # Rejecting a requested but inapplicable slot is fail-closed.
                    self.assertEqual(error.reason, "v3-explicit-module-inapplicable")
                else:
                    self.assertNotIn(module_id, _selected(plan))
                    self.assertEqual(_slots(plan)[slot_id]["applicability"], "not-applicable")

    def test_explicit_selection_selects_exactly_one_optional_module(self):
        for module_id, (_, slot_id, operation) in OPTIONAL.items():
            with self.subTest(module=module_id):
                plan = self._resolve(self._request(operation=operation, explicit=(module_id,)))
                self.assertEqual(_slots(plan)[slot_id]["selectedModules"], [module_id])
                self.assertEqual(set(_selected(plan)) & OPTIONAL.keys(), {module_id})

    def test_framework_preserves_test_design(self):
        plan = self._resolve(self._request(explicit=("tea-framework",)))
        self.assertEqual(_slots(plan)["plan.assessment"]["selectedModules"], ["tea-framework"])
        self.assertEqual(_slots(plan)["test.quality.plan"]["selectedModules"], ["tea-test-design"])

    def test_spec_preserves_tdd_and_replaces_legacy_orchestrator(self):
        plan = self._resolve(self._request(operation="implement", explicit=("implement-spec",)))
        self.assertEqual(_slots(plan)["implement.spec"]["selectedModules"], ["implement-spec"])
        self.assertEqual(_slots(plan)["implement.tdd"]["selectedModules"], ["implement-tdd"])
        self.assertNotIn("implement-matt", _selected(plan))
        self.assertEqual(_slots(plan)["implement.orchestrator"]["applicability"], "not-applicable")

    def test_spec_fails_closed_when_each_implementation_precondition_is_absent(self):
        valid = self._request(operation="implement", explicit=("implement-spec",))
        self.assertIn("implement-spec", _selected(self._resolve(valid)))
        for field, value in (
            ("durableSpec", False),
            ("requirementsMaturity", "defined"),
            ("requirementsMaturity", "exploratory"),
            ("writeTask", False),
            ("operationType", "debug"),
        ):
            with self.subTest(field=field, value=value):
                request = deepcopy(valid)
                request[field] = value
                if field == "writeTask":
                    # The request schema rejects implement + read-only before
                    # slot selection can run.
                    with self.assertRaises(ResolveError):
                        self._resolve(request)
                else:
                    with self.assertRaisesRegex(ResolveError, "v3-explicit-module-inapplicable"):
                        self._resolve(request)

    def test_spec_fails_closed_when_evidence_gate_is_invalid(self):
        valid = self._request(operation="implement", explicit=("implement-spec",))
        for field in ("ticketDagHash", "planReviewStatus", "tickets"):
            with self.subTest(field=field):
                request = deepcopy(valid)
                if field == "ticketDagHash":
                    request["implementSpecEvidence"][field] = "sha256:" + "0" * 64
                elif field == "planReviewStatus":
                    request["implementSpecEvidence"][field] = "unreviewed"
                else:
                    request["implementSpecEvidence"][field] = [{
                        "id": "only-ticket", "dependencies": [],
                        "acceptanceHash": "sha256:" + "a" * 64,
                    }]
                with self.assertRaisesRegex(ResolveError, "implement-spec-evidence-invalid"):
                    self._resolve(request)


if __name__ == "__main__":
    unittest.main()
