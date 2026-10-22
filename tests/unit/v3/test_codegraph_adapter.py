import copy
import json
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


class CodeGraphAdapterTests(unittest.TestCase):
    def _result(self, exit_code=0, stdout="", stderr=""):
        from selfworkflow.v3.providers.codegraph import CommandResult

        return CommandResult(exit_code=exit_code, stdout=stdout, stderr=stderr)

    def _adapter(self, port):
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapter

        return CodeGraphAdapter(
            command_port=port,
            command_prefix=("node", "C:/tools/codegraph/cli.js"),
            ownership="user-local",
        )

    def test_status_version_and_help_use_only_injected_readonly_port(self):
        port = FakeCommandPort(
            self._result(stdout='{"initialized":true,"fileCount":2,"index":{"state":"complete"}}'),
            self._result(stdout="1.3.1"),
            self._result(stdout="Usage: codegraph"),
        )
        adapter = self._adapter(port)

        status = adapter.status("C:/work/project")
        version = adapter.version()
        help_result = adapter.help()

        self.assertTrue(status["initialized"])
        self.assertEqual(status["fileCount"], 2)
        self.assertEqual(status["indexState"], "complete")
        self.assertEqual(version["version"], "1.3.1")
        self.assertIn("Usage", help_result["summary"])
        self.assertTrue(status["readOnly"])
        self.assertTrue(version["readOnly"])
        self.assertTrue(help_result["readOnly"])
        self.assertEqual(status["supportStatus"], "unverified")
        self.assertEqual(version["supportStatus"], "unverified")
        self.assertEqual(help_result["supportStatus"], "unverified")
        self.assertEqual(port.calls[0]["argv"][-3:], ("status", "C:/work/project", "--json"))

    def test_command_failure_has_stable_error_without_stderr_leak(self):
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapterError

        port = FakeCommandPort(self._result(7, stderr="token=do-not-log"))
        with self.assertRaises(CodeGraphAdapterError) as caught:
            self._adapter(port).version()

        self.assertEqual(caught.exception.reason, "codegraph-command-failed")
        self.assertNotIn("do-not-log", str(caught.exception))

    def test_unchecked_metadata_and_explicit_null_pending_changes_are_never_fresh(self):
        observations = (
            {"initialized": True, "index": {"state": "complete"}, "pendingChanges": None,
             "workingTreeChecked": False},
            {"initialized": True, "index": {"state": "complete"}, "pendingChanges": None},
            {"initialized": False, "pendingChanges": None, "workingTreeChecked": False},
        )
        for value in observations:
            with self.subTest(value=value):
                adapter = self._adapter(FakeCommandPort(self._result(stdout=json.dumps(value))))
                self.assertEqual(adapter.status("C:/work/project")["freshness"], "unknown")

    def test_verified_fork_advertised_metadata_observation_remains_unknown(self):
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapter

        port = FakeCommandPort(
            self._result(stdout="Usage: codegraph status\n  --metadata-only  Read metadata without checking files\n"),
            self._result(stdout=json.dumps({"initialized": True, "pendingChanges": None,
                                           "workingTreeChecked": False, "index": {"state": "complete"}})),
            self._result(stdout=json.dumps({"initialized": True, "pendingChanges": {"added": 0, "modified": 0, "removed": 0},
                                           "index": {"state": "complete"}})),
        )
        adapter = CodeGraphAdapter(command_port=port, command_prefix=("codegraph",),
                                   ownership="selfworkflow-managed", allow_metadata_only_status=True)
        metadata = adapter.maintenance_status("C:/work/project")
        self.assertEqual(metadata["freshness"], "unknown")
        self.assertFalse(metadata["workingTreeChecked"])
        self.assertIsNone(metadata["pendingChanges"])
        self.assertEqual(adapter.status("C:/work/project")["freshness"], "fresh")
        self.assertEqual([call["argv"][1:] for call in port.calls], [
            ("status", "--help"), ("status", "C:/work/project", "--json", "--metadata-only"),
            ("status", "C:/work/project", "--json"),
        ])

    def test_capability_errors_and_invalid_metadata_responses_do_not_fall_back(self):
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapter, CodeGraphAdapterError

        for results, reason in (
            ([self._result(1, stderr="unknown option")], "codegraph-command-failed"),
            ([self._result(stdout="")], "codegraph-metadata-capability-invalid"),
            ([self._result(stdout="  --metadata-only  Read metadata\n"),
              self._result(stdout='{"initialized":true,"workingTreeChecked":true,"pendingChanges":null}')],
             "codegraph-metadata-status-invalid"),
        ):
            with self.subTest(reason=reason):
                port = FakeCommandPort(*results)
                adapter = CodeGraphAdapter(command_port=port, command_prefix=("codegraph",),
                                           ownership="selfworkflow-managed", allow_metadata_only_status=True)
                with self.assertRaises(CodeGraphAdapterError) as caught:
                    adapter.maintenance_status("C:/work/project")
                self.assertEqual(caught.exception.reason, reason)
                self.assertEqual(len(port.calls), len(results))

    def test_verified_old_fork_without_the_option_keeps_strict_status(self):
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapter

        port = FakeCommandPort(
            self._result(stdout="Usage: codegraph status\n  -j, --json  JSON output\n"),
            self._result(stdout='{"initialized":true,"version":"1.6.2","pendingChanges":{"added":0,"modified":1,"removed":0}}'),
        )
        adapter = CodeGraphAdapter(command_port=port, command_prefix=("codegraph",),
                                   ownership="selfworkflow-managed", allow_metadata_only_status=True)
        self.assertEqual(adapter.maintenance_status("C:/work/project")["freshness"], "stale")
        self.assertEqual(port.calls[-1]["argv"], ("codegraph", "status", "C:/work/project", "--json"))

    def test_strict_cpp_environment_must_be_observed_complete_and_unchanged_to_be_fresh(self):
        for environment, expected in (
            (None, "unknown"),
            ({"observed": False, "complete": False, "changed": True, "affectedFiles": []}, "unknown"),
            ({"observed": True, "complete": False, "changed": False, "affectedFiles": []}, "unknown"),
            ({"observed": True, "complete": True, "changed": True, "affectedFiles": ["private/Actor.cpp"]}, "stale"),
            ({"observed": True, "complete": True, "changed": False, "affectedFiles": []}, "fresh"),
            ({"observed": True, "complete": True, "changed": False, "affectedFileCount": 0}, "fresh"),
            ({"observed": True, "complete": True, "changed": True, "affectedFileCount": 90000}, "stale"),
        ):
            with self.subTest(environment=environment):
                value = {"initialized": True, "index": {"state": "complete"},
                         "pendingChanges": {"added": 0, "modified": 0, "removed": 0},
                         "cppIncludeEnvironment": environment}
                result = self._adapter(FakeCommandPort(self._result(stdout=json.dumps(value)))).status("C:/work/project")
                self.assertEqual(result["freshness"], expected)
                self.assertNotIn("private/Actor.cpp", str(result))

    def test_official_sync_lock_error_is_busy_for_both_glyphs_and_ansi(self):
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapterError

        for glyph, pid in (("✗", " (PID 123)"), ("[ERR]", ""), ("\x1b[31m✗\x1b[39m", " (PID 123)")):
            message = (
                f"Failed to sync: CodeGraph database is locked by another process{pid}. "
                "If this is stale, run 'codegraph unlock' or delete C:/private/codegraph.lock"
            )
            with self.subTest(glyph=glyph):
                adapter = self._adapter(FakeCommandPort(self._result(1, stderr=glyph + " " + message + "\n")))
                plan = adapter.plan_maintenance("sync", "C:/work/project")
                with self.assertRaises(CodeGraphAdapterError) as caught:
                    adapter.execute_maintenance(plan, "C:/work/project", confirmed_plan_hash=plan["planHash"])
                self.assertEqual(caught.exception.reason, "codegraph-project-busy")
                self.assertNotIn("private", str(caught.exception))

    def test_sync_lock_classification_rejects_quotes_stdout_and_other_errors(self):
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapterError

        line = (
            "✗ Failed to sync: CodeGraph database is locked by another process. "
            "If this is stale, run 'codegraph unlock' or delete C:/private/codegraph.lock"
        )
        results = (
            self._result(1, stderr="quoted: " + line),
            self._result(1, stderr='"' + line + '"'),
            self._result(1, stdout=line),
            self._result(1, stderr="✗ Failed to sync: EACCES C:/private/codegraph.lock"),
        )
        for result in results:
            with self.subTest(result=result):
                adapter = self._adapter(FakeCommandPort(result))
                plan = adapter.plan_maintenance("sync", "C:/work/project")
                with self.assertRaises(CodeGraphAdapterError) as caught:
                    adapter.execute_maintenance(plan, "C:/work/project", confirmed_plan_hash=plan["planHash"])
                self.assertEqual(caught.exception.reason, "codegraph-command-failed")
                self.assertNotIn("private", str(caught.exception))

    def test_official_162_sync_lock_routes_to_bounded_busy_handling(self):
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapterError

        message = (
            "[ERR] Failed to sync: Sync could not acquire the file lock; retry when the index is available. "
            "CodeGraph database is locked by another process (PID 123). "
            "If this is stale, run 'codegraph unlock' or delete C:/private/codegraph.lock\n"
        )
        adapter = self._adapter(FakeCommandPort(self._result(1, stderr=message)))
        plan = adapter.plan_maintenance("sync", "C:/work/project")
        with self.assertRaises(CodeGraphAdapterError) as caught:
            adapter.execute_maintenance(plan, "C:/work/project", confirmed_plan_hash=plan["planHash"])
        self.assertEqual(caught.exception.reason, "codegraph-project-busy")

    def test_query_and_status_lock_text_do_not_become_sync_busy(self):
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapterError

        line = (
            "✗ Failed to sync: CodeGraph database is locked by another process. "
            "If this is stale, run 'codegraph unlock' or delete C:/private/codegraph.lock"
        )
        with self.assertRaises(CodeGraphAdapterError) as status_error:
            self._adapter(FakeCommandPort(self._result(1, stderr=line))).status("C:/work/project")
        self.assertEqual(status_error.exception.reason, "codegraph-command-failed")
        adapter = self._adapter(FakeCommandPort(
            self._result(stdout='{"initialized":true,"index":{"state":"complete"}}'),
            self._result(1, stderr=line),
        ))
        with self.assertRaises(CodeGraphAdapterError) as query_error:
            adapter.query("C:/work/project", "find Widget")
        self.assertEqual(query_error.exception.reason, "codegraph-command-failed")

    def test_query_never_initializes_index_implicitly(self):
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapterError

        port = FakeCommandPort(self._result(stdout='{"initialized":false}'))
        with self.assertRaises(CodeGraphAdapterError) as caught:
            self._adapter(port).plan_query("C:/work/project", "find Widget")

        self.assertEqual(caught.exception.reason, "codegraph-project-not-initialized")
        self.assertEqual(len(port.calls), 1)
        self.assertEqual(port.calls[0]["argv"][-3], "status")

    def test_query_plan_is_readonly_after_lifecycle_maintenance(self):
        port = FakeCommandPort(self._result(stdout='{"initialized":true,"index":{"state":"complete"}}'))

        plan = self._adapter(port).plan_query("C:/work/project", "find Widget")

        self.assertEqual(plan["operation"], "query")
        self.assertTrue(plan["readOnly"])
        self.assertEqual(plan["sideEffectClass"], "none")
        self.assertEqual(plan["supportStatus"], "unverified")
        self.assertEqual(plan["reasonCode"], "codegraph-query-after-ensure")
        self.assertRegex(plan["adapterCommandHash"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(plan["planHash"], r"^sha256:[0-9a-f]{64}$")
        self.assertNotIn("C:/work/project", str(plan))
        self.assertEqual(len(port.calls), 1)

    def test_query_plan_is_deterministic_and_rejects_invalid_input(self):
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapterError

        first = self._adapter(FakeCommandPort(
            self._result(stdout='{"initialized":true,"index":{"state":"complete"}}')
        )).plan_query("C:/work/project", "find Widget")
        second = self._adapter(FakeCommandPort(
            self._result(stdout='{"initialized":true,"index":{"state":"complete"}}')
        )).plan_query("C:/work/project", "find Widget")
        self.assertEqual(first["planHash"], second["planHash"])

        with self.assertRaises(CodeGraphAdapterError) as caught:
            self._adapter(FakeCommandPort()).plan_query("C:/work/project", "  ")
        self.assertEqual(caught.exception.reason, "codegraph-query-invalid")

    def test_maintenance_requires_exact_plan_hash_and_rejects_tampering(self):
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapterError

        port = FakeCommandPort(self._result(stdout='{"ok":true}'))
        adapter = self._adapter(port)
        plan = adapter.plan_maintenance("sync", "C:/work/project")
        self.assertEqual(plan["adapterCommandHash"], adapter.command_hash)
        tampered = copy.deepcopy(plan)
        tampered["action"] = "rebuild"

        with self.assertRaises(CodeGraphAdapterError) as caught:
            adapter.execute_maintenance(
                tampered, "C:/work/project", confirmed_plan_hash=plan["planHash"]
            )
        self.assertEqual(caught.exception.reason, "codegraph-maintenance-plan-tampered")
        self.assertEqual(port.calls, [])

    def test_maintenance_success_consumes_plan_and_blocks_replay(self):
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapterError

        port = FakeCommandPort(self._result(stdout='{"ok":true}'))
        adapter = self._adapter(port)
        plan = adapter.plan_maintenance("sync", "C:/work/project")

        result = adapter.execute_maintenance(
            plan, "C:/work/project", confirmed_plan_hash=plan["planHash"]
        )
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["planHash"], plan["planHash"])
        self.assertEqual(port.calls[0]["argv"][-2:], ("sync", "C:/work/project"))

        with self.assertRaises(CodeGraphAdapterError) as caught:
            adapter.execute_maintenance(
                plan, "C:/work/project", confirmed_plan_hash=plan["planHash"]
            )
        self.assertEqual(caught.exception.reason, "codegraph-maintenance-plan-replayed")
        self.assertEqual(len(port.calls), 1)

    def test_maintenance_plan_is_bound_to_issuing_adapter_instance(self):
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapterError

        issuing = self._adapter(FakeCommandPort())
        plan = issuing.plan_maintenance("sync", "C:/work/project")
        fresh_port = FakeCommandPort(self._result(stdout='{"ok":true}'))

        with self.assertRaises(CodeGraphAdapterError) as caught:
            self._adapter(fresh_port).execute_maintenance(
                plan, "C:/work/project", confirmed_plan_hash=plan["planHash"]
            )
        self.assertEqual(caught.exception.reason, "codegraph-maintenance-plan-not-issued")
        self.assertEqual(fresh_port.calls, [])

    def test_user_owned_override_can_never_be_upgraded(self):
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapterError

        with self.assertRaises(CodeGraphAdapterError) as caught:
            self._adapter(FakeCommandPort()).plan_maintenance(
                "upgrade-managed-install", "C:/work/project"
            )
        self.assertEqual(caught.exception.reason, "codegraph-user-owned-upgrade-forbidden")


if __name__ == "__main__":
    unittest.main()
