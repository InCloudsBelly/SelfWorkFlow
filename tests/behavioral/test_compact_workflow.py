"""Approved cost policy, observed at routing and dispatch boundaries."""

from pathlib import Path
import unittest

from selfworkflow.catalog import compile_catalog
from selfworkflow.router import ModuleRouteRequest, route_modules


ROOT = Path(__file__).resolve().parents[2]


class CompactRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = compile_catalog(ROOT / "catalog").content

    def route(self, strength, slot, *, explicit=(), defaults=()):
        return route_modules(self.catalog, ModuleRouteRequest(
            slot_id=slot,
            cardinality="gate" if slot == "plan.gate" else "zero-or-many",
            operation_type="implement", strength=strength, write_task=True,
            explicit_module_ids=explicit, project_default_module_ids=defaults,
            capability_states={
                "skill-discovery": "supported",
                "independent-context": "supported",
                "user-confirmation": "supported",
            },
        )).selected_modules

    def test_grilling_and_tea_never_start_from_mode_or_project_default(self):
        optional = {
            "design.specialists": ("design-grilling", "design-grill-me"),
            "test.quality.plan": ("tea-test-design",),
            "test.quality.review": ("tea-test-review",),
        }
        for strength in ("Light", "Full", "Deep"):
            for slot, modules in optional.items():
                with self.subTest(strength=strength, slot=slot):
                    self.assertEqual(self.route(strength, slot), ())
                    self.assertEqual(self.route(strength, slot, defaults=modules), ())

    def test_explicit_tea_and_grilling_remain_available(self):
        for slot, module in (
            ("design.specialists", "design-grilling"),
            ("test.quality.plan", "tea-test-design"),
            ("test.quality.review", "tea-test-review"),
        ):
            with self.subTest(module=module):
                self.assertIn(module, self.route("Full", slot, explicit=(module,)))

    def test_readonly_analysis_and_review_have_one_independent_full_deep_route(self):
        for operation in ("analyze", "review"):
            for strength in ("Light", "Full", "Deep"):
                with self.subTest(operation=operation, strength=strength):
                    route = route_modules(self.catalog, ModuleRouteRequest(
                        slot_id="review.independent", cardinality="zero-or-one",
                        operation_type=operation, strength=strength, write_task=False,
                        capability_states={"skill-discovery": "supported", "independent-context": "supported"},
                    ))
                    self.assertEqual(route.selected_modules, () if strength == "Light" else ("review-code-review",))

    def test_v3_readonly_analysis_requires_review_without_write_or_tdd_slots(self):
        from selfworkflow.v3.catalog import compile_catalog as compile_v3
        from selfworkflow.v3.host import Host
        from selfworkflow.v3.pipeline import load_pipeline
        from selfworkflow.v3.plan_graph import build_plan_graph
        from tests.conformance.test_testing_review_hardening import TestingReviewHardeningTests as Fixtures

        catalog = compile_v3()
        pipeline = load_pipeline(ROOT / "workflow/v3/pipeline.yaml")
        for operation in ("analyze", "review"):
            for strength, level in (("Light", "T1"), ("Full", "T2"), ("Deep", "T3")):
                request = Fixtures._request(operation, "mechanical-change", strength, level)
                request["risk"] = "R0"
                plan = build_plan_graph(request, catalog, pipeline,
                    execution_policy_snapshot=Fixtures._execution_policy(catalog, request))
                stages = {stage["stageId"]: stage for stage in plan.as_dict()["stages"]}
                with self.subTest(operation=operation, strength=strength):
                    expected = "not-applicable" if strength == "Light" else "applicable"
                    review = next(slot for slot in stages["reviewed"]["slots"] if slot["slotId"] == "review.independent")
                    self.assertEqual(review["applicability"], expected)
                    self.assertEqual(review["selectedModules"], [] if strength == "Light" else ["review-code-review"])
                    write_slots = [slot for slot in stages["implemented"]["slots"] if slot["slotId"] in {"implement.orchestrator", "implement.spec", "implement.tdd"}]
                    self.assertTrue(all(slot["applicability"] == "not-applicable" for slot in write_slots))
                    self.assertNotIn("implement-tdd", {m for stage in stages.values() for slot in stage["slots"] for m in slot["selectedModules"]})
                    ledger = Host(plan, request, catalog, pipeline).new_ledger()
                    self.assertEqual(next(s for s in ledger["stages"] if s["stageId"] == "reviewed")["status"], "skipped" if strength == "Light" else "pending")

    def test_runtime_suggestion_cannot_enable_any_explicit_only_module(self):
        from selfworkflow.v3.catalog import compile_catalog as compile_v3
        from selfworkflow.v3.host import Host, HostError
        from selfworkflow.v3.pipeline import load_pipeline
        from selfworkflow.v3.plan_graph import build_plan_graph, _EXPLICIT_ONLY_MODULES
        from selfworkflow.v3.selector import SelectionInput, select_modules
        from tests.conformance.test_testing_review_hardening import TestingReviewHardeningTests as Fixtures

        catalog = compile_v3()
        pipeline = load_pipeline(ROOT / "workflow/v3/pipeline.yaml")
        request = Fixtures._request("implement", "bounded-feature", "Full", "T2")
        request["risk"] = "R1"
        plan = build_plan_graph(request, catalog, pipeline,
            execution_policy_snapshot=Fixtures._execution_policy(catalog, request))
        host = Host(plan, request, catalog, pipeline)
        signal = "sha256:" + "7" * 64
        ledger = host.start_stage(host.new_ledger(), "discovered", "attempt-discovered",
            "2026-10-19T06:30:00Z", input_artifact_hashes=(signal,))
        for module_id in _EXPLICIT_ONLY_MODULES:
            result = select_modules(plan, "discovered", "knowledge.read", "attempt-discovered",
                SelectionInput(artifact_id="runtime-signal", artifact_hash=signal,
                    requested_module_ids=(module_id,)))
            with self.subTest(module_id=module_id):
                with self.assertRaisesRegex(HostError, "v3-next-stage-request-explicit-user-required"):
                    host.extend_from_next_stage_request(ledger, result,
                        superseded_at="2026-10-19T06:31:00Z")

    def test_normal_full_and_deep_plan_use_self_check(self):
        for strength in ("Full", "Deep"):
            with self.subTest(strength=strength):
                self.assertEqual(self.route(strength, "plan.gate"), ("plan-gate",))

    def test_v2_plan_graph_does_not_require_tea_without_explicit_request(self):
        from selfworkflow.plan_graph import build_plan_graph

        request = {
            "complexity": "C2", "risk": "R2", "writeTask": True,
            "operationType": "implement", "projectMinimums": {"strength": "Full"},
            "explicitModuleIds": [], "projectDefaultModuleIds": [],
        }
        graph, _reasons = build_plan_graph(
            self.catalog, request, "sha256:" + "a" * 64,
            "sha256:" + "b" * 64, {"skill-discovery": "supported"}, ROOT,
        )
        slots = {slot["slotId"]: slot for stage in graph["stages"] for slot in stage["slots"]}
        self.assertEqual(slots["test.quality.plan"]["applicability"], "not-applicable")
        self.assertEqual(slots["test.quality.review"]["applicability"], "not-applicable")

    def test_v2_material_risk_keeps_a_preimplementation_review(self):
        from selfworkflow.plan_graph import build_plan_graph

        request = {
            "complexity": "C2", "risk": "R3", "writeTask": True,
            "operationType": "implement", "projectMinimums": {"strength": "Full"},
            "explicitModuleIds": [], "projectDefaultModuleIds": [],
        }
        for risk in ("R2", "R3"):
            request["risk"] = risk
            graph, _reasons = build_plan_graph(
                self.catalog, request, "sha256:" + "a" * 64,
                "sha256:" + "b" * 64,
                {"skill-discovery": "supported", "independent-context": "supported"}, ROOT,
            )
            gate = next(slot for stage in graph["stages"] for slot in stage["slots"] if slot["slotId"] == "plan.gate")
            with self.subTest(risk=risk):
                self.assertEqual(gate["selectedModules"], ["plan-integrated-review"])

    def test_v3_security_and_persistence_risk_cannot_skip_plan_review(self):
        from selfworkflow.v3.catalog import compile_catalog as compile_v3
        from selfworkflow.v3.pipeline import load_pipeline
        from selfworkflow.v3.plan_graph import build_plan_graph
        from tests.conformance.test_testing_review_hardening import TestingReviewHardeningTests as Fixtures

        catalog = compile_v3()
        pipeline = load_pipeline(ROOT / "workflow/v3/pipeline.yaml")
        for archetype in ("bugfix", "bounded-feature"):
            request = Fixtures._request("implement", archetype, "Full", "T2")
            self.assertEqual(request["risk"], "R2")
            graph = build_plan_graph(
                request, catalog, pipeline,
                execution_policy_snapshot=Fixtures._execution_policy(catalog, request),
            ).as_dict()
            gate = next(slot for stage in graph["stages"] for slot in stage["slots"] if slot["slotId"] == "plan.integrated-review")
            with self.subTest(archetype=archetype):
                self.assertEqual(gate["selectedModules"], ["plan-integrated-review"])

    def test_explicit_tea_selection_does_not_enable_other_optional_capabilities(self):
        from selfworkflow.v3.catalog import compile_catalog as compile_v3
        from selfworkflow.v3.pipeline import load_pipeline
        from selfworkflow.v3.plan_graph import build_plan_graph
        from selfworkflow.v3.selector import SelectionInput, select_modules
        from tests.conformance.test_testing_review_hardening import TestingReviewHardeningTests as Fixtures

        catalog = compile_v3()
        pipeline = load_pipeline(ROOT / "workflow/v3/pipeline.yaml")
        for requested, other in (("tea-trace", "tea-nfr"), ("tea-nfr", "tea-trace")):
            for old_default in (False, True):
                request = Fixtures._request("implement", "bugfix", "Full", "T2")
                request["explicitModuleIds"].append(requested)
                request["projectDefaultModuleIds"] = [other] if old_default else []
                graph = build_plan_graph(
                    request, catalog, pipeline,
                    execution_policy_snapshot=Fixtures._execution_policy(catalog, request),
                )
                result = select_modules(
                    graph, "verified", "test.quality.verify", "attempt-verified",
                    SelectionInput(artifact_id="verification-input", artifact_hash="sha256:" + "7" * 64),
                )
                with self.subTest(requested=requested, old_default=old_default):
                    self.assertEqual(result.status, "selected")
                    self.assertEqual(result.receipt.document["selectedModuleIds"], [requested])
                    self.assertEqual(result.receipt.document["eligibleModuleIds"], [requested])

    def test_v3_mode_and_test_floor_do_not_enable_optional_workflows(self):
        from selfworkflow.v3.catalog import compile_catalog as compile_v3
        from selfworkflow.v3.pipeline import load_pipeline
        from selfworkflow.v3.plan_graph import build_plan_graph
        from tests.conformance.test_testing_review_hardening import TestingReviewHardeningTests

        catalog = compile_v3()
        pipeline = load_pipeline(ROOT / "workflow/v3/pipeline.yaml")
        for strength, level in (("Full", "T2"), ("Deep", "T3")):
            request = TestingReviewHardeningTests._request(
                "implement", "bounded-feature", strength, level,
            )
            request["risk"] = "R1"
            request["projectDefaultModuleIds"] = [
                "design-grilling", "tea-test-design", "tea-test-review",
            ]
            graph = build_plan_graph(
                request, catalog, pipeline,
                execution_policy_snapshot=TestingReviewHardeningTests._execution_policy(catalog, request),
            ).as_dict()
            selected = {
                module for stage in graph["stages"] for slot in stage["slots"]
                for module in slot["selectedModules"]
            }
            with self.subTest(strength=strength):
                self.assertFalse(selected & {
                    "design-grilling", "design-grill-me", "tea-test-design",
                    "tea-test-review", "plan-integrated-review",
                })
                self.assertIn("implement-tdd", selected)
                self.assertIn("review-code-review", selected)


class CompactReviewTests(unittest.TestCase):
    def test_review_model_override_is_rejected_instead_of_switching_models(self):
        from selfworkflow.v3.review_dispatch import ReviewDispatchError, dispatch_independent_review
        from tests.unit.v3.test_review_dispatch import PLAN_HASH, _SpyPort, _verified

        port = _SpyPort()
        with self.assertRaisesRegex(ReviewDispatchError, "review-model-override-disabled"):
            dispatch_independent_review(
                _verified(), implementation_agent_identity="author",
                implementation_context_identity="author-context", port=port,
                plan_hash=PLAN_HASH, attempt_ref="attempt-designed",
                review_model={
                    "agentId": "codex", "model": "different-model",
                    "reasoningEffort": "max", "selectionMode": "one-time",
                },
            )
        self.assertEqual(port.calls, [])

    def test_cli_does_not_offer_review_specific_model_configuration(self):
        import io
        from contextlib import redirect_stdout
        from selfworkflow.cli import main

        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as caught:
            main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertNotIn("review-model", output.getvalue())

    def test_code_review_dispatches_once_and_checks_both_axes(self):
        from selfworkflow.v3.review_dispatch import dispatch_code_review
        from tests.unit.v3.test_review_dispatch import PLAN_HASH, _SpyPort, _verified

        port = _SpyPort(unique_dispatches=True)
        result = dispatch_code_review(
            _verified(), implementation_agent_identity="author",
            implementation_context_identity="author-context", port=port,
            plan_hash=PLAN_HASH, attempt_ref="attempt-reviewed",
        )
        self.assertEqual(len(port.calls), 1)
        self.assertEqual(set(result["reviewers"]), {"combined"})
        self.assertEqual(port.calls[0]["payload"]["reviewAxis"], "combined")
        self.assertFalse(port.calls[0]["fork_context"])
        self.assertNotIn("review_model", port.calls[0])


if __name__ == "__main__":
    unittest.main()
