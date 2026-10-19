from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ReviewRoleBoundaryTests(unittest.TestCase):
    def test_workflow_makes_primary_only_codegraph_and_reviewer_read_only(self):
        workflow = (ROOT / "WORKFLOW.md").read_text(encoding="utf-8")
        review = (ROOT / "workflow" / "modules" / "review.md").read_text(
            encoding="utf-8"
        )
        codegraph = (ROOT / "workflow" / "modules" / "codegraph-read.md").read_text(
            encoding="utf-8"
        )
        text = f"{workflow}\n{review}\n{codegraph}".lower()

        self.assertIn("主 agent", text)
        self.assertIn("reviewer", text)
        self.assertIn("codegraph", text)
        self.assertIn("不得调用", text)
        self.assertNotIn("deep topic", text)
        self.assertIn("只读", text)
        self.assertIn("缺少 codegraph evidence", text)
        self.assertIn("继承主 agent 模型", text)
        self.assertIn("所有模式取消双", text)
        self.assertIn("下级 agent", text)
