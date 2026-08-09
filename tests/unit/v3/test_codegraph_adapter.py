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
            self._result(stdout='{"initialized":true,"revision":"r1"}'),
            self._result(stdout="1.3.1"),
            self._result(stdout="Usage: codegraph"),
        )
        adapter = self._adapter(port)

        status = adapter.status("C:/work/project")
        version = adapter.version()
        help_result = adapter.help()

        self.assertTrue(status["initialized"])
        self.assertEqual(status["revision"], "r1")
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

    def test_query_never_initializes_index_implicitly(self):
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapterError

        port = FakeCommandPort(self._result(stdout='{"initialized":false}'))
        with self.assertRaises(CodeGraphAdapterError) as caught:
            self._adapter(port).plan_query("C:/work/project", "find Widget")

        self.assertEqual(caught.exception.reason, "codegraph-project-not-initialized")
        self.assertEqual(len(port.calls), 1)
        self.assertEqual(port.calls[0]["argv"][-3], "status")

    def test_query_plan_declares_unavoidable_potential_local_write(self):
        port = FakeCommandPort(self._result(stdout='{"initialized":true,"revision":"r2"}'))

        plan = self._adapter(port).plan_query("C:/work/project", "find Widget")

        self.assertEqual(plan["operation"], "query")
        self.assertFalse(plan["readOnly"])
        self.assertEqual(plan["sideEffectClass"], "potential-local-write")
        self.assertEqual(plan["supportStatus"], "unverified")
        self.assertEqual(plan["reasonCode"], "codegraph-query-no-no-sync")
        self.assertRegex(plan["adapterCommandHash"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(plan["planHash"], r"^sha256:[0-9a-f]{64}$")
        self.assertNotIn("C:/work/project", str(plan))
        self.assertEqual(len(port.calls), 1)

    def test_query_plan_is_deterministic_and_rejects_invalid_input(self):
        from selfworkflow.v3.providers.codegraph import CodeGraphAdapterError

        first = self._adapter(FakeCommandPort(
            self._result(stdout='{"initialized":true,"revision":"r2"}')
        )).plan_query("C:/work/project", "find Widget")
        second = self._adapter(FakeCommandPort(
            self._result(stdout='{"initialized":true,"revision":"r2"}')
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
        self.assertEqual(port.calls[0]["argv"][-3:], ("sync", "C:/work/project", "--json"))

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
