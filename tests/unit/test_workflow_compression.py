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
        self.assertLessEqual(len(text), 10_500)
        baseline = subprocess.check_output(
            ["git", "show", f"{self.BASELINE_COMMIT}:WORKFLOW.md"],
            cwd=ROOT,
        )
        self.assertEqual(hashlib.sha256(baseline).hexdigest(), self.BASELINE_WORKFLOW_SHA256)
        baseline_text = baseline.decode("utf-8", errors="strict")
        self.assertFalse(baseline.startswith(b"\xef\xbb\xbf"))
        self.assertLessEqual(len(text), int(len(baseline_text) * 0.30))
        for phrase in (
            "沟通和工程文档用中文",
            "不伪造能力或降级冒充通过",
            "凭据",
            "保护用户已有修改",
            "完成前核对新鲜证据",
            "任务外异常隔离",
            "workflow/modes/<mode>.md",
            "只读选定的",
            "缺失、不可读、hash 漂移",
            "unverified",
            "Capability Check",
            "关键决策",
            "需重新确认",
            "artifact-manifest.json",
            "Plan 是实施边界",
            "不得省略必需规则冒充优化",
            "当前目标根因或完成验收必需的故障",
            "必须用户明确授权后另行处理",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_mode_and_task_files_exist_with_routing_contract(self):
        for relative in self.MODES + self.MODULES:
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).is_file())
        full = (ROOT / "workflow/modes/full.md").read_text(encoding="utf-8")
        deep = (ROOT / "workflow/modes/deep.md").read_text(encoding="utf-8")
        for phrase in (
            "不自动 Grilling 或 TEA",
            "plan-integrated-review",
            "一个独立 Reviewer",
            "implement-tdd",
        ):
            self.assertIn(phrase, full)
        self.assertIn("grilling", deep.casefold())
        self.assertIn("用户显式点名", deep)
        self.assertIn("一个独立 Reviewer", deep)

    def test_route_order_and_optional_tea_are_explicit(self):
        full = (ROOT / "workflow/modes/full.md").read_text(encoding="utf-8")
        deep = (ROOT / "workflow/modes/deep.md").read_text(encoding="utf-8")
        for text in (full, deep):
            self.assertIn("显式", text)
            self.assertIn("TEA", text)
            self.assertIn("grilling", text.casefold())
            self.assertIn("plan-integrated-review", text)
        self.assertIn("tdd", full.casefold())
        self.assertIn("tdd", deep.casefold())

        self.assertIn("Full/Deep 交付前一个独立 SubAgent", (ROOT / "WORKFLOW.md").read_text(encoding="utf-8"))

    def test_light_and_full_deep_keep_distinct_review_and_tea_gates(self):
        bootstrap = (ROOT / "WORKFLOW.md").read_text(encoding="utf-8")
        light = (ROOT / "workflow/modes/light.md").read_text(encoding="utf-8")
        for phrase in (
            "Full/Deep 交付前一个独立 SubAgent",
            "Light 窄结构化自审",
            "所有模式禁止双 Reviewer",
        ):
            self.assertIn(phrase, bootstrap)
        self.assertIn("不自动 Grill 或 TEA", light)
        self.assertIn("不冒充独立 SubAgent Review", light)

    def test_review_model_boundary_and_compact_dispatch_policy_are_explicit(self):
        review = (ROOT / "workflow/modules/review.md").read_text(encoding="utf-8")
        for phrase in (
            "默认继承主 Agent 模型/推理配置",
            "不读取机器本地 Review 模型配置",
            "不传 model/reasoning_effort 覆盖",
            "普通设计/计划/测试设计合并",
            "一个独立 SubAgent 同时检查 Standards/Spec",
            "两个轴不是两个上下文",
            "不接收完整主历史、Wiki 或无关材料",
            "修复后只复核未关闭问题及影响项",
            "不设“超预算中止”",
            "TEA 仅显式启用",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, review)

    def test_reuse_and_wait_policy_keeps_freshness_and_completion_boundaries(self):
        text = (ROOT / "WORKFLOW.md").read_text(encoding="utf-8")
        for phrase in (
            "跨阶段/相邻轮次复用", "正文缺失只补受影响内容",
            "摘要不冒充已读完整规则", "同职责由最窄匹配 Skill 承接",
            "关键词重叠不叠加编排", "工具端按问题投影",
            "可中断长等待", "避免秒级空轮询",
            "不因 Token/次数预算耗尽中止未完成任务",
        ):
            with self.subTest(boundary=phrase):
                self.assertIn(phrase, text)

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
        result = resolve_task(
            catalog,
            {
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
            },
        )
        self.assertEqual(result["status"], "active")
        for stage in result["planGraph"]["stages"]:
            for slot in stage["slots"]:
                if slot["slotId"] in {"design.specialists", "plan.gate"}:
                    self.assertEqual(slot["selectedModules"], [])

    def test_read_only_keeps_write_protection_and_codegraph_is_bounded(self):
        text = (ROOT / "WORKFLOW.md").read_text(encoding="utf-8")
        for phrase in (
            "writeTask=false",
            "不得编辑或产生副作用",
            "CodeGraph",
            "不伪造能力或降级冒充通过",
        ):
            self.assertIn(phrase, text)

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
