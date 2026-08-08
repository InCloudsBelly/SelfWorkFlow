from pathlib import Path
import tempfile
import unittest
from unittest import mock

from selfworkflow.adapters import build_runtime
from selfworkflow.cli import main


class RuntimeSnapshotTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_runtime_is_deterministic_standalone_and_has_no_maintainer_paths(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            first = build_runtime(self.ROOT, root / "first", "0.1.0.dev0")
            second = build_runtime(self.ROOT, root / "second", "0.1.0.dev0")
            self.assertEqual(first["runtimeHash"], second["runtimeHash"])
            self.assertTrue((root / "first/WORKFLOW.md").is_file())
            self.assertTrue((root / "first/skills/code-quality/SKILL.md").is_file())
            content = b"".join(
                path.read_bytes() for path in (root / "first").rglob("*") if path.is_file()
            ).lower()
            self.assertNotIn(b"e:\\", content)
            self.assertNotIn(b"d:\\openwikic7", content)

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


if __name__ == "__main__":
    unittest.main()
