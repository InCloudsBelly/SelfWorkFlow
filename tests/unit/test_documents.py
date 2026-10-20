from pathlib import Path
import re
import io
import json
import os
import subprocess
from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import tempfile
import unittest
from unittest import mock

from selfworkflow.documents import DocumentError, publish_documents


def source_tree(root):
    source = root / "source"
    source.mkdir()
    (source / "WORKFLOW.md").write_text("# Workflow\nRead [code](workflow/modules/code.md).\n", encoding="utf-8")
    module = source / "workflow/modules/code.md"
    module.parent.mkdir(parents=True)
    module.write_text("# Code\nUse [method](../../skills/example/SKILL.md).\n", encoding="utf-8")
    method = source / "skills/example/SKILL.md"
    method.parent.mkdir(parents=True)
    method.write_text("---\nname: example\ndescription: Example method\n---\n# Method\nUse [details](details.md).\n", encoding="utf-8")
    (method.parent / "details.md").write_text("# Details\nFirst version.\n", encoding="utf-8")
    return source


class DocumentPublicationTests(unittest.TestCase):
    def test_interrupted_public_copy_preserves_entry_and_removes_its_partial_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = source_tree(root)
            public = root / "public"
            publish_documents(source, public)
            before = (public / "WORKFLOW.md").read_bytes()
            (source / "skills/example/details.md").write_text("Changed rule\n", encoding="utf-8")

            def interrupted_copy(source, destination, **kwargs):
                (destination / "partial.md").write_text("Partial\n", encoding="utf-8")
                raise OSError("publication-copy-interrupted")

            with mock.patch("selfworkflow.documents.shutil.copytree", side_effect=interrupted_copy):
                with self.assertRaisesRegex(OSError, "publication-copy-interrupted"):
                    publish_documents(source, public)
            self.assertEqual((public / "WORKFLOW.md").read_bytes(), before)
            self.assertEqual(list((public / "releases").glob(".publishing-*")), [])

    @unittest.skipUnless(os.name == "nt", "Windows document-sharing ACLs")
    def test_published_version_inherits_public_read_access_instead_of_private_staging_acl(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = source_tree(root)
            public = root / "public"
            public.mkdir()
            subprocess.run(["icacls", str(public), "/grant", "*S-1-5-32-545:(OI)(CI)RX"], check=True, capture_output=True)
            result = publish_documents(source, public)
            for path in (Path(result["documentRoot"]), Path(result["documentRoot"]) / "methods/example/METHOD.md"):
                with self.subTest(path=path):
                    literal = str(path).replace("'", "''")
                    command = "(Get-Acl -LiteralPath '" + literal + "').Access | ForEach-Object { $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value }"
                    identities = subprocess.check_output(["powershell", "-NoProfile", "-Command", command], text=True, encoding="utf-8")
                    self.assertIn("S-1-5-32-545", identities.splitlines())

    def test_publication_can_repair_an_older_content_bound_release_with_a_bad_route(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = source_tree(root)
            public = root / "public"
            (source / "WORKFLOW.md").write_text("Old route: `modules/code.md`\n", encoding="utf-8")
            with mock.patch("selfworkflow.documents._validate_links"):
                old = publish_documents(source, public)
            (source / "WORKFLOW.md").write_text("Fixed route: [code](workflow/modules/code.md)\n", encoding="utf-8")
            new = publish_documents(source, public)
            self.assertNotEqual(old["revision"], new["revision"])
            self.assertIn("modules/code.md", (Path(old["documentRoot"]) / "WORKFLOW.md").read_text(encoding="utf-8"))

    def test_output_inside_a_collected_source_tree_is_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            source = source_tree(Path(folder))
            output = source / "workflow/public"
            with self.assertRaisesRegex(DocumentError, "document-output-invalid"):
                publish_documents(source, output)
            self.assertFalse(output.exists())

    def test_concurrent_publication_cannot_switch_the_entry_or_remove_another_lock(self):
        from selfworkflow.documents import _collect
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = source_tree(root)
            public = root / "public"
            publish_documents(source, public)
            before = (public / "WORKFLOW.md").read_bytes()
            (source / "skills/example/details.md").write_text("Updated rule\n", encoding="utf-8")
            entered, proceed = Event(), Event()

            def collect(*args):
                if not entered.is_set():
                    entered.set()
                    if not proceed.wait(10):
                        raise RuntimeError("publication-test-timeout")
                return _collect(*args)

            with ThreadPoolExecutor(max_workers=1) as executor, mock.patch("selfworkflow.documents._collect", side_effect=collect):
                first = executor.submit(publish_documents, source, public)
                try:
                    self.assertTrue(entered.wait(10))
                    with self.assertRaisesRegex(DocumentError, "document-publisher-locked"):
                        publish_documents(source, public)
                    self.assertEqual((public / "WORKFLOW.md").read_bytes(), before)
                    with self.assertRaisesRegex(DocumentError, "document-publisher-locked"):
                        publish_documents(source, public)
                finally:
                    proceed.set()
                self.assertNotEqual(first.result()["revision"], re.search(rb"releases/([a-f0-9]+)/", before)[1].decode())
            self.assertEqual(publish_documents(source, public)["status"], "published")

    def test_repository_tea_references_are_readable_without_bypassing_the_adapter(self):
        with tempfile.TemporaryDirectory() as folder:
            repository = Path(__file__).resolve().parents[2]
            result = publish_documents(repository, Path(folder) / "public")
            release = Path(result["documentRoot"])
            tea = release / "methods/tea-quality"
            entry = (tea / "METHOD.md").read_text(encoding="utf-8")
            self.assertIn("`METHOD.md`", entry)
            self.assertIn("`references/bmod-tea/knowledge/tea-index.csv.md`", entry)
            self.assertTrue((tea / "references/bmod-tea/knowledge/tea-index.csv.md").is_file())
            self.assertIn("`../METHOD.md`", (tea / "references/headless-contract.md").read_text(encoding="utf-8"))
            self.assertTrue((tea / "references/bmad-testarch-test-design/METHOD.md").is_file())
            selected = (tea / "references/bmad-testarch-test-design/METHOD.md").read_text(encoding="utf-8")
            self.assertIn("{tea-knowledge}/tea-index.csv.md", selected)
            atdd = (tea / "references/bmad-testarch-atdd/METHOD.md").read_text(encoding="utf-8")
            canonical = tea / "references/bmad-testarch-automate"
            for required in ("METHOD.md", "resources/test-generation-routing.md", "resources/run-and-heal.md", "red/steps-c/step-01-preflight-and-context.md"):
                self.assertTrue((canonical / required).is_file(), required)
            self.assertIn("`{skill-root}/METHOD.md`", atdd)
            self.assertNotIn("npx skills add", atdd)
            self.assertNotIn("npx skills add", (canonical / "METHOD.md").read_text(encoding="utf-8"))
            preflight = (canonical / "red/steps-c/step-01-preflight-and-context.md").read_text(encoding="utf-8")
            self.assertIn("knowledgeIndex: '{tea-knowledge}/tea-index.csv.md'", preflight)
            index = (release / "methods/INDEX.md").read_text(encoding="utf-8")
            self.assertIn("[tea-quality]", index)
            self.assertNotIn("[bmad-testarch-", index)
            self.assertNotIn("[tea-framework]", index)
            self.assertNotIn("[tea-ci]", index)

    def test_entry_routes_are_checked_even_when_written_as_code_spans(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = source_tree(root)
            (source / "WORKFLOW.md").write_text("Required route: `modules/code.md`\n", encoding="utf-8")
            with self.assertRaisesRegex(DocumentError, "document-route-missing"):
                publish_documents(source, root / "public")

    def test_cli_publishes_and_prints_a_stable_unversioned_host_reference(self):
        from selfworkflow.cli import main
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = source_tree(root)
            public = root / "public"
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["documents", "publish", "--repository", str(source), "--output", str(public)]), 0)
            publication = json.loads(output.getvalue())
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["documents", "snippet", "--root", str(public)]), 0)
            self.assertIn(public.resolve().as_posix() + "/WORKFLOW.md", output.getvalue())
            self.assertNotIn(publication["revision"], output.getvalue())

    def test_broken_publication_keeps_the_last_good_entry_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = source_tree(root)
            public = root / "public"
            published = publish_documents(source, public)
            before = (public / "WORKFLOW.md").read_bytes()
            (source / "skills/example/details.md").write_text("[missing](absent.md)\n", encoding="utf-8")
            with self.assertRaisesRegex(DocumentError, "document-reference-missing"):
                publish_documents(source, public)
            self.assertEqual((public / "WORKFLOW.md").read_bytes(), before)
            (Path(published["documentRoot"]) / "methods/example/details.md").write_text("Tampered", encoding="utf-8")
            with self.assertRaisesRegex(DocumentError, "document-release-drift"):
                publish_documents(source, public)

    def test_executable_reference_is_read_only_documentation_not_a_consumer_program(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = source_tree(root)
            (source / "skills/example/details.md").write_text("[tool source](tool.py)\n`[example](missing)`\n", encoding="utf-8")
            (source / "skills/example/tool.py").write_text("raise SystemExit('must not execute')\n", encoding="utf-8")
            result = publish_documents(source, root / "public")
            release = Path(result["documentRoot"])
            self.assertFalse((release / "methods/example/tool.py").exists())
            self.assertIn("must not execute", (release / "methods/example/tool.py.md").read_text(encoding="utf-8"))

    def test_consumer_needs_only_documents_and_updates_leave_old_task_readable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = source_tree(root)
            public = root / "public"
            first = publish_documents(source, public)
            entry = (public / "WORKFLOW.md").read_text(encoding="utf-8")
            self.assertIn(first["revision"], entry)
            release = Path(first["documentRoot"])
            self.assertTrue((release / "methods/example/METHOD.md").is_file())
            self.assertIn("Example method", (release / "methods/INDEX.md").read_text(encoding="utf-8"))
            self.assertTrue(all(p.suffix == ".md" for p in public.rglob("*") if p.is_file()))
            module = (release / "workflow/modules/code.md").read_text(encoding="utf-8")
            self.assertIn("methods/example/METHOD.md", module)
            old = (release / "methods/example/details.md").read_bytes()
            (source / "skills/example/details.md").write_text("# Details\nSecond version.\n", encoding="utf-8")
            second = publish_documents(source, public)
            self.assertNotEqual(first["revision"], second["revision"])
            self.assertEqual((release / "methods/example/details.md").read_bytes(), old)
            self.assertIn(second["revision"], (public / "WORKFLOW.md").read_text(encoding="utf-8"))
            self.assertEqual(publish_documents(source, public)["revision"], second["revision"])


if __name__ == "__main__":
    unittest.main()
