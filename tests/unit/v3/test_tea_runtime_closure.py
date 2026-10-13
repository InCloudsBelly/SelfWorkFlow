from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from selfworkflow.adapters import AdapterError, build_runtime
from selfworkflow.v3.tea_adapter import (
    TeaAdapterError, build_packaged_invocation, validate_packaged_output,
    validate_tea_receipt,
)


ROOT = Path(__file__).resolve().parents[3]
CONTEXT = {
    "requirements": "Repair bounded adapter closure",
    "acceptanceCriteria": "Reject missing dependencies",
    "design": "Validate before invocation",
    "risk": "Stale evidence must fail closed",
}


class TeaRuntimeClosureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.runtime = Path(self.temporary.name) / "runtime"
        skill = self.runtime / "skills/tea-quality"
        shutil.copytree(ROOT / "skills/tea-quality", skill)
        references = skill / "references"
        references.mkdir(exist_ok=True)
        upstream = ROOT / "dependencies/upstream/tea/skills"
        shutil.copytree(upstream / "bmad-testarch-test-design", references / "bmad-testarch-test-design")
        shutil.copytree(upstream / "bmod-tea/knowledge", references / "bmod-tea/knowledge")
        self.knowledge = self.runtime / "skills/tea-quality/references/bmod-tea/knowledge"

    def invocation(self):
        return build_packaged_invocation(self.runtime, "test-design", CONTEXT, "test-design.md")

    def test_missing_required_knowledge_blocks_invocation(self):
        (self.knowledge / "risk-governance.md").unlink()
        with self.assertRaisesRegex(TeaAdapterError, "tea-runtime-knowledge-invalid"):
            self.invocation()

    def test_knowledge_and_headless_drift_invalidate_existing_output_and_receipt(self):
        project = Path(self.temporary.name) / "project"
        project.mkdir()
        output = project / "test-design.md"
        output.write_text("# Scope\n# Risks\n# Coverage\n# Cases\n", encoding="utf-8")
        binding = {
            "planHash": "sha256:" + "a" * 64, "attemptRef": "attempt-1",
            "stageId": "planned", "slotId": "test.quality.plan", "moduleId": "tea-test-design",
        }
        for path in (
            self.knowledge / "risk-governance.md",
            self.runtime / "skills/tea-quality/SKILL.md",
            self.runtime / "skills/tea-quality/references/headless-contract.md",
        ):
            with self.subTest(path=path):
                invocation = self.invocation()
                receipt = validate_packaged_output(self.runtime, project, invocation, binding=binding)
                original = path.read_bytes()
                path.write_bytes(original + b"\nChanged dependency\n")
                try:
                    with self.assertRaisesRegex(TeaAdapterError, "tea-runtime-invocation-invalid"):
                        validate_packaged_output(self.runtime, project, invocation)
                    with self.assertRaisesRegex(TeaAdapterError, "tea-runtime-reference-stale"):
                        validate_tea_receipt(
                            receipt, plan_hash=binding["planHash"], stage_id="planned",
                            attempt_ref="attempt-1", slot_id="test.quality.plan",
                            module_id="tea-test-design", output_hash=receipt["outputHash"],
                            runtime_root=self.runtime,
                        )
                finally:
                    path.write_bytes(original)
        self.assertFalse((project / "_bmad").exists())
        self.assertEqual([p.name for p in project.iterdir()], ["test-design.md"])

    def test_invalid_index_or_missing_required_row_is_rejected(self):
        index = self.knowledge / "tea-index.csv"
        original = index.read_text(encoding="utf-8")
        invalid_indexes = [
            "id,fragment_file\n",
            "id,wrong_column\nx,risk-governance.md\n",
            "\n".join(line for line in original.splitlines() if "risk-governance.md" not in line),
        ]
        for name in ("../escape.md", "/escape.md", "C:/escape.md", "C:escape.md", "..\\escape.md", "missing.md", "./risk-governance.md", "risk-governance.md"):
            invalid_indexes.append(original + f'bad,bad,bad,bad,core,{name}\n')
        for content in invalid_indexes:
            with self.subTest(index=content[-90:]):
                index.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(TeaAdapterError, "tea-runtime-knowledge-invalid"):
                    self.invocation()
        index.write_text(original, encoding="utf-8")

    def test_assessment_only_does_not_require_unused_knowledge(self):
        reference = self.runtime / "skills/tea-quality/references/bmad-testarch-framework"
        shutil.copytree(ROOT / "skills/tea-quality/assessments/framework", reference)
        self.knowledge.rename(self.knowledge.with_name("unavailable"))
        context = {field: "provided" for field in ("projectManifest", "testInventory", "projectRules", "acceptanceCriteria")}
        result = build_packaged_invocation(self.runtime, "framework", context, "framework.md")
        self.assertEqual(result["workflowId"], "framework")

    def test_each_workflow_rejects_missing_fragment_even_when_index_row_is_removed(self):
        cases = (
            ("atdd", "component-tdd.md", ("requirements", "acceptanceCriteria", "implementationPlan", "testDesign")),
            ("test-review", "data-factories.md", ("acceptanceCriteria", "implementationDelta", "testDesign", "verificationEvidence")),
            ("trace", "selective-testing.md", ("acceptanceCriteria", "testInventory", "verificationEvidence")),
            ("nfr", "error-handling.md", ("design", "nfrRequirements", "verificationEvidence")),
            ("test-design", "contract-testing.md", tuple(CONTEXT)),
        )
        index = self.knowledge / "tea-index.csv"
        original_index = index.read_bytes()
        for workflow, name, fields in cases:
            with self.subTest(workflow=workflow):
                reference = self.runtime / "skills/tea-quality/references" / f"bmad-testarch-{workflow}"
                if not reference.exists():
                    shutil.copytree(ROOT / "dependencies/upstream/tea/skills" / reference.name, reference)
                fragment = self.knowledge / name
                original_fragment = fragment.read_bytes()
                index.write_bytes(b"\n".join(line for line in original_index.splitlines() if name.encode() not in line))
                fragment.unlink()
                try:
                    with self.assertRaisesRegex(TeaAdapterError, "tea-runtime-knowledge-invalid"):
                        build_packaged_invocation(self.runtime, workflow, {field: "provided" for field in fields}, f"{workflow}.md")
                finally:
                    fragment.write_bytes(original_fragment)
                    index.write_bytes(original_index)

    def test_build_does_not_publish_incomplete_knowledge(self):
        import selfworkflow.adapters as adapters

        copy_tree = adapters._copy_tree

        def incomplete_copy(source, destination):
            copy_tree(source, destination)
            if destination.as_posix().endswith("references/bmod-tea/knowledge"):
                (destination / "risk-governance.md").unlink()

        output = Path(self.temporary.name) / "broken-runtime"
        with mock.patch.object(adapters, "_copy_tree", side_effect=incomplete_copy):
            with self.assertRaisesRegex(AdapterError, "tea-runtime-knowledge-invalid"):
                build_runtime(ROOT, output, "test")
        self.assertFalse(output.exists())

    def test_reference_junction_is_rejected(self):
        import os
        import subprocess

        original = self.knowledge
        outside = original.with_name("outside")
        original.rename(outside)
        if os.name == "nt":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(original), str(outside)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            original.symlink_to(outside, target_is_directory=True)
        try:
            with self.assertRaisesRegex(TeaAdapterError, "tea-runtime-knowledge-invalid"):
                self.invocation()
        finally:
            if os.name == "nt":
                original.rmdir()
            else:
                original.unlink()


if __name__ == "__main__":
    unittest.main()
