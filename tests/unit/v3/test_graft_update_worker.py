import json
from pathlib import Path
import tempfile
import unittest


class FakeGraft:
    def __init__(
        self, *, missing=True, fail_build=False, unavailable=False,
        fail_status=False,
    ):
        self.missing = missing
        self.fail_build = fail_build
        self.unavailable = unavailable
        self.fail_status = fail_status
        self.builds = []

    def provider_preflight(self):
        if self.unavailable:
            from selfworkflow.v3.providers.graft import GraftAdapterError
            raise GraftAdapterError("graft-provider-unavailable")
        return {
            "providerId": "graft", "providerStatus": "verified",
            "version": "0.18.0", "queryCapabilities": [
                "build", "check",
                "ask", "callers", "grep", "map", "skeleton",
            ],
        }

    def status(self, project_root):
        if self.fail_status:
            from selfworkflow.v3.providers.graft import GraftAdapterError
            raise GraftAdapterError("graft-command-failed")
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
        self.assertEqual(result["providerStatus"], "verified")
        self.assertEqual(result["graphStatus"], "fresh")
        self.assertEqual(len(provider.builds), 1)
        self.assertIn("/graft/", (self.root / ".gitignore").read_text())

    def test_provider_unavailable_never_initializes_or_builds_project_graph(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle

        provider = FakeGraft(unavailable=True)
        result = GraftProjectLifecycle(provider).preflight(str(self.root))

        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["providerStatus"], "unavailable")
        self.assertEqual(result["graphStatus"], "unknown")
        self.assertEqual(provider.builds, [])
        self.assertFalse((self.root / "graft").exists())
        self.assertFalse((self.root / ".gitignore").exists())

    def test_provider_unavailable_does_not_enqueue_or_create_project_cache(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle

        result = GraftProjectLifecycle(FakeGraft(unavailable=True)).enqueue(
            str(self.root), ["src/a.cpp"],
        )

        self.assertEqual(result["status"], "unverified")
        self.assertFalse(result["pending"])
        self.assertEqual(result["providerStatus"], "unavailable")
        self.assertFalse((self.root / "graft").exists())
        self.assertFalse((self.root / ".gitignore").exists())

    def test_worker_keeps_existing_queue_when_provider_becomes_unavailable(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle

        provider = FakeGraft(missing=False)
        lifecycle = GraftProjectLifecycle(provider)
        lifecycle.enqueue(str(self.root), ["src/a.cpp"])
        provider.unavailable = True

        result = lifecycle.run_once(str(self.root))

        self.assertEqual(result["status"], "unverified")
        self.assertTrue(result["pending"])
        self.assertEqual(provider.builds, [])
        queue = json.loads(
            (self.root / "graft/.cache/selfworkflow/queue.json").read_text()
        )
        self.assertEqual(queue["changedPaths"], ["src/a.cpp"])

    def test_query_fails_closed_when_provider_preflight_is_unavailable(self):
        from selfworkflow.v3.graft_lifecycle import (
            GraftProjectError, GraftProjectLifecycle,
        )

        with self.assertRaisesRegex(
            GraftProjectError, "graft-provider-unavailable",
        ):
            GraftProjectLifecycle(FakeGraft(unavailable=True)).query(
                str(self.root), "helper", query_kind="ask",
            )

    def test_graph_check_failure_preserves_verified_provider_state(self):
        from selfworkflow.v3.graft_lifecycle import GraftProjectLifecycle

        result = GraftProjectLifecycle(
            FakeGraft(missing=False, fail_status=True),
        ).preflight(str(self.root))

        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["providerStatus"], "verified")
        self.assertEqual(result["graphStatus"], "unknown")
        self.assertEqual(result["reason"], "graft-command-failed")

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
