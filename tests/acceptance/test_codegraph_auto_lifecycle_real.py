"""Opt-in checks against the configured official CodeGraph CLI and MCP watcher."""

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import unittest

from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError, CodeGraphProjectLifecycle
from selfworkflow.v3.providers.codegraph import CodeGraphAdapter, CommandResult


class RealCommandPort:
    def __init__(self, environment):
        self.environment = environment
        self.calls = []

    def run(self, argv, *, cwd=None):
        self.calls.append(tuple(argv))
        completed = subprocess.run(
            argv, cwd=cwd, env=self.environment, capture_output=True,
            text=True, encoding="utf-8", timeout=90,
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@unittest.skipUnless(
    os.environ.get("SELFWORKFLOW_CODEGRAPH_E2E_NODE")
    and os.environ.get("SELFWORKFLOW_CODEGRAPH_E2E_SCRIPT"),
    "set SELFWORKFLOW_CODEGRAPH_E2E_NODE/SCRIPT to run the real provider checks",
)
class CodeGraphAutoLifecycleRealTests(unittest.TestCase):
    def setUp(self):
        self.node = os.environ["SELFWORKFLOW_CODEGRAPH_E2E_NODE"]
        self.script = os.environ["SELFWORKFLOW_CODEGRAPH_E2E_SCRIPT"]
        self.git = os.environ.get("SELFWORKFLOW_CODEGRAPH_E2E_GIT") or shutil.which("git")
        if not self.git:
            self.skipTest("Git is required for the isolated branch fixture")
        self.temporary = tempfile.TemporaryDirectory(
            prefix="selfworkflow-cg-auto-",
            dir=os.environ.get("SELFWORKFLOW_CODEGRAPH_E2E_TEMP"),
            ignore_cleanup_errors=True,
        )
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name).resolve()
        self.environment = dict(os.environ)
        self.environment.update({
            "CODEGRAPH_NO_DAEMON": "1", "CODEGRAPH_WASM_RELAUNCHED": "1",
            "CODEGRAPH_TELEMETRY": "0",
        })
        # Native Windows recursive watching requires the long form of TEMP/TMP.
        if os.environ.get("SELFWORKFLOW_CODEGRAPH_E2E_TEMP"):
            self.environment["TEMP"] = os.environ["SELFWORKFLOW_CODEGRAPH_E2E_TEMP"]
            self.environment["TMP"] = self.environment["TEMP"]
        self.port = RealCommandPort(self.environment)
        self._git("init", "-b", "codex/fixture-alpha")
        self._write(".gitignore", ".codegraph/\nignored/\n")
        self._write("alpha.py", "def branch_alpha_only():\n    return 1\n")
        self._commit("alpha fixture")
        self._git("checkout", "-b", "codex/fixture-beta")
        (self.project / "alpha.py").unlink()
        self._write("beta.py", "def branch_beta_only():\n    return 2\n")
        self._commit("beta fixture")
        self._git("checkout", "codex/fixture-alpha")

    def _lifecycle(self):
        # Match the official CLI/Manager's separate adapter session per boundary.
        return CodeGraphProjectLifecycle(CodeGraphAdapter(
            command_port=self.port, command_prefix=(self.node, self.script),
            ownership="user-local",
        ))

    def _git(self, *arguments, project=None):
        root = project or self.project
        result = subprocess.run(
            [self.git, "-c", "user.name=SelfWorkflow fixture", "-c",
             "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
             "-c", f"core.hooksPath={root / 'empty-hooks'}", *arguments],
            cwd=root, env=self.environment, capture_output=True,
            text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def _commit(self, message):
        self._git("add", "--all")
        self._git("commit", "-m", message)

    def _write(self, relative, content):
        target = self.project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def _symbols(self, name, *, project=None):
        result = self.port.run((
            self.node, self.script, "query", name, "--json", "--path", str(project or self.project),
        ))
        self.assertEqual(result.exit_code, 0, result.stderr)
        raw = json.loads(result.stdout)
        self.assertIsInstance(raw, list)
        return [entry["node"] for entry in raw]

    def _has_symbol(self, name):
        return any(node.get("name") == name for node in self._symbols(name))

    def test_branch_manual_untracked_and_workflow_batches_reconcile_actual_nodes(self):
        initial = self._lifecycle().preflight(str(self.project))
        self.assertEqual(initial["actions"], ["initialize"])
        self.assertTrue(self._has_symbol("branch_alpha_only"))

        self._git("checkout", "codex/fixture-beta")
        switched = self._lifecycle().query(str(self.project), "branch_beta_only")
        self.assertEqual(switched["freshness"], "fresh")
        self.assertTrue(self._has_symbol("branch_beta_only"))
        self.assertFalse(self._has_symbol("branch_alpha_only"))

        self._write("beta.py", "def manual_tracked_revision():\n    return 3\n")
        self._write("untracked.py", "def untracked_source_symbol():\n    return 4\n")
        self._write("ignored/hidden.py", "def ignored_symbol():\n    return 5\n")
        self.assertIn("?? untracked.py", self._git("status", "--short"))
        edited = self._lifecycle().query(str(self.project), "manual_tracked_revision")
        self.assertEqual(edited["freshness"], "fresh")
        self.assertTrue(self._has_symbol("manual_tracked_revision"))
        self.assertTrue(self._has_symbol("untracked_source_symbol"))
        self.assertFalse(self._has_symbol("branch_beta_only"))
        self.assertFalse(self._has_symbol("ignored_symbol"))

        (self.project / "beta.py").rename(self.project / "renamed.py")
        (self.project / "untracked.py").unlink()
        self._write("batch_new.py", "def final_batch_symbol():\n    return 6\n")
        updated = self._lifecycle().sync(str(self.project), changed_paths=(
            "beta.py", "renamed.py", "untracked.py", "batch_new.py", "renamed.py",
        ))
        self.assertEqual(updated["freshness"], "fresh")
        self.assertEqual(updated["changedPathCount"], 4)
        self.assertTrue(self._has_symbol("final_batch_symbol"))
        self.assertFalse(self._has_symbol("untracked_source_symbol"))
        renamed = self._symbols("manual_tracked_revision")
        self.assertIn("renamed.py", json.dumps(renamed))
        self.assertNotIn("beta.py", json.dumps(renamed))

        unchanged_node = self._symbols("final_batch_symbol")[0]
        before = len(self.port.calls)
        fresh = self._lifecycle().sync(str(self.project), changed_paths=("batch_new.py",))
        self.assertEqual(fresh["actions"], ["sync"])
        self.assertEqual([call[2] for call in self.port.calls[before:]], ["status", "sync", "status"])
        self.assertEqual(self._symbols("final_batch_symbol")[0]["updatedAt"], unchanged_node["updatedAt"])

    def test_official_mcp_default_watcher_and_cross_project_preflight(self):
        self._lifecycle().preflight(str(self.project))
        other_temporary = tempfile.TemporaryDirectory(
            prefix="selfworkflow-cg-cross-", dir=self.project.parent, ignore_cleanup_errors=True,
        )
        # Register before the MCP cleanup so cached DB connections close first.
        self.addCleanup(other_temporary.cleanup)
        other_project = Path(other_temporary.name).resolve()
        messages = queue.Queue()
        watcher_active = threading.Event()
        errors = []
        process = subprocess.Popen(
            [self.node, self.script, "serve", "--mcp", "--path", str(self.project)],
            cwd=self.project, env=self.environment, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1,
        )
        self.addCleanup(self._stop_mcp, process)

        def read_stdout():
            for line in process.stdout:
                try:
                    messages.put(json.loads(line))
                except json.JSONDecodeError:
                    errors.append(line)

        def read_stderr():
            for line in process.stderr:
                errors.append(line)
                if "File watcher active" in line:
                    watcher_active.set()

        readers = [threading.Thread(target=reader, daemon=True)
                   for reader in (read_stdout, read_stderr)]
        for reader in readers:
            reader.start()
        process.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-11-25", "capabilities": {},
                "clientInfo": {"name": "SelfWorkflow fixture", "version": "1"},
                "rootUri": self.project.as_uri(),
            },
        }) + "\n")
        process.stdin.flush()
        self.assertTrue(watcher_active.wait(30), "".join(errors)[-2000:])
        response = messages.get(timeout=10)
        self.assertEqual(response.get("id"), 1)
        self.assertNotIn("error", response)
        process.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        process.stdin.flush()
        def explore(project, query, request_id):
            process.stdin.write(json.dumps({
                "jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {
                    "name": "codegraph_explore", "arguments": {
                        "projectPath": str(project), "query": query, "maxFiles": 1,
                    },
                },
            }) + "\n")
            process.stdin.flush()
            response = messages.get(timeout=15)
            self.assertEqual(response.get("id"), request_id)
            self.assertNotIn("error", response)
            self.assertNotEqual(response.get("result", {}).get("isError"), True)
            return response

        # Complete the initial read/catch-up gate before testing later file events.
        self.assertIn("branch_alpha_only", json.dumps(explore(self.project, "branch_alpha_only", 2)))

        self._write("alpha.py", "def native_watcher_new_symbol():\n    return 7\n")
        self._write("native_untracked.py", "def native_untracked_symbol():\n    return 8\n")
        before = len(self.port.calls)
        deadline = time.monotonic() + 30
        found = False
        while time.monotonic() < deadline and process.poll() is None:
            if self._has_symbol("native_watcher_new_symbol") and self._has_symbol("native_untracked_symbol"):
                found = True
                break
        self.assertTrue(found, "official watcher did not update nodes: " + "".join(errors)[-2000:])
        self.assertFalse(self._has_symbol("branch_alpha_only"))
        self.assertTrue(all(call[2] == "query" for call in self.port.calls[before:]))
        # Only after observing real new nodes do we verify the workflow reuses them.
        unchanged_node = self._symbols("native_watcher_new_symbol")[0]
        fresh = self._lifecycle().sync(str(self.project), changed_paths=("alpha.py", "native_untracked.py"))
        self.assertEqual(fresh["actions"], ["sync"])
        self.assertEqual(self._symbols("native_watcher_new_symbol")[0]["updatedAt"], unchanged_node["updatedAt"])

        # The same MCP session reads another root whose cached graph has no watcher.
        self._git("init", "-b", "codex/cross-alpha", project=other_project)
        (other_project / ".gitignore").write_text(".codegraph/\n", encoding="utf-8")
        (other_project / "cross.py").write_text("def cross_branch_alpha_only():\n    return 1\n", encoding="utf-8")
        self._git("add", "--all", project=other_project)
        self._git("commit", "-m", "cross alpha", project=other_project)
        self._git("checkout", "-b", "codex/cross-beta", project=other_project)
        (other_project / "cross.py").write_text("def cross_branch_beta_only():\n    return 2\n", encoding="utf-8")
        self._git("add", "--all", project=other_project)
        self._git("commit", "-m", "cross beta", project=other_project)
        self._git("checkout", "codex/cross-alpha", project=other_project)
        self._lifecycle().preflight(str(other_project))
        self.assertIn("cross_branch_alpha_only", json.dumps(explore(other_project, "cross_branch_alpha_only", 3)))
        self._git("checkout", "codex/cross-beta", project=other_project)
        self.assertEqual(self._git("status", "--porcelain", project=other_project), "")
        self.assertFalse(self._symbols("cross_branch_beta_only", project=other_project))
        self.assertTrue(self._symbols("cross_branch_alpha_only", project=other_project))
        before = len(self.port.calls)
        cross = self._lifecycle().preflight(str(other_project))
        self.assertEqual(cross["freshness"], "fresh")
        self.assertEqual([call[2] for call in self.port.calls[before:]], ["status", "sync", "status"])
        self.assertIn("cross_branch_beta_only", json.dumps(explore(other_project, "cross_branch_beta_only", 4)))
        self.assertFalse(self._symbols("cross_branch_alpha_only", project=other_project))
        self.assertTrue(self._has_symbol("native_watcher_new_symbol"))

    def test_native_lock_contention_is_busy_and_next_boundary_recovers(self):
        self._lifecycle().preflight(str(self.project))
        self._git("checkout", "codex/fixture-beta")
        sdk = Path(self.script).resolve().parent.parent / "index.js"
        holder_code = (
            "(async () => {\n"
            "const { default: CodeGraph } = require(" + json.dumps(str(sdk)) + ");\n"
            "const { readSync } = require('node:fs');\n"
            "const cg = await CodeGraph.open(process.argv[1]);\n"
            "let held = false;\n"
            "try { await cg.sync({ throwOnLockFailure: true, onProgress(progress) {\n"
            "  if (!held && progress.phase === 'scanning') {\n"
            "    held = true; console.log('NATIVE_SYNC_LOCK_HELD');\n"
            "    readSync(0, Buffer.alloc(1), 0, 1, null);\n"
            "  }\n"
            "}}); } finally { cg.destroy(); }\n"
            "})().catch(error => { console.error(error); process.exitCode = 1; });\n"
        )
        holder = subprocess.Popen(
            [self.node, "-e", holder_code, str(self.project)],
            cwd=self.project, env=self.environment, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        )
        self.addCleanup(self._stop_mcp, holder)
        ready = queue.Queue()
        threading.Thread(target=lambda: ready.put(holder.stdout.readline()), daemon=True).start()
        self.assertEqual(ready.get(timeout=30).strip(), "NATIVE_SYNC_LOCK_HELD")
        before = len(self.port.calls)
        with self.assertRaises(CodeGraphProjectError) as caught:
            self._lifecycle().preflight(str(self.project))
        self.assertEqual(caught.exception.reason, "codegraph-project-busy")
        self.assertEqual([call[2] for call in self.port.calls[before:]], ["status", "sync"])
        self.assertFalse(self._has_symbol("branch_beta_only"))
        self.assertTrue(self._has_symbol("branch_alpha_only"))
        holder.communicate(input="x", timeout=30)
        self.assertEqual(holder.returncode, 0)
        recovered = self._lifecycle().preflight(str(self.project))
        self.assertEqual(recovered["freshness"], "fresh")
        self.assertTrue(self._has_symbol("branch_beta_only"))
        self.assertFalse(self._has_symbol("branch_alpha_only"))

    @staticmethod
    def _stop_mcp(process):
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=8)
        for stream in (process.stdout, process.stderr):
            if stream:
                stream.close()


if __name__ == "__main__":
    unittest.main()
