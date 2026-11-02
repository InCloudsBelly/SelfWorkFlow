from pathlib import Path
import re
import tempfile
import unittest

from selfworkflow.adapters import build_runtime
from selfworkflow.documents import document_binding
from selfworkflow.v3.tea_adapter import TeaAdapterError, build_packaged_invocation, load_jit_artifact, validate_packaged_output, validate_packaged_runtime, validate_tea_receipt


class TeaV3LayoutTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[3]

    def test_public_atdd_macro_roots_close_over_the_red_workflow(self):
        release = Path(document_binding(self.ROOT / "public")["documentRoot"])
        method = release / "methods/tea-quality"
        contract = (method / "references/headless-contract.md").read_text(encoding="utf-8")
        roots = set(re.findall(r"`(references/bmad-testarch-[a-z]+(?:-[a-z]+)*)(?:/[^`]+)?`", contract))
        self.assertIn("references/bmad-testarch-atdd", roots)
        for root in roots:
            for fragment in ("METHOD.md", "red/workflow.yaml.md", "red/instructions.md", "red/atdd-checklist-template.md"):
                with self.subTest(root=root, fragment=fragment):
                    self.assertTrue((method / root / fragment).is_file())

    def test_runtime_keeps_one_atdd_entry_and_only_red_steps(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary) / "runtime"
            build_runtime(self.ROOT, runtime, "0.1.0.dev0", profile="core")
            references = runtime / "skills/tea-quality/references"
            selected = references / "bmad-testarch-atdd"
            entry = load_jit_artifact(self.ROOT, workflow_id="atdd", kind="skill", relative_path="SKILL.md")
            self.assertEqual((selected / "SKILL.md").read_text(encoding="utf-8"), entry["content"])
            self.assertTrue((selected / "red/instructions.md").is_file())
            self.assertTrue((selected / "red/atdd-checklist-template.md").is_file())
            self.assertTrue((selected / "red/steps-c/step-01-preflight-and-context.md").is_file())
            self.assertFalse((selected / "steps-c").exists())
            self.assertFalse((references / "atdd-entry.md").exists())
            shared = references / "bmod-tea/contracts/story-identity.md"
            self.assertTrue(shared.is_file())
            before = validate_packaged_runtime(runtime)
            project = Path(temporary) / "project"
            project.mkdir()
            (project / "atdd.md").write_text("# Red Evidence\n# Acceptance Tests\n# Fixtures\n", encoding="utf-8")
            invocation = build_packaged_invocation(runtime, "atdd", {key: "provided" for key in ("requirements", "acceptanceCriteria", "implementationPlan", "testDesign")}, "atdd.md")
            binding = {"planHash": "sha256:" + "a" * 64, "attemptRef": "attempt-1", "stageId": "implemented", "slotId": "test.quality.implementation", "moduleId": "tea-atdd"}
            receipt = validate_packaged_output(runtime, project, invocation, binding=binding)
            shared.write_bytes(shared.read_bytes() + b"\nfixture drift\n")
            after = validate_packaged_runtime(runtime)
            for workflow in ("atdd", "test-review", "trace", "nfr"):
                self.assertNotEqual(before[workflow], after[workflow])
            for workflow in ("test-design", "framework", "ci"):
                self.assertEqual(before[workflow], after[workflow])
            def verify_receipt():
                return validate_tea_receipt(receipt, plan_hash=binding["planHash"], stage_id=binding["stageId"], attempt_ref=binding["attemptRef"], slot_id=binding["slotId"], module_id=binding["moduleId"], output_hash=receipt["outputHash"], runtime_root=runtime)
            with self.assertRaisesRegex(TeaAdapterError, "tea-runtime-reference-stale"):
                verify_receipt()
            shared.unlink()
            with self.assertRaises(TeaAdapterError):
                verify_receipt()

    def test_story_contract_is_available_through_bounded_jit(self):
        for workflow in ("atdd", "test-review", "trace", "nfr"):
            with self.subTest(workflow=workflow):
                result = load_jit_artifact(self.ROOT, workflow_id=workflow, kind="resource", relative_path="contracts/story-identity.md")
                self.assertTrue(result["path"].endswith("bmod-tea/contracts/story-identity.md"))
                self.assertIn("Story identity and intake", result["content"])
        for path in ("contracts", "contracts/other.md", "contracts/../knowledge/tea-index.csv"):
            with self.subTest(path=path), self.assertRaises(TeaAdapterError):
                load_jit_artifact(self.ROOT, workflow_id="atdd", kind="resource", relative_path=path)

    def test_native_source_entries_name_bound_public_fallbacks(self):
        release = Path(document_binding(self.ROOT / "public")["documentRoot"])
        entries = {
            "skills/tea-quality/SKILL.md": "methods/tea-quality/METHOD.md",
            "skills/tea-quality/assessments/ci/SKILL.md": "methods/tea-quality/references/bmad-testarch-ci/METHOD.md",
            "skills/tea-quality/assessments/framework/SKILL.md": "methods/tea-quality/references/bmad-testarch-framework/METHOD.md",
        }
        for source, target in entries.items():
            with self.subTest(source=source):
                text = (self.ROOT / source).read_text(encoding="utf-8")
                self.assertIn("documentRoot", text)
                self.assertIn(target, text)
                self.assertTrue((release / target).is_file())

    def test_existing_atdd_jit_api_selects_only_the_red_workflow(self):
        entry = load_jit_artifact(self.ROOT, workflow_id="atdd", kind="skill", relative_path="SKILL.md")
        self.assertIn("bmad-tea-automate/red", entry["content"])
        workflow = load_jit_artifact(self.ROOT, workflow_id="atdd", kind="workflow", relative_path="workflow.yaml")
        self.assertTrue(workflow["path"].endswith("red/workflow.yaml"))
        self.assertIn("bmad-tea-atdd", workflow["content"])
        step = load_jit_artifact(self.ROOT, workflow_id="atdd", kind="step", relative_path="steps-c/step-01-preflight-and-context.md")
        self.assertTrue(step["path"].endswith("red/steps-c/step-01-preflight-and-context.md"))
        instructions = load_jit_artifact(self.ROOT, workflow_id="atdd", kind="resource", relative_path="red/instructions.md")
        self.assertIn("Acceptance Test-Driven Development", instructions["content"])
        template = load_jit_artifact(self.ROOT, workflow_id="atdd", kind="resource", relative_path="red/atdd-checklist-template.md")
        self.assertTrue(template["path"].endswith("red/atdd-checklist-template.md"))
        self.assertIn("# ATDD Checklist", template["content"])
        for path in ("red/../../LICENSE", "red", "red/steps-c/../../workflow.yaml"):
            with self.subTest(path=path), self.assertRaises(TeaAdapterError):
                load_jit_artifact(self.ROOT, workflow_id="atdd", kind="resource", relative_path=path)
