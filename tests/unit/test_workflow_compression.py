import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from selfworkflow.catalog import compile_catalog
from selfworkflow.adapters import AdapterError, build_runtime
from selfworkflow.resolver import resolve_task
from selfworkflow.router import ModuleRouteRequest, route_modules


ROOT = Path(__file__).resolve().parents[2]


class WorkflowCompressionTests(unittest.TestCase):
    # Default prose has no fixed mode, role, tool-name or character-count contract.
    # Keep executable routing, fail-closed packaging and explicit runtime checks here.
    MODES = (
        "workflow/modes/light.md",
        "workflow/modes/full.md",
        "workflow/modes/deep.md",
    )
    MODULES = (
        "workflow/modules/build-unreal.md",
        "workflow/modules/code.md",
        "workflow/modules/codegraph-read.md",
        "workflow/modules/codegraph-update.md",
        "workflow/modules/review.md",
        "workflow/modules/knowledge.md",
        "workflow/modules/artifacts.md",
    )


    def test_cli_query_includes_the_read_boundary_check(self):
        text = (ROOT / "workflow/modules/codegraph-read.md").read_text(encoding="utf-8")
        query = next(line for line in text.splitlines() if "`provider query --provider-id codegraph " in line)
        for boundary in ("每次", "核验后查询", "无需另跑 preflight"):
            self.assertIn(boundary, query)
        self.assertIn("确认 fresh 后仍须实际查询", text)
        code = (ROOT / "workflow/modules/code.md").read_text(encoding="utf-8")
        self.assertNotIn("`provider preflight`", code)


    def test_build_cache_rules_are_loaded_at_the_build_boundary(self):
        bootstrap = (ROOT / "WORKFLOW.md").read_text(encoding="utf-8")
        build = (ROOT / "workflow/modules/build.md").read_text(encoding="utf-8")
        unreal = (ROOT / "workflow/modules/build-unreal.md").read_text(encoding="utf-8")
        self.assertIn("workflow/modules/build.md", bootstrap)
        self.assertNotIn("build-unreal.md", bootstrap)
        self.assertIn("(build-unreal.md)", build)
        for boundary in ("Clean/Rebuild", "隔离输出", "取得用户确认"):
            self.assertIn(boundary, build)
        for boundary in ("-NoLiveCoding", "共享 Intermediate/PCH", "WITH_LIVE_CODING"):
            self.assertNotIn(boundary, build)
            self.assertIn(boundary, unreal)
        self.assertNotIn("Clean/Rebuild", bootstrap)


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
