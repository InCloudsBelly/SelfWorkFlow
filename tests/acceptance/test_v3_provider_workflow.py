from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import unittest
from unittest.mock import patch

from selfworkflow.cli import main


class FakeManager:
    def __init__(self):
        self.calls = []

    def preflight(self, project_root):
        self.calls.append(("preflight", project_root))
        return {"providerId": "codegraph", "status": "succeeded", "freshness": "fresh"}

    def sync(self, project_root, changed_paths):
        self.calls.append(("sync", project_root, tuple(changed_paths)))
        return {"providerId": "codegraph", "status": "succeeded", "freshness": "fresh"}

    def query(self, provider_id, project_root, query, *, query_kind):
        self.calls.append(("query", provider_id, project_root, query, query_kind))
        return {"providerId": "codegraph", "status": "succeeded", "freshness": "fresh", "data": "ok"}

    def status(self, provider_id, project_root):
        self.calls.append(("status", provider_id, project_root))
        return {"providerId": "codegraph", "freshness": "fresh"}


class CodeGraphProviderWorkflowAcceptanceTests(unittest.TestCase):
    def invoke(self, arguments, manager):
        stdout, stderr = StringIO(), StringIO()
        with patch("selfworkflow.cli._provider_manager", return_value=manager), \
             redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(arguments)
        return code, json.loads(stdout.getvalue()), stderr.getvalue()

    def test_preflight_is_the_single_read_route_and_does_not_need_conversation_state(self):
        manager = FakeManager()
        code, payload, errors = self.invoke(
            ["provider", "preflight", "--project-root", "C:/work/project"], manager
        )
        self.assertEqual(code, 0, errors)
        self.assertEqual(payload["freshness"], "fresh")
        self.assertEqual(manager.calls, [("preflight", "C:/work/project")])

    def test_sync_coalesces_changed_paths_and_uses_codegraph_route(self):
        manager = FakeManager()
        code, payload, errors = self.invoke(
            [
                "provider", "sync", "--project-root", "C:/work/project",
                "--changed-path", "src/main.cpp", "--changed-path", "src/helper.cpp",
            ], manager
        )
        self.assertEqual(code, 0, errors)
        self.assertEqual(payload["providerId"], "codegraph")
        self.assertEqual(manager.calls, [(
            "sync", "C:/work/project", ("src/main.cpp", "src/helper.cpp")
        )])

    def test_query_routes_only_after_the_lifecycle_manager(self):
        manager = FakeManager()
        code, payload, errors = self.invoke(
            [
                "provider", "query", "--project-root", "C:/work/project",
                "--query", "find request flow", "--query-kind", "ask",
            ], manager
        )
        self.assertEqual(code, 0, errors)
        self.assertEqual(payload["data"], "ok")
        self.assertEqual(manager.calls, [(
            "query", "codegraph", "C:/work/project", "find request flow", "ask"
        )])

    def test_legacy_routes_are_not_accepted_by_the_cli(self):
        with self.assertRaises(SystemExit):
            main(["provider", "graft-sync", "--project-root", "C:/work/project"])


if __name__ == "__main__":
    unittest.main()
