from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from jsonschema import Draft202012Validator
import yaml

from selfworkflow.adapters import build_runtime
from selfworkflow.v3.catalog import compile_catalog
from selfworkflow.v3.pipeline import load_pipeline
from selfworkflow.v3.plan_graph import PlanGraphError, build_plan_graph
from selfworkflow.v3.tea_adapter import (
    TeaAdapterError,
    build_packaged_invocation,
    validate_packaged_output,
)


class TestingReviewHardeningTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    UNVERIFIED_CORE = [
        "capability-check", "classify-task", "discover-context",
        "implement-matt", "plan-core",
    ]

    @staticmethod
    def _request(operation: str, archetype: str, strength: str, test_level: str) -> dict[str, object]:
        evidence = []
        for name in (
            "filesystem-read", "filesystem-write", "skill-discovery",
            "test-execution", "independent-context", "user-confirmation",
        ):
            evidence.append({
                "name": name, "provider": "test-host",
                "subject": {"kind": "host", "id": "fixture", "version": "1", "build": "1", "sourceLock": "sha256:" + "1" * 64},
                "state": "supported", "observedAt": "2026-08-14T00:00:00Z",
                "validUntil": "2099-01-01T00:00:00Z",
                "evidenceRef": "fixture", "evidenceHash": "sha256:" + "2" * 64,
            })
        explicit_modules = list(TestingReviewHardeningTests.UNVERIFIED_CORE)
        if operation != "implement":
            explicit_modules.remove("implement-matt")
        project_defaults = []
        return {
            "schemaVersion": 3, "operationType": operation,
            "complexity": "C2" if strength != "Light" else "C1",
            "risk": "R2" if strength != "Light" else "R1",
            "writeTask": operation in {"implement", "debug", "document", "install", "publish", "knowledge-write"},
            "ambiguity": False, "explicitModuleIds": explicit_modules,
            "projectDefaultModuleIds": project_defaults,
            "projectMinimums": {"strength": strength},
            "capabilityEvidenceSnapshot": {"schemaVersion": 1, "capturedAt": "2026-08-14T00:00:00Z", "evidence": evidence},
            "taskArchetype": archetype, "requirementsMaturity": "approved",
            "scopeShape": "single-module", "durableSpec": strength != "Light",
            "classificationConfidence": 1.0,
            "classificationEvidence": [{"evidenceRef": "fixture", "evidenceHash": "sha256:" + "3" * 64, "classifierVersion": "1", "classifierHash": "sha256:" + "4" * 64}],
            "testLevelFloor": test_level,
        }

    @staticmethod
    def _execution_policy(catalog, request: dict[str, object]) -> dict[str, object]:
        return {
            "allowUnverifiedModuleIds": [
                *request["explicitModuleIds"],
                *request["projectDefaultModuleIds"],
            ]
        }

    def test_runtime_contains_bounded_tea_adapter_and_all_seven_workflows(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime"
            build_runtime(self.ROOT, runtime, "test", profile="core")
            self.assertEqual(
                (runtime / "WORKFLOW.md").read_bytes(),
                (self.ROOT / "WORKFLOW.md").read_bytes(),
            )
            skill = runtime / "skills/tea-quality/SKILL.md"
            self.assertTrue(skill.is_file())
            references = runtime / "skills/tea-quality/references"
            expected = {
                "bmad-testarch-test-design", "bmad-testarch-atdd",
                "bmad-testarch-test-review", "bmad-testarch-trace",
                "bmad-testarch-nfr", "bmad-testarch-framework",
                "bmad-testarch-ci",
                "bmod-tea",
                "bmod-tea",
            }
            self.assertEqual(
                {path.name for path in references.iterdir() if path.is_dir()},
                expected,
            )
            self.assertTrue((references / "LICENSE").is_file())
            self.assertFalse((runtime / "dependencies/upstream/tea").exists())
            for module_name in ("tea-test-design", "tea-atdd", "tea-test-review", "tea-trace", "tea-nfr", "tea-framework", "tea-ci"):
                module = yaml.safe_load((runtime / f"catalog/v3/modules/{module_name}.yaml").read_text(encoding="utf-8"))
                self.assertEqual(module["invocation"]["ref"], "selfworkflow:tea-quality")
                self.assertTrue(all(value == "supported" for value in module["supportEvidence"].values()))

            project = Path(directory) / "project"
            project.mkdir()
            cases = {
                "test-design": ({"requirements":"r","acceptanceCriteria":"a","design":"d","risk":"r"}, "test-design.md", ["Scope","Risks","Coverage","Cases"]),
                "atdd": ({"requirements":"r","acceptanceCriteria":"a","implementationPlan":"p","testDesign":"t"}, "atdd.md", ["Red Evidence","Acceptance Tests","Fixtures"]),
                "test-review": ({"acceptanceCriteria":"a","implementationDelta":"d","testDesign":"t","verificationEvidence":"v"}, "test-review.md", ["Coverage Review","Failure Paths","Findings"]),
                "trace": ({"acceptanceCriteria":"a","testInventory":"t","verificationEvidence":"v"}, "trace.md", ["Trace Matrix","Gaps"]),
                "nfr": ({"design":"d","nfrRequirements":"n","verificationEvidence":"v"}, "nfr.md", ["Performance","Security","Reliability"]),
                "framework": ({"projectManifest":"manifest","testInventory":"tests","projectRules":"rules","acceptanceCriteria":"criteria"}, "framework.md", ["Framework","Conventions","Commands","Gaps"]),
                "ci": ({"pipelineFiles":"pipeline","verificationPlan":"plan","projectRules":"rules","runEvidence":"evidence"}, "ci.md", ["Pipeline","Quality Gates","Artifacts","Run Evidence","Gaps"]),
            }
            for workflow_id, (context, filename, headings) in cases.items():
                invocation = build_packaged_invocation(runtime, workflow_id, context, filename)
                (project / filename).write_text("\n".join(f"# {heading}" for heading in headings), encoding="utf-8")
                receipt = validate_packaged_output(runtime, project, invocation)
                self.assertEqual(receipt["status"], "validated")

                unresolved_context = dict(context)
                for placeholder in ("{project-root}", "{id}"):
                    unresolved_context[next(iter(unresolved_context))] = placeholder
                    with self.assertRaisesRegex(TeaAdapterError, "tea-runtime-context-invalid"):
                        build_packaged_invocation(runtime, workflow_id, unresolved_context, filename)

                (project / filename).write_text(
                    "\n".join([*(f"# {heading}" for heading in headings), "{project-root}"]),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(TeaAdapterError, "tea-runtime-output-invalid"):
                    validate_packaged_output(runtime, project, invocation)

            outside = Path(directory) / "outside"
            outside.mkdir()
            (outside / "test-design.md").write_text(
                "# Scope\n# Risks\n# Coverage\n# Cases\n", encoding="utf-8",
            )
            linked = project / "linked"
            if os.name == "nt":
                created = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(linked), str(outside)],
                    check=False, capture_output=True,
                )
                self.assertEqual(created.returncode, 0, created.stderr.decode(errors="replace"))
            else:
                linked.symlink_to(outside, target_is_directory=True)
            invocation = build_packaged_invocation(
                runtime, "test-design", cases["test-design"][0], "linked/test-design.md",
            )
            with self.assertRaisesRegex(TeaAdapterError, "tea-runtime-output-invalid"):
                validate_packaged_output(runtime, project, invocation)

    def test_v2_routes_tdd_tea_and_concrete_quality_skills(self):
        modules = yaml.safe_load((self.ROOT / "catalog/modules.yaml").read_text(encoding="utf-8"))["modules"]
        by_id = {module["id"]: module for module in modules}
        self.assertEqual(by_id["design-core"]["activation"], "default")
        self.assertEqual(by_id["design-grilling"]["activation"], "explicit")
        self.assertEqual(by_id["design-grill-me"]["activation"], "explicit")
        self.assertEqual(by_id["implement-tdd"]["slot"], "implement.tdd")
        self.assertEqual(set(by_id["implement-tdd"]["when"]["operationTypes"]), {"implement", "debug"})
        for module_id in ("tea-test-design", "tea-test-review"):
            self.assertEqual(by_id[module_id]["invocation"]["ref"], "selfworkflow:tea-quality")
            self.assertEqual(by_id[module_id]["activation"], "explicit")
        for module_id in ("plan-integrated-review", "review-self", "verify-execution", "complete-gate"):
            self.assertEqual(by_id[module_id]["invocation"]["ref"], "selfworkflow:testing-review-quality")
        pipeline = yaml.safe_load((self.ROOT / "workflow/pipeline.yaml").read_text(encoding="utf-8"))
        review_slot = next(
            slot
            for stage in pipeline["stages"] if stage["id"] == "reviewed"
            for slot in stage["slots"] if slot["id"] == "review.independent"
        )
        self.assertIn(
            {"gte": ["projectMinimums", "Full"]},
            review_slot["condition"]["all"][1]["any"],
        )

    def test_strength_has_fail_closed_test_floor(self):
        schema = json.loads((self.ROOT / "schemas/v3/resolve-request.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        self.assertFalse(list(validator.iter_errors(self._request("implement", "bounded-feature", "Full", "T2"))))
        self.assertFalse(list(validator.iter_errors(self._request("implement", "bounded-feature", "Deep", "T3"))))
        self.assertFalse(list(validator.iter_errors(self._request("review", "bounded-feature", "Full", "T2"))))
        self.assertTrue(list(validator.iter_errors(self._request("implement", "bounded-feature", "Full", "T1"))))
        self.assertTrue(list(validator.iter_errors(self._request("implement", "bounded-feature", "Deep", "T2"))))
        complexity_full = self._request("implement", "bounded-feature", "Light", "T1")
        complexity_full["complexity"] = "C2"
        self.assertTrue(list(validator.iter_errors(complexity_full)))
        risk_full = self._request("implement", "bounded-feature", "Light", "T1")
        risk_full["risk"] = "R2"
        self.assertTrue(list(validator.iter_errors(risk_full)))
        complexity_deep = self._request("implement", "bounded-feature", "Light", "T2")
        complexity_deep["complexity"] = "C3"
        self.assertTrue(list(validator.iter_errors(complexity_deep)))

    def test_behavior_signal_requires_tdd_and_conflicting_classification_pauses(self):
        catalog = compile_catalog()
        pipeline = load_pipeline(self.ROOT / "workflow/v3/pipeline.yaml")
        for operation, archetype in (
            ("implement", "mechanical-change"),
            ("debug", "bugfix"),
            ("install", "migration"),
        ):
            with self.subTest(operation=operation, archetype=archetype):
                request = self._request(operation, archetype, "Full", "T2")
                policy = self._execution_policy(catalog, request)
                if operation == "install":
                    with self.assertRaisesRegex(PlanGraphError, "contract-schema-invalid"):
                        build_plan_graph(request, catalog, pipeline, execution_policy_snapshot=policy)
                    continue
                graph = build_plan_graph(request, catalog, pipeline, execution_policy_snapshot=policy)
                implemented = next(stage for stage in graph.document["stages"] if stage["stageId"] == "implemented")
                tdd = next(slot for slot in implemented["slots"] if slot["slotId"] == "implement.tdd")
                self.assertEqual(tdd["selectedModules"], ["implement-tdd"])

        non_behavior = self._request("document", "spec-document", "Light", "T1")
        graph = build_plan_graph(
            non_behavior,
            catalog,
            pipeline,
            execution_policy_snapshot=self._execution_policy(catalog, non_behavior),
        )
        implemented = next(stage for stage in graph.document["stages"] if stage["stageId"] == "implemented")
        tdd = next(slot for slot in implemented["slots"] if slot["slotId"] == "implement.tdd")
        self.assertEqual(tdd["applicability"], "not-applicable")
        orchestrator = next(
            slot for slot in implemented["slots"] if slot["slotId"] == "implement.orchestrator"
        )
        self.assertEqual(orchestrator["applicability"], "not-applicable")

        read_only_review = self._request("review", "bounded-feature", "Full", "T2")
        graph = build_plan_graph(
            read_only_review,
            catalog,
            pipeline,
            execution_policy_snapshot=self._execution_policy(catalog, read_only_review),
        )
        reviewed = next(stage for stage in graph.document["stages"] if stage["stageId"] == "reviewed")
        for slot_id in ("review.self", "review.independent", "test.quality.review"):
            slot = next(slot for slot in reviewed["slots"] if slot["slotId"] == slot_id)
            self.assertEqual(slot["applicability"], "not-applicable")
        implemented = next(stage for stage in graph.document["stages"] if stage["stageId"] == "implemented")
        tdd = next(slot for slot in implemented["slots"] if slot["slotId"] == "implement.tdd")
        self.assertEqual(tdd["applicability"], "not-applicable")

    def test_full_pipeline_keeps_core_gates_without_automatic_tea(self):
        catalog = compile_catalog()
        pipeline = load_pipeline(self.ROOT / "workflow/v3/pipeline.yaml")
        request = self._request("implement", "bounded-feature", "Full", "T2")
        graph = build_plan_graph(
            request,
            catalog,
            pipeline,
            execution_policy_snapshot=self._execution_policy(catalog, request),
        )
        selected = {
            slot["slotId"]: slot["selectedModules"]
            for stage in graph.document["stages"] for slot in stage["slots"]
        }
        self.assertEqual(selected["test.quality.plan"], [])
        self.assertEqual(selected["test.quality.review"], [])
        self.assertEqual(selected["review.independent"], ["review-code-review"])
        self.assertEqual(selected["verify.execution"], ["verify-execution"])
        self.assertEqual(selected["complete.gate"], ["complete-gate"])

    def test_active_policies_have_no_superpowers_or_brainstorming_stage(self):
        core = (self.ROOT / "WORKFLOW.md").read_text(encoding="utf-8")
        self.assertNotIn("修改任务默认使用 Matt Pocock `grilling`", core)
        policy = yaml.safe_load((self.ROOT / "workflow/v3/post-grill-review.yaml").read_text(encoding="utf-8"))
        self.assertEqual(policy["dispatch"]["reviewMode"], "independent-design-review")
        schema = (self.ROOT / "schemas/v3/post-grill-review-policy.schema.json").read_text(encoding="utf-8")
        self.assertNotIn("brainstorming-cross-review", schema)
        active_contracts = "\n".join(
            (self.ROOT / relative).read_text(encoding="utf-8")
            for relative in (
                "workflow/protected-rules.yaml",
                "schemas/protected-rules.schema.json",
                "src/selfworkflow/evidence.py",
            )
        )
        self.assertNotIn(
            "require-independent-post-grill-brainstorming-review",
            active_contracts,
        )
        self.assertIn("require-independent-post-grill-review", active_contracts)

    def test_verify_complete_and_review_modules_use_concrete_skills(self):
        expected = {
            "plan-integrated-review": "selfworkflow:testing-review-quality",
            "review-self": "selfworkflow:testing-review-quality",
            "verify-execution": "selfworkflow:testing-review-quality",
            "complete-gate": "selfworkflow:testing-review-quality",
            "review-code-review": "selfworkflow:testing-review-quality",
        }
        for module_id, ref in expected.items():
            module = yaml.safe_load((self.ROOT / f"catalog/v3/modules/{module_id}.yaml").read_text(encoding="utf-8"))
            self.assertEqual(module["invocation"], {"kind": "skill", "ref": ref})
            self.assertTrue(all(value == "supported" for value in module["supportEvidence"].values()))


if __name__ == "__main__":
    unittest.main()
