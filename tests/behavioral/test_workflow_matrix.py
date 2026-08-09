from pathlib import Path
import unittest

from selfworkflow.catalog import compile_catalog
from selfworkflow.classifier import classify_task, workflow_strength
from selfworkflow.router import ModuleRouteRequest, route_modules


class WorkflowMatrixTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    @classmethod
    def setUpClass(cls):
        cls.catalog = compile_catalog(cls.ROOT / "catalog").content

    def test_all_complexity_risk_cells_choose_design_without_implicit_grill(self):
        for complexity in range(4):
            for risk in range(4):
                with self.subTest(complexity=complexity, risk=risk):
                    classification = classify_task(f"C{complexity}", f"R{risk}")
                    strength = workflow_strength(classification.complexity, classification.risk)
                    route = route_modules(
                        self.catalog,
                        ModuleRouteRequest(
                            slot_id="design.primary", cardinality="exactly-one",
                            operation_type="implement", strength=strength, write_task=True,
                            capability_states={"skill-discovery": "supported"},
                        ),
                    )
                    self.assertEqual(route.selected_modules, ("design-brainstorming",))
                    self.assertNotIn("design-grill-me", route.selected_modules)
                    self.assertEqual(classification.suggest_grill_me, max(complexity, risk) >= 3 or (complexity >= 2 and risk >= 2))

    def test_explicit_grill_adds_independent_brainstorming_after_it(self):
        explicit = ("design-grill-me",)
        common = dict(
            operation_type="implement", strength="Deep", write_task=True,
            explicit_module_ids=explicit,
            capability_states={"skill-discovery": "supported", "independent-context": "supported", "user-confirmation": "supported"},
        )
        grill = route_modules(self.catalog, ModuleRouteRequest(slot_id="design.specialists", cardinality="zero-or-many", **common))
        review = route_modules(self.catalog, ModuleRouteRequest(slot_id="design.cross-review", cardinality="zero-or-one", **common))
        self.assertEqual(grill.selected_modules + review.selected_modules, ("design-grill-me", "design-cross-review"))

    def test_post_grill_policy_is_an_enforced_host_gate(self):
        import yaml
        from selfworkflow.v3.host import HostError
        from tests.unit.v3.test_host_post_grill import HostPostGrillGateTests

        protected = yaml.safe_load(
            (self.ROOT / "workflow/protected-rules.yaml").read_text(encoding="utf-8")
        )
        rule = next(
            item for item in protected["rules"]
            if item["id"] == "require-independent-post-grill-brainstorming-review"
        )
        self.assertEqual(
            rule,
            {
                "id": "require-independent-post-grill-brainstorming-review",
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

    def test_core_policy_requires_reviewed_landing_and_bounded_decisions(self):
        for relative in ("WORKFLOW.md", "workflow/core.md"):
            content = (self.ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(relative=relative):
                for phrase in (
                    "design.gate", "plan.gate", "post-landing Review",
                    "decision-record", "selectedId == recommendationId",
                    "local component", "easy rollback", "critical decision",
                ):
                    self.assertIn(phrase, content)


if __name__ == "__main__":
    unittest.main()
