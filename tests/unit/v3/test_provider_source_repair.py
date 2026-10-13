import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from selfworkflow import cli
from selfworkflow.v3.provider_manager import MachineLocalPaths, ProviderManager, ProviderManagerError


class NoDispatchPort:
    def run(self, *_args, **_kwargs):
        raise AssertionError("identity failure must not dispatch")


class ProviderSourceRepairTests(unittest.TestCase):
    def test_real_identity_drift_reports_changed_fields_without_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            manager = ProviderManager(
                paths=MachineLocalPaths(config_file=root / "config/providers.local.yaml"),
                command_port=NoDispatchPort(),
                source_identity_resolver=lambda value: {"source": Path(value), "report": {
                    "commit": "c" * 40, "sourceHash": "sha256:" + "d" * 64, "dirty": False,
                }},
            )
            manager.configure(provider_id="codegraph", source_path=str(root), command_prefix=("node", "runtime.js"),
                              ownership="user-local", source_version="1", source_commit="b" * 40,
                              source_hash="sha256:" + "a" * 64, dirty=True)
            before = (root / "config/providers.local.yaml").read_bytes()
            with self.assertRaises(ProviderManagerError) as caught:
                manager.doctor("codegraph")
            self.assertEqual(caught.exception.reason, "provider-source-identity-drift")
            self.assertEqual(caught.exception.diagnostics["changedFields"], ["commit", "sourceHash", "dirty"])
            self.assertEqual((root / "config/providers.local.yaml").read_bytes(), before)

    def test_cli_inspection_error_preserves_safe_git_cause(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary).resolve()
            (source / "dist/bin").mkdir(parents=True)
            (source / "dist/bin/codegraph.js").write_text("runtime\n", encoding="utf-8")
            result = subprocess.CompletedProcess([], 128, b"", b"fatal: not a git repository private-secret")
            error = io.StringIO()
            with patch.object(cli.subprocess, "run", return_value=result), contextlib.redirect_stderr(error):
                code = cli.main(["provider", "inspect", "--codegraph-path", str(source)])
            self.assertEqual(code, 70)
            self.assertIn("provider-source-inspection-failed", error.getvalue())
            self.assertIn("not-a-repository", error.getvalue())
            self.assertNotIn("private-secret", error.getvalue())
            self.assertNotIn("provider-source-identity-drift", error.getvalue())

    def test_failed_source_inspection_is_not_identity_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()

            def failed(_source):
                raise ValueError("private error that must not be exposed")

            manager = ProviderManager(
                paths=MachineLocalPaths(config_file=root / "config/providers.local.yaml"),
                command_port=NoDispatchPort(), source_identity_resolver=failed,
            )
            manager.configure(
                provider_id="codegraph", source_path=str(root), command_prefix=("node", "runtime.js"),
                ownership="user-local", source_version="1", source_commit="b" * 40,
                source_hash="sha256:" + "a" * 64, dirty=True,
            )
            before = (root / "config/providers.local.yaml").read_bytes()
            with self.assertRaises(ProviderManagerError) as caught:
                manager.doctor("codegraph")
            self.assertEqual(caught.exception.reason, "provider-source-inspection-failed")
            self.assertNotIn("private error", str(caught.exception.diagnostics))
            self.assertEqual((root / "config/providers.local.yaml").read_bytes(), before)

    def test_inspect_uses_only_the_explicit_source_as_command_scoped_git_trust(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary).resolve()
            script = source / "dist/bin/codegraph.js"
            script.parent.mkdir(parents=True)
            script.write_text("// test runtime\n", encoding="utf-8")
            (source / "package.json").write_text('{"name":"@colbymchenry/codegraph","version":"1.6.2"}', encoding="utf-8")
            commands = []

            def git(command, **kwargs):
                commands.append(command)
                if f"safe.directory={source.as_posix()}" not in command:
                    return subprocess.CompletedProcess(command, 128, b"", b"fatal: detected dubious ownership")
                if "--show-toplevel" in command:
                    data = str(source).encode()
                elif "HEAD^{tree}" in command:
                    data = b"b" * 40
                elif "HEAD" in command and "rev-parse" in command:
                    data = b"a" * 40
                else:
                    data = b""
                return subprocess.CompletedProcess(command, 0, data, b"")

            output = io.StringIO()
            with patch.object(cli.subprocess, "run", side_effect=git), contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                result = cli.main(["provider", "inspect", "--codegraph-path", str(source)])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(output.getvalue())["commit"], "a" * 40)
            self.assertTrue(commands)
            self.assertFalse(any("safe.directory=*" in command or "--global" in command for command in commands))


if __name__ == "__main__":
    unittest.main()
