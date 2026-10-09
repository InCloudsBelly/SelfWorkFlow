from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

from selfworkflow.v3.graft_lifecycle import GraftProjectError, GraftProjectLifecycle
from selfworkflow.v3.providers.codegraph import CommandResult
from selfworkflow.v3.providers.graft import GraftAdapter


ROOT = Path(__file__).resolve().parents[2]
GRAFT_CLI = ROOT / "dependencies" / "upstream" / "graft" / "dist" / "cli.js"


class _NodeCommandPort:
    def __init__(self) -> None:
        self.node = shutil.which("node") or "node"
        self.calls = []

    def run(self, argv, *, cwd=None):
        self.calls.append(tuple(argv))
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "DO_NOT_TRACK": "1"},
            timeout=120,
        )
        return CommandResult(
            completed.returncode, completed.stdout, completed.stderr
        )


class GraftRealE2ETests(unittest.TestCase):
    def test_cpp_project_queries_and_agent_write_worker(self):
        if not GRAFT_CLI.is_file():
            self.fail("pinned Graft dist/cli.js is missing")

        with TemporaryDirectory(prefix="selfworkflow-graft-e2e-") as temporary:
            project = Path(temporary).resolve()
            source = project / "src" / "main.cpp"
            source.parent.mkdir(parents=True)
            source.write_text(
                "#include <string>\n"
                "int helper(int value) { return value + 1; }\n"
                "int main() { return helper(41); }\n",
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "init", "-q", str(project)], check=True,
                capture_output=True, text=True,
            )

            port = _NodeCommandPort()
            adapter = GraftAdapter(
                command_port=port,
                command_prefix=(shutil.which("node") or "node", str(GRAFT_CLI)),
                ownership="selfworkflow-managed",
            )
            lifecycle = GraftProjectLifecycle(adapter)

            with self.assertRaisesRegex(GraftProjectError, "graft-graph-not-ready"):
                lifecycle.query(str(project), "helper", query_kind="ask")
            self.assertFalse((project / "graft").exists())

            initialized = lifecycle.preflight(str(project))
            self.assertEqual(initialized["status"], "initialized")
            wiring = project / "graft" / ".graph" / "wiring.json"
            self.assertTrue(wiring.is_file())
            self.assertIn("/graft/", (project / ".gitignore").read_text())
            self.assertEqual(adapter.version()["version"], "0.21.1")
            self.assertEqual(adapter.plan_query(str(project), "helper")["queryKind"], "ask")

            query_specs = (
                ("ask", "helper"),
                ("map", "orientation"),
                ("grep", "helper"),
                ("callers", "helper"),
                ("skeleton", "src/main.cpp"),
            )
            for query_kind, query in query_specs:
                with self.subTest(query_kind=query_kind):
                    result = lifecycle.query(
                        str(project), query, query_kind=query_kind
                    )
                    self.assertEqual(result["queryKind"], query_kind)
                    self.assertTrue(result["readOnly"])
                    self.assertEqual(result["sideEffectClass"], "none")
                    self.assertIsInstance(result["data"], dict)

            graph_before = wiring.read_bytes()
            source.write_text(
                source.read_text(encoding="utf-8")
                + "int added(int value) { return value * 2; }\n",
                encoding="utf-8",
            )
            queued = lifecycle.enqueue(str(project), ["src/main.cpp"])
            coalesced = lifecycle.enqueue(str(project), ["src/main.cpp"])
            self.assertEqual(queued["status"], "queued")
            self.assertEqual(coalesced["status"], "coalesced")
            updated = lifecycle.run_once(
                str(project), conversation_id="thread-real-e2e",
            )
            self.assertEqual(updated["status"], "succeeded")
            self.assertFalse(updated["pending"])
            self.assertNotEqual(
                graph_before, wiring.read_bytes()
            )
            self.assertEqual(
                lifecycle.query_status(str(project))["freshness"], "fresh"
            )

            maintenance = adapter.plan_maintenance("rebuild", str(project))
            rebuilt = adapter.execute_maintenance(
                maintenance,
                str(project),
                confirmed_plan_hash=maintenance["planHash"],
            )
            self.assertEqual(rebuilt["status"], "succeeded")
            self.assertTrue(all("--deep" not in call for call in port.calls))


if __name__ == "__main__":
    unittest.main()
