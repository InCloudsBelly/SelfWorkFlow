"""The mathematical method must reach a clone-only document consumer."""

from pathlib import Path
import tempfile
import unittest

import yaml

from selfworkflow.documents import publish_documents


ROOT = Path(__file__).resolve().parents[2]


class SympySkillIntegrationTests(unittest.TestCase):
    def test_public_documents_ship_the_selected_math_method(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            result = publish_documents(ROOT, Path(folder) / "public")
            release = Path(result["documentRoot"])
            method = release / "methods/sympy/METHOD.md"
            self.assertTrue(method.is_file(), "math routing must reach a bundled method")
            source = release / "references/community-skills/scientific-agent-skills"
            self.assertTrue((source / "skills/sympy/METHOD.md").is_file())
            self.assertTrue((source / "LICENSE.md").is_file())
            lock = yaml.safe_load(
                (ROOT / "dependencies/locks/scientific-agent-skills.lock.yaml").read_text(encoding="utf-8")
            )
            for relative in lock["files"]:
                destination = relative.removesuffix("SKILL.md") + "METHOD.md" if relative.endswith("SKILL.md") else relative
                self.assertTrue((source / destination).is_file(), relative)
            self.assertIn("sympy", (release / "methods/INDEX.md").read_text(encoding="utf-8"))
            self.assertFalse((release / "dependencies/upstream").exists())
            self.assertEqual(
                sorted(p.parent.name for p in (source / "skills").glob("*/METHOD.md")),
                ["sympy"],
            )


if __name__ == "__main__":
    unittest.main()
