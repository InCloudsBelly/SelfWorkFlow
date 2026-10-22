import hashlib
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import yaml


class CodeGraphUESourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.cleanup_temporary)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "extensions/codegraph/codegraph_ue"
        self.source.mkdir(parents=True)
        self.git(self.root, "init", "-q")
        self.git(self.source, "init", "-q")
        self.git(self.source, "remote", "add", "origin", "https://github.com/InCloudsBelly/codegraph_ue.git")
        (self.source / ".gitignore").write_text("dist/\nnode_modules/\n", encoding="utf-8")
        (self.source / "package.json").write_text(json.dumps({"name": "@colbymchenry/codegraph", "version": "1.6.2"}), encoding="utf-8")
        (self.source / "package-lock.json").write_text("{}\n", encoding="utf-8")
        (self.source / "source.ts").write_text("export const ue = true;\n", encoding="utf-8")
        self.git(self.source, "add", ".")
        self.git(self.source, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "source")
        self.commit = self.git(self.source, "rev-parse", "HEAD")
        (self.root / ".gitmodules").write_text('[submodule "extensions/codegraph/codegraph_ue"]\n path = extensions/codegraph/codegraph_ue\n url = https://github.com/InCloudsBelly/codegraph_ue.git\n', encoding="utf-8")
        self.git(self.root, "update-index", "--add", "--cacheinfo", "160000", self.commit, "extensions/codegraph/codegraph_ue")
        self.lock = {
            "schemaVersion": 1, "sourceId": "codegraph-ue",
            "canonicalUrl": "https://github.com/InCloudsBelly/codegraph_ue.git",
            "path": "extensions/codegraph/codegraph_ue", "gitlinkCommit": self.commit,
            "sourceTree": self.git(self.source, "rev-parse", "HEAD^{tree}"),
            "package": {"name": "@colbymchenry/codegraph", "version": "1.6.2",
                        "packageJsonHash": self.digest("package.json"),
                        "packageLockHash": self.digest("package-lock.json")},
        }
        self.lock_path = self.root / "dependencies/locks/codegraph-ue.lock.yaml"
        self.lock_path.parent.mkdir(parents=True)
        self.save_lock()

    def cleanup_temporary(self):
        # Windows may release a just-exited Git process's directory handle late.
        for attempt in range(6):
            try:
                self.temporary.cleanup()
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.2 * (attempt + 1))

    def git(self, root, *arguments):
        result = subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "core.fsmonitor=false", "-c", "gc.auto=0", "-c", "maintenance.auto=false", *arguments], cwd=root, capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def digest(self, name):
        return "sha256:" + hashlib.sha256((self.source / name).read_bytes()).hexdigest()

    def save_lock(self):
        self.lock_path.write_text(yaml.safe_dump(self.lock), encoding="utf-8")

    def test_fixed_source_build_is_recognized_and_runtime_drift_is_rejected(self):
        from selfworkflow.codegraph_ue import prepare_codegraph_ue
        from selfworkflow import cli

        calls = []

        def npm(command, cwd):
            calls.append(tuple(command[1:]))
            if command[1:] == ["run", "build"]:
                entry = cwd / "dist/bin/codegraph.js"
                entry.parent.mkdir(parents=True)
                entry.write_text("console.log('fixture');\n", encoding="utf-8")
                asset = cwd / "ui/dist/asset.json"
                asset.parent.mkdir(parents=True)
                asset.write_text("{}\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        report = prepare_codegraph_ue(self.root, npm_runner=npm)
        self.assertEqual(calls, [("ci",), ("run", "build")])
        self.assertEqual(report["status"], "built-and-verified")
        self.assertEqual(report["commit"], self.commit)
        def forbidden(*_arguments):
            self.fail("unchanged verified runtime must not run npm again")

        reused = prepare_codegraph_ue(self.root, npm_runner=forbidden)
        self.assertTrue(reused["reused"])
        receipt_path = self.root / "extensions/codegraph/.build/codegraph-ue.json"
        original_receipt = receipt_path.read_bytes()
        redirected = json.loads(original_receipt)
        redirected["sourcePath"] = str(self.root / "unrelated-backend")
        receipt_path.write_text(json.dumps(redirected), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "build-identity-drift"):
            prepare_codegraph_ue(self.root, npm_runner=forbidden)
        receipt_path.write_bytes(original_receipt)
        observed = cli._inspect_provider_source_identity(str(self.source))["report"]
        self.assertEqual(observed["sourceType"], "managed-submodule")
        asset = self.source / "ui/dist/asset.json"
        asset.write_text("{\"changed\":true}\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            cli._inspect_provider_source_identity(str(self.source))
        asset.write_text("{}\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "machine")}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["provider", "configure", "--codegraph-path", str(self.source), "--expected-source-hash", observed["sourceHash"]]), 0)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(["provider", "list"]), 0)
        provider = json.loads(output.getvalue())["providers"][0]
        self.assertEqual(provider["ownership"], "selfworkflow-managed")
        self.assertEqual(provider["source"]["kind"], "managed-submodule")
        (self.source / "dist/bin/codegraph.js").write_text("stale artifact\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            cli._inspect_provider_source_identity(str(self.source))
        with self.assertRaisesRegex(ValueError, "build-identity-drift"):
            prepare_codegraph_ue(self.root, npm_runner=forbidden)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(cli.main(["source", "codegraph-ue-prepare", "--repository", str(self.root)]), 63)
        self.assertIn("codegraph-ue-build-identity-drift", errors.getvalue())

    def test_dirty_source_or_mismatched_gitlink_is_rejected_before_npm(self):
        from selfworkflow.codegraph_ue import prepare_codegraph_ue

        def forbidden(*_args):
            self.fail("unverified source must not run npm")

        (self.source / "source.ts").write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source-dirty"):
            prepare_codegraph_ue(self.root, npm_runner=forbidden)
        self.git(self.source, "checkout", "--", "source.ts")
        self.lock["gitlinkCommit"] = "a" * 40
        self.save_lock()
        with self.assertRaisesRegex(ValueError, "gitlink-mismatch"):
            prepare_codegraph_ue(self.root, npm_runner=forbidden)

    def test_failed_build_does_not_publish_an_artifact_or_fall_back(self):
        from selfworkflow.codegraph_ue import prepare_codegraph_ue, RECEIPT_PATH

        calls = []

        def failing_npm(command, cwd):
            calls.append(tuple(command[1:]))
            return subprocess.CompletedProcess(command, 1, "", "fixture npm failure")

        with self.assertRaisesRegex(ValueError, "build-failed"):
            prepare_codegraph_ue(self.root, npm_runner=failing_npm)
        self.assertEqual(calls, [("ci",)])
        self.assertEqual(json.loads((self.root / RECEIPT_PATH).read_text())["status"], "failed")
        self.assertFalse((self.source / "dist/bin/codegraph.js").exists())

    @unittest.skipUnless(os.name == "nt", "Windows unsupported executable boundary")
    def test_unsupported_node_is_rejected_before_npm_gate_or_receipt(self):
        from selfworkflow.codegraph_ue import prepare_codegraph_ue, RECEIPT_PATH

        fake_node = self.root / "unsupported-node.cmd"
        fake_node.write_bytes(b"@echo off\r\nexit /b 19\r\n")
        real_which = shutil.which

        def which(name):
            return str(fake_node) if name in {"node", "node.exe"} else real_which(name)

        def forbidden(*_arguments):
            self.fail("unsupported Node must not invoke npm")

        with mock.patch("selfworkflow.codegraph_ue.shutil.which", side_effect=which):
            with self.assertRaisesRegex(ValueError, "node-runtime-unsupported"):
                prepare_codegraph_ue(self.root, npm_runner=forbidden)
        self.assertFalse((self.root / RECEIPT_PATH).exists())
        self.assertFalse((self.root / RECEIPT_PATH).with_suffix(".lock").exists())

    def test_lock_package_or_actual_source_commit_mismatch_is_rejected(self):
        from selfworkflow.codegraph_ue import verify_codegraph_ue_checkout

        self.lock["package"]["packageJsonHash"] = "sha256:" + "a" * 64
        self.save_lock()
        with self.assertRaisesRegex(ValueError, "package-mismatch"):
            verify_codegraph_ue_checkout(self.root)
        self.lock["package"]["packageJsonHash"] = self.digest("package.json")
        self.save_lock()
        self.git(self.source, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", "unexpected source")
        with self.assertRaisesRegex(ValueError, "source-mismatch"):
            verify_codegraph_ue_checkout(self.root)


class CodeGraphUEWindowsLaunchTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows npm.cmd launch seam")
    def test_npm_cmd_is_executable_through_the_real_subprocess_boundary(self):
        from selfworkflow.codegraph_ue import _npm

        npm = shutil.which("npm.cmd")
        self.assertIsNotNone(npm)
        with tempfile.TemporaryDirectory() as temporary:
            result = _npm([npm, "--version"], Path(temporary))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout.strip(), r"^\d+\.\d+\.\d+")

    def test_real_current_node_opens_a_sqlite_memory_database(self):
        from selfworkflow.codegraph_ue import _node_runtime_probe

        node = Path(shutil.which("node.exe") or shutil.which("node"))
        result = _node_runtime_probe(node)
        self.assertTrue(result["sqlite"])
        self.assertNotEqual(result["version"].split(".")[0], "25")

    def test_node25_is_rejected_even_when_sqlite_is_reported_available(self):
        from selfworkflow.codegraph_ue import _node_runtime_probe

        reported = subprocess.CompletedProcess([], 0, '{"version":"25.0.0","sqlite":true}', "")
        with mock.patch("selfworkflow.codegraph_ue.subprocess.run", return_value=reported):
            with self.assertRaisesRegex(ValueError, "node-runtime-unsupported"):
                _node_runtime_probe(Path("node.exe"))
