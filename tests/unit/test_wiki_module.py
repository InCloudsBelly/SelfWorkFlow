import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from selfworkflow.cli import main


class WikiModuleInspectionTests(unittest.TestCase):
    def test_inspect_works_without_python312_pathlib_capabilities(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            Path, "is_junction", side_effect=AttributeError("Python 3.11 has no is_junction"), create=True,
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["wiki", "inspect", "--repository", temporary])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["reason"], "source-module-missing")

    def test_missing_source_module_is_reported_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["wiki", "inspect", "--repository", str(root)])
            self.assertEqual(code, 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report["status"], "setup-required")
            self.assertEqual(report["reason"], "source-module-missing")
            self.assertEqual(report["hostRegistration"], "unverified")
            self.assertEqual(list(root.iterdir()), [])

    def test_relative_source_repository_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            code = main(["wiki", "inspect", "--repository", "."])
        self.assertNotEqual(code, 0)
