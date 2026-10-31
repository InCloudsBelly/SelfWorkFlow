from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class CodeQualityScenarioTests(unittest.TestCase):
    def test_scenarios_cover_all_approved_failure_classes(self):
        value = yaml.safe_load(
            (ROOT / "tests/behavioral/scenarios/code-quality.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(value["schemaVersion"], 1)
        self.assertEqual(
            {scenario["id"] for scenario in value["scenarios"]},
            {
                "downstream-compensation",
                "partial-persistence",
                "stale-recovery-data",
                "shared-path-regression",
                "dirty-worktree",
                "false-noop-success",
                "application-layer-intrusion",
                "test-driven-production-intrusion",
                "local-test-seam",
                "implementation-contract-boundary-drift",
                "in-budget-private-detail",
                "adjacent-diagnostic-subsystem",
                "unplanned-regression-blocker",
                "stable-callers-reverse-dependency",
                "shared-invariant-owner-migration",
                "batch-configuration-write",
                "review-complete-supported-scope",
                "review-publication-lifetime",
                "review-compact-feature-boundary",
            },
        )
        self.assertTrue(all(scenario["critical"] for scenario in value["scenarios"]))

    def test_review_cases_have_inputs_and_criteria_in_the_existing_rubric(self):
        scenarios = yaml.safe_load(
            (ROOT / "tests/behavioral/scenarios/code-quality.yaml").read_text(encoding="utf-8")
        )["scenarios"]
        rubric = yaml.safe_load(
            (ROOT / "tests/behavioral/rubrics/code-quality.yaml").read_text(encoding="utf-8")
        )
        cases = [case for case in scenarios if case["id"].startswith("review-")]
        self.assertTrue(cases)
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertTrue(case["input"].strip())
                self.assertTrue(case["expected"].strip())
                self.assertTrue(set(case["critical"]).issubset(rubric["critical"]))

    def test_skills_are_standalone_generic_and_contain_core_invariants(self):
        code_quality = (ROOT / "skills/code-quality/SKILL.md").read_text(encoding="utf-8")
        workflow_quality = (ROOT / "skills/workflow-quality/SKILL.md").read_text(
            encoding="utf-8"
        )
        change_rules = (ROOT / "skills/code-quality/references/change-rules.md").read_text(encoding="utf-8")
        combined_rules = code_quality + change_rules
        self.assertIn("references/change-rules.md", code_quality)
        for phrase in (
            "失败边界", "last-good", "first-bad", "owner", "检测点",
            "缓存", "失效/重建范围", "受影响共享路径", "消费者成功",
            "用户修改", "plan → review → confirm → apply → reread",
            "侵入性", "影响半径", "测试不能反向驱动生产架构",
            "公共枚举", "全局编译宏", "translation unit",
            "明确确认", "实施契约", "第一次编辑测试",
            "安全/性能/兼容性/维护成本", "停止受影响编辑",
            "Plan 冻结目标", "发现问题不等于授权修复",
            "广回归失败", "同步计划", "有界迁移",
            "稳定现有调用者", "真实共享不变量", "测试方便", "unverified",
        ):
            self.assertTrue(phrase in combined_rules, phrase)
        self.assertIn("新鲜证据", workflow_quality)
        combined = code_quality + workflow_quality
        for name, content in (("code-quality", code_quality), ("workflow-quality", workflow_quality)):
            frontmatter = yaml.safe_load(content.split("---", 2)[1])
            self.assertEqual(frontmatter["name"], name)
            self.assertTrue(frontmatter["description"].strip())
        self.assertNotIn("kuaishou", combined.casefold())
        self.assertNotIn(":\\", combined)

    def test_code_quality_supports_read_only_analysis_without_change_rules(self):
        code_quality = (ROOT / "skills/code-quality/SKILL.md").read_text(
            encoding="utf-8"
        )
        catalog = yaml.safe_load(
            (ROOT / "catalog/domains/code-quality.yaml").read_text(encoding="utf-8")
        )
        entry = next(item for item in catalog["entries"] if item["id"] == "code-quality")

        self.assertIn("用于解释、诊断或变更行为", code_quality)
        self.assertIn("## 只读", code_quality)
        self.assertIn("只读分析不启动 TDD、构建、写入", code_quality)
        self.assertIn("analyze", entry["selectors"]["operationTypes"])
        self.assertIn("read code", entry["selectors"]["semanticTerms"])

    def test_baseline_records_the_observed_old_rule_failure(self):
        baseline = (ROOT / "docs/provenance/code-quality-baseline.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "observed baseline failure",
            "public EMeshPass",
            "test-only enum slot",
            "production Renderer path",
            "narrowest compatible owner-layer change",
        ):
            self.assertIn(phrase, baseline)


if __name__ == "__main__":
    unittest.main()
