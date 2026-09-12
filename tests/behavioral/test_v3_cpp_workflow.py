from pathlib import Path
import hashlib
import unittest

import yaml

from selfworkflow.v3.cpp_router import CppRouteRequest, route_cpp_capabilities
from selfworkflow.v3.catalog import compile_catalog
from selfworkflow.v3.plan_graph import _condition_matches
from selfworkflow.v3.pipeline import load_pipeline


class V3CppWorkflowTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_cpp_core_is_standalone_and_progressively_discloses_specialists(self):
        skill = self.ROOT / "skills" / "cpp-core" / "SKILL.md"
        text = skill.read_text(encoding="utf-8")

        self.assertIn("name: cpp-core", text)
        self.assertIn("failure envelope", text)
        self.assertIn("root-cause owner", text)
        self.assertIn("references/ownership.md", text)
        self.assertIn("references/unreal.md", text)
        self.assertNotIn("E:\\", text)
        self.assertNotIn("kuaishou", text.casefold())

    def test_every_specialist_has_an_independently_useful_reference(self):
        expected = {
            "ownership", "type-system", "concurrency", "abi", "performance",
            "safety", "build", "debugging", "unreal",
        }
        references = self.ROOT / "skills" / "cpp-core" / "references"

        self.assertEqual({path.stem for path in references.glob("*.md")}, expected)
        for name in expected:
            content = (references / f"{name}.md").read_text(encoding="utf-8")
            self.assertIn("## 验证", content, name)
            self.assertIn("## 边界", content, name)

    def test_catalog_source_hashes_bind_progressively_loaded_skill_files(self):
        catalog = compile_catalog().document["catalog"]
        for module in catalog["modules"]:
            if module["id"] != "cpp-core" and not module["id"].startswith("cpp."):
                continue
            target = self.ROOT / module["invocation"]["ref"]
            actual = "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
            self.assertEqual(module["sourceHash"], actual, module["id"])

    def test_native_capability_files_never_claim_runtime_support(self):
        capability_root = self.ROOT / "capabilities" / "cpp"
        for name in ("build", "debugging", "engine-unreal"):
            content = yaml.safe_load(
                (capability_root / f"{name}.yaml").read_text(encoding="utf-8")
            )
            self.assertNotEqual(content.get("status"), "supported", name)
        self.assertEqual(
            yaml.safe_load((capability_root / "build.yaml").read_text(encoding="utf-8"))["nativeBuildStatus"],
            "unverified",
        )
        self.assertEqual(
            yaml.safe_load((capability_root / "debugging.yaml").read_text(encoding="utf-8"))["debugExecutionStatus"],
            "unsupported",
        )
        self.assertEqual(
            yaml.safe_load((capability_root / "engine-unreal.yaml").read_text(encoding="utf-8"))["nativeValidationStatus"],
            "unverified",
        )

    def test_routing_fixture_covers_positive_false_conflict_and_composition(self):
        fixture_path = self.ROOT / "tests" / "fixtures" / "v3" / "cpp-routing.yaml"
        fixture = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))

        categories = {case["category"] for case in fixture["cases"]}
        self.assertEqual(categories, {"positive", "false-trigger", "conflict", "composition"})

    def test_cpp_debug_route_keeps_real_execution_outside_reasoning(self):
        route = route_cpp_capabilities(CppRouteRequest(
            operation_type="debug",
            languages=("cpp",),
            file_extensions=(".cpp",),
            task_signals=("native-crash", "unreal-engine"),
            risk="R2",
            explicit_module_ids=(),
            user_confirmed_heavy=False,
            project_allows_execution=False,
        ))

        self.assertIn("debug.reason", route.capability_ids)
        self.assertNotIn("debug.execute", route.capability_ids)
        self.assertIn("runtime-debugger-not-authorized", route.unverified_items)

    def test_cpp_read_only_analysis_loads_reasoning_without_change_execution(self):
        text = (self.ROOT / "skills/cpp-core/SKILL.md").read_text(encoding="utf-8")
        route = route_cpp_capabilities(CppRouteRequest(
            operation_type="analyze",
            languages=("cpp",),
            file_extensions=(".cpp",),
            task_signals=(),
            risk="R0",
            explicit_module_ids=(),
            user_confirmed_heavy=False,
            project_allows_execution=False,
        ))

        self.assertIn("只读分析只应用推理核心", text)
        self.assertEqual(route.selected_module_ids, ("cpp-core",))
        self.assertEqual(route.capability_ids, ("cpp.reasoning",))
        self.assertNotIn("debug.execute", route.capability_ids)

    def test_repository_catalog_and_pipeline_expose_bounded_cpp_reasoning(self):
        catalog = compile_catalog().document["catalog"]
        pipeline = load_pipeline().document
        module_ids = {item["id"] for item in catalog["modules"]}
        self.assertTrue({
            "cpp-core", "cpp.ownership", "cpp.type-system", "cpp.concurrency",
            "cpp.abi", "cpp.performance", "cpp.safety", "cpp.build",
            "cpp.debugging", "cpp.engine.unreal",
        } <= module_ids)
        slots = {
            slot["id"]: slot
            for stage in pipeline["stages"]
            for slot in stage["slots"]
        }
        self.assertEqual(slots["code.reasoning"]["selectionMode"], "bounded-runtime")
        self.assertEqual(slots["code.verify"]["selectionMode"], "bounded-runtime")
        cpp_modules = [item for item in catalog["modules"] if item["id"].startswith("cpp")]
        self.assertTrue(all(
            item["supportEvidence"]["runtimeCapability"] == "unverified"
            for item in cpp_modules
        ))

    def test_v3_routes_grilling_and_deep_grill_me_by_strength(self):
        catalog = compile_catalog().document["catalog"]
        pipeline = load_pipeline().document
        design = next(
            item for item in catalog["modules"] if item["id"] == "design-grilling"
        )
        slot = next(
            slot
            for stage in pipeline["stages"] if stage["id"] == "designed"
            for slot in stage["slots"] if slot["id"] == "design.precheck"
        )

        self.assertEqual(
            design["invocation"],
            {"kind": "skill", "ref": "matt-pocock:grilling"},
        )
        self.assertEqual(slot["allowedInvocationKinds"], ["skill"])
        self.assertEqual(slot["cardinality"], "exactly-one")
        self.assertEqual(slot["selectionMode"], "static")
        self.assertIn("any", slot["condition"])

        deep_slot = next(
            slot
            for stage in pipeline["stages"] if stage["id"] == "designed"
            for slot in stage["slots"] if slot["id"] == "design.deep-grill"
        )
        deep = next(
            item for item in catalog["modules"] if item["id"] == "design-grill-me"
        )
        self.assertEqual(deep["slot"], "design.deep-grill")
        self.assertEqual(deep_slot["cardinality"], "exactly-one")
        self.assertEqual(deep_slot["selectionMode"], "static")
        self.assertIn("all", deep_slot["condition"])
        self.assertIn("any", deep_slot["condition"]["all"][0])
        self.assertIn("any", deep_slot["condition"]["all"][1])

        def condition(slot_id, **values):
            slot = next(
                slot
                for stage in pipeline["stages"] if stage["id"] == "designed"
                for slot in stage["slots"] if slot["id"] == slot_id
            )
            return _condition_matches(slot.get("condition"), values)

        self.assertTrue(condition(
            "design.precheck", writeTask=True, complexity="C2", risk="R2",
            projectMinimums={"strength": "Full"}, explicitModuleIds=[],
        ))
        self.assertFalse(condition(
            "design.deep-grill", operationType="design", writeTask=True,
            complexity="C2", risk="R2",
            projectMinimums={"strength": "Full"}, explicitModuleIds=[],
        ))
        self.assertFalse(condition(
            "design.precheck", writeTask=True, complexity="C3", risk="R3",
            projectMinimums={"strength": "Deep"}, explicitModuleIds=[],
        ))
        self.assertTrue(condition(
            "design.deep-grill", operationType="design", writeTask=False,
            complexity="C3", risk="R3",
            projectMinimums={"strength": "Deep"}, explicitModuleIds=[],
        ))
        self.assertFalse(condition(
            "design.precheck", writeTask=True, complexity="C1", risk="R1",
            projectMinimums={"strength": "Light"}, explicitModuleIds=[],
        ))
        self.assertFalse(condition(
            "design.deep-grill", operationType="analyze", writeTask=False,
            complexity="C1", risk="R1",
            projectMinimums={"strength": "Light"}, explicitModuleIds=[],
        ))


if __name__ == "__main__":
    unittest.main()
