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

    def test_code_review_loads_applicable_method_without_change_rules(self):
        review = (ROOT / "workflow/modules/review.md").read_text(encoding="utf-8")
        self.assertIn("行为代码审查补读", review)
        self.assertIn("../../skills/code-quality/references/review-rules.md", review)
        method = (ROOT / "skills/code-quality/references/review-rules.md").read_text(encoding="utf-8")
        for boundary in ("已支持场景", "证伪", "被调函数", "持有时间", "优先级/标签/历史", "删除/内联"):
            with self.subTest(boundary=boundary):
                self.assertIn(boundary, method)
        self.assertNotIn("change-rules.md", method)
        self.assertNotIn("modules/review.md", method)
        self.assertIn("不启动 TDD、构建或写入", method)
        self.assertIn("普通解释分析不加载本页", method)

    def test_review_evidence_and_followup_preserve_existing_boundaries(self):
        review = (ROOT / "workflow/modules/review.md").read_text(encoding="utf-8")
        for boundary in (
            "候选分别确认、证伪、范围外或待证据", "消费者后果", "增量归因", "确定后果与条件风险",
            "共享状态、发布顺序和恢复路径的交互", "输入未变不重复执行",
            "纯审查交付完整发现，不要求先修复", "完成后一次汇总", "not-run/unverified",
        ):
            with self.subTest(boundary=boundary):
                self.assertIn(boundary, review)
        for text in (review, (ROOT / "skills/code-quality/references/review-rules.md").read_text(encoding="utf-8")):
            self.assertNotIn("MeshGrass", text)
            self.assertNotIn("SetByCode", text)
