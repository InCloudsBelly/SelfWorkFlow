import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from selfworkflow.catalog import compile_catalog
from selfworkflow.adapters import AdapterError, build_runtime
from selfworkflow.resolver import resolve_task
from selfworkflow.router import ModuleRouteRequest, route_modules


ROOT = Path(__file__).resolve().parents[2]


class WorkflowCompressionTests(unittest.TestCase):
    BASELINE_COMMIT = "ff4d991cb32f53df65fbedc67da69b11445c5cb3"
    BASELINE_WORKFLOW_SHA256 = "508736beb117ee7e64ea17f8896250d265a2461112927f733aa7489039eeb1be"
    MODES = (
        "workflow/modes/light.md",
        "workflow/modes/full.md",
        "workflow/modes/deep.md",
    )
    MODULES = (
        "workflow/modules/code.md",
        "workflow/modules/codegraph-read.md",
        "workflow/modules/codegraph-update.md",
        "workflow/modules/review.md",
        "workflow/modules/knowledge.md",
        "workflow/modules/artifacts.md",
    )

    def test_bootstrap_is_compact_and_has_complete_startup_contract(self):
        raw = (ROOT / "WORKFLOW.md").read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        text = raw.decode("utf-8", errors="strict")
        baseline = subprocess.check_output(["git", "show", f"{self.BASELINE_COMMIT}:WORKFLOW.md"], cwd=ROOT)
        self.assertEqual(hashlib.sha256(baseline).hexdigest(), self.BASELINE_WORKFLOW_SHA256)
        self.assertLessEqual(len(text), 1_000)
        self.assertLessEqual(len(text), int(len(baseline.decode("utf-8")) * 0.10))
        for path in ("workflow/modes/full.md", "workflow/modes/deep.md", "skills/code-quality/SKILL.md", "workflow/modules/build.md", "workflow/legacy-host.md"):
            self.assertIn(path, text)
            self.assertTrue((ROOT / path).is_file())
        self.assertNotIn("workflow/modes/light.md", text)
        self.assertNotIn("workflow/core.md", text)
        for boundary in ("已有修改/凭据", "关键选择", "沿授权", "不编造或跳过", "unverified"):
            self.assertIn(boundary, text)

    def test_mode_and_task_files_exist_with_routing_contract(self):
        for relative in self.MODES + self.MODULES:
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).is_file())
        full = (ROOT / "workflow/modes/full.md").read_text(encoding="utf-8")
        deep = (ROOT / "workflow/modes/deep.md").read_text(encoding="utf-8")
        for text in (full, deep):
            self.assertIn("modules/review.md", text)
            self.assertIn("testing-review-quality", text)
        self.assertIn("../../skills/testing-review-quality/SKILL.md", full)
        self.assertNotIn("implement-tdd", full)
        self.assertIn("本模式不要求再读 Full", deep)
        review = (ROOT / "workflow/modules/review.md").read_text(encoding="utf-8")
        self.assertIn("plan-integrated-review", review)
        self.assertIn("一个独立 SubAgent 同时检查 Standards/Spec", review)

    def test_route_order_and_optional_tea_are_explicit(self):
        bootstrap = (ROOT / "WORKFLOW.md").read_text(encoding="utf-8")
        for relative in ("workflow/modes/full.md", "workflow/modes/deep.md"):
            mode = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("TDD", mode)
            self.assertIn("交付前一个独立 Reviewer", mode)
        for capability in ("TEA", "grilling", "Superpowers"):
            self.assertIn(capability, bootstrap)
        self.assertIn("仅显式点名", bootstrap)

    def test_light_and_full_deep_keep_distinct_review_and_tea_gates(self):
        bootstrap = (ROOT / "WORKFLOW.md").read_text(encoding="utf-8")
        light = (ROOT / "workflow/modes/light.md").read_text(encoding="utf-8")
        self.assertIn("Light：低风险小任务", bootstrap)
        self.assertIn("窄自审", bootstrap)
        self.assertNotIn("workflow/modes/light.md", bootstrap)
        self.assertIn("无需再读本页", light)
        self.assertIn("不冒充独立审查", light)
        self.assertIn("不自动 Grill 或 TEA", light)

    def test_review_model_boundary_and_compact_dispatch_policy_are_explicit(self):
        review = (ROOT / "workflow/modules/review.md").read_text(encoding="utf-8")
        for phrase in (
            "默认继承主 Agent 模型/推理配置",
            "不读取机器本地 Review 模型配置",
            "不传 model/reasoning_effort 覆盖",
            "普通设计/计划/测试设计合并",
            "一个独立 SubAgent 同时检查 Standards/Spec",
            "两个轴不是两个上下文",
            "不接收完整主历史、整库 Wiki 或无关材料",
            "修复后只复核未关闭问题及影响项",
            "不设“超预算中止”",
            "TEA 仅显式启用",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, review)

    def test_reuse_and_wait_policy_keeps_freshness_and_completion_boundaries(self):
        text = (ROOT / "WORKFLOW.md").read_text(encoding="utf-8")
        for boundary in ("版本/输入/完整正文未变则复用", "只补缺口", "无新证据", "可中断等待", "未完成不因预算停工"):
            self.assertIn(boundary, text)
        for relative in ("workflow/modes/full.md", "workflow/modes/deep.md"):
            self.assertIn("Token/次数预算", (ROOT / relative).read_text(encoding="utf-8"))

    def test_representative_rule_route_stays_compact_without_duplicating_review(self):
        # Character budget for regression protection, not a measured token count.
        paths = (
            "WORKFLOW.md", "workflow/modes/full.md",
            "workflow/modules/codegraph-read.md", "workflow/modules/review.md",
            "skills/code-quality/SKILL.md", "skills/workflow-quality/SKILL.md",
            "skills/testing-review-quality/SKILL.md",
        )
        self.assertLessEqual(sum(len((ROOT / path).read_text(encoding="utf-8")) for path in paths), 10_000)
        for relative in (
            "workflow/modes/full.md", "workflow/modes/deep.md",
            "skills/testing-review-quality/SKILL.md",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertIn("modules/review.md", text)
                self.assertNotIn("model/reasoning_effort", text)
                self.assertNotIn("不接收完整主历史", text)

    def test_review_followup_selects_available_tools_and_lifecycle(self):
        text = (ROOT / "workflow/modules/review.md").read_text(encoding="utf-8")
        for phrase in ("本会话实际工具", "运行中与空闲", "send_message", "followup_task", "send_input"):
            self.assertIn(phrase, text)
        self.assertNotIn("Codex `send_input`", text)
        self.assertNotIn("DSH `send_message`", text)

    def test_cli_query_includes_the_read_boundary_check(self):
        text = (ROOT / "workflow/modules/codegraph-read.md").read_text(encoding="utf-8")
        self.assertIn("CLI 路径", text)
        self.assertIn("它已包含核对，不先另跑 preflight", text)
        self.assertIn("成功核对且 fresh 后才查询", text)
        self.assertIn("独立 CLI 调用不共享阶段缓存", text)
        code = (ROOT / "workflow/modules/code.md").read_text(encoding="utf-8")
        self.assertNotIn("`provider preflight`", code)

    def test_projection_and_resume_preserve_only_bound_task_state(self):
        text = (ROOT / "WORKFLOW.md").read_text(encoding="utf-8")
        for boundary in ("定向查询并投影", "续接/换阶段不重启", "交接仅留目标/授权、绑定、有效证据与待办"):
            self.assertIn(boundary, text)
        legacy = (ROOT / "workflow/legacy-host.md").read_text(encoding="utf-8")
        for phrase in ("artifact-manifest.json", "在工具内解析", "version/profile/runtimeHash", "path/sha256"):
            self.assertIn(phrase, legacy)
        self.assertIn("workflow/legacy-host.md", text)

    def test_build_cache_rules_are_loaded_at_the_build_boundary(self):
        bootstrap = (ROOT / "WORKFLOW.md").read_text(encoding="utf-8")
        build = (ROOT / "workflow/modules/build.md").read_text(encoding="utf-8")
        self.assertIn("workflow/modules/build.md", bootstrap)
        for boundary in ("Clean/Rebuild", "-NoLiveCoding", "共享 Intermediate/PCH", "隔离输出", "取得用户确认"):
            self.assertIn(boundary, build)
        self.assertNotIn("Clean/Rebuild", bootstrap)

    def test_module_restrictions_are_scoped_to_their_operations_and_artifacts(self):
        expected = {
            "WORKFLOW.md": ("按实际操作读取", "模块失败仅阻塞依赖动作"),
            "workflow/modules/knowledge.md": ("不适用于普通代码", "其他后端走显式 adapter"),
            "workflow/modules/artifacts.md": ("不强制普通任务新建", "不自动触发知识发布"),
            "workflow/modules/optional-integrations.md": ("只约束对应增强模块", "不阻塞无关模块"),
            "skills/kg-selfopenwiki/SKILL.md": ("不约束其他模块或 SelfWorkflow 源 Git", "本次Wiki首次MCP调用openwiki_status"),
            "workflow/modules/review.md": ("知识 Review 可读绑定候选与必要来源",),
        }
        for relative, phrases in expected.items():
            text = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                for phrase in phrases:
                    self.assertIn(phrase, text)

    def test_unavailable_knowledge_capabilities_do_not_block_other_owners(self):
        catalog = compile_catalog(ROOT / "catalog").content
        cases = (
            ("implement", "Full", True, "implement.tdd", "exactly-one", "implement-tdd"),
            ("review", "Full", False, "review.independent", "zero-or-one", "review-code-review"),
            ("document", "Light", True, "implement.method", "zero-or-one", "implement-documentation"),
        )
        for knowledge_state in ("unsupported", "unverified"):
            for operation, strength, write, slot, cardinality, expected in cases:
                result = route_modules(catalog, ModuleRouteRequest(
                    slot_id=slot, cardinality=cardinality, operation_type=operation,
                    strength=strength, write_task=write,
                    capability_states={
                        "skill-discovery": "supported", "filesystem-read": "supported",
                        "filesystem-write": "supported", "test-execution": "supported",
                        "independent-context": "supported", "user-confirmation": "supported",
                        "knowledge-read": knowledge_state, "knowledge-write": knowledge_state,
                    },
                ))
                with self.subTest(operation=operation, knowledge=knowledge_state):
                    self.assertEqual(result.status, "routed")
                    self.assertEqual(result.selected_modules, (expected,))

    def test_catalog_routes_match_the_split_mode_contract(self):
        catalog = compile_catalog(ROOT / "catalog").content
        for strength, expected in (
            ("Light", ()),
            ("Full", ()),
            ("Deep", ()),
        ):
            capabilities = {"skill-discovery": "supported"}
            if strength == "Deep":
                capabilities["user-confirmation"] = "supported"
            route = route_modules(
                catalog,
                ModuleRouteRequest(
                    slot_id="design.specialists",
                    cardinality="zero-or-many",
                    operation_type="implement",
                    strength=strength,
                    write_task=True,
                    capability_states=capabilities,
                ),
            )
            self.assertEqual(route.selected_modules, expected)

    def test_full_read_only_design_and_plan_do_not_auto_load_grilling(self):
        catalog = compile_catalog(ROOT / "catalog").content
        evidence = [
            {
                "name": name,
                "provider": "compression-test",
                "subject": {
                    "kind": "test",
                    "id": "full-read-only",
                    "version": "1",
                    "build": "1",
                    "sourceLock": "sha256:" + "4" * 64,
                },
                "state": "supported",
                "observedAt": "2020-01-01T00:00:00Z",
                "validUntil": "2099-01-01T00:00:00Z",
                "evidenceRef": "compression:full-read-only:" + name,
                "evidenceHash": "sha256:" + "4" * 64,
            }
            for name in ("filesystem-read", "skill-discovery", "independent-context")
        ]
        for operation in ("design", "plan"):
            with self.subTest(operation=operation):
                result = resolve_task(
                    catalog,
                    {
                        "schemaVersion": 2,
                        "operationType": operation,
                        "complexity": "C1",
                        "risk": "R1",
                        "writeTask": False,
                        "ambiguity": False,
                        "explicitModuleIds": [],
                        "projectDefaultModuleIds": [],
                        "projectMinimums": {"strength": "Full"},
                        "capabilityEvidenceSnapshot": {
                            "schemaVersion": 1,
                            "capturedAt": "2020-01-01T00:00:00Z",
                            "evidence": evidence,
                        },
                    },
                )
                self.assertEqual(result["status"], "active")
                selected = [
                    module
                    for stage in result["planGraph"]["stages"]
                    for slot in stage["slots"]
                    for module in slot["selectedModules"]
                ]
                self.assertNotIn("design-grilling", selected)

    def test_read_only_and_non_code_routes_do_not_load_behavior_modules(self):
        catalog = compile_catalog(ROOT / "catalog").content
        deep_read = route_modules(
            catalog,
            ModuleRouteRequest(
                slot_id="design.specialists",
                cardinality="zero-or-many",
                operation_type="analyze",
                strength="Deep",
                write_task=False,
                capability_states={
                    "skill-discovery": "supported",
                    "user-confirmation": "supported",
                },
            ),
        )
        self.assertEqual(deep_read.selected_modules, ())
        for slot in ("test.quality.plan", "review.independent", "test.quality.review"):
            with self.subTest(slot=slot):
                route = route_modules(
                    catalog,
                    ModuleRouteRequest(
                        slot_id=slot,
                        cardinality="zero-or-one",
                        operation_type="document",
                        strength="Full",
                        write_task=True,
                        capability_states={
                            "skill-discovery": "supported",
                            "independent-context": "supported",
                        },
                    ),
                )
                self.assertEqual(route.selected_modules, ())

    def test_codegraph_is_the_only_code_graph_provider_with_rg_fallback(self):
        active_files = (
            "WORKFLOW.md",
            "workflow/core.md",
            "workflow/modules/code.md",
            "workflow/modules/codegraph-read.md",
            "workflow/modules/codegraph-update.md",
            "skills/cpp-core/SKILL.md",
            "docs/providers/codegraph.md",
            "README.md",
            "scripts/install-selfworkflow.ps1",
        )
        active_text = "\n".join(
            (ROOT / relative).read_text(encoding="utf-8")
            for relative in active_files
        ).casefold()
        self.assertIn("codegraph", active_text)
        self.assertIn("rg", active_text)

    def test_non_code_document_plan_skips_behavior_gates_without_blocking(self):
        catalog = compile_catalog(ROOT / "catalog").content
        evidence = []
        for name in (
            "filesystem-read",
            "filesystem-write",
            "skill-discovery",
            "test-execution",
            "independent-context",
        ):
            evidence.append(
                {
                    "name": name,
                    "provider": "compression-test",
                    "subject": {
                        "kind": "test",
                        "id": "compression",
                        "version": "1",
                        "build": "1",
                        "sourceLock": "sha256:" + "1" * 64,
                    },
                    "state": "supported",
                    "observedAt": "2020-01-01T00:00:00Z",
                    "validUntil": "2099-01-01T00:00:00Z",
                    "evidenceRef": "compression:" + name,
                    "evidenceHash": "sha256:" + "1" * 64,
                }
            )
        result = resolve_task(
            catalog,
            {
                "schemaVersion": 2,
                "operationType": "document",
                "complexity": "C2",
                "risk": "R1",
                "writeTask": True,
                "ambiguity": False,
                "explicitModuleIds": [],
                "projectDefaultModuleIds": [],
                "projectMinimums": {"strength": "Full"},
                "capabilityEvidenceSnapshot": {
                    "schemaVersion": 1,
                    "capturedAt": "2020-01-01T00:00:00Z",
                    "evidence": evidence,
                },
            },
        )
        self.assertEqual(result["status"], "active")
        for stage in result["planGraph"]["stages"]:
            for slot in stage["slots"]:
                if slot["slotId"] in {
                    "test.quality.plan",
                    "review.independent",
                    "test.quality.review",
                }:
                    self.assertEqual(slot["applicability"], "not-applicable")
                    self.assertEqual(slot["selectedModules"], [])

    def test_deep_read_only_plan_skips_write_gates_without_blocking(self):
        catalog = compile_catalog(ROOT / "catalog").content
        request = {
            "schemaVersion": 2,
            "operationType": "analyze",
            "complexity": "C3",
            "risk": "R1",
            "writeTask": False,
            "ambiguity": False,
            "explicitModuleIds": [],
            "projectDefaultModuleIds": [],
            "projectMinimums": {"strength": "Deep"},
            "capabilityEvidenceSnapshot": {
                "schemaVersion": 1,
                "capturedAt": "2020-01-01T00:00:00Z",
                "evidence": [
                    {
                        "name": "skill-discovery",
                        "provider": "compression-test",
                        "subject": {
                            "kind": "test",
                            "id": "compression-read",
                            "version": "1",
                            "build": "1",
                            "sourceLock": "sha256:" + "2" * 64,
                        },
                        "state": "supported",
                        "observedAt": "2020-01-01T00:00:00Z",
                        "validUntil": "2099-01-01T00:00:00Z",
                        "evidenceRef": "compression:skill-discovery",
                        "evidenceHash": "sha256:" + "2" * 64,
                    },
                    {
                        "name": "filesystem-read",
                        "provider": "compression-test",
                        "subject": {
                            "kind": "test",
                            "id": "compression-read",
                            "version": "1",
                            "build": "1",
                            "sourceLock": "sha256:" + "3" * 64,
                        },
                        "state": "supported",
                        "observedAt": "2020-01-01T00:00:00Z",
                        "validUntil": "2099-01-01T00:00:00Z",
                        "evidenceRef": "compression:filesystem-read",
                        "evidenceHash": "sha256:" + "3" * 64,
                    }
                ],
            },
        }
        evidence = request["capabilityEvidenceSnapshot"]["evidence"]
        evidence.append({
            **evidence[-1],
            "name": "independent-context",
            "evidenceRef": "compression:independent-context",
        })
        result = resolve_task(catalog, request)
        self.assertEqual(result["status"], "active")
        for stage in result["planGraph"]["stages"]:
            for slot in stage["slots"]:
                if slot["slotId"] in {"design.specialists", "plan.gate"}:
                    self.assertEqual(slot["selectedModules"], [])

        evidence.pop()
        blocked = resolve_task(catalog, request)
        self.assertEqual(blocked["status"], "paused")
        self.assertIn("required-capability-unavailable", blocked["reasonCodes"])

    def test_read_only_keeps_write_protection_and_codegraph_is_bounded(self):
        text = (ROOT / "WORKFLOW.md").read_text(encoding="utf-8")
        for boundary in ("只读不写", "CodeGraph 索引例外", "不编造或跳过", "unverified"):
            self.assertIn(boundary, text)

    def test_runtime_package_contains_split_files_and_codegraph_lock(self):
        output_parent = Path(tempfile.mkdtemp(prefix="selfworkflow-compression-"))
        output = output_parent / "runtime"
        try:
            build_runtime(ROOT, output, "compression-test", profile="core")
            for relative in self.MODES + self.MODULES:
                with self.subTest(relative=relative):
                    self.assertTrue((output / relative).is_file())
            manifest = json.loads(
                (output / "artifact-manifest.json").read_text(encoding="utf-8")
            )
            entries = {item["path"]: item["sha256"] for item in manifest["files"]}
            for relative in self.MODES + self.MODULES:
                with self.subTest(manifest_path=relative):
                    self.assertEqual(
                        entries[relative],
                        hashlib.sha256((output / relative).read_bytes()).hexdigest(),
                    )
                    self.assertEqual(
                        hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
                        entries[relative],
                    )
            self.assertIn("dependencies/locks/codegraph.lock.yaml", entries)
            self.assertEqual(
                entries["dependencies/locks/codegraph.lock.yaml"],
                hashlib.sha256((ROOT / "dependencies/locks/codegraph.lock.yaml").read_bytes()).hexdigest(),
            )
        finally:
            shutil.rmtree(output_parent, ignore_errors=True)

    def test_runtime_packaging_fails_closed_when_a_required_split_file_is_missing(self):
        output_parent = Path(tempfile.mkdtemp(prefix="selfworkflow-compression-missing-"))
        output = output_parent / "runtime"
        try:
            import selfworkflow.adapters as adapters

            with mock.patch.object(
                adapters,
                "_CORE_PATHS",
                adapters._CORE_PATHS + ("workflow/modules/missing.md",),
            ):
                with self.assertRaisesRegex(AdapterError, "runtime-source-invalid"):
                    build_runtime(ROOT, output, "compression-missing", profile="core")
            self.assertFalse(output.exists())
        finally:
            shutil.rmtree(output_parent, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
