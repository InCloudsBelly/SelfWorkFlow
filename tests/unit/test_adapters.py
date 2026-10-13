import tempfile
import unittest
from pathlib import Path

from selfworkflow.adapters import AdapterError, _resolve_tea_checklist


class TeaChecklistResolutionTests(unittest.TestCase):
    def test_ci_prefers_legacy_checklist_when_both_layouts_exist(self):
        with tempfile.TemporaryDirectory() as folder:
            upstream = Path(folder)
            legacy = upstream / "skills/bmad-testarch-ci/checklist.md"
            current = upstream / "skills/bmad-testarch-framework/ci/checklist.md"
            legacy.parent.mkdir(parents=True)
            current.parent.mkdir(parents=True)
            legacy.write_text("legacy", encoding="utf-8")
            current.write_text("current", encoding="utf-8")

            self.assertEqual(_resolve_tea_checklist(upstream, "ci"), legacy)

    def test_ci_falls_back_to_framework_checklist(self):
        with tempfile.TemporaryDirectory() as folder:
            upstream = Path(folder)
            current = upstream / "skills/bmad-testarch-framework/ci/checklist.md"
            current.parent.mkdir(parents=True)
            current.write_text("current", encoding="utf-8")

            self.assertEqual(_resolve_tea_checklist(upstream, "ci"), current)

    def test_missing_checklist_paths_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(AdapterError, "tea-source-invalid"):
                _resolve_tea_checklist(Path(folder), "ci")


if __name__ == "__main__":
    unittest.main()
