from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ReviewRoleBoundaryTests(unittest.TestCase):
    def test_workflow_makes_primary_only_graft_and_reviewer_read_only(self):
        workflow = (ROOT / "WORKFLOW.md").read_text(encoding="utf-8")
        review = (ROOT / "workflow" / "modules" / "review.md").read_text(
            encoding="utf-8"
        )
        text = f"{workflow}\n{review}".lower()

        self.assertIn("主 agent", text)
        self.assertIn("review subagent", text)
        self.assertIn("graft", text)
        self.assertIn("不得调用", text)
        self.assertIn("graft deep", text)
        self.assertIn("只读", text)
        self.assertIn("缺少 graft evidence", text)
        self.assertIn("reviewmodel", text)
        self.assertIn("review-only", text)
        self.assertIn("其他 subagent", text)
