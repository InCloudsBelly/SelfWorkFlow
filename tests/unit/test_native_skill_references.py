from pathlib import Path
import re
import tempfile
import unittest

from selfworkflow.adapters import build_runtime
from selfworkflow.documents import publish_documents


ROOT = Path(__file__).resolve().parents[2]
COMMUNITY = {
    "sympy": "references/community-skills/scientific-agent-skills/skills/sympy",
    "content-research-writer": "references/community-skills/composio-skills/content-research-writer",
    "obsidian-markdown": "references/community-skills/obsidian-skills/skills/obsidian-markdown",
    "obsidian-bases": "references/community-skills/obsidian-skills/skills/obsidian-bases",
    "json-canvas": "references/community-skills/obsidian-skills/skills/json-canvas",
    "workflow-skill-maintenance": "references/anthropic-skills/skill-creator",
}
MATT = {
    "skills/testing-review-quality/SKILL.md": ("tdd", "METHOD.md", "SKILL.md"),
    "skills/implement-spec/SKILL.md": ("implement-spec", "METHOD.md", "SKILL.md"),
    "workflow/skills/diagnosing-bugs/SKILL.md": ("diagnosing-bugs", "references/upstream/guide.md", "references/upstream/guide.md"),
}


class NativeSkillReferenceTests(unittest.TestCase):
    """Check published instruction paths; this does not execute an Agent."""

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        folder = Path(cls.temporary.name)
        cls.release = Path(publish_documents(ROOT, folder / "public")["documentRoot"])
        cls.runtime = folder / "runtime"
        build_runtime(ROOT, cls.runtime, "native-route-test", profile="core")

    def test_community_entries_name_both_bound_entry_formats(self):
        for name, relative in COMMUNITY.items():
            with self.subTest(entry=name):
                native = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
                public = (self.release / "methods" / name / "METHOD.md").read_text(encoding="utf-8")
                for text in (native, public):
                    self.assertIn(f"`{relative}/`", text)
                    self.assertIn("文档模式 `METHOD.md`", text)
                    self.assertIn("runtime 模式 `SKILL.md`", text)
                self.assertTrue((self.release / relative / "METHOD.md").is_file())
                self.assertTrue((self.runtime / relative / "SKILL.md").is_file())

    def test_matt_entries_keep_document_and_runtime_roots_separate(self):
        for source, (name, document_leaf, runtime_leaf) in MATT.items():
            with self.subTest(entry=source):
                native = (ROOT / source).read_text(encoding="utf-8")
                published = (self.release / (f"methods/matt-pocock/{name}/METHOD.md" if name == "diagnosing-bugs" else source.replace("skills/", "methods/", 1).replace("SKILL.md", "METHOD.md"))).read_text(encoding="utf-8")
                for text in (native, published):
                    prose = re.sub(r"(?ms)^```.*?^```[^\n]*(?:\n|$)", "", text)
                    self.assertIn(f"`methods/matt-pocock/{name}/{document_leaf}`", prose)
                    self.assertIn(f"`skills/matt-pocock/{name}/`", prose)
                    self.assertIn(f"`{runtime_leaf}`", prose)
                self.assertTrue((self.release / f"methods/matt-pocock/{name}" / document_leaf).is_file())
                self.assertTrue((self.runtime / f"skills/matt-pocock/{name}" / runtime_leaf).is_file())

    def test_evaluation_methods_are_documents_and_metadata_stays_excluded(self):
        prefix = "references/anthropic-skills/skill-creator/agents"
        for name in ("grader", "comparator", "analyzer"):
            with self.subTest(method=name):
                upstream = ROOT / "dependencies/upstream/anthropic-skills/skills/skill-creator/agents" / f"{name}.md"
                self.assertIn(upstream.read_text(encoding="utf-8").splitlines()[0], (self.release / prefix / f"{name}.md").read_text(encoding="utf-8"))
                self.assertTrue((self.runtime / prefix / f"{name}.md").is_file())
        allowed = {f"{prefix}/{name}.md" for name in ("grader", "comparator", "analyzer")}
        shipped = {p.relative_to(self.release).as_posix() for p in self.release.rglob("*") if p.is_file() and "/agents/" in p.relative_to(self.release).as_posix()}
        self.assertEqual(shipped, allowed)
