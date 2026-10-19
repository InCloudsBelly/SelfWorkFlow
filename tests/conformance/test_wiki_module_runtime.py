from pathlib import Path
import hashlib
import os
import subprocess
import tempfile
import unittest
from uuid import uuid4

from selfworkflow.adapters import AdapterError, _copy_tree, build_runtime


class WikiModuleRuntimeTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_knowledge_artifact_packages_backend_reference_bytes(self):
        references = self.ROOT / "skills/kg-selfopenwiki/references"
        references.mkdir(exist_ok=True)
        name = "test-reference-" + uuid4().hex + ".md"
        reference = references / name
        content = "# 按需加载\n只读取本操作引用。\n".encode("utf-8")
        reference.write_bytes(content)
        try:
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "knowledge"
                manifest = build_runtime(
                    self.ROOT, output, "0.1.0.dev0", profile="knowledge"
                )
                relative = "skills/kg-selfopenwiki/references/" + name
                self.assertTrue((output / relative).is_file())
                self.assertEqual((output / relative).read_bytes(), content)
                entry = next(
                    item for item in manifest["files"] if item["path"] == relative
                )
                self.assertEqual(
                    entry["sha256"], hashlib.sha256(content).hexdigest()
                )
        finally:
            reference.unlink(missing_ok=True)
            if not any(references.iterdir()):
                references.rmdir()

    @unittest.skipUnless(os.name == "nt", "Windows junction protection")
    def test_packaging_rejects_a_junction_to_private_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source"
            private = root / "private"
            output = root / "output"
            source.mkdir()
            private.mkdir()
            (private / "secret.json").write_text("private fixture", encoding="utf-8")
            junction = source / "linked"
            subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(private)], check=True, capture_output=True)
            try:
                with self.assertRaisesRegex(AdapterError, "runtime-source-link-rejected"):
                    _copy_tree(source, output, excluded_roots=(source / "excluded",))
                self.assertFalse((output / "linked/secret.json").exists())
            finally:
                junction.rmdir()

    @unittest.skipUnless(os.name == "nt", "Windows module root junction protection")
    def test_packaging_rejects_a_junction_as_the_source_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            private = root / "private"
            private.mkdir()
            (private / "secret.json").write_text("private fixture", encoding="utf-8")
            junction = root / "module"
            subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(private)], check=True, capture_output=True)
            output = root / "output"
            try:
                with self.assertRaisesRegex(AdapterError, "runtime-source-link-rejected"):
                    _copy_tree(junction, output, excluded_roots=(junction / "excluded",))
                self.assertFalse(output.exists())
            finally:
                junction.rmdir()

    def test_knowledge_artifact_excludes_wiki_dependencies_and_private_outputs(self):
        module = self.ROOT / "extensions/knowledge/selfopenwiki"
        name = "test-private-" + uuid4().hex + ".json"
        files = []
        directories = []
        try:
            for relative in (".work", "self-openwiki/runtime", "self-openwiki/mcp-server/node_modules"):
                directory = module / relative
                if not directory.exists():
                    directory.mkdir(parents=True)
                    directories.append(directory)
                sentinel = directory / name
                sentinel.write_text("private runtime fixture", encoding="utf-8")
                files.append(sentinel)
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "knowledge"
                build_runtime(self.ROOT, output, "0.1.0.dev0", profile="knowledge")
                packaged = output / "extensions/knowledge/selfopenwiki"
                self.assertTrue((packaged / "adapter.yaml").is_file())
                self.assertTrue((output / "skills/kg-selfopenwiki/SKILL.md").is_file())
                for relative in ("upstream", "visualizer", ".work", "self-openwiki/runtime", "self-openwiki/mcp-server/node_modules", "self-openwiki/win32-helper/bootstrap"):
                    self.assertFalse((packaged / relative).exists(), relative)
        finally:
            for file in files:
                file.unlink(missing_ok=True)
            for directory in reversed(directories):
                if directory.exists() and not any(directory.iterdir()):
                    directory.rmdir()

    def test_maintainer_keeps_wiki_source_without_activating_backend_skill(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "maintainer"
            build_runtime(self.ROOT, output, "0.1.0.dev0", profile="maintainer")
            self.assertTrue((output / "extensions/knowledge/selfopenwiki/adapter.yaml").is_file())
            self.assertFalse((output / "skills/kg-selfopenwiki").exists())
