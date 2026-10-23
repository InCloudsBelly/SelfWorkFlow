import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from selfworkflow.cli import main
from selfworkflow.documents import _publication_lock, document_binding, publish_documents
from tests.unit.test_documents import source_tree


ROOT = Path(__file__).resolve().parents[2]
BUNDLE = Path("skills/selfworkflow/references/public")
ENTRY = """---
name: selfworkflow
description: Use the selected SelfWorkflow engineering process.
---

# SelfWorkflow

Read the [public entry](skills/selfworkflow/references/public/WORKFLOW.md).
"""


def invoke(*arguments):
    output, errors = io.StringIO(), io.StringIO()
    with redirect_stdout(output), redirect_stderr(errors):
        try:
            code = main(list(arguments))
        except SystemExit as error:
            code = error.code
    return code, output.getvalue() + errors.getvalue()


def repository(folder):
    source = source_tree(Path(folder))
    (source / "SKILL.md").write_text(ENTRY, encoding="utf-8")
    (source / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
    return source


class SkillBundleTests(unittest.TestCase):
    def sync(self, source):
        code, output = invoke("skill", "sync", "--repository", str(source))
        self.assertEqual(code, 0, output)
        return json.loads(output)

    def test_sync_rejects_a_non_skill_directory_before_creating_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            code, output = invoke("skill", "sync", "--repository", str(source))
            self.assertNotEqual(code, 0, output)
            self.assertEqual(list(source.iterdir()), [])

    def test_sync_updates_the_repository_skill_and_compatibility_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            source = repository(folder)
            result = self.sync(source)
            self.assertEqual(document_binding(source / BUNDLE)["revision"], result["revision"])
            self.assertEqual(document_binding(source / "public")["revision"], result["revision"])
            portable = (source / "skills/selfworkflow/SKILL.md").read_text(encoding="utf-8")
            self.assertIn("(references/public/WORKFLOW.md)", portable)
            self.assertNotIn("(skills/selfworkflow/", portable)
            self.assertEqual(invoke("skill", "check", "--repository", str(source))[0], 0)

    def test_sync_refreshes_the_visible_version_in_both_skill_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            source = repository(folder)
            first = self.sync(source)
            entries = (source / "SKILL.md", source / "skills/selfworkflow/SKILL.md")
            for entry in entries:
                text = entry.read_text(encoding="utf-8")
                self.assertIn(f"规则版本：`{first['revision'][:12]}`", text)
                self.assertEqual(text.count("规则版本："), 1)
            (source / "skills/example/details.md").write_text("Updated rule\n", encoding="utf-8")
            second = self.sync(source)
            self.assertNotEqual(first["revision"], second["revision"])
            for entry in entries:
                text = entry.read_text(encoding="utf-8")
                self.assertIn(f"规则版本：`{second['revision'][:12]}`", text)
                self.assertNotIn(first["revision"][:12], text)
                self.assertEqual(text.count("规则版本："), 1)
            before = [entry.read_bytes() for entry in entries]
            self.sync(source)
            self.assertEqual([entry.read_bytes() for entry in entries], before)

    def test_check_rejects_a_stale_visible_version_even_when_both_copies_match(self):
        with tempfile.TemporaryDirectory() as folder:
            source = repository(folder)
            result = self.sync(source)
            for relative in ("SKILL.md", "skills/selfworkflow/SKILL.md"):
                entry = source / relative
                text = entry.read_text(encoding="utf-8")
                entry.write_text(text.replace(result["revision"][:12], "0" * 12), encoding="utf-8")
            code, output = invoke("skill", "check", "--repository", str(source))
            self.assertNotEqual(code, 0, output)
            self.assertIn("skill-version-stale", output)

    def test_check_rejects_stale_delivery_even_when_its_internal_hash_is_valid(self):
        with tempfile.TemporaryDirectory() as folder:
            source = repository(folder)
            self.sync(source)
            (source / "skills/example/details.md").write_text("New source rule\n", encoding="utf-8")
            self.assertTrue(document_binding(source / BUNDLE)["revision"])
            code, output = invoke("skill", "check", "--repository", str(source))
            self.assertNotEqual(code, 0, output)
            self.assertIn("skill-bundle-stale", output)
            self.sync(source)
            self.assertEqual(invoke("skill", "check", "--repository", str(source))[0], 0)

    def test_check_rejects_a_drifted_portable_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            source = repository(folder)
            self.sync(source)
            (source / "skills/selfworkflow/SKILL.md").write_text("stale entry\n", encoding="utf-8")
            code, output = invoke("skill", "check", "--repository", str(source))
            self.assertNotEqual(code, 0, output)
            self.assertIn("skill-entry-drift", output)

    def test_updates_preserve_versions_needed_by_in_flight_tasks(self):
        with tempfile.TemporaryDirectory() as folder:
            source = repository(folder)
            first = self.sync(source)
            old = Path(first["documentRoot"]) / "methods/example/details.md"
            before = old.read_bytes()
            (source / "skills/example/details.md").write_text("Next rule\n", encoding="utf-8")
            second = self.sync(source)
            self.assertNotEqual(first["revision"], second["revision"])
            self.assertEqual(old.read_bytes(), before)
            self.assertEqual(invoke("skill", "check", "--repository", str(source))[0], 0)

    def test_invalid_update_does_not_switch_either_delivered_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            source = repository(folder)
            self.sync(source)
            paths = [source / BUNDLE / "WORKFLOW.md", source / "public/WORKFLOW.md", source / "skills/selfworkflow/SKILL.md"]
            before = [path.read_bytes() for path in paths]
            (source / "skills/example/details.md").write_text("[missing](missing.md)\n", encoding="utf-8")
            code, output = invoke("skill", "sync", "--repository", str(source))
            self.assertNotEqual(code, 0, output)
            self.assertEqual([path.read_bytes() for path in paths], before)

    def test_clone_uses_only_committed_skill_content_at_a_different_path(self):
        with tempfile.TemporaryDirectory() as folder:
            source = repository(folder)
            # Content-addressed releases must preserve even mixed source line endings.
            (source / "skills/example/diagram.svg").write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg">\r\n</svg>\r\n')
            (source / "skills/example/details.md").write_text("First version.\n[diagram](diagram.svg)\n", encoding="utf-8")
            self.sync(source)
            for arguments in (
                ["git", "init", "-q", str(source)],
                ["git", "-C", str(source), "add", ".gitattributes", "SKILL.md", "skills/selfworkflow"],
                ["git", "-C", str(source), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "core.hooksPath=", "commit", "-qm", "complete skill"],
            ):
                subprocess.run(arguments, check=True, capture_output=True)
            clone = Path(folder) / "consumer with spaces"
            subprocess.run(["git", "-c", "core.autocrlf=true", "clone", "-q", "--no-local", str(source), str(clone)], check=True, capture_output=True)
            entry = (clone / "SKILL.md").read_text(encoding="utf-8")
            route = re.search(r"\]\(([^)]+WORKFLOW\.md)\)", entry)[1]
            binding = document_binding((clone / route).parent)
            self.assertIn("First version.", (Path(binding["documentRoot"]) / "methods/example/details.md").read_text(encoding="utf-8"))
            for unwanted in (".venv", "dependencies", "src", "WORKFLOW.md"):
                self.assertFalse((clone / unwanted).exists())

    def test_full_source_clone_can_verify_the_delivered_skill(self):
        with tempfile.TemporaryDirectory() as folder:
            source = repository(folder)
            (source / "skills/example/diagram.svg").write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg">\r\n</svg>\r\n')
            (source / "skills/example/details.md").write_text("First version.\n[diagram](diagram.svg)\n", encoding="utf-8")
            self.sync(source)
            for arguments in (
                ["git", "init", "-q", str(source)],
                ["git", "-C", str(source), "add", "."],
                ["git", "-C", str(source), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "core.hooksPath=", "commit", "-qm", "source and delivered skill"],
            ):
                subprocess.run(arguments, check=True, capture_output=True)
            clone = Path(folder) / "full source clone"
            subprocess.run(["git", "-c", "core.autocrlf=true", "clone", "-q", "--no-local", str(source), str(clone)], check=True, capture_output=True)
            code, output = invoke("skill", "check", "--repository", str(clone))
            self.assertEqual(code, 0, output)

    def test_busy_compatibility_output_does_not_switch_the_skill_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            source = repository(folder)
            self.sync(source)
            entry = source / BUNDLE / "WORKFLOW.md"
            before = entry.read_bytes()
            (source / "skills/example/details.md").write_text("Next rule\n", encoding="utf-8")
            with _publication_lock(source / "public"):
                code, output = invoke("skill", "sync", "--repository", str(source))
            self.assertNotEqual(code, 0, output)
            self.assertIn("document-publisher-locked", output)
            self.assertEqual(entry.read_bytes(), before)

    def test_repository_delivery_is_current(self):
        code, output = invoke("skill", "check", "--repository", str(ROOT))
        self.assertEqual(code, 0, output)

    def test_ui_search_executes_from_the_bundled_resources_without_the_source_tree(self):
        with tempfile.TemporaryDirectory() as folder:
            published = publish_documents(ROOT, Path(folder) / "public")
            release = Path(published["documentRoot"])
            resources = release / "references/community-skills/ui-ux-pro-max/src/ui-ux-pro-max"
            script = resources / "scripts/search.py"
            self.assertTrue(script.is_file(), "UI instructions require an executable search.py")
            self.assertNotIn(b"\r\n", script.read_bytes())
            self.assertTrue((resources / "data/styles.csv").is_file())
            result = subprocess.run(
                [sys.executable, "-B", "-X", "utf8", str(script), "minimalism", "--domain", "style", "--max-results", "1"],
                cwd=folder, capture_output=True, text=True, encoding="utf-8", check=True,
            )
            self.assertIn("Found:", result.stdout)
            self.assertNotIn("Error:", result.stdout)
            self.assertNotIn("Found: 0", result.stdout)
            self.assertFalse(list(release.rglob("__pycache__")))


if __name__ == "__main__":
    unittest.main()
