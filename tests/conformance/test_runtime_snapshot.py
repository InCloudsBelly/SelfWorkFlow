from pathlib import Path
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from selfworkflow.adapters import AdapterError, build_runtime
from selfworkflow.cli import main


class RuntimeSnapshotTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_default_runtime_is_deterministic_lightweight_core(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            first = build_runtime(self.ROOT, root / "first", "0.1.0.dev0")
            second = build_runtime(self.ROOT, root / "second", "0.1.0.dev0")
            self.assertEqual(first["runtimeHash"], second["runtimeHash"])
            self.assertEqual(first["profile"], "core")
            self.assertTrue((root / "first/WORKFLOW.md").is_file())
            self.assertTrue((root / "first/skills/code-quality/SKILL.md").is_file())
            self.assertEqual(
                (root / "first/WORKFLOW.md").read_bytes(),
                (self.ROOT / "workflow/core.md").read_bytes(),
            )
            self.assertFalse((root / "first/extensions").exists())
            self.assertFalse((root / "first/schemas").exists())
            self.assertFalse((root / "first/workflow/protected-rules.yaml").exists())
            core_catalog = json.loads((root / "first/catalog.json").read_text())
            self.assertEqual(
                {entry["id"] for entry in core_catalog["catalog"]["entries"]},
                {"workflow-core", "workflow-quality", "code-quality", "grill-me"},
            )
            core_ids = {entry["id"] for entry in core_catalog["catalog"]["entries"]}
            self.assertTrue(all(
                set(entry["dependencies"]) <= core_ids
                for entry in core_catalog["catalog"]["entries"]
            ))
            content = b"".join(
                path.read_bytes() for path in (root / "first").rglob("*") if path.is_file()
            ).lower()
            self.assertNotIn(b"e:\\", content)
            self.assertNotIn(b"d:\\openwikic7", content)

    def test_explicit_profiles_add_only_their_intended_boundaries(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            knowledge = build_runtime(
                self.ROOT, root / "knowledge", "0.1.0.dev0", profile="knowledge"
            )
            maintainer = build_runtime(
                self.ROOT, root / "maintainer", "0.1.0.dev0", profile="maintainer"
            )
            self.assertEqual(knowledge["profile"], "knowledge")
            self.assertTrue((root / "knowledge/extensions/knowledge/contract.yaml").is_file())
            self.assertFalse((root / "knowledge/workflow/protected-rules.yaml").exists())
            knowledge_catalog = json.loads((root / "knowledge/catalog.json").read_text())
            self.assertIn(
                "knowledge-on-demand-loading",
                {entry["id"] for entry in knowledge_catalog["catalog"]["entries"]},
            )
            self.assertEqual(maintainer["profile"], "maintainer")
            self.assertTrue((root / "maintainer/workflow/protected-rules.yaml").is_file())
            self.assertTrue((root / "maintainer/extensions/knowledge/contract.yaml").is_file())
            self.assertEqual(
                (root / "maintainer/WORKFLOW.md").read_bytes(),
                (self.ROOT / "WORKFLOW.md").read_bytes(),
            )

    def test_unknown_runtime_profile_is_rejected(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            with self.assertRaises(AdapterError):
                build_runtime(
                    self.ROOT,
                    Path(temporary) / "runtime",
                    "0.1.0.dev0",
                    profile="unknown",
                )

    def test_profile_catalog_rejects_dangling_dependencies(self):
        from selfworkflow.catalog import compile_catalog

        compiled = json.loads(compile_catalog(self.ROOT / "catalog").content)
        next(
            entry
            for entry in compiled["catalog"]["entries"]
            if entry["id"] == "workflow-quality"
        )["dependencies"].append("missing-profile-entry")
        content = (json.dumps(compiled, separators=(",", ":"), sort_keys=True) + "\n").encode()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            with mock.patch(
                "selfworkflow.adapters.compile_catalog",
                return_value=SimpleNamespace(content=content),
            ):
                with self.assertRaisesRegex(
                    AdapterError, "runtime-profile-dependency-invalid"
                ):
                    build_runtime(
                        self.ROOT,
                        Path(temporary) / "runtime",
                        "0.1.0.dev0",
                    )

    def test_cli_build_publishes_runtime(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            output = Path(temporary) / "runtime"
            with mock.patch("sys.stdout"):
                result = main([
                    "build", "--repository", str(self.ROOT), "--output", str(output),
                    "--version", "0.1.0.dev0",
                ])
            self.assertEqual(result, 0)
            self.assertTrue((output / "artifact-manifest.json").is_file())
            manifest = json.loads((output / "artifact-manifest.json").read_text())
            self.assertEqual(manifest["profile"], "core")

    def test_cli_build_accepts_explicit_profile(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            output = Path(temporary) / "runtime"
            with mock.patch("sys.stdout"):
                result = main([
                    "build", "--repository", str(self.ROOT), "--output", str(output),
                    "--version", "0.1.0.dev0", "--profile", "knowledge",
                ])
            self.assertEqual(result, 0)
            manifest = json.loads((output / "artifact-manifest.json").read_text())
            self.assertEqual(manifest["profile"], "knowledge")


if __name__ == "__main__":
    unittest.main()
