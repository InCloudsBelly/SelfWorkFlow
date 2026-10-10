"""Observe command failures at the Graft adapter's process boundary."""

import subprocess
import sys
import unittest
from unittest.mock import patch

from selfworkflow.cli import _SubprocessCommandPort
from selfworkflow.v3.providers.graft import GraftAdapter, GraftAdapterError


class GraftCommandDiagnosticsTests(unittest.TestCase):
    def adapter(self):
        return GraftAdapter(
            command_port=_SubprocessCommandPort(),
            command_prefix=("node", "C:/tools/graft/cli.js"),
            ownership="selfworkflow-managed",
        )

    def test_timeout_preserves_partial_output_without_inventing_child_exit(self):
        timeout = subprocess.TimeoutExpired(
            ["node"], 120, output=b"scanning files\n",
            stderr=b"API_KEY=private-test-token\nscan still running\n",
        )
        with patch("selfworkflow.cli.subprocess.run", side_effect=timeout):
            with self.assertRaises(GraftAdapterError) as caught:
                self.adapter().status("C:/work/project")

        error = caught.exception
        self.assertEqual(error.reason, "graft-command-timeout")
        details = error.diagnostics
        self.assertEqual(details["operation"], "check")
        self.assertEqual(details["timeoutMs"], 120000)
        self.assertGreaterEqual(details["durationMs"], 0)
        self.assertIsNone(details["childExitCode"])
        self.assertEqual(details["exceptionType"], "TimeoutExpired")
        self.assertIn("scanning files", details["stdoutTail"])
        self.assertIn("scan still running", details["stderrTail"])
        self.assertNotIn("private-test-token", str(details))

    def test_missing_executable_reports_start_failure_without_child_exit(self):
        adapter = GraftAdapter(
            command_port=_SubprocessCommandPort(),
            command_prefix=("selfworkflow-nonexistent-graft-test-executable",),
            ownership="selfworkflow-managed",
        )
        with self.assertRaises(GraftAdapterError) as caught:
            adapter.version()
        self.assertEqual(caught.exception.reason, "graft-command-start-failed")
        self.assertIsNone(caught.exception.diagnostics["childExitCode"])
        self.assertEqual(caught.exception.diagnostics["exceptionType"], "FileNotFoundError")

    def test_real_child_failure_preserves_exit_code_and_bounded_redacted_tail(self):
        script = (
            "import sys; "
            "sys.stderr.write('x' * 6000 + '\\nAuthorization: Bearer private-test-token\\n'"
            " + 'https://user:private-password@example.test/failure\\nparser failed\\n'); "
            "sys.exit(23)"
        )
        adapter = GraftAdapter(
            command_port=_SubprocessCommandPort(),
            command_prefix=(sys.executable, "-c", script),
            ownership="selfworkflow-managed",
        )
        with self.assertRaises(GraftAdapterError) as caught:
            adapter.version()
        self.assertEqual(caught.exception.reason, "graft-command-failed")
        details = caught.exception.diagnostics
        self.assertEqual(details["childExitCode"], 23)
        self.assertGreaterEqual(details["durationMs"], 0)
        self.assertIn("parser failed", details["stderrTail"])
        self.assertLessEqual(len(details["stderrTail"].encode("utf-8")), 4096)
        self.assertNotIn("private-test-token", str(details))
        self.assertNotIn("private-password", str(details))

    def test_invalid_json_reports_parse_failure_and_redacts_output(self):
        result = subprocess.CompletedProcess(
            ["node"], 0, "not json\nAPI_KEY=private-test-token", "",
        )
        with patch("selfworkflow.cli.subprocess.run", return_value=result):
            with self.assertRaises(GraftAdapterError) as caught:
                self.adapter().status("C:/work/project")
        self.assertEqual(caught.exception.reason, "graft-status-invalid")
        details = caught.exception.diagnostics
        self.assertEqual(details["failureKind"], "response-invalid")
        self.assertEqual(details["exceptionType"], "JSONDecodeError")
        self.assertEqual(details["childExitCode"], 0)
        self.assertIn("not json", details["stdoutTail"])
        self.assertNotIn("private-test-token", str(details))

    def test_non_utf8_child_stderr_does_not_hide_exit_code(self):
        adapter = GraftAdapter(
            command_port=_SubprocessCommandPort(),
            command_prefix=(sys.executable, "-c", "import os; os.write(2, b'bad byte: \\xff'); raise SystemExit(24)"),
            ownership="selfworkflow-managed",
        )
        with self.assertRaises(GraftAdapterError) as caught:
            adapter.version()
        self.assertEqual(caught.exception.reason, "graft-command-failed")
        self.assertEqual(caught.exception.diagnostics["childExitCode"], 24)
        self.assertIn("bad byte:", caught.exception.diagnostics["stderrTail"])

    def test_redaction_covers_multiline_credentials_and_environment_values(self):
        stderr = '"api_key":\n  "private-multiline-value"\nopaque-env-value\nparser failed'
        result = subprocess.CompletedProcess(["node"], 25, "", stderr)
        with patch.dict("os.environ", {"TEST_GRAFT_SECRET": "opaque-env-value"}), \
             patch("selfworkflow.cli.subprocess.run", return_value=result):
            with self.assertRaises(GraftAdapterError) as caught:
                self.adapter().version()
        tail = caught.exception.diagnostics["stderrTail"]
        self.assertNotIn("private-multiline-value", tail)
        self.assertNotIn("opaque-env-value", tail)
        self.assertIn("parser failed", tail)

    def test_output_limit_does_not_discard_original_child_exit(self):
        result = subprocess.CompletedProcess(["node"], 23, "", "x" * (1024 * 1024 + 1))
        with patch("selfworkflow.cli.subprocess.run", return_value=result):
            with self.assertRaises(GraftAdapterError) as caught:
                self.adapter().version()
        self.assertEqual(caught.exception.reason, "graft-command-output-too-large")
        self.assertEqual(caught.exception.diagnostics["childExitCode"], 23)
        self.assertLessEqual(len(caught.exception.diagnostics["stderrTail"].encode("utf-8")), 4096)


if __name__ == "__main__":
    unittest.main()
