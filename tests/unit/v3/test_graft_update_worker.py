import json
from pathlib import Path
import tempfile
import unittest


class FakeGraft:
    def __init__(self, *, missing=True, fail_build=False):
        self.missing = missing
        self.fail_build = fail_build
        self.builds = []

    def status(self, project_root):
        return {
            "providerId": "graft",
            "initialized": not self.missing,
            "freshness": "missing" if self.missing else "fresh",
        }

    def build_structural(self, project_root):
        self.builds.append(project_root)
        if self.fail_build:
            from selfworkflow.v3.providers.graft import GraftAdapterError
            raise GraftAdapterError("graft-command-failed")
        self.missing = False
        return {"providerId": "graft", "operation": "build", "status": "succeeded"}


class GraftUpdateWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root / ".git").mkdir()

    def test_first_code_preflight_initializes_missing_project_graph(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle

        provider = FakeGraft()
        result = GraftProjectLifecycle(provider).preflight(str(self.root))

        self.assertEqual(result["status"], "initialized")
        self.assertEqual(len(provider.builds), 1)
        self.assertIn("/graft/", (self.root / ".gitignore").read_text())

    def test_write_events_are_coalesced_into_one_structural_build(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle

        provider = FakeGraft(missing=False)
        lifecycle = GraftProjectLifecycle(provider)
        first = lifecycle.enqueue(str(self.root), ["src/a.cpp"])
        second = lifecycle.enqueue(str(self.root), ["src/b.cpp", "src/a.cpp"])

        self.assertEqual(first["status"], "queued")
        self.assertEqual(second["status"], "coalesced")
        result = lifecycle.run_once(str(self.root))
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(len(provider.builds), 1)
        state = json.loads(
            (self.root / "graft/.cache/selfworkflow/state.json").read_text()
        )
        self.assertEqual(state["lastChangedPaths"], ["src/a.cpp", "src/b.cpp"])

    def test_build_failure_retains_retryable_pending_event_and_old_graph(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle

        provider = FakeGraft(missing=False, fail_build=True)
        lifecycle = GraftProjectLifecycle(provider)
        lifecycle.enqueue(str(self.root), ["src/a.cpp"])

        result = lifecycle.run_once(str(self.root))

        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["retryable"])
        queue = json.loads(
            (self.root / "graft/.cache/selfworkflow/queue.json").read_text()
        )
        self.assertEqual(queue["changedPaths"], ["src/a.cpp"])

    def test_query_path_never_creates_worker_queue(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle

        provider = FakeGraft(missing=False)
        lifecycle = GraftProjectLifecycle(provider)

        result = lifecycle.query_status(str(self.root))

        self.assertEqual(result["freshness"], "fresh")
        self.assertFalse((self.root / "graft").exists())

    def test_outside_or_graph_paths_are_rejected(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectError, GraftProjectLifecycle

        provider = FakeGraft(missing=False)
        lifecycle = GraftProjectLifecycle(provider)
        with self.assertRaisesRegex(GraftProjectError, "graft-event-path-invalid"):
            lifecycle.enqueue(str(self.root), ["graft/INDEX.md"])


if __name__ == "__main__":
    unittest.main()
