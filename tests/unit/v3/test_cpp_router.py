from dataclasses import FrozenInstanceError
from copy import deepcopy
from pathlib import Path
import unittest



def _v3_request():
    return {
        "schemaVersion": 3,
        "operationType": "implement",
        "complexity": "C1",
        "risk": "R1",
        "writeTask": True,
        "ambiguity": False,
        "explicitModuleIds": [],
        "projectDefaultModuleIds": [],
        "projectMinimums": {"strength": "Light"},
        "capabilityEvidenceSnapshot": {
            "schemaVersion": 1,
            "capturedAt": "2026-08-09T00:00:00Z",
            "evidence": [],
        },
        "taskArchetype": "bounded-feature",
        "requirementsMaturity": "defined",
        "scopeShape": "single-module",
        "durableSpec": True,
        "classificationConfidence": 0.9,
        "classificationEvidence": [{
            "evidenceRef": "classification-1",
            "evidenceHash": "sha256:" + "d" * 64,
            "classifierVersion": "classifier-v1",
            "classifierHash": "sha256:" + "e" * 64,
        }],
        "testLevelFloor": "T1",
    }


class CppRouterTests(unittest.TestCase):
    def _route(self, **overrides):
        from selfworkflow.v3.cpp_router import CppRouteRequest, route_cpp_capabilities

        values = {
            "operation_type": "implement",
            "languages": ("cpp",),
            "file_extensions": (".cpp", ".h"),
            "task_signals": (),
            "risk": "R1",
            "explicit_module_ids": (),
            "user_confirmed_heavy": False,
            "project_allows_execution": False,
        }
        values.update(overrides)
        return route_cpp_capabilities(CppRouteRequest(**values))

    def test_non_code_task_does_not_load_cpp_core(self):
        route = self._route(
            operation_type="document",
            languages=("markdown",),
            file_extensions=(".md",),
        )

        self.assertEqual(route.selected_module_ids, ())
        self.assertEqual(route.capability_ids, ())
        self.assertEqual(route.context_cost, 0)

    def test_cpp_implementation_loads_only_core_by_default(self):
        route = self._route()

        self.assertEqual(route.selected_module_ids, ("cpp-core",))
        self.assertEqual(route.capability_ids, ("cpp.reasoning",))
        self.assertNotIn("cpp.audit", route.capability_ids)
        self.assertNotIn("debug.execute", route.capability_ids)

    def test_concurrency_and_abi_signals_compose_in_stable_order(self):
        route = self._route(
            task_signals=("atomics", "memory-order", "binary-compatibility"),
        )

        self.assertEqual(
            route.selected_module_ids,
            ("cpp-core", "cpp.concurrency", "cpp.abi"),
        )
        self.assertEqual(
            route.capability_ids,
            ("cpp.reasoning", "cpp.concurrency", "cpp.abi"),
        )

    def test_unreal_signal_adds_unreal_lens_without_claiming_native_build(self):
        route = self._route(task_signals=("unreal-engine", "uobject", "uht"))

        self.assertIn("cpp.engine.unreal", route.selected_module_ids)
        self.assertIn("native-build-unverified", route.unverified_items)
        self.assertNotIn("cpp.verify", route.capability_ids)

    def test_native_debug_selects_reasoning_not_runtime_debugger(self):
        route = self._route(
            operation_type="debug",
            task_signals=("native-crash", "stack-trace"),
            project_allows_execution=True,
        )

        self.assertEqual(
            route.selected_module_ids,
            ("cpp-core", "cpp.debugging"),
        )
        self.assertIn("debug.reason", route.capability_ids)
        self.assertNotIn("debug.execute", route.capability_ids)
        self.assertIn("runtime-debugger-not-authorized", route.unverified_items)

    def test_heavy_audit_is_recommended_but_not_selected_without_confirmation(self):
        route = self._route(
            operation_type="review",
            risk="R3",
            task_signals=("memory-corruption", "security-critical"),
        )

        self.assertIn("cpp.audit", route.recommended_capability_ids)
        self.assertNotIn("cpp.audit", route.capability_ids)
        self.assertIn("heavy-audit-user-confirmation-required", route.unverified_items)

    def test_confirmed_heavy_audit_stays_unverified_without_provider(self):
        route = self._route(
            operation_type="review",
            risk="R3",
            task_signals=("memory-corruption", "security-critical"),
            user_confirmed_heavy=True,
        )

        self.assertNotIn("cpp.audit", route.capability_ids)
        self.assertNotIn("cpp.audit", route.selected_module_ids)
        self.assertIn("heavy-audit-provider-unverified", route.unverified_items)
        self.assertNotIn("debug.execute", route.capability_ids)

    def test_explicit_specialist_requires_cpp_task_and_rejects_duplicates(self):
        from selfworkflow.v3.cpp_router import CppRouteError

        with self.assertRaisesRegex(CppRouteError, "cpp-route-explicit-module-not-applicable"):
            self._route(
                operation_type="document",
                languages=("markdown",),
                file_extensions=(".md",),
                explicit_module_ids=("cpp.performance",),
            )
        with self.assertRaisesRegex(CppRouteError, "cpp-route-explicit-module-duplicate"):
            self._route(explicit_module_ids=("cpp.abi", "cpp.abi"))

    def test_context_trace_accounts_only_for_loaded_modules(self):
        route = self._route(task_signals=("lock", "deadlock"))

        self.assertEqual(
            tuple(item["moduleId"] for item in route.module_load_trace),
            route.selected_module_ids,
        )
        self.assertEqual(
            route.context_cost,
            sum(item["estimatedContextCost"] for item in route.module_load_trace),
        )
        self.assertTrue(all(item["reason"] for item in route.module_load_trace))

    def test_route_is_deterministic_immutable_and_rejects_untyped_requests(self):
        from selfworkflow.v3.cpp_router import (
            CppRouteError,
            CppRouteRequest,
            route_cpp_capabilities,
        )

        first = self._route(task_signals=("binary-compatibility", "atomics"))
        second = self._route(task_signals=("atomics", "binary-compatibility"))
        self.assertEqual(first.route_hash, second.route_hash)
        with self.assertRaises(FrozenInstanceError):
            first.context_cost = 0
        with self.assertRaises(TypeError):
            first.module_load_trace[0]["reason"] = "forged"
        with self.assertRaisesRegex(CppRouteError, "cpp-route-request-not-typed"):
            route_cpp_capabilities({"operation_type": "implement"})

        class RequestSubclass(CppRouteRequest):
            pass

        with self.assertRaisesRegex(CppRouteError, "cpp-route-request-not-typed"):
            route_cpp_capabilities(RequestSubclass(
                operation_type="implement",
                languages=("cpp",),
                file_extensions=(".cpp",),
                task_signals=(),
                risk="R1",
                explicit_module_ids=(),
                user_confirmed_heavy=False,
                project_allows_execution=False,
            ))

    def test_resolve_contract_rejects_unknown_and_duplicate_code_signals(self):
        from selfworkflow.v3.contracts import ContractError, load_contract
        import json

        request = _v3_request()
        request["codeSignals"] = {
            "languages": ["cpp"],
            "fileExtensions": [".cpp"],
            "taskSignals": ["ownership"],
            "explicitCppModuleIds": [],
            "userConfirmedHeavy": False,
            "projectAllowsExecution": False,
            "unknown": True,
        }
        with self.assertRaisesRegex(ContractError, "contract-schema-invalid"):
            load_contract("resolve-request.schema.json", json.dumps(request))

        del request["codeSignals"]["unknown"]
        request["codeSignals"]["languages"] = ["cpp", "cpp"]
        with self.assertRaisesRegex(ContractError, "contract-schema-invalid"):
            load_contract("resolve-request.schema.json", json.dumps(request))

    def test_v3_resolve_emits_hash_bound_route_only_when_code_signals_exist(self):
        from selfworkflow.v3.contracts import ContractError, validate_resolve_result
        from selfworkflow.v3.resolver import resolve_request

        legacy = _v3_request()
        legacy_result = resolve_request(legacy)
        self.assertNotIn("capabilityRoute", legacy_result)

        request = deepcopy(legacy)
        request["codeSignals"] = {
            "languages": ["cpp"],
            "fileExtensions": [".cpp", ".h"],
            "taskSignals": ["ownership", "unreal-engine"],
            "explicitCppModuleIds": [],
            "userConfirmedHeavy": False,
            "projectAllowsExecution": False,
        }
        result = resolve_request(request)
        route = result["capabilityRoute"]
        self.assertEqual(
            route["selectedModuleIds"],
            ["cpp-core", "cpp.ownership", "cpp.engine.unreal"],
        )
        self.assertIn("native-build-unverified", route["unverifiedItems"])
        from selfworkflow.v3.catalog import compile_catalog
        catalog_ids = {
            item["id"] for item in compile_catalog().document["catalog"]["modules"]
        }
        self.assertTrue(set(route["selectedModuleIds"]) <= catalog_ids)
        validate_resolve_result(result)

        tampered = deepcopy(result)
        tampered["capabilityRoute"]["contextCost"] += 1
        with self.assertRaisesRegex(ContractError, "capability-route-hash-invalid"):
            validate_resolve_result(tampered)

        execution_forgery = deepcopy(result)
        execution_forgery["capabilityRoute"]["capabilityIds"].append("debug.execute")
        material = deepcopy(execution_forgery["capabilityRoute"])
        material.pop("routeHash")
        import hashlib
        import json
        execution_forgery["capabilityRoute"]["routeHash"] = (
            "sha256:" + hashlib.sha256(
                json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        with self.assertRaisesRegex(ContractError, "capability-route-execution-forbidden"):
            validate_resolve_result(execution_forgery)

    def test_active_plan_contains_every_automatically_routed_cpp_module_as_eligible(self):
        from selfworkflow.v3.catalog import compile_catalog
        from selfworkflow.v3.pipeline import load_pipeline
        from selfworkflow.v3.resolver import resolve_request

        request = _v3_request()
        request["codeSignals"] = {
            "languages": ["cpp"],
            "fileExtensions": [".cpp"],
            "taskSignals": ["concurrency"],
            "explicitCppModuleIds": [],
            "userConfirmedHeavy": False,
            "projectAllowsExecution": False,
        }
        required = {
            "discover-context", "capability-check", "classify-task",
            "design-grilling", "plan-core",
            "implement-matt", "implement-tdd",
            "review-self", "verify-execution", "complete-gate",
        }
        request["explicitModuleIds"] = sorted(required)
        approved = sorted(required | {"cpp-core", "cpp.concurrency"})
        root = Path(__file__).resolve().parents[3]

        result = resolve_request(
            request,
            catalog_source=compile_catalog(root / "catalog/v3/index.yaml"),
            pipeline_source=load_pipeline(root / "workflow/v3/pipeline.yaml"),
            execution_policy_snapshot={"allowUnverifiedModuleIds": approved},
        )

        self.assertEqual(result["status"], "active")
        designed = next(
            stage for stage in result["planGraph"]["stages"]
            if stage["stageId"] == "designed"
        )
        code_slot = next(
            slot for slot in designed["slots"]
            if slot["slotId"] == "code.reasoning"
        )
        self.assertTrue(
            set(result["capabilityRoute"]["selectedModuleIds"])
            <= set(code_slot["eligibleModules"])
        )

    def test_resolved_cpp_plan_constructs_host_with_original_request(self):
        from selfworkflow.v3.catalog import compile_catalog
        from selfworkflow.v3.pipeline import load_pipeline
        from selfworkflow.v3.resolver import resolve_plan

        request = _v3_request()
        request["codeSignals"] = {
            "languages": ["cpp"],
            "fileExtensions": [".cpp"],
            "taskSignals": ["concurrency"],
            "explicitCppModuleIds": [],
            "userConfirmedHeavy": False,
            "projectAllowsExecution": False,
        }
        required = {
            "discover-context", "capability-check", "classify-task",
            "design-grilling", "plan-core",
            "implement-matt", "implement-tdd",
            "review-self", "verify-execution", "complete-gate",
        }
        request["explicitModuleIds"] = sorted(required)
        root = Path(__file__).resolve().parents[3]

        resolved = resolve_plan(
            request,
            catalog_source=compile_catalog(root / "catalog/v3/index.yaml"),
            pipeline_source=load_pipeline(root / "workflow/v3/pipeline.yaml"),
            execution_policy_snapshot={
                "allowUnverifiedModuleIds": sorted(
                    required | {"cpp-core", "cpp.concurrency"}
                )
            },
        )
        host = resolved.create_host()

        self.assertEqual(host.request, request)
        self.assertEqual(
            host.plan["requestHash"],
            resolved.result["planGraph"]["requestHash"],
        )
        self.assertEqual(
            set(resolved.result["capabilityRoute"]["selectedModuleIds"]),
            {"cpp-core", "cpp.concurrency"},
        )


if __name__ == "__main__":
    unittest.main()
