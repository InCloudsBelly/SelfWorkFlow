"""Consumer tests for the explicitly selected workflow extensions."""
import copy
import tempfile
import unittest
from pathlib import Path

from selfworkflow.adapters import build_runtime
from selfworkflow.v3.tea_adapter import (
    TeaAdapterError, eligible_workflows, build_packaged_invocation,
    validate_packaged_output, load_jit_artifact,
)

ROOT = Path(__file__).resolve().parents[2]


class OptionalTeaTests(unittest.TestCase):
    def test_assessments_are_explicit_and_stage_bounded(self):
        self.assertEqual(eligible_workflows(stage="plan", test_level="T1"), ())
        self.assertEqual(eligible_workflows(stage="plan", test_level="T1", framework_assessment=True), ("framework",))
        for stage in ("verify", "release"):
            self.assertEqual(eligible_workflows(stage=stage, test_level="T1", ci_validation=True), ("ci",))
        for kwargs in ({"stage": "review", "framework_assessment": True}, {"stage": "plan", "ci_validation": True}, {"stage": "plan", "framework_assessment": "yes"}):
            with self.assertRaises(TeaAdapterError):
                eligible_workflows(test_level="T2", **kwargs)

    def test_jit_cannot_enter_upstream_scaffolding(self):
        for workflow in ("framework", "ci"):
            skill = load_jit_artifact(ROOT, workflow_id=workflow, kind="skill", relative_path="SKILL.md")
            self.assertIn("assessment-only", skill["content"])
            with self.assertRaises(TeaAdapterError):
                load_jit_artifact(ROOT, workflow_id=workflow, kind="step", relative_path="steps-c/step-01-preflight.md")

    def test_packaged_assessments_bind_inputs_and_outputs_without_project_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runtime = root / "runtime"
            build_runtime(ROOT, runtime, "optional-test")
            self.assertTrue((runtime / "skills/implement-spec/SKILL.md").is_file())
            self.assertTrue((runtime / "skills/matt-pocock/implement-spec/SKILL.md").is_file())
            debt = (runtime / "skills/ponytail-debt/SKILL.md").read_text(encoding="utf-8")
            self.assertIn("one-shot", debt)
            self.assertFalse((runtime / "skills/ponytail-gain").exists())
            project = root / "project"
            project.mkdir()
            sentinel = project / "pyproject.toml"
            sentinel.write_text("[project]\nname='existing'\n", encoding="utf-8")
            contexts = {
                "framework": {"projectManifest": "pyproject.toml: existing", "testInventory": "unittest discovery", "projectRules": "preserve existing framework", "acceptanceCriteria": "map commands and gaps"},
                "ci": {"pipelineFiles": "test.yml: run unittest", "verificationPlan": "unittest discovery", "projectRules": "read only", "runEvidence": "not supplied; unverified"},
            }
            for workflow, context in contexts.items():
                before = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
                invocation = build_packaged_invocation(runtime, workflow, context, f"reports/{workflow}.md")
                for invalid_path in (f"../{workflow}.md", f"/outside/{workflow}.md", "reports/incorrect.md"):
                    with self.assertRaises(TeaAdapterError):
                        build_packaged_invocation(runtime, workflow, context, invalid_path)
                incomplete = dict(context)
                incomplete.pop(next(iter(context)))
                with self.assertRaises(TeaAdapterError):
                    build_packaged_invocation(runtime, workflow, incomplete, f"reports/{workflow}.md")
                self.assertEqual(before, {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()})
                reference = runtime / "skills/tea-quality/references" / f"bmad-testarch-{workflow}"
                self.assertTrue((reference / "checklist.md").is_file())
                self.assertFalse((reference / "steps-c").exists())
                headings = ("Framework", "Conventions", "Commands", "Gaps") if workflow == "framework" else ("Pipeline", "Quality Gates", "Artifacts", "Run Evidence", "Gaps")
                output = project / invocation["outputRelative"]
                output.parent.mkdir(exist_ok=True)
                output.write_text("Missing required evidence sections", encoding="utf-8")
                with self.assertRaises(TeaAdapterError):
                    validate_packaged_output(runtime, project, invocation)
                output.write_text("\n".join(f"## {h}\nObserved input; unresolved findings are unverified." for h in headings), encoding="utf-8")
                binding = {"planHash": "sha256:" + "a" * 64, "attemptRef": "attempt-1", "stageId": "planned" if workflow == "framework" else "verified", "slotId": "plan.assessment" if workflow == "framework" else "verify.ci", "moduleId": f"tea-{workflow}"}
                receipt = validate_packaged_output(runtime, project, invocation, binding=binding)
                self.assertEqual(receipt["workflowId"], workflow)
                wrong = {**binding, "stageId": "implemented"}
                with self.assertRaises(TeaAdapterError):
                    validate_packaged_output(runtime, project, invocation, binding=wrong)
                stale = copy.deepcopy(invocation)
                stale["context"][next(iter(context))] = "changed"
                with self.assertRaises(TeaAdapterError):
                    validate_packaged_output(runtime, project, stale)
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "[project]\nname='existing'\n")
            self.assertFalse((runtime / "skills/tea-quality/references/bmad-teach-me-testing").exists())


if __name__ == "__main__":
    unittest.main()
