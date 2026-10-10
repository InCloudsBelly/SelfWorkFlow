"""Provider CLI diagnostics through the real manager/lifecycle/adapter chain."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from selfworkflow.cli import _SubprocessCommandPort, main
from selfworkflow.v3.provider_manager import MachineLocalPaths, ProviderManager


class GraftCommandDiagnosticsAcceptanceTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        source = self.root / "provider"
        source.mkdir()
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / ".git").mkdir()
        report = {
            "version": "0.21.1", "commit": "b" * 40,
            "sourceHash": "sha256:" + "a" * 64, "dirty": False,
        }
        self.manager = ProviderManager(
            paths=MachineLocalPaths(config_file=self.root / "providers.local.yaml"),
            command_port=_SubprocessCommandPort(),
            source_identity_resolver=lambda path: {"source": Path(path), "report": report},
        )
        self.manager.configure(
            provider_id="graft", source_path=str(source),
            command_prefix=("node", str(source / "cli.js")),
            ownership="selfworkflow-managed", source_version=report["version"],
            source_commit=report["commit"], source_hash=report["sourceHash"], dirty=False,
        )
        self.manager.graft_topic_select(str(self.project), "diagnostic-test", global_only=True)

    def invoke(self, command, failure, *, allow_update=False):
        def run(argv, **kwargs):
            if argv[-1] == "--version":
                return subprocess.CompletedProcess(argv, 0, "0.21.1", "")
            if argv[-1] == "--help":
                return subprocess.CompletedProcess(argv, 0, "build\ncheck\nask\nmap\ngrep\ncallers\nskeleton", "")
            if allow_update and "check" in argv:
                return subprocess.CompletedProcess(argv, 1, json.dumps({
                    "context": {"missing": False}, "graph": {"ok": False},
                }), "")
            if isinstance(failure, Exception):
                raise failure
            return failure

        args = ["provider", command, "--project-root", str(self.project),
                "--conversation-id", "diagnostic-test"]
        if command == "status":
            args += ["--provider-id", "graft"]
        if command == "graft-sync":
            args += ["--changed-path", "main.py"]
        if allow_update:
            args.append("--allow-update")
        output, errors = StringIO(), StringIO()
        with patch("selfworkflow.cli._provider_manager", return_value=self.manager), \
             patch("selfworkflow.cli.subprocess.run", side_effect=run), \
             redirect_stdout(output), redirect_stderr(errors):
            code = main(args)
        return code, output.getvalue(), errors.getvalue()

    def test_ensure_exception_and_status_result_expose_timeout_as_exit_74(self):
        for command in ("graft-ensure", "status"):
            with self.subTest(command=command):
                failure = subprocess.TimeoutExpired(["node"], 120, stderr=b"scan in progress")
                code, output, errors = self.invoke(command, failure)
                self.assertEqual(code, 74)
                payload = json.loads(output)
                self.assertEqual(payload["reason"], "graft-command-timeout")
                self.assertEqual(payload["diagnostics"]["operation"], "check")
                self.assertIsNone(payload["diagnostics"]["childExitCode"])
                self.assertEqual(payload["diagnostics"]["timeoutMs"], 120000)

    def test_build_failure_keeps_child_exit_and_emits_cli_exit_76(self):
        failure = subprocess.CompletedProcess(["node"], 23, "", "parser failed")
        code, output, errors = self.invoke("graft-ensure", failure, allow_update=True)
        self.assertEqual(code, 76)
        payload = json.loads(output)
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["diagnostics"]["operation"], "build")
        self.assertEqual(payload["diagnostics"]["childExitCode"], 23)
        self.assertEqual(payload["diagnostics"]["stderrTail"], "parser failed")

    def test_start_and_parse_failures_have_distinct_cli_exits(self):
        cases = (
            (FileNotFoundError("missing executable"), 75, "graft-command-start-failed"),
            (subprocess.CompletedProcess(["node"], 0, "not json", ""), 77, "graft-status-invalid"),
            (subprocess.CompletedProcess(["node"], 0, "{}", ""), 77, "graft-status-invalid"),
        )
        for failure, expected, reason in cases:
            with self.subTest(expected=expected, failure=failure):
                code, output, _ = self.invoke("status", failure)
                self.assertEqual(code, expected)
                self.assertEqual(json.loads(output)["reason"], reason)

    def test_success_keeps_existing_json_shape_and_exit_zero(self):
        fresh = subprocess.CompletedProcess(["node"], 0, json.dumps({
            "context": {"missing": False}, "graph": {"ok": True},
        }), "")
        code, output, errors = self.invoke("graft-ensure", fresh)
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["status"], "succeeded")
        self.assertNotIn("diagnostics", payload)
        self.assertEqual(errors, "")

    def test_sync_worker_keeps_build_diagnostics_and_pending_work(self):
        (self.project / "graft").mkdir()
        (self.project / "main.py").write_text("pass\n", encoding="utf-8")
        failure = subprocess.CompletedProcess(["node"], 23, "", "parser failed")
        code, output, _ = self.invoke("graft-sync", failure)
        self.assertEqual(code, 76)
        worker = json.loads(output)["worker"]
        self.assertEqual(worker["diagnostics"]["childExitCode"], 23)
        self.assertEqual(worker["diagnostics"]["operation"], "build")
        self.assertTrue(worker["pending"])
        self.assertFalse(worker["globalMapUpdated"])


if __name__ == "__main__":
    unittest.main()
