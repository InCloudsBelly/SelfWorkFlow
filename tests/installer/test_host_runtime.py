import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from selfworkflow.adapters import build_runtime
from selfworkflow.host_runtime import build_host_runtime
from selfworkflow.installer import (
    InstallerError, create_install_plan, apply_install_plan, verify_install,
    create_rollback_plan, apply_rollback_plan,
)


ROOT = Path(__file__).resolve().parents[2]


class HostRuntimeTests(unittest.TestCase):
    def fixture(self, root):
        source = root / "development"
        package = source / "src/selfworkflow"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        code = package / "cli.py"
        code.write_text('def main(args):\n    print("frozen-one")\n    return 0\n', encoding="utf-8")
        scripts = source / "scripts"
        scripts.mkdir()
        (scripts / "selfworkflow-host-bootstrap.py").write_bytes((ROOT / "scripts/selfworkflow-host-bootstrap.py").read_bytes())
        runtime = root / "artifact"
        runtime.mkdir()
        (runtime / "WORKFLOW.md").write_text("# fixture\n", encoding="utf-8")
        build_host_runtime(source, runtime)
        return source, runtime, root / "bin/selfworkflow.cmd"

    def plan(self, root, runtime, launcher):
        return create_install_plan(runtime, root / "agents", root / "codex", root / "state", "test",
                                   host_launcher=launcher, host_python=sys.executable)

    def run_launcher(self, launcher, *arguments, **kwargs):
        return subprocess.run(["cmd", "/d", "/c", str(launcher), *arguments], capture_output=True, text=True, **kwargs)

    def test_built_runtime_can_execute_cli_without_development_pythonpath(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary) / "runtime"
            build_runtime(ROOT, runtime, "test")
            self.assertTrue((runtime / "src/selfworkflow/cli.py").is_file())
            self.assertTrue((runtime / "host/site-packages/yaml/__init__.py").is_file())
            plan = self.plan(Path(temporary), runtime, Path(temporary) / "bin/selfworkflow.cmd")
            apply_install_plan(plan, plan["planHash"])
            actual = self.run_launcher(Path(temporary) / "bin/selfworkflow.cmd", "--help")
            self.assertEqual(actual.returncode, 0, actual.stderr)
            self.assertIn("provider", actual.stdout)

    def test_installed_launcher_executes_frozen_code_and_ignores_pythonpath(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source, runtime, launcher = self.fixture(root)
            plan = self.plan(root, runtime, launcher)
            result = apply_install_plan(plan, plan["planHash"])
            self.assertEqual(verify_install(result["manifestPath"])["status"], "verified")
            (source / "src/selfworkflow/cli.py").write_text('def main(args):\n    print("mutable-two")\n    return 0\n', encoding="utf-8")
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(source / "src")
            process = subprocess.run(["cmd", "/d", "/c", str(launcher)], cwd=source,
                                     env=environment, capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stdout.strip(), "frozen-one")

    def test_launcher_rejects_tampered_bootstrap_code_dependency_and_pointer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            _source, runtime, launcher = self.fixture(root)
            plan = self.plan(root, runtime, launcher)
            apply_install_plan(plan, plan["planHash"])
            pointer = root / "agents/selfworkflow/current.json"
            identity = json.loads(pointer.read_text())
            snapshot = Path(identity["snapshot"])
            for relative in ("host/bootstrap.py", "src/selfworkflow/cli.py", "host/site-packages/yaml/__init__.py"):
                target = snapshot / relative
                original = target.read_bytes()
                target.write_bytes(b'raise RuntimeError("must-not-execute")\n')
                try:
                    actual = self.run_launcher(launcher)
                    self.assertEqual(actual.returncode, 21)
                    self.assertIn("workflow-host-artifact-drift", actual.stderr)
                    self.assertNotIn("must-not-execute", actual.stderr)
                finally:
                    target.write_bytes(original)
            original = pointer.read_bytes()
            identity["artifactHash"] = "sha256:" + "0" * 64
            pointer.write_text(json.dumps(identity), encoding="utf-8")
            self.assertIn("workflow-host-pointer-invalid", self.run_launcher(launcher).stderr)
            pointer.write_bytes(original)

    def test_host_launcher_is_idempotent_schema_valid_and_rollback_restores_old_entry(self):
        from jsonschema import Draft202012Validator
        from selfworkflow.host_runtime import legacy_host_launcher

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            _source, runtime, launcher = self.fixture(root)
            launcher.parent.mkdir()
            original = legacy_host_launcher(Path(sys.executable))
            launcher.write_bytes(original)
            plan = self.plan(root, runtime, launcher)
            Draft202012Validator(json.loads((ROOT / "schemas/install-plan.schema.json").read_text())).validate(plan)
            result = apply_install_plan(plan, plan["planHash"])
            manifest = json.loads(Path(result["manifestPath"]).read_text())
            Draft202012Validator(json.loads((ROOT / "schemas/install-manifest.schema.json").read_text())).validate(manifest)
            same = self.plan(root, runtime, launcher)
            self.assertEqual(same["status"], "already-installed")
            self.assertEqual(apply_install_plan(same, same["planHash"])["status"], "already-installed")
            rollback = create_rollback_plan(result["transactionPath"])
            apply_rollback_plan(rollback, rollback["planHash"])
            self.assertEqual(launcher.read_bytes(), original)

    def test_foreign_launcher_and_changed_preimage_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            _source, runtime, launcher = self.fixture(root)
            launcher.parent.mkdir()
            launcher.write_bytes(b"foreign script")
            plan = self.plan(root, runtime, launcher)
            self.assertEqual(plan["status"], "paused")
            self.assertIn("unmanaged-host-launcher-conflict", plan["issues"])
            launcher.unlink()
            plan = self.plan(root, runtime, launcher)
            launcher.write_bytes(b"new external script")
            with self.assertRaisesRegex(InstallerError, "host-launcher-drift"):
                apply_install_plan(plan, plan["planHash"])
            self.assertEqual(launcher.read_bytes(), b"new external script")
            self.assertFalse((root / "agents/selfworkflow/current.json").exists())

    def test_legacy_powershell_launcher_line_endings_migrate_and_rollback_exactly(self):
        from selfworkflow.host_runtime import legacy_host_launcher

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            _source, runtime, launcher = self.fixture(root)
            launcher.parent.mkdir()
            # The former LF PowerShell here-string appends a final CRLF.
            original = legacy_host_launcher(Path(sys.executable)).replace(b"\r\n", b"\n")[:-1] + b"\r\n"
            launcher.write_bytes(original)
            plan = self.plan(root, runtime, launcher)
            self.assertEqual(plan["status"], "ready", plan["issues"])
            result = apply_install_plan(plan, plan["planHash"])
            self.assertEqual(self.run_launcher(launcher).stdout.strip(), "frozen-one")
            rollback = create_rollback_plan(result["transactionPath"])
            apply_rollback_plan(rollback, rollback["planHash"])
            self.assertEqual(launcher.read_bytes(), original)

    def test_python_drift_reparse_and_failed_publish_are_rejected_or_rolled_back(self):
        import shutil
        import selfworkflow.installer as installer
        from selfworkflow.host_runtime import legacy_host_launcher

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            _source, runtime, launcher = self.fixture(root)
            python = root / "python.exe"
            shutil.copyfile(sys.executable, python)
            plan = create_install_plan(runtime, root / "agents", root / "codex", root / "state", "test",
                                       host_launcher=launcher, host_python=python)
            python.write_bytes(b"changed executable")
            with self.assertRaises(InstallerError):
                apply_install_plan(plan, plan["planHash"])
            self.assertFalse(launcher.exists())
            launcher.parent.mkdir()
            original = legacy_host_launcher(Path(sys.executable))
            launcher.write_bytes(original)
            plan = self.plan(root, runtime, launcher)
            publish = installer._publish_operation

            def fail_at_launcher(operation, content):
                if operation["target"] == str(launcher):
                    raise OSError("fixture publish failure")
                publish(operation, content)

            with patch.object(installer, "_publish_operation", side_effect=fail_at_launcher):
                with self.assertRaisesRegex(InstallerError, "apply-failed"):
                    apply_install_plan(plan, plan["planHash"])
            self.assertEqual(launcher.read_bytes(), original)
            self.assertFalse((root / "agents/selfworkflow/current.json").exists())
            self.assertFalse((root / "state/install.lock").exists())

    def test_unicode_space_paths_and_reparse_snapshot_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "中文 path"
            root.mkdir()
            _source, runtime, launcher = self.fixture(root)
            plan = self.plan(root, runtime, launcher)
            apply_install_plan(plan, plan["planHash"])
            information = self.run_launcher(launcher, "--host-info")
            self.assertEqual(information.returncode, 0, information.stderr)
            snapshot = Path(json.loads(information.stdout)["snapshot"])
            target = snapshot / "src"
            original = snapshot / "moved-src"
            target.rename(original)
            linked = subprocess.run(["cmd", "/c", "mklink", "/J", str(target), str(original)], capture_output=True)
            self.assertEqual(linked.returncode, 0, linked.stderr)
            actual = self.run_launcher(launcher)
            self.assertEqual(actual.returncode, 21)
            self.assertIn("workflow-host-reparse-path", actual.stderr)
            target.rmdir()
            original.rename(target)

    def test_launcher_drift_after_locked_baseline_preserves_external_edit(self):
        import selfworkflow.installer as installer
        from selfworkflow.host_runtime import legacy_host_launcher

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            _source, runtime, launcher = self.fixture(root)
            launcher.parent.mkdir()
            launcher.write_bytes(legacy_host_launcher(Path(sys.executable)))
            plan = self.plan(root, runtime, launcher)
            pointer = root / "agents/selfworkflow/current.json"
            external_edit = b"external edit after locked baseline"
            publish = installer._publish_operation

            def inject_external_edit(operation, content):
                publish(operation, content)
                if operation["target"] == str(pointer):
                    launcher.write_bytes(external_edit)

            with patch.object(installer, "_publish_operation", side_effect=inject_external_edit):
                with self.assertRaisesRegex(InstallerError, "apply-failed"):
                    apply_install_plan(plan, plan["planHash"])
            self.assertEqual(launcher.read_bytes(), external_edit)
            self.assertFalse(pointer.exists())
            self.assertFalse((root / "state/install.lock").exists())

    def test_already_installed_plan_and_verify_reject_changed_python(self):
        import shutil

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            _source, runtime, launcher = self.fixture(root)
            python = root / "python.exe"
            shutil.copyfile(sys.executable, python)

            def make_plan():
                return create_install_plan(runtime, root / "agents", root / "codex", root / "state", "test",
                                           host_launcher=launcher, host_python=python)

            plan = make_plan()
            result = apply_install_plan(plan, plan["planHash"])
            same = make_plan()
            self.assertEqual(same["status"], "already-installed")
            original = launcher.read_bytes()
            python.write_bytes(python.read_bytes() + b"changed executable")
            with self.assertRaises(InstallerError):
                apply_install_plan(same, same["planHash"])
            with self.assertRaises(InstallerError):
                verify_install(result["manifestPath"])
            self.assertEqual(launcher.read_bytes(), original)

    def test_launcher_accepts_unicode_filename_in_hash_bound_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            _source, runtime, launcher = self.fixture(root)
            (runtime / "host/site-packages/中文模块.py").write_text("# fixture only\n", encoding="utf-8")
            plan = self.plan(root, runtime, launcher)
            apply_install_plan(plan, plan["planHash"])
            actual = self.run_launcher(launcher, "--host-info")
            self.assertEqual(actual.returncode, 0, actual.stderr)
            self.assertEqual(json.loads(actual.stdout)["artifactHash"], plan["artifactHash"])


if __name__ == "__main__":
    unittest.main()
