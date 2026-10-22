import json
from pathlib import Path
import tempfile
import unittest


class FakeCommandPort:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def run(self, argv, *, cwd=None):
        self.calls.append({"argv": tuple(argv), "cwd": cwd})
        if not self.results:
            raise AssertionError("unexpected command")
        return self.results.pop(0)


class CodeGraphLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name).resolve()

    def _result(self, exit_code=0, stdout="", stderr=""):
        from selfworkflow.v3.providers.codegraph import CommandResult

        return CommandResult(exit_code=exit_code, stdout=stdout, stderr=stderr)

    def _status(self, *, initialized=True, pending=None, state="complete", reindex=False, pending_refs=0):
        return json.dumps({
            "initialized": initialized,
            "projectPath": str(self.project),
            "indexPath": str(self.project / ".codegraph"),
            "lastIndexed": "2026-10-12T00:00:00.000Z" if initialized else None,
            "fileCount": 1 if initialized else 0,
            "nodeCount": 2 if initialized else 0,
            "edgeCount": 1 if initialized else 0,
            "pendingChanges": pending or {"added": 0, "modified": 0, "removed": 0},
            "worktreeMismatch": None,
            "index": {
                "state": state,
                "reindexRecommended": reindex,
                "pendingRefs": pending_refs,
            },
        })

    def _lifecycle(self, port, *, metadata_capability=False):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectLifecycle
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapter

        adapter = CodeGraphAdapter(
            command_port=port,
            command_prefix=("codegraph",),
            ownership="selfworkflow-managed",
            allow_metadata_only_status=metadata_capability,
        )
        return CodeGraphProjectLifecycle(adapter), adapter

    def test_metadata_gate_is_unknown_until_sync_and_strict_status_succeed(self):
        metadata = json.loads(self._status())
        metadata.update({"pendingChanges": None, "workingTreeChecked": False})
        port = FakeCommandPort(
            self._result(stdout="  --metadata-only  Read index metadata\n"),
            self._result(stdout=json.dumps(metadata)),
            self._result(stdout="synced"),
            self._result(stdout=self._status()),
        )
        lifecycle, _ = self._lifecycle(port, metadata_capability=True)
        result = lifecycle.ensure(str(self.project))
        self.assertEqual(result["freshness"], "fresh")
        self.assertEqual(result["actions"], ["sync"])
        self.assertEqual([call["argv"][1:] for call in port.calls], [
            ("status", "--help"), ("status", str(self.project).replace("\\", "/"), "--json", "--metadata-only"),
            ("sync", str(self.project).replace("\\", "/")), ("status", str(self.project).replace("\\", "/"), "--json"),
        ])

    def test_metadata_then_sync_cannot_hide_a_same_stat_edit_reported_by_strict_status(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        metadata = json.loads(self._status())
        metadata.update(pendingChanges=None, workingTreeChecked=False)
        database = self.project / ".codegraph/codegraph.db"
        database.parent.mkdir()
        database.write_bytes(b"preserve the unsynced index")
        for boundary in ("ensure", "preflight", "sync", "query"):
            with self.subTest(boundary=boundary):
                port = FakeCommandPort(
                    self._result(stdout="  --metadata-only  Read index metadata\n"),
                    self._result(stdout=json.dumps(metadata)),
                    self._result(stdout="synced"),
                    self._result(stdout=self._status(pending={"added": 0, "modified": 1, "removed": 0})),
                )
                lifecycle, _ = self._lifecycle(port, metadata_capability=True)
                arguments = (str(self.project), "symbol") if boundary == "query" else (str(self.project),)
                with self.assertRaises(CodeGraphProjectError) as caught:
                    getattr(lifecycle, boundary)(*arguments)
                self.assertEqual(caught.exception.reason, "codegraph-index-not-fresh")
                self.assertEqual([call["argv"][1] for call in port.calls], ["status", "status", "sync", "status"])
                self.assertEqual(database.read_bytes(), b"preserve the unsynced index")

    def test_metadata_config_version_and_busy_gates_preserve_the_database_without_writers(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        database = self.project / ".codegraph/codegraph.db"
        database.parent.mkdir()
        database.write_bytes(b"last good index")
        cases = (
            ({"indexingConfig": {"error": "invalid JSON"}}, "codegraph-indexing-config-invalid"),
            ({"index": {"state": "indexing"}}, "codegraph-project-busy"),
            ({"index": {"state": "complete", "reindexRecommended": True}}, "codegraph-rebuild-required-preserving-existing-index"),
        )
        for boundary in ("ensure", "preflight", "sync", "query"):
            for fields, reason in cases:
                with self.subTest(boundary=boundary, reason=reason):
                    value = json.loads(self._status())
                    value.update(fields, pendingChanges=None, workingTreeChecked=False)
                    port = FakeCommandPort(self._result(stdout="  --metadata-only  Read metadata\n"),
                                           self._result(stdout=json.dumps(value)))
                    lifecycle, _ = self._lifecycle(port, metadata_capability=True)
                    arguments = (str(self.project), "symbol") if boundary == "query" else (str(self.project),)
                    with self.assertRaises(CodeGraphProjectError) as caught:
                        getattr(lifecycle, boundary)(*arguments)
                    self.assertEqual(caught.exception.reason, reason)
                    self.assertEqual(len(port.calls), 2)
                    self.assertEqual(database.read_bytes(), b"last good index")

    def test_metadata_pending_refs_are_repaired_only_when_strict_post_sync_is_fresh(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        for remaining in (0, 3):
            with self.subTest(remaining=remaining):
                metadata = json.loads(self._status(pending_refs=3))
                metadata.update(pendingChanges=None, workingTreeChecked=False)
                port = FakeCommandPort(self._result(stdout="  --metadata-only  Read metadata\n"),
                                       self._result(stdout=json.dumps(metadata)), self._result(stdout="synced"),
                                       self._result(stdout=self._status(pending_refs=remaining)))
                lifecycle, _ = self._lifecycle(port, metadata_capability=True)
                if remaining:
                    with self.assertRaisesRegex(CodeGraphProjectError, "codegraph-index-not-fresh"):
                        lifecycle.ensure(str(self.project))
                else:
                    self.assertEqual(lifecycle.ensure(str(self.project))["freshness"], "fresh")
                self.assertEqual(port.calls[-1]["argv"][-1], "--json")
                self.assertEqual(len(port.calls), 4)

    def test_failed_or_locked_sync_after_metadata_does_not_run_a_fallback_status_or_rebuild(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        lock_error = ("[ERR] Failed to sync: Sync could not acquire the file lock; retry when the index is available. "
                      "CodeGraph database is locked by another process (PID 42). If this is stale, run 'codegraph unlock' or delete C:/private/codegraph.lock")
        for stderr, reason in (("sync failed", "codegraph-command-failed"), (lock_error, "codegraph-project-busy")):
            with self.subTest(reason=reason):
                metadata = json.loads(self._status())
                metadata.update(pendingChanges=None, workingTreeChecked=False)
                port = FakeCommandPort(self._result(stdout="  --metadata-only  Read metadata\n"),
                                       self._result(stdout=json.dumps(metadata)), self._result(1, stderr=stderr))
                lifecycle, _ = self._lifecycle(port, metadata_capability=True)
                with self.assertRaises(CodeGraphProjectError) as caught:
                    lifecycle.ensure(str(self.project))
                self.assertEqual(caught.exception.reason, reason)
                self.assertEqual(len(port.calls), 3)

    def test_strict_cpp_environment_failure_after_sync_cannot_be_reported_fresh(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        for environment in (None,
                            {"observed": False, "complete": False, "changed": True, "affectedFiles": []},
                            {"observed": True, "complete": False, "changed": False, "affectedFiles": []},
                            {"observed": True, "complete": True, "changed": True, "affectedFiles": ["Actor.cpp"]}):
            with self.subTest(environment=environment):
                metadata = json.loads(self._status())
                metadata.update(pendingChanges=None, workingTreeChecked=False, cppIncludeEnvironment=None)
                final = json.loads(self._status())
                final["cppIncludeEnvironment"] = environment
                port = FakeCommandPort(self._result(stdout="  --metadata-only  Read metadata\n"),
                                       self._result(stdout=json.dumps(metadata)), self._result(stdout="synced"),
                                       self._result(stdout=json.dumps(final)))
                lifecycle, _ = self._lifecycle(port, metadata_capability=True)
                with self.assertRaisesRegex(CodeGraphProjectError, "codegraph-index-not-fresh"):
                    lifecycle.ensure(str(self.project))
                self.assertEqual(len(port.calls), 4)

    def test_missing_project_is_fully_initialized_before_it_is_reported_fresh(self):
        port = FakeCommandPort(
            self._result(stdout=self._status(initialized=False)),
            self._result(stdout="initialized"),
            self._result(stdout=self._status()),
        )
        lifecycle, _ = self._lifecycle(port)

        result = lifecycle.ensure(str(self.project))

        self.assertEqual(result["providerId"], "codegraph")
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["freshness"], "fresh")
        self.assertEqual(result["actions"], ["initialize"])
        self.assertEqual(port.calls[1]["argv"], ("codegraph", "init", str(self.project).replace("\\", "/")))

    def test_stale_index_is_preserved_without_automatic_rebuild_at_every_boundary(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        database = self.project / ".codegraph" / "codegraph.db"
        database.parent.mkdir()
        database.write_bytes(b"existing index must survive")
        states = (
            self._status(reindex=True),
            self._status(state="partial"),
            self._status(state="failed"),
            self._status(pending_refs=3),
            self._status(pending={"added": 0, "modified": 1, "removed": 0}),
        )
        for boundary in ("ensure", "preflight", "sync", "query"):
            for status in states:
                with self.subTest(boundary=boundary, status=status):
                    port = FakeCommandPort(
                        self._result(stdout=self._status()),
                        self._result(stdout="synced"),
                        self._result(stdout=status),
                        self._result(stdout="indexed"),
                        self._result(stdout=self._status()),
                        self._result(stdout=self._status()),
                        self._result(stdout="query result"),
                    )
                    lifecycle, _ = self._lifecycle(port)
                    arguments = (str(self.project), "symbol") if boundary == "query" else (str(self.project),)

                    with self.assertRaises(CodeGraphProjectError) as caught:
                        getattr(lifecycle, boundary)(*arguments)

                    self.assertEqual(caught.exception.reason, "codegraph-index-not-fresh")
                    self.assertEqual(database.read_bytes(), b"existing index must survive")
                    self.assertEqual([call["argv"][1] for call in port.calls], ["status", "sync", "status"])

    def test_existing_database_is_never_reinitialized_when_status_reports_missing(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        database = self.project / ".codegraph" / "codegraph.db"
        database.parent.mkdir()
        database.write_bytes(b"existing incompatible index")
        port = FakeCommandPort(
            self._result(stdout=self._status(initialized=False)),
            self._result(stdout="initialized"),
            self._result(stdout=self._status()),
        )
        lifecycle, _ = self._lifecycle(port)

        with self.assertRaises(CodeGraphProjectError) as caught:
            lifecycle.preflight(str(self.project))

        self.assertEqual(caught.exception.reason, "codegraph-existing-index-not-initialized")
        self.assertEqual(database.read_bytes(), b"existing incompatible index")
        self.assertEqual([call["argv"][1] for call in port.calls], ["status"])

    def test_reindex_advisory_stops_automatic_sync_before_existing_database_is_touched(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        database = self.project / ".codegraph" / "codegraph.db"
        database.parent.mkdir()
        database.write_bytes(b"last good index")
        for boundary in ("ensure", "preflight", "sync", "query"):
            with self.subTest(boundary=boundary):
                port = FakeCommandPort(
                    self._result(stdout=self._status(reindex=True)),
                    self._result(stdout="synced"),
                    self._result(stdout=self._status()),
                )
                lifecycle, _ = self._lifecycle(port)
                arguments = (str(self.project), "symbol") if boundary == "query" else (str(self.project),)
                with self.assertRaises(CodeGraphProjectError) as caught:
                    getattr(lifecycle, boundary)(*arguments)
                self.assertEqual(caught.exception.reason, "codegraph-rebuild-required-preserving-existing-index")
                self.assertEqual([call["argv"][1] for call in port.calls], ["status"])
                self.assertEqual(database.read_bytes(), b"last good index")

    def test_invalid_indexing_config_is_reported_stale_without_starting_a_writer(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        database = self.project / ".codegraph" / "codegraph.db"
        database.parent.mkdir()
        database.write_bytes(b"last good index")
        status = json.loads(self._status())
        status["pendingChanges"] = None
        status["indexingConfig"] = {"error": "invalid include type"}
        status_lifecycle, _ = self._lifecycle(FakeCommandPort(self._result(stdout=json.dumps(status))))
        observation = status_lifecycle.status(str(self.project))
        self.assertEqual(observation["freshness"], "stale")
        self.assertTrue(observation["indexingConfigInvalid"])
        for boundary in ("ensure", "preflight", "sync", "query"):
            with self.subTest(boundary=boundary):
                port = FakeCommandPort(self._result(stdout=json.dumps(status)))
                lifecycle, _ = self._lifecycle(port)
                arguments = (str(self.project), "symbol") if boundary == "query" else (str(self.project),)
                with self.assertRaises(CodeGraphProjectError) as caught:
                    getattr(lifecycle, boundary)(*arguments)
                self.assertEqual(caught.exception.reason, "codegraph-indexing-config-invalid")
                self.assertEqual([call["argv"][1] for call in port.calls], ["status"])
                self.assertEqual(database.read_bytes(), b"last good index")

    def test_agent_write_sync_updates_once_without_a_topic_queue_or_deep_context(self):
        port = FakeCommandPort(
            self._result(stdout=self._status(pending={"added": 0, "modified": 1, "removed": 0})),
            self._result(stdout="synced"),
            self._result(stdout=self._status()),
        )
        lifecycle, _ = self._lifecycle(port)

        result = lifecycle.sync(str(self.project), changed_paths=("src/main.cpp", "src/main.cpp"))

        self.assertTrue(result["updated"])
        self.assertEqual(result["changedPathCount"], 1)
        self.assertEqual(result["freshness"], "fresh")
        self.assertEqual(
            [call["argv"][1] for call in port.calls],
            ["status", "sync", "status"],
        )
        self.assertNotIn("deep", result)
        self.assertNotIn("conversationId", result)

    def test_query_initializes_and_then_uses_codegraph_explore(self):
        port = FakeCommandPort(
            self._result(stdout=self._status(initialized=False)),
            self._result(stdout="initialized"),
            self._result(stdout=self._status()),
            self._result(stdout=self._status()),
            self._result(stdout="symbols: main -> helper"),
        )
        lifecycle, _ = self._lifecycle(port)

        result = lifecycle.query(str(self.project), "main helper")

        self.assertEqual(result["providerId"], "codegraph")
        self.assertEqual(result["data"], "symbols: main -> helper")
        self.assertEqual(result["freshness"], "fresh")
        self.assertEqual(port.calls[-1]["argv"][:2], ("codegraph", "explore"))
        self.assertIn("--path", port.calls[-1]["argv"])

    def test_write_boundary_reconciles_even_when_status_appears_fresh(self):
        port = FakeCommandPort(
            self._result(stdout=self._status()),
            self._result(stdout="synced"),
            self._result(stdout=self._status()),
        )
        lifecycle, _ = self._lifecycle(port)

        result = lifecycle.sync(str(self.project), changed_paths=("src/main.cpp",))

        self.assertEqual(result["actions"], ["sync"])
        self.assertTrue(result["updated"])
        self.assertEqual(result["changedPathCount"], 1)
        self.assertEqual(result["freshness"], "fresh")
        self.assertEqual([call["argv"][1] for call in port.calls], ["status", "sync", "status"])

    def test_indexing_is_busy_without_starting_competing_maintenance(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        for initialized in (False, True):
            with self.subTest(initialized=initialized):
                port = FakeCommandPort(self._result(stdout=self._status(
                    initialized=initialized, state="indexing",
                )))
                lifecycle, _ = self._lifecycle(port)

                with self.assertRaises(CodeGraphProjectError) as caught:
                    lifecycle.preflight(str(self.project))

                self.assertEqual(caught.exception.reason, "codegraph-project-busy")
                self.assertEqual([call["argv"][1] for call in port.calls], ["status"])

    def test_indexing_after_maintenance_never_escalates_to_another_writer(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        cases = (
            (self._status(initialized=False), (), "init"),
            (self._status(state="partial"), (), "sync"),
        )
        for initial, before_last, last in cases:
            with self.subTest(action=last):
                port = FakeCommandPort(
                    self._result(stdout=initial), *before_last,
                    self._result(stdout="maintenance started"),
                    self._result(stdout=self._status(state="indexing")),
                )
                lifecycle, _ = self._lifecycle(port)

                with self.assertRaises(CodeGraphProjectError) as caught:
                    lifecycle.ensure(str(self.project))

                self.assertEqual(caught.exception.reason, "codegraph-project-busy")
                self.assertEqual(port.calls[-2]["argv"][1], last)
                self.assertEqual(port.calls[-1]["argv"][1], "status")

    def test_busy_retry_rechecks_and_reconciles_only_after_native_index_completes(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        port = FakeCommandPort(
            self._result(stdout=self._status(state="indexing")),
            self._result(stdout=self._status()),
            self._result(stdout="no changes"),
            self._result(stdout=self._status()),
        )
        lifecycle, _ = self._lifecycle(port)

        with self.assertRaises(CodeGraphProjectError):
            lifecycle.sync(str(self.project), changed_paths=("src/main.cpp",))
        result = lifecycle.sync(str(self.project), changed_paths=("src/main.cpp",))

        self.assertEqual(result["actions"], ["sync"])
        self.assertEqual([call["argv"][1] for call in port.calls], ["status", "status", "sync", "status"])

    def test_failed_sync_does_not_hide_command_failure_by_rebuilding(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        port = FakeCommandPort(
            self._result(stdout=self._status(state="partial")),
            self._result(exit_code=9, stderr="provider failure"),
        )
        lifecycle, _ = self._lifecycle(port)

        with self.assertRaises(CodeGraphProjectError) as caught:
            lifecycle.sync(str(self.project), changed_paths=("src/main.cpp",))

        self.assertEqual(caught.exception.reason, "codegraph-command-failed")
        self.assertEqual([call["argv"][1] for call in port.calls], ["status", "sync"])

    def test_failed_initialization_never_returns_a_fake_fresh_status(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        port = FakeCommandPort(
            self._result(stdout=self._status(initialized=False)),
            self._result(exit_code=9, stderr="provider failure"),
        )
        lifecycle, _ = self._lifecycle(port)

        with self.assertRaises(CodeGraphProjectError) as caught:
            lifecycle.ensure(str(self.project))

        self.assertEqual(caught.exception.reason, "codegraph-command-failed")
        self.assertNotIn("fresh", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
