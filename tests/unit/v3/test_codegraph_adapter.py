import copy
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
