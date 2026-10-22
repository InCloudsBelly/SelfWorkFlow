import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch


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


class RecordingLogger:
    def __init__(self):
        self.events = []

    def __call__(self, event, fields):
        self.events.append({"event": event, **dict(fields)})


class ProviderManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def _result(self, exit_code=0, stdout="", stderr=""):
        from selfworkflow.v3.providers.codegraph import CommandResult

        return CommandResult(exit_code=exit_code, stdout=stdout, stderr=stderr)

    def _status(self, *, initialized=True, pending=False, reindex=False):
        return json.dumps({
            "initialized": initialized,
            "index": {
                "state": "complete",
                "reindexRecommended": reindex,
                "pendingRefs": 1 if pending else 0,
            },
            "pendingChanges": {
                "added": 1 if pending else 0,
                "modified": 0,
                "removed": 0,
            },
            "worktreeMismatch": None,
        })

    def _manager(self, port=None, logger=None, replace_operation=None, source_type=None):
        from selfworkflow.v3.provider_manager import MachineLocalPaths, ProviderManager

        source = self.root / "private" / "codegraph"
        source.mkdir(parents=True, exist_ok=True)
        kwargs = {
            "paths": MachineLocalPaths(
                config_file=self.root / "machine" / "providers.local.yaml"
            ),
            "command_port": port or FakeCommandPort(),
            "logger": logger,
            "source_identity_resolver": lambda source_path: {
                "source": Path(source_path),
                "report": {
                    "sourceType": source_type,
                    "version": "1.6.2-local",
                    "commit": "b" * 40,
                    "sourceHash": "sha256:" + "a" * 64,
                    "dirty": True,
                },
            },
        }
        if replace_operation is not None:
            kwargs["replace_operation"] = replace_operation
        manager = ProviderManager(**kwargs)
        return manager, source

    def _configure(self, manager, *, replace_existing=False, token=False):
        source = self.root / "private" / "codegraph"
        return manager.configure(
            provider_id="codegraph",
            source_path=str(source),
            command_prefix=("node", str(source / "dist" / "bin" / "codegraph.js")),
            ownership="user-local",
            source_version="1.6.2-local",
            source_commit="b" * 40,
            source_hash="sha256:" + "a" * 64,
            dirty=True,
            replace_existing=replace_existing,
            rollback_token=uuid.uuid4().hex if token else None,
        )

    def test_list_is_empty_without_scanning_or_creating_config(self):
        manager, _ = self._manager()
        self.assertEqual(manager.list_providers(), {"providers": []})
        self.assertFalse((self.root / "machine" / "providers.local.yaml").exists())

    def test_only_a_verified_managed_submodule_can_probe_metadata_status_capability(self):
        for kind, source_type in ((None, None), ("managed-submodule", None), ("managed-submodule", "managed-submodule")):
            metadata_allowed = kind == source_type == "managed-submodule"
            with self.subTest(kind=kind, source_type=source_type):
                port = FakeCommandPort(
                    self._result(stdout="  --metadata-only  Read metadata\n") if metadata_allowed else self._result(stdout=self._status()),
                    *([self._result(stdout=json.dumps({"initialized": True, "pendingChanges": None, "workingTreeChecked": False,
                                                       "index": {"state": "complete"}}))] if metadata_allowed else []),
                    self._result(stdout="synced"), self._result(stdout=self._status()),
                )
                manager, project = self._manager(port=port, source_type=source_type)
                manager.configure(
                    provider_id="codegraph", source_path=str(project), command_prefix=("node", "cli.js"),
                    ownership="selfworkflow-managed", source_version="1.6.2", source_commit="b" * 40,
                    source_hash="sha256:" + "a" * 64, dirty=True, source_kind=kind,
                    replace_existing=True,
                )
                self.assertEqual(manager.ensure(str(project))["freshness"], "fresh")
                self.assertEqual(port.calls[0]["argv"][-2:], ("status", "--help") if metadata_allowed else (str(project).replace("\\", "/"), "--json"))

    def test_configure_is_machine_local_atomic_and_sanitized(self):
        manager, _ = self._manager()
        result = self._configure(manager)
        listed = manager.list_providers()
        self.assertEqual(result["providerId"], "codegraph")
        self.assertEqual(listed["providers"][0]["providerId"], "codegraph")
        self.assertEqual(listed["providers"][0]["ownership"], "user-local")
        self.assertNotIn(str(self.root), json.dumps(listed))

    def test_repeated_configure_is_idempotent(self):
        manager, _ = self._manager()
        first = self._configure(manager)
        before = (self.root / "machine" / "providers.local.yaml").read_bytes()
        second = self._configure(manager)
        self.assertEqual(first["configurationHash"], second["configurationHash"])
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual(before, (self.root / "machine" / "providers.local.yaml").read_bytes())

    def test_only_codegraph_can_be_configured_and_legacy_binding_can_be_retired(self):
        from selfworkflow.v3.provider_manager import ProviderManagerError

        manager, _ = self._manager()
        with self.assertRaisesRegex(ProviderManagerError, "provider-not-supported"):
            manager.configure(
                provider_id="other", source_path=str(self.root / "private" / "codegraph"),
                command_prefix=("node", "other.js"), ownership="user-local",
                source_version="1", source_commit="b" * 40,
                source_hash="sha256:" + "a" * 64, dirty=False,
            )
        self.assertEqual(manager.retire("legacy-provider")["status"], "absent")

    def test_preflight_initializes_missing_project_before_returning_fresh(self):
        port = FakeCommandPort(
            self._result(stdout=self._status(initialized=False)),
            self._result(stdout="initialized"),
            self._result(stdout=self._status()),
        )
        manager, project = self._manager(port=port)
        self._configure(manager)
        result = manager.preflight(str(project))
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["actions"], ["initialize"])
        self.assertEqual(
            port.calls[1]["argv"][:2],
            ("node", str(self.root / "private" / "codegraph" / "dist" / "bin" / "codegraph.js")),
        )
        self.assertIn("init", port.calls[1]["argv"])

    def test_sync_reports_rebuild_requirement_without_rebuilding(self):
        from selfworkflow.v3.provider_manager import ProviderManagerError

        port = FakeCommandPort(
            self._result(stdout=self._status()),
            self._result(stdout="synced"),
            self._result(stdout=self._status(reindex=True)),
            self._result(stdout="indexed"),
            self._result(stdout=self._status()),
        )
        manager, project = self._manager(port=port)
        self._configure(manager)
        with self.assertRaisesRegex(ProviderManagerError, "codegraph-index-not-fresh"):
            manager.sync(str(project), ("src/main.cpp", "src/main.cpp", "src/helper.cpp"))
        self.assertEqual(
            [call["argv"][2] for call in port.calls],
            ["status", "sync", "status"],
        )

    def test_query_ensures_fresh_index_and_returns_codegraph_data(self):
        port = FakeCommandPort(
            self._result(stdout=self._status()),
            self._result(stdout="synced"),
            self._result(stdout=self._status()),
            self._result(stdout=self._status()),
            self._result(stdout="symbols: main -> helper"),
        )
        manager, project = self._manager(port=port)
        self._configure(manager)
        result = manager.query("codegraph", str(project), "main helper")
        self.assertEqual(result["providerId"], "codegraph")
        self.assertEqual(result["data"], "symbols: main -> helper")
        self.assertEqual(port.calls[-1]["argv"][2], "explore")

    def test_continuous_automatic_boundaries_do_not_replay_consumed_plans(self):
        results = []
        for _ in range(3):
            results.extend((
                self._result(stdout=self._status()),
                self._result(stdout="synced"),
                self._result(stdout=self._status()),
            ))
        port = FakeCommandPort(*results,
            self._result(stdout=self._status()),
            self._result(stdout="symbols: current_revision"),
        )
        manager, project = self._manager(port=port)
        self._configure(manager)

        first = manager.ensure(str(project))
        second = manager.sync(str(project), ("source.py",))
        third = manager.query("codegraph", str(project), "current_revision")

        self.assertEqual(first["actions"], ["sync"])
        self.assertEqual(second["actions"], ["sync"])
        self.assertEqual(third["maintenanceActions"], ["sync"])
        self.assertEqual(third["data"], "symbols: current_revision")
        self.assertEqual(sum(call["argv"][2] == "sync" for call in port.calls), 3)
        self.assertEqual(port.calls[-1]["argv"][2], "explore")

    def test_automatic_boundary_preserves_explicit_plan_binding_and_replay_guard(self):
        from selfworkflow.v3.provider_manager import ProviderManagerError

        port = FakeCommandPort(
            self._result(stdout=self._status()),
            self._result(stdout="automatically synced"),
            self._result(stdout=self._status()),
            self._result(stdout="explicitly synced"),
        )
        manager, project = self._manager(port=port)
        self._configure(manager)
        plan = manager.maintain("codegraph", "sync", str(project), plan_only=True)

        manager.ensure(str(project))
        applied = manager.maintain(
            "codegraph", "sync", str(project), plan_only=False,
            confirmed_plan_hash=plan["planHash"],
        )

        self.assertEqual(applied["status"], "succeeded")
        self.assertEqual(applied["planHash"], plan["planHash"])
        with self.assertRaisesRegex(ProviderManagerError, "codegraph-maintenance-plan-replayed"):
            manager.maintain(
                "codegraph", "sync", str(project), plan_only=False,
                confirmed_plan_hash=plan["planHash"],
            )
        self.assertEqual([call["argv"][2] for call in port.calls], ["status", "sync", "status", "sync"])

    def test_failure_is_fail_closed_and_does_not_claim_fresh(self):
        from selfworkflow.v3.provider_manager import ProviderManagerError

        port = FakeCommandPort(
            self._result(stdout=self._status(initialized=False)),
            self._result(exit_code=9, stderr="provider output"),
        )
        manager, project = self._manager(port=port)
        self._configure(manager)
        with self.assertRaisesRegex(ProviderManagerError, "codegraph-command-failed"):
            manager.preflight(str(project))

    def test_rollback_token_restores_previous_config_and_commit_discards_receipt(self):
        manager, _ = self._manager()
        self._configure(manager)
        config = self.root / "machine" / "providers.local.yaml"
        previous = config.read_bytes()
        token = uuid.uuid4().hex
        manager.configure(
            provider_id="codegraph", source_path=str(self.root / "private" / "codegraph"),
            command_prefix=("node", "new.js"), ownership="user-local",
            source_version="1.6.3", source_commit="c" * 40,
            source_hash="sha256:" + "c" * 64, dirty=False,
            replace_existing=True, rollback_token=token,
        )
        manager.rollback_config(token)
        self.assertEqual(config.read_bytes(), previous)
        self.assertFalse((self.root / "machine" / ".provider-transactions" / f"{token}.json").exists())

    def test_maintenance_is_plan_bound_and_requires_confirmation(self):
        port = FakeCommandPort(self._result(stdout="synced"))
        manager, project = self._manager(port=port)
        self._configure(manager)
        plan = manager.maintain("codegraph", "sync", str(project), plan_only=True)
        self.assertEqual(plan["sideEffectClass"], "local-write")
        result = manager.maintain(
            "codegraph", "sync", str(project), plan_only=False,
            confirmed_plan_hash=plan["planHash"],
        )
        self.assertEqual(result["status"], "succeeded")

    def test_logger_and_errors_do_not_expose_provider_output_or_path(self):
        logger = RecordingLogger()
        manager, source = self._manager(
            port=FakeCommandPort(self._result(exit_code=9, stderr="secret-output")),
            logger=logger,
        )
        self._configure(manager)
        from selfworkflow.v3.provider_manager import ProviderManagerError

        with self.assertRaises(ProviderManagerError) as caught:
            manager.doctor("codegraph")
        self.assertNotIn("secret-output", json.dumps(logger.events))
        self.assertNotIn(str(source), str(caught.exception))

    def test_cli_source_identity_resolver_forwards_the_configured_source_path(self):
        from selfworkflow import cli

        observation = {"source": "resolved"}
        with patch.object(
            cli, "_inspect_codegraph_source_identity", return_value=observation
        ) as inspect:
            self.assertIs(
                cli._inspect_provider_source_identity(r"E:\kg-code-graph"),
                observation,
            )
        inspect.assert_called_once_with(r"E:\kg-code-graph")


if __name__ == "__main__":
    unittest.main()
