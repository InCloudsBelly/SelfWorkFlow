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
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class GraftAdapterTests(unittest.TestCase):
    def _result(self, exit_code=0, stdout="", stderr=""):
        from selfworkflow.v3.providers.codegraph import CommandResult

        return CommandResult(exit_code=exit_code, stdout=stdout, stderr=stderr)

    def _adapter(self, port):
        from selfworkflow.v3.providers.graft import GraftAdapter

        return GraftAdapter(
            command_port=port,
            command_prefix=("node", "C:/tools/graft/dist/cli.js"),
            ownership="selfworkflow-managed",
        )

    def _fresh_status(self):
        return json.dumps({
            "context": {"ok": True, "missing": False},
            "graph": {"ok": True, "missing": False},
        })

    def _help(self):
        return """Commands:
  build
  check
  ask
  map
  skeleton
  callers
  grep
"""

    def test_provider_preflight_verifies_runtime_and_query_commands(self):
        port = FakeCommandPort(
            self._result(stdout="0.18.0\n"),
            self._result(stdout=self._help()),
        )

        result = self._adapter(port).provider_preflight()

        self.assertEqual(result["providerStatus"], "verified")
        self.assertEqual(result["version"], "0.18.0")
        self.assertEqual(result["queryCapabilities"], [
            "ask", "build", "callers", "check", "grep", "map",
            "skeleton",
        ])
        self.assertEqual(port.calls[0]["argv"][-1], "--version")
        self.assertEqual(port.calls[1]["argv"][-1], "--help")

    def test_provider_preflight_rejects_missing_query_capability(self):
        from selfworkflow.v3.providers.graft import GraftAdapterError

        port = FakeCommandPort(
            self._result(stdout="0.18.0\n"),
            self._result(stdout="Commands:\n  build\n  check\n"),
        )

        with self.assertRaisesRegex(
            GraftAdapterError, "graft-provider-capability-missing",
        ):
            self._adapter(port).provider_preflight()

    def test_status_accepts_fresh_and_stale_exit_without_leaking_output(self):
        port = FakeCommandPort(
            self._result(stdout=self._fresh_status()),
            self._result(
                exit_code=1,
                stdout=json.dumps({
                    "context": {"ok": False, "missing": False},
                    "graph": None,
                }),
                stderr="private absolute path",
            ),
        )
        adapter = self._adapter(port)

        fresh = adapter.status("C:/work/project")
        stale = adapter.status("C:/work/project")

        self.assertEqual(fresh["freshness"], "fresh")
        self.assertEqual(stale["freshness"], "stale")
        self.assertTrue(fresh["readOnly"])
        self.assertNotIn("private absolute path", str(stale))
        self.assertEqual(port.calls[0]["argv"][-2:], (
            "C:/work/project", "--json",
        ))

    def test_status_missing_graph_is_reported_without_implicit_build(self):
        port = FakeCommandPort(self._result(stdout=json.dumps({
            "context": {"ok": False, "missing": True},
            "graph": None,
        })))

        result = self._adapter(port).status("C:/work/project")

        self.assertEqual(result["freshness"], "missing")
        self.assertEqual(len(port.calls), 1)
        self.assertNotIn("build", port.calls[0]["argv"])

    def test_status_accepts_structural_graph_when_optional_context_is_missing(self):
        port = FakeCommandPort(self._result(stdout=json.dumps({
            "context": {"ok": False, "missing": True},
            "graph": {"ok": True, "missing": False, "pending": 0},
        })))

        result = self._adapter(port).status("C:/work/project")

        self.assertEqual(result["freshness"], "fresh")
        self.assertTrue(result["initialized"])

    def test_status_allows_large_bounded_drift_report_but_returns_only_summary(self):
        payload = {
            "context": {"ok": False, "missing": False},
            "graph": {"ok": False, "missing": False, "padding": "x" * (1024 * 1024 + 1)},
        }
        port = FakeCommandPort(self._result(exit_code=1, stdout=json.dumps(payload)))

        result = self._adapter(port).status("C:/work/project")

        self.assertEqual(result["freshness"], "stale")
        self.assertNotIn("padding", result)

    def test_query_is_readonly_no_refresh_and_returns_json_payload(self):
        payload = {"hits": [{"path": "Source/main.cpp", "pointer": "fn"}]}
        port = FakeCommandPort(
            self._result(stdout=self._fresh_status()),
            self._result(stdout=json.dumps(payload)),
        )

        result = self._adapter(port).query(
            "C:/work/project", "find Widget", query_kind="ask",
        )

        self.assertEqual(result["providerId"], "graft")
        self.assertEqual(result["data"], payload)
        self.assertTrue(result["readOnly"])
        self.assertEqual(port.calls[1]["argv"][-4:], (
            "find Widget", "C:/work/project", "--json", "--no-refresh",
        ))

    def test_query_rejects_graph_absence_and_never_builds(self):
        from selfworkflow.v3.providers.graft import GraftAdapterError

        port = FakeCommandPort(self._result(stdout=json.dumps({
            "context": {"ok": False, "missing": True},
            "graph": None,
        })))

        with self.assertRaises(GraftAdapterError) as caught:
            self._adapter(port).query("C:/work/project", "find Widget")

        self.assertEqual(caught.exception.reason, "graft-graph-not-ready")
        self.assertEqual(len(port.calls), 1)

    def test_query_rejects_unknown_kind_and_bad_json_fail_closed(self):
        from selfworkflow.v3.providers.graft import GraftAdapterError

        with self.assertRaisesRegex(GraftAdapterError, "graft-query-kind-invalid"):
            self._adapter(FakeCommandPort()).query(
                "C:/work/project", "x", query_kind="build",
            )
        port = FakeCommandPort(
            self._result(stdout=self._fresh_status()),
            self._result(stdout="not-json", stderr="token=secret"),
        )
        with self.assertRaises(GraftAdapterError) as caught:
            self._adapter(port).query("C:/work/project", "x")
        self.assertEqual(caught.exception.reason, "graft-query-invalid")
        self.assertNotIn("secret", str(caught.exception))

    def test_maintenance_requires_exact_confirmation_and_consumes_plan(self):
        from selfworkflow.v3.providers.graft import GraftAdapterError

        port = FakeCommandPort(self._result(stdout="graft build: done\n"))
        adapter = self._adapter(port)
        plan = adapter.plan_maintenance("rebuild", "C:/work/project")

        result = adapter.execute_maintenance(
            plan, "C:/work/project", confirmed_plan_hash=plan["planHash"],
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(port.calls[0]["argv"][-3:], (
            "C:/work/project", "--no-gitignore", "--no-ignore",
        ))
        with self.assertRaisesRegex(
            GraftAdapterError, "graft-maintenance-plan-replayed",
        ):
            adapter.execute_maintenance(
                plan, "C:/work/project", confirmed_plan_hash=plan["planHash"],
            )

    def test_tampered_plan_never_dispatches(self):
        from selfworkflow.v3.providers.graft import GraftAdapterError

        port = FakeCommandPort()
        adapter = self._adapter(port)
        plan = adapter.plan_maintenance("initialize", "C:/work/project")
        tampered = copy.deepcopy(plan)
        tampered["action"] = "rebuild"

        with self.assertRaisesRegex(
            GraftAdapterError, "graft-maintenance-plan-tampered",
        ):
            adapter.execute_maintenance(
                tampered, "C:/work/project",
                confirmed_plan_hash=plan["planHash"],
            )
        self.assertEqual(port.calls, [])

    def test_invalid_roots_and_oversized_output_fail_closed(self):
        from selfworkflow.v3.providers.graft import GraftAdapterError

        with self.assertRaisesRegex(
            GraftAdapterError, "graft-project-root-invalid",
        ):
            self._adapter(FakeCommandPort()).status("relative/project")
        port = FakeCommandPort(self._result(stdout="x" * (1024 * 1024 + 1)))
        with self.assertRaisesRegex(
            GraftAdapterError, "graft-command-output-too-large",
        ):
            self._adapter(port).version()


if __name__ == "__main__":
    unittest.main()
