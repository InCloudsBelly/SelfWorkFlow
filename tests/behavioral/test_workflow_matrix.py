import unittest

from selfworkflow.classifier import classify_task
from selfworkflow.superpowers import decide_overlay


class WorkflowMatrixTests(unittest.TestCase):
    def test_all_complexity_risk_cells_preserve_design_and_grill_semantics(self):
        for complexity in range(4):
            for risk in range(4):
                with self.subTest(complexity=complexity, risk=risk):
                    classification = classify_task(f"C{complexity}", f"R{risk}")
                    self.assertEqual(classification.complexity.value, f"C{complexity}")
                    self.assertEqual(classification.risk.value, f"R{risk}")
                    decision = decide_overlay(
                        stage="designed", operation="design",
                        complexity=complexity, risk=risk, explicit_grill=False,
                        source_status="supported", write_task=True,
                    )
                    self.assertIn("brainstorming", decision["selectedSkills"])
                    self.assertNotIn("grill-me", decision["selectedSkills"])
                    expected_recommendation = max(complexity, risk) >= 3 or (complexity >= 2 and risk >= 2)
                    self.assertEqual(decision["grillRecommended"], expected_recommendation)

    def test_explicit_grill_requires_independent_brainstorming_review(self):
        decision = decide_overlay(
            stage="designed", operation="design", complexity=1, risk=1,
            explicit_grill=True, source_status="supported", write_task=True,
        )
        self.assertEqual(decision["postGrillReview"]["independentContextRequired"], True)


if __name__ == "__main__":
    unittest.main()
