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

    def test_verified_partial_cpp_coverage_survives_sync_and_query_with_warning(self):
        final = json.loads(self._status())
        final["cppIncludeEnvironment"] = {
            "observed": True, "complete": False, "changed": False,
            "inputsVerified": True, "affectedFileCount": 0,
        }
        port = FakeCommandPort(
            self._result(stdout=json.dumps(final)), self._result(stdout="synced"),
            self._result(stdout=json.dumps(final)), self._result(stdout=json.dumps(final)),
            self._result(stdout="Widget references"),
        )
        lifecycle, _ = self._lifecycle(port)
        result = lifecycle.query(str(self.project), "find Widget")
        self.assertEqual(result["freshness"], "fresh")
        self.assertEqual(result["analysisWarnings"], ["cpp-include-coverage-incomplete"])
        self.assertEqual(result["maintenanceActions"], ["sync"])
        self.assertEqual([call["argv"][1] for call in port.calls], ["status", "sync", "status", "status", "explore"])

    def test_missing_project_requires_explicit_initialization(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        port = FakeCommandPort(
            self._result(stdout=self._status(initialized=False)),
        )
        lifecycle, _ = self._lifecycle(port)

        with self.assertRaisesRegex(CodeGraphProjectError, "codegraph-explicit-initialization-required"):
            lifecycle.ensure(str(self.project))
        self.assertEqual([call["argv"][1] for call in port.calls], ["status"])

    def test_automatic_boundaries_never_initialize_a_missing_or_unrecognized_index(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        for artifact in (None, "codegraph.db-wal", "codegraph.db-shm", "codegraph.db-journal"):
            index = self.project / ".codegraph"
            if artifact:
                index.mkdir(exist_ok=True)
                (index / artifact).write_bytes(b"preserve recovery data")
            for boundary in ("ensure", "preflight", "sync", "query"):
                with self.subTest(artifact=artifact, boundary=boundary):
                    port = FakeCommandPort(self._result(stdout=self._status(initialized=False)))
                    lifecycle, _ = self._lifecycle(port)
                    arguments = (str(self.project), "symbol") if boundary == "query" else (str(self.project),)
                    with self.assertRaisesRegex(CodeGraphProjectError, "codegraph-explicit-initialization-required"):
                        getattr(lifecycle, boundary)(*arguments)
                    self.assertEqual([call["argv"][1] for call in port.calls], ["status"])
                    self.assertFalse((index / "codegraph.db").exists())
                    if artifact:
                        self.assertEqual((index / artifact).read_bytes(), b"preserve recovery data")

    def test_incomplete_or_unknown_index_state_never_starts_automatic_sync(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        for state in ("partial", "failed", "unknown", "", None):
            value = json.loads(self._status())
            value["index"]["state"] = state
            for boundary in ("ensure", "preflight", "sync", "query"):
                with self.subTest(state=state, boundary=boundary):
                    port = FakeCommandPort(self._result(stdout=json.dumps(value)))
                    lifecycle, _ = self._lifecycle(port)
                    arguments = (str(self.project), "symbol") if boundary == "query" else (str(self.project),)
                    with self.assertRaisesRegex(CodeGraphProjectError, "codegraph-index-state-not-complete"):
                        getattr(lifecycle, boundary)(*arguments)
                    self.assertEqual([call["argv"][1] for call in port.calls], ["status"])

    def test_inconsistent_file_and_node_presence_never_triggers_automatic_reextraction(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        for files, nodes in ((80000, 0), (0, 2000000)):
            value = json.loads(self._status())
            value.update(fileCount=files, nodeCount=nodes)
            for boundary in ("ensure", "preflight", "sync", "query"):
                with self.subTest(files=files, nodes=nodes, boundary=boundary):
                    port = FakeCommandPort(self._result(stdout=json.dumps(value)))
                    lifecycle, _ = self._lifecycle(port)
                    arguments = (str(self.project), "symbol") if boundary == "query" else (str(self.project),)
                    with self.assertRaisesRegex(CodeGraphProjectError, "codegraph-index-data-inconsistent"):
                        getattr(lifecycle, boundary)(*arguments)
                    self.assertEqual([call["argv"][1] for call in port.calls], ["status"])

    def test_legitimate_empty_complete_index_can_sync_without_initialization(self):
        value = json.loads(self._status())
        value.update(fileCount=0, nodeCount=0, edgeCount=0)
        port = FakeCommandPort(self._result(stdout=json.dumps(value)),
                               self._result(stdout="synced"), self._result(stdout=json.dumps(value)))
        lifecycle, _ = self._lifecycle(port)
        self.assertEqual(lifecycle.ensure(str(self.project))["actions"], ["sync"])
        self.assertEqual([call["argv"][1] for call in port.calls], ["status", "sync", "status"])

    def test_publication_marker_blocks_all_boundaries_before_provider_dispatch(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        marker = self.project / ".codegraph.publication.json"
        for content in ("", "{}", '{"schemaVersion": 999}', "partial JSON"):
            marker.write_text(content, encoding="utf-8")
            for boundary in ("status", "ensure", "preflight", "sync", "query"):
                with self.subTest(content=content, boundary=boundary):
                    port = FakeCommandPort()
                    lifecycle, _ = self._lifecycle(port)
                    arguments = (str(self.project), "symbol") if boundary == "query" else (str(self.project),)
                    with self.assertRaisesRegex(CodeGraphProjectError, "codegraph-publication-recovery-required"):
                        getattr(lifecycle, boundary)(*arguments)
                    self.assertEqual(port.calls, [])
                    self.assertEqual(marker.read_text(encoding="utf-8"), content)

    def test_platform_default_publication_markers_block_without_an_override(self):
        from unittest.mock import patch
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        for suffix in (".publication.json", ".publication.lock"):
            marker = self.project / (".codegraph-wsl" + suffix)
            marker.write_text("pending", encoding="utf-8")
            try:
                port = FakeCommandPort(self._result(stdout=self._status()))
                lifecycle, _ = self._lifecycle(port)
                with patch.dict("os.environ", {"CODEGRAPH_DIR": ""}):
                    with self.assertRaisesRegex(CodeGraphProjectError, "codegraph-publication-recovery-required"):
                        lifecycle.status(str(self.project))
                self.assertEqual(port.calls, [])
            finally:
                marker.unlink()

    def test_publication_during_final_or_query_status_stops_before_explore(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        marker = self.project / ".codegraph.publication.json"
        for status_number in (2, 3):
            with self.subTest(status_number=status_number):
                class PublicationPort(FakeCommandPort):
                    def run(port, argv, *, cwd=None):
                        result = super().run(argv, cwd=cwd)
                        count = sum(call["argv"][1] == "status" for call in port.calls)
                        if argv[1] == "status" and count == status_number:
                            marker.write_text("pending", encoding="utf-8")
                        return result

                port = PublicationPort(
                    self._result(stdout=self._status()), self._result(stdout="synced"),
                    self._result(stdout=self._status()), self._result(stdout=self._status()),
                    self._result(stdout="symbols: main"),
                )
                lifecycle, adapter = self._lifecycle(port)
                try:
                    with self.assertRaisesRegex(CodeGraphProjectError, "codegraph-publication-recovery-required"):
                        lifecycle.query(str(self.project), "main")
                    self.assertNotIn("explore", [call["argv"][1] for call in port.calls])
                    # The automatic guard is scoped; another project's diagnostic
                    # must retain the adapter's ordinary source validation.
                    other = self.project / "other"
                    other.mkdir(exist_ok=True)
                    state = json.loads(self._status())
                    state["projectPath"] = str(other)
                    port.results = [self._result(stdout=json.dumps(state))]
                    self.assertEqual(adapter.status(str(other))["freshness"], "fresh")
                finally:
                    marker.unlink(missing_ok=True)

    def test_publication_marker_is_scoped_to_selected_index_directory(self):
        from unittest.mock import patch
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        (self.project / ".codegraph.publication.json").write_text("pending", encoding="utf-8")
        port = FakeCommandPort(self._result(stdout=self._status(initialized=False)))
        lifecycle, _ = self._lifecycle(port)
        with patch.dict("os.environ", {"CODEGRAPH_DIR": ".codegraph-candidate"}):
            with self.assertRaisesRegex(CodeGraphProjectError, "codegraph-explicit-initialization-required"):
                lifecycle.ensure(str(self.project))
            (self.project / ".codegraph-candidate.publication.json").write_text("pending", encoding="utf-8")
            with self.assertRaisesRegex(CodeGraphProjectError, "codegraph-publication-recovery-required"):
                lifecycle.ensure(str(self.project))
        self.assertEqual(len(port.calls), 1)

    def test_lease_without_a_marker_blocks_before_provider_dispatch(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        lease = self.project / ".codegraph.publication.lock"
        lease.write_text('{"purpose":"publication"}', encoding="utf-8")
        for boundary in ("status", "ensure", "preflight", "sync", "query"):
            with self.subTest(boundary=boundary):
                port = FakeCommandPort()
                lifecycle, _ = self._lifecycle(port)
                arguments = (str(self.project), "symbol") if boundary == "query" else (str(self.project),)
                with self.assertRaisesRegex(CodeGraphProjectError, "codegraph-publication-recovery-required"):
                    getattr(lifecycle, boundary)(*arguments)
                self.assertEqual(port.calls, [])

    def test_uncertain_publication_state_stops_before_provider_dispatch(self):
        from unittest.mock import patch
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        original = Path.lstat
        marker = self.project / ".codegraph.publication.json"

        def deny_marker(candidate, *arguments, **keywords):
            if candidate == marker:
                raise PermissionError("injected publication permission failure")
            return original(candidate, *arguments, **keywords)

        port = FakeCommandPort()
        lifecycle, _ = self._lifecycle(port)
        with patch.object(Path, "lstat", deny_marker):
            with self.assertRaisesRegex(CodeGraphProjectError, "codegraph-publication-state-unknown"):
                lifecycle.ensure(str(self.project))
        self.assertEqual(port.calls, [])

    def test_publication_appearing_during_status_stops_before_sync(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        marker = self.project / ".codegraph.publication.json"
        result = self._result(stdout=self._status())

        class PublicationDuringStatusPort(FakeCommandPort):
            def run(self, argv, *, cwd=None):
                observed = super().run(argv, cwd=cwd)
                marker.write_text("pending", encoding="utf-8")
                return observed

        port = PublicationDuringStatusPort(result)
        lifecycle, _ = self._lifecycle(port)
        with self.assertRaisesRegex(CodeGraphProjectError, "codegraph-publication-recovery-required"):
            lifecycle.ensure(str(self.project))
        self.assertEqual([call["argv"][1] for call in port.calls], ["status"])

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

        self.assertEqual(caught.exception.reason, "codegraph-explicit-initialization-required")
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

    def test_query_syncs_an_existing_complete_graph_then_uses_codegraph_explore(self):
        port = FakeCommandPort(
            self._result(stdout=self._status()),
            self._result(stdout="synced"),
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

        cases = ((self._status(), (), "sync"),)
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
            self._result(stdout=self._status()),
            self._result(exit_code=9, stderr="provider failure"),
        )
        lifecycle, _ = self._lifecycle(port)

        with self.assertRaises(CodeGraphProjectError) as caught:
            lifecycle.sync(str(self.project), changed_paths=("src/main.cpp",))

        self.assertEqual(caught.exception.reason, "codegraph-command-failed")
        self.assertEqual([call["argv"][1] for call in port.calls], ["status", "sync"])

    def test_absent_index_never_runs_failing_initialization_or_returns_fresh(self):
        from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError

        port = FakeCommandPort(
            self._result(stdout=self._status(initialized=False)),
            self._result(exit_code=9, stderr="provider failure"),
        )
        lifecycle, _ = self._lifecycle(port)

        with self.assertRaises(CodeGraphProjectError) as caught:
            lifecycle.ensure(str(self.project))

        self.assertEqual(caught.exception.reason, "codegraph-explicit-initialization-required")
        self.assertEqual([call["argv"][1] for call in port.calls], ["status"])
        self.assertNotIn("fresh", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
