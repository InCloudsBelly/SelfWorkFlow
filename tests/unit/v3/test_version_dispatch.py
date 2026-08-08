from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


class VersionDispatchTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[3]

    def test_v3_request_is_dispatched_to_v3_resolver(self):
        from selfworkflow.cli import _resolve_by_version

        request = {"schemaVersion": 3}
        expected = {"schemaVersion": 3, "status": "active"}
        with patch("selfworkflow.v3.resolver.resolve_request", return_value=expected) as resolver:
            result = _resolve_by_version(b"ignored", request)
        resolver.assert_called_once()
        self.assertIs(result, expected)

    def test_v2_request_is_dispatched_to_unchanged_v2_resolver(self):
        from selfworkflow.cli import _resolve_by_version

        request = {"schemaVersion": 2}
        expected = {"schemaVersion": 2}
        with patch("selfworkflow.cli.resolve_task", return_value=expected) as resolver:
            result = _resolve_by_version(b"catalog", request)
        resolver.assert_called_once_with(b"catalog", request)
        self.assertIs(result, expected)

    def test_unknown_version_fails_closed_without_fallback(self):
        from selfworkflow.cli import _resolve_by_version

        with self.assertRaisesRegex(ValueError, "unsupported-contract-version"):
            _resolve_by_version(b"catalog", {"schemaVersion": 99})

    def test_v3_dispatch_preserves_content_addressed_cpp_route(self):
        from copy import deepcopy
        from selfworkflow.cli import _resolve_by_version
        from tests.unit.v3.test_cpp_router import _v3_request

        request = _v3_request()
        request["codeSignals"] = {
            "languages": ["cpp"],
            "fileExtensions": [".cpp"],
            "taskSignals": ["concurrency"],
            "explicitCppModuleIds": [],
            "userConfirmedHeavy": False,
            "projectAllowsExecution": False,
        }
        result = _resolve_by_version(
            b"ignored",
            deepcopy(request),
            catalog_source=self.ROOT / "catalog/v3/index.yaml",
            pipeline_source=self.ROOT / "workflow/v3/pipeline.yaml",
        )

        self.assertEqual(result["schemaVersion"], 3)
        self.assertEqual(
            result["capabilityRoute"]["selectedModuleIds"],
            ["cpp-core", "cpp.concurrency"],
        )
        self.assertRegex(
            result["capabilityRoute"]["routeHash"],
            r"^sha256:[0-9a-f]{64}$",
        )

    def test_v2_cli_end_to_end_preserves_output_and_error_text(self):
        from selfworkflow.catalog import compile_catalog
        from selfworkflow.cli import main
        from selfworkflow.resolver import resolve_task
        from tests.unit.test_resolver import TaskResolverV2Tests

        with TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "catalog.json"
            request_path = root / "request.json"
            catalog_content = compile_catalog(self.ROOT / "catalog").content
            request = TaskResolverV2Tests._request()
            expected = resolve_task(catalog_content, request)
            catalog_path.write_bytes(catalog_content)
            request_path.write_text(
                json.dumps(request), encoding="utf-8"
            )
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([
                    "resolve", "--catalog", str(catalog_path),
                    "--request", str(request_path),
                ])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout.getvalue()), expected)
            self.assertEqual(stderr.getvalue(), "")

            request_path.write_text('{"schemaVersion":99}', encoding="utf-8")
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([
                    "resolve", "--catalog", str(catalog_path),
                    "--request", str(request_path),
                ])
            self.assertEqual(code, 50)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "SelfWorkFlow: resolve-failed\n")


if __name__ == "__main__":
    unittest.main()
