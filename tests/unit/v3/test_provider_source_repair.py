import contextlib
import io
import json
from pathlib import Path
import shutil
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
    def _managed_runtime(self, root):
        source = root / "managed runtime"
        (source / "bin").mkdir(parents=True)
        (source / "lib/dist/bin").mkdir(parents=True)
        shutil.copyfile(shutil.which("node.exe") or shutil.which("node"), source / "node.exe")
        (source / "lib/package.json").write_text('{"name":"@colbymchenry/codegraph","version":"1.6.2"}', encoding="utf-8")
        (source / "lib/dist/bin/codegraph.js").write_text(
            "const args=process.argv.slice(2); console.log(JSON.stringify(args[0]==='status'?"
            "{initialized:true,index:{state:'complete'}}:args));\n", encoding="utf-8")
        (source / "bin/codegraph.cmd").write_text(
            '@"%~dp0..\\node.exe" "%~dp0..\\lib\\dist\\bin\\codegraph.js" %*\r\n', encoding="utf-8")
        return source

    def _inspect(self, source):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(["provider", "inspect", "--codegraph-path", str(source)]), 0)
        return json.loads(output.getvalue())

    def test_managed_query_keeps_shell_metacharacters_as_literal_data(self):
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapter

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = self._managed_runtime(root)
            report = self._inspect(source)
            adapter = CodeGraphAdapter(command_port=cli._SubprocessCommandPort(),
                                       command_prefix=report["commandPrefix"], ownership="selfworkflow-managed")
            marker = root / "audit-marker.txt"
            query = "symbol&echo.audit>" + str(marker)
            result = adapter.query(str(root), query)
            self.assertFalse(marker.exists(), "query data must never be interpreted by cmd")
            self.assertEqual(json.loads(result["data"])[1], query)

    def test_legacy_batch_binding_fails_without_executing_query_commands(self):
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapter, CodeGraphAdapterError

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = self._managed_runtime(root)
            adapter = CodeGraphAdapter(command_port=cli._SubprocessCommandPort(),
                                       command_prefix=(str(source / "bin/codegraph.cmd"),), ownership="selfworkflow-managed")
            marker = root / "audit-marker.txt"
            with self.assertRaises(CodeGraphAdapterError):
                adapter.query(str(root), "symbol&echo.audit>" + str(marker))
            self.assertFalse(marker.exists())

    def test_managed_dependency_drift_changes_inspected_source_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = self._managed_runtime(Path(temporary).resolve())
            dependency = source / "lib/dist/sdk/index.js"
            dependency.parent.mkdir(parents=True)
            dependency.write_text("module.exports=1;\n", encoding="utf-8")
            before = self._inspect(source)
            self.assertEqual(before["sourceHash"], self._inspect(source)["sourceHash"])
            dependency.write_text("module.exports=2;\n", encoding="utf-8")
            self.assertNotEqual(before["sourceHash"], self._inspect(source)["sourceHash"])

    def test_ignored_local_sdk_changes_invalidate_an_otherwise_clean_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary).resolve()
            (source / "dist/bin").mkdir(parents=True)
            (source / "dist/bin/codegraph.js").write_text("require('../sdk/index.js');\n", encoding="utf-8")
            dependency = source / "dist/sdk/index.js"
            dependency.parent.mkdir()
            dependency.write_text("module.exports=1;\n", encoding="utf-8")
            (source / ".gitignore").write_text("dist/\n", encoding="utf-8")
            (source / "package.json").write_text('{"name":"@colbymchenry/codegraph","version":"1"}', encoding="utf-8")
            for args in (("init", "-q"), ("config", "--local", "core.autocrlf", "false"), ("add", "."),
                         ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "source")):
                subprocess.run(["git", *args], cwd=source, check=True, capture_output=True)
            before = self._inspect(source)
            self.assertFalse(before["dirty"])
            dependency.write_text("module.exports=2;\n", encoding="utf-8")
            after = self._inspect(source)
            self.assertFalse(after["dirty"])
            self.assertNotEqual(before["sourceHash"], after["sourceHash"])

    def test_internal_pnpm_junction_is_supported_and_bound_to_its_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = self._managed_runtime(root)
            target = source / "lib/node_modules/.pnpm/pkg/node_modules/pkg"
            target.mkdir(parents=True)
            module = target / "index.js"
            module.write_text("module.exports=1;\n", encoding="utf-8")
            link = source / "lib/node_modules/pkg"
            subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                           check=True, capture_output=True)
            before = self._inspect(source)
            module.write_text("module.exports=2;\n", encoding="utf-8")
            self.assertNotEqual(before["sourceHash"], self._inspect(source)["sourceHash"])

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
