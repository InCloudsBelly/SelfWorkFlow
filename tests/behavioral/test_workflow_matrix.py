from pathlib import Path
import unittest

from selfworkflow.catalog import compile_catalog
from selfworkflow.classifier import classify_task
from selfworkflow.router import ModuleRouteRequest, route_modules


class WorkflowMatrixTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    @classmethod
    def setUpClass(cls):
        cls.catalog = compile_catalog(cls.ROOT / "catalog").content

    def test_strength_routes_bounded_grilling_and_deep_grill_me(self):
        expected = {
            "Light": (),
            "Full": (),
            "Deep": (),
        }
        for strength, selected in expected.items():
            with self.subTest(strength=strength):
                capabilities = {"skill-discovery": "supported"}
                if strength == "Deep":
                    capabilities["user-confirmation"] = "supported"
                route = route_modules(
                    self.catalog,
                    ModuleRouteRequest(
                        slot_id="design.specialists", cardinality="zero-or-many",
                        operation_type="implement", strength=strength, write_task=True,
                        capability_states=capabilities,
                    ),
                )
                self.assertEqual(route.selected_modules, selected)

        for complexity in range(4):
            for risk in range(4):
                with self.subTest(complexity=complexity, risk=risk):
                    classification = classify_task(f"C{complexity}", f"R{risk}")
                    self.assertEqual(
                        classification.suggest_grill_me,
                        max(complexity, risk) >= 3 or (complexity >= 2 and risk >= 2),
                    )

    def test_explicit_grill_augments_core_and_uses_separate_host_review_gate(self):
        explicit = ("design-grill-me",)
        common = dict(
            operation_type="implement", strength="Deep", write_task=True,
            explicit_module_ids=explicit,
            capability_states={"skill-discovery": "supported", "independent-context": "supported", "user-confirmation": "supported"},
        )
        grill = route_modules(self.catalog, ModuleRouteRequest(slot_id="design.specialists", cardinality="zero-or-many", **common))
        self.assertIn("design-grill-me", grill.selected_modules)
        self.assertNotIn("design-cross-review", grill.selected_modules)

    def test_post_grill_policy_is_an_enforced_host_gate(self):
        import yaml
        from selfworkflow.v3.host import HostError
        from tests.unit.v3.test_host_post_grill import HostPostGrillGateTests

        protected = yaml.safe_load(
            (self.ROOT / "workflow/protected-rules.yaml").read_text(encoding="utf-8")
        )
        rule = next(
            item for item in protected["rules"]
            if item["id"] == "require-independent-post-grill-review"
        )
        self.assertEqual(
            rule,
            {
                "id": "require-independent-post-grill-review",
                "strength": "enforced",
                "gate": "design.post-grill-review",
                "evaluator": "post-grill-review-independence-v1",
                "reasonCodes": [
                    "post-grill-independent-review-required",
                    "post-grill-review-input-invalid",
                    "post-grill-review-attestation-missing",
                    "post-grill-review-user-authorization-required",
                    "post-grill-review-changes-required",
                    "post-grill-review-authorization-replayed",
                    "post-grill-review-attestation-replayed",
                ],
            },
        )
        fixture = HostPostGrillGateTests()
        fixture.setUp()
        with self.assertRaisesRegex(HostError, "post-grill-independent-review-required"):
            fixture.host.apply_stage_result(
                fixture.ledger,
                fixture._result("designed", "attempt-designed"),
            )

    def test_contract_reference_documents_decision_gate_fields(self):
        content = (self.ROOT / "workflow/core.md").read_text(encoding="utf-8")
        for phrase in (
            "design.gate", "plan.gate",
            "decision-record", "selectedId == recommendationId",
            "local component", "easy rollback", "critical decision",
        ):
            self.assertIn(phrase, content)

    def test_plan_gate_keeps_light_lightweight_and_requires_integrated_review_for_full(self):
        expectations = {
            "Light": ("plan-gate",),
            "Full": ("plan-gate",),
            "Deep": ("plan-gate",),
        }
        for strength, expected in expectations.items():
            with self.subTest(strength=strength):
                route = route_modules(
                    self.catalog,
                    ModuleRouteRequest(
                        slot_id="plan.gate", cardinality="gate",
                        operation_type="implement", strength=strength,
                        write_task=True,
                        capability_states={"independent-context": "supported"},
                    ),
                )
                self.assertEqual(route.selected_modules, expected)

    def test_capability_relevance_is_independent_from_workflow_depth(self):
        content = (self.ROOT / "workflow/core.md").read_text(encoding="utf-8")
        self.assertIn("流程深度与能力 Skill 选择相互独立", content)
        self.assertIn(
            "加载能力 Skill 不会自动创建 Design、Plan、Review 或 Verify 流程",
            content,
        )

    def test_current_design_routes_grill_by_strength_without_default_brainstorming(self):
        design = (
            self.ROOT
            / "docs/specs/2026-08-14-testing-review-hardening.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Full 自动启用", design)
        self.assertIn("Deep 自动启用", design)
        self.assertNotIn("默认调用 Brainstorming", design)


if __name__ == "__main__":
    unittest.main()
