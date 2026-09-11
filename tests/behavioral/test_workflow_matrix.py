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
            "Full": ("design-grilling",),
            "Deep": ("design-grill-me",),
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

    def test_core_policy_requires_reviewed_landing_and_bounded_decisions(self):
        content = (self.ROOT / "workflow/core.md").read_text(encoding="utf-8")
        for phrase in (
            "design.gate", "plan.gate", "post-landing Review",
            "decision-record", "selectedId == recommendationId",
            "local component", "easy rollback", "critical decision",
        ):
            self.assertIn(phrase, content)

    def test_plan_gate_keeps_light_lightweight_and_requires_integrated_review_for_full(self):
        expectations = {
            "Light": ("plan-gate",),
            "Full": ("plan-integrated-review",),
            "Deep": ("plan-integrated-review",),
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


class LightweightPolicyTextTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_reusable_knowledge_prompts_once_without_trivial_noise(self):
        content = (self.ROOT / "workflow/core.md").read_text(encoding="utf-8")
        for phrase in (
            "可复用的技术知识",
            "主动提示一次是否沉淀",
            "每个任务最多提示一次",
            "用户拒绝后不再重复",
            "简单问答、机械修改、临时状态",
        ):
            self.assertIn(phrase, content)

    def test_unrelated_workflow_incident_stops_without_scope_drift(self):
        bootstrap = (self.ROOT / "WORKFLOW.md").read_text(encoding="utf-8")
        self.assertIn("任务外异常隔离", bootstrap)
        self.assertIn("当前目标根因或完成验收必需的故障", bootstrap)
        self.assertIn("必须用户明确授权后另行处理", bootstrap)
        content = (self.ROOT / "workflow/core.md").read_text(encoding="utf-8")
        for phrase in (
            "任务外异常隔离",
            "立即停止当前任务并向用户报告",
            "不得在原任务对话中",
            "用户明确回复授权",
            "当前任务自身的根因",
        ):
            self.assertIn(phrase, content)

    def test_progress_updates_are_low_noise_honest_ranges(self):
        content = (self.ROOT / "workflow/core.md").read_text(encoding="utf-8")
        for phrase in (
            "SelfWorkflow active: <profile>",
            "mode: <Light|Full|Deep>",
            "首条进度更新同时包含",
            "已完成主阶段/总主阶段",
            "当前",
            "剩余",
            "预计",
            "粗略区间",
            "单点精确百分比",
            "暂无法可靠估算",
            "重新估算",
            "保持单调",
            "不得按每个命令",
        ):
            self.assertIn(phrase, content)

    def test_caveman_lite_is_always_on_without_weakening_clarity_or_artifacts(self):
        content = (self.ROOT / "workflow/core.md").read_text(encoding="utf-8")
        for phrase in (
            "Caveman lite",
            "常驻",
            "Default: full",
            "技术信息完整",
            "代码、命令、错误",
            "文档、提交信息",
            "安全警告",
            "不可逆操作",
            "多步流程",
            "完整表达",
            "只能由用户明确指定",
        ):
            self.assertIn(phrase, content)

    def test_formal_document_packages_require_fresh_independent_review(self):
        content = (self.ROOT / "workflow/core.md").read_text(encoding="utf-8")
        for phrase in (
            "Full/Deep",
            "至少两份正式文档",
            "独立 SubAgent",
            "完整文档包",
            "最终文档包 hash",
            "同一 Agent",
            "unverified",
            "暂停实施",
            "post-landing Review",
        ):
            self.assertIn(phrase, content)

    def test_intrusion_budget_blocks_test_driven_production_architecture(self):
        content = (self.ROOT / "workflow/core.md").read_text(encoding="utf-8")
        for phrase in (
            "侵入性预算",
            "影响半径",
            "测试覆盖不能反向驱动生产架构",
            "公共枚举",
            "全局编译宏",
            "用户明确确认",
            "超出预算",
            "unverified",
        ):
            self.assertIn(phrase, content)

    def test_implementation_converges_without_solving_adjacent_problems(self):
        content = (self.ROOT / "workflow/core.md").read_text(encoding="utf-8")
        for phrase in (
            "设计阶段允许发散",
            "实施阶段必须收敛",
            "Plan 是实施边界",
            "允许修改的组件",
            "发现问题不等于获得解决授权",
            "计划外发现不得自动进入实现",
            "阻塞当前验收",
            "修订 Plan",
            "重新确认",
            "相邻改进",
            "完成当前目标",
            "有界的收敛检查",
            "主目标、根因修复或验收条件",
            "更窄方案",
            "独立接口、状态、生命周期或构建变体",
            "重新取得用户确认",
        ):
            self.assertIn(phrase, content)

        self.assertRegex(
            content,
            r"相邻改进[^\n]*(?:记录|汇报)[^\n]*(?:不实施|延后)",
        )

    def test_code_implementation_contract_precedes_all_code_edits(self):
        content = (self.ROOT / "workflow/core.md").read_text(encoding="utf-8")
        for phrase in (
            "代码实施契约",
            "第一次编辑测试或生产代码前",
            "只读分析和文档修订",
            "明确实施确认",
            "设计/规格",
            "TEA/测试设计",
            "实施计划",
            "安全、性能、可维护性",
            "Review → 用户确认 → TDD",
            "确认失效",
            "Light",
            "紧凑",
            "批准的侵入性预算",
            "共享热路径",
            "测试来源的生产改动",
            "关键测试接缝",
        ):
            self.assertIn(phrase, content)
        self.assertRegex(
            content,
            r"实施计划[\s\S]{0,300}侵入性预算[\s\S]{0,100}回滚",
        )


if __name__ == "__main__":
    unittest.main()
