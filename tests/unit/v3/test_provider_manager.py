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
        return self.results.pop(0)


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

    def _manager(
        self, port=None, logger=None, replace_operation=None,
        source_identity_resolver=None,
    ):
        from selfworkflow.v3.provider_manager import MachineLocalPaths, ProviderManager

        kwargs = {
            "paths": MachineLocalPaths(
                config_file=self.root / "machine" / "providers.local.yaml"
            ),
            "command_port": port or FakeCommandPort(),
            "logger": logger,
            "source_identity_resolver": source_identity_resolver or (
                lambda source_path: {
                    "source": Path(source_path),
                    "report": {
                        "version": "1.3.1-local", "commit": "b" * 40,
                        "sourceHash": "sha256:" + "a" * 64,
                        "dirty": True,
                    },
                }
            ),
        }
        if replace_operation is not None:
            kwargs["replace_operation"] = replace_operation
        return ProviderManager(**kwargs)

    def _configure(
        self, manager, command_suffix="cli.js", *, replace_existing=False,
        issue_rollback_token=False,
    ):
        source = self.root / "private" / "codegraph"
        source.mkdir(parents=True, exist_ok=True)
        return manager.configure(
            provider_id="codegraph",
            source_path=str(source.resolve()),
            command_prefix=("node", str(self.root / "private" / command_suffix)),
            ownership="user-local",
            source_version="1.3.1-local",
            source_commit="b" * 40,
            source_hash="sha256:" + "a" * 64,
            dirty=True,
            replace_existing=replace_existing,
            rollback_token=uuid.uuid4().hex if issue_rollback_token else None,
        )

    def _configure_graft(self, manager, *, replace_existing=False):
        source = self.root / "private" / "graft"
        source.mkdir(parents=True, exist_ok=True)
        return manager.configure(
            provider_id="graft",
            source_path=str(source.resolve()),
            command_prefix=("node", str(source / "dist" / "cli.js")),
            ownership="selfworkflow-managed",
            source_version="0.18.0",
            source_commit="b" * 40,
            source_hash="sha256:" + "a" * 64,
            dirty=False,
            replace_existing=replace_existing,
        )

    def test_list_is_empty_without_scanning_or_creating_config(self):
        manager = self._manager()

        self.assertEqual(manager.list_providers(), {"providers": []})
        self.assertFalse((self.root / "machine" / "providers.local.yaml").exists())

    def test_configure_is_machine_local_atomic_and_list_is_sanitized(self):
        manager = self._manager()

        result = self._configure(manager)
        listed = manager.list_providers()

        self.assertEqual(result["status"], "configured")
        self.assertEqual(listed["providers"][0]["providerId"], "codegraph")
        self.assertEqual(listed["providers"][0]["ownership"], "user-local")
        self.assertTrue(listed["providers"][0]["source"]["dirty"])
        self.assertRegex(listed["providers"][0]["commandHash"], r"^sha256:[0-9a-f]{64}$")
        self.assertNotIn(str(self.root), json.dumps(listed))
        self.assertTrue((self.root / "machine" / "providers.local.yaml").exists())
        from selfworkflow.v3.provider_config import load_provider_config
        routing_config = load_provider_config(
            path=self.root / "machine" / "providers.local.yaml",
            root=self.root / "machine",
        )
        self.assertEqual(routing_config["providers"][0]["providerId"], "codegraph")
        self.assertTrue(routing_config["providers"][0]["enabled"])

    def test_repeated_configure_is_idempotent(self):
        manager = self._manager()
        first = self._configure(manager)
        config = self.root / "machine" / "providers.local.yaml"
        before = config.read_bytes()

        second = self._configure(manager)

        self.assertEqual(first["configurationHash"], second["configurationHash"])
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual(config.read_bytes(), before)

    def test_graft_is_a_managed_provider_and_not_a_user_override(self):
        manager = self._manager()

        result = self._configure_graft(manager)
        listed = manager.list_providers()

        self.assertEqual(result["providerId"], "graft")
        self.assertEqual(listed["providers"][0]["providerId"], "graft")
        self.assertEqual(listed["providers"][0]["ownership"], "selfworkflow-managed")
        from selfworkflow.v3.provider_config import load_provider_config
        loaded = load_provider_config(
            path=self.root / "machine" / "providers.local.yaml",
            root=self.root / "machine",
        )
        self.assertEqual(
            loaded["providers"][0]["source"]["kind"], "managed-submodule",
        )

    def test_graft_preflight_and_worker_use_the_managed_adapter(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        port = FakeCommandPort(
            self._result(stdout="0.18.0"),
            self._result(stdout="""Commands:
  build
  check
  ask
  map
  grep
  callers
  skeleton
"""),
            self._result(1, stdout='{"context":{"missing":true},"graph":null}'),
            self._result(stdout="build complete"),
            self._result(stdout='{"context":{"ok":false,"missing":true},"graph":{"ok":true,"missing":false}}'),
        )
        manager = self._manager(
            port=port,
            source_identity_resolver=lambda source_path: {
                "source": Path(source_path),
                "report": {
                    "version": "0.18.0", "commit": "b" * 40,
                    "sourceHash": "sha256:" + "a" * 64, "dirty": False,
                },
            },
        )
        self._configure_graft(manager)

        result = manager.graft_preflight(str(project))

        self.assertEqual(result["status"], "initialized")
        self.assertEqual(port.calls[0]["argv"][0:2], ("node", str(self.root / "private" / "graft" / "dist" / "cli.js")))
        self.assertEqual(result["providerStatus"], "verified")
        self.assertEqual(result["graphStatus"], "fresh")
        self.assertIn("build", port.calls[3]["argv"])

    def test_graft_preflight_reports_provider_failure_without_building(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        port = FakeCommandPort(self._result(1, stderr="runtime path"))
        manager = self._manager(
            port=port,
            source_identity_resolver=lambda source_path: {
                "source": Path(source_path),
                "report": {
                    "version": "0.18.0", "commit": "b" * 40,
                    "sourceHash": "sha256:" + "a" * 64, "dirty": False,
                },
            },
        )
        self._configure_graft(manager)

        result = manager.graft_preflight(str(project))

        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["providerStatus"], "unavailable")
        self.assertEqual(result["graphStatus"], "unknown")
        self.assertNotIn("build", port.calls[0]["argv"])
        self.assertFalse((project / "graft").exists())
        self.assertFalse((project / ".gitignore").exists())

    def test_graft_deep_routes_the_explicit_model_to_the_codex_bridge(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        manager = self._manager(
            source_identity_resolver=lambda source_path: {
                "source": Path(source_path),
                "report": {
                    "version": "0.18.0", "commit": "b" * 40,
                    "sourceHash": "sha256:" + "a" * 64, "dirty": False,
                },
            },
        )
        self._configure_graft(manager)

        with patch(
            "selfworkflow.v3.graft_codex_bridge.run_codex_graft_deep",
            return_value={"status": "succeeded"},
        ) as run:
            result = manager.graft_deep(
                str(project), "gpt-5.6-luna", "xhigh",
                conversation_id="thread-manager-test",
                topic_id="kgpr-coverage",
                scope_files=("Source/main.cpp",),
            )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(run.call_args.kwargs["model"], "gpt-5.6-luna")
        self.assertEqual(run.call_args.kwargs["reasoning_effort"], "xhigh")
        self.assertEqual(run.call_args.kwargs["conversation_id"], "thread-manager-test")
        self.assertEqual(run.call_args.kwargs["topic_id"], "kgpr-coverage")
        self.assertEqual(run.call_args.kwargs["scope_files"], ("Source/main.cpp",))
        self.assertEqual(run.call_args.kwargs["graft_command"][0], "node")

    def test_graft_worker_automatically_refreshes_bound_topic_with_host_model(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        manager = self._manager(
            source_identity_resolver=lambda source_path: {
                "source": Path(source_path),
                "report": {
                    "version": "0.18.0", "commit": "b" * 40,
                    "sourceHash": "sha256:" + "a" * 64, "dirty": False,
                },
            },
        )
        self._configure_graft(manager)
        lifecycle_result = {
            "providerId": "graft", "status": "partial",
            "globalMapUpdated": False,
            "globalMap": {"deep": False, "status": "failed"},
            "conversationId": "thread-auto",
            "topicRefresh": {
                "status": "refresh-required", "action": "run-graft-deep",
                "topicId": "kgpr", "conversationId": "thread-auto",
            },
            "nextAction": "run-graft-deep",
        }
        fake_lifecycle = type(
            "FakeLifecycle", (), {"run_once": lambda self, *args, **kwargs: lifecycle_result}
        )()
        with patch(
            "selfworkflow.v3.graft_lifecycle.GraftProjectLifecycle",
            return_value=fake_lifecycle,
        ), patch.dict(
            os.environ,
            {
                "SELFWORKFLOW_HOST_CURRENT_MODEL": "gpt-5.6-sol",
                "SELFWORKFLOW_HOST_CURRENT_REASONING_EFFORT": "xhigh",
            },
            clear=False,
        ), patch.object(
            manager, "graft_deep", return_value={"status": "succeeded"}
        ) as deep, patch.object(
            manager, "status",
            side_effect=[
                {
                    "providerId": "graft", "freshness": "fresh",
                    "graphStatus": "fresh", "topicFreshness": "fresh",
                },
            ],
        ) as status:
            result = manager.graft_worker(
                str(project), conversation_id="thread-auto",
            )

        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["topicUpdated"])
        self.assertEqual(result["nextAction"], "retry-global-map")
        self.assertTrue(result["completionEligible"])
        deep.assert_called_once_with(
            str(project), "gpt-5.6-sol", "xhigh",
            conversation_id="thread-auto", topic_id="kgpr", scope_files=(),
        )
        self.assertEqual(status.call_count, 1)
        self.assertEqual(
            status.call_args_list[0].kwargs,
            {"conversation_id": "thread-auto"},
        )

    def test_graft_worker_reports_missing_host_model_without_interrupting_global_update(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        manager = self._manager(
            source_identity_resolver=lambda source_path: {
                "source": Path(source_path),
                "report": {
                    "version": "0.18.0", "commit": "b" * 40,
                    "sourceHash": "sha256:" + "a" * 64, "dirty": False,
                },
            },
        )
        self._configure_graft(manager)
        lifecycle_result = {
            "providerId": "graft", "status": "succeeded",
            "globalMapUpdated": True, "conversationId": "thread-no-model",
            "topicRefresh": {
                "status": "refresh-required", "action": "run-graft-deep",
                "topicId": "kgpr", "conversationId": "thread-no-model",
            },
            "nextAction": "run-graft-deep",
        }
        fake_lifecycle = type(
            "FakeLifecycle", (), {"run_once": lambda self, *args, **kwargs: lifecycle_result}
        )()
        with patch(
            "selfworkflow.v3.graft_lifecycle.GraftProjectLifecycle",
            return_value=fake_lifecycle,
        ), patch.dict(
            os.environ,
            {},
            clear=True,
        ), patch.object(manager, "graft_deep") as deep:
            result = manager.graft_worker(
                str(project), conversation_id="thread-no-model",
            )

        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["globalMapUpdated"])
        self.assertFalse(result["topicUpdated"])
        self.assertEqual(result["nextAction"], "retry-topic-deep")
        self.assertEqual(result["reason"], "graft-deep-current-model-unavailable")
        deep.assert_not_called()

    def test_graft_worker_keeps_global_retry_separate_when_topic_is_fresh(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        manager = self._manager(
            source_identity_resolver=lambda source_path: {
                "source": Path(source_path),
                "report": {
                    "version": "0.18.0", "commit": "b" * 40,
                    "sourceHash": "sha256:" + "a" * 64, "dirty": False,
                },
            },
        )
        self._configure_graft(manager)
        lifecycle_result = {
            "providerId": "graft", "status": "partial",
            "globalMapUpdated": False,
            "globalMap": {"deep": False, "status": "failed"},
            "conversationId": "thread-global-only-retry",
            "topicRefresh": {
                "status": "fresh", "action": "none",
                "topicId": "kgpr", "conversationId": "thread-global-only-retry",
            },
            "nextAction": "retry-global-map",
        }
        fake_lifecycle = type(
            "FakeLifecycle", (), {"run_once": lambda self, *args, **kwargs: lifecycle_result}
        )()
        with patch(
            "selfworkflow.v3.graft_lifecycle.GraftProjectLifecycle",
            return_value=fake_lifecycle,
        ), patch.object(manager, "graft_deep") as deep:
            result = manager.graft_worker(
                str(project), conversation_id="thread-global-only-retry",
            )

        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["topicUpdated"])
        self.assertTrue(result["completionEligible"])
        self.assertEqual(result["nextAction"], "retry-global-map")
        deep.assert_not_called()

    def test_graft_worker_does_not_claim_fresh_when_post_deep_verification_fails(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        manager = self._manager(
            source_identity_resolver=lambda source_path: {
                "source": Path(source_path),
                "report": {
                    "version": "0.18.0", "commit": "b" * 40,
                    "sourceHash": "sha256:" + "a" * 64, "dirty": False,
                },
            },
        )
        self._configure_graft(manager)
        lifecycle_result = {
            "providerId": "graft", "status": "succeeded",
            "globalMapUpdated": True, "conversationId": "thread-stale",
            "topicRefresh": {
                "status": "refresh-required", "action": "run-graft-deep",
                "topicId": "kgpr", "conversationId": "thread-stale",
            },
            "nextAction": "run-graft-deep",
        }
        fake_lifecycle = type(
            "FakeLifecycle", (), {"run_once": lambda self, *args, **kwargs: lifecycle_result}
        )()
        with patch(
            "selfworkflow.v3.graft_lifecycle.GraftProjectLifecycle",
            return_value=fake_lifecycle,
        ), patch.dict(
            os.environ,
            {
                "SELFWORKFLOW_HOST_CURRENT_MODEL": "gpt-5.6-sol",
                "SELFWORKFLOW_HOST_CURRENT_REASONING_EFFORT": "xhigh",
            },
            clear=False,
        ), patch.object(
            manager, "graft_deep", return_value={"status": "succeeded"}
        ), patch.object(
            manager, "status",
            side_effect=[
                {"providerId": "graft", "freshness": "fresh", "graphStatus": "fresh"},
                {
                    "providerId": "graft", "freshness": "stale",
                    "graphStatus": "stale", "topicFreshness": "stale",
                },
            ],
        ):
            result = manager.graft_worker(
                str(project), conversation_id="thread-stale",
            )

        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["globalMapUpdated"])
        self.assertFalse(result["topicUpdated"])
        self.assertEqual(result["nextAction"], "retry-topic-deep")
        self.assertEqual(result["reason"], "graft-freshness-verification-failed")

    def test_graft_status_enforces_project_binding_before_provider_dispatch(self):
        from selfworkflow.v3.provider_manager import ProviderManagerError

        port = FakeCommandPort()
        manager = self._manager(
            port=port,
            source_identity_resolver=lambda source_path: {
                "source": Path(source_path),
                "report": {
                    "version": "0.18.0", "commit": "b" * 40,
                    "sourceHash": "sha256:" + "a" * 64, "dirty": False,
                },
            },
        )
        self._configure_graft(manager)

        with self.assertRaisesRegex(
            ProviderManagerError, "graft-project-root-invalid",
        ):
            manager.status("graft", "C:/not-a-project")
        self.assertEqual(port.calls, [])

    def test_graft_query_enforces_project_binding_before_provider_dispatch(self):
        from selfworkflow.v3.provider_manager import ProviderManagerError

        port = FakeCommandPort()
        manager = self._manager(
            port=port,
            source_identity_resolver=lambda source_path: {
                "source": Path(source_path),
                "report": {
                    "version": "0.18.0", "commit": "b" * 40,
                    "sourceHash": "sha256:" + "a" * 64, "dirty": False,
                },
            },
        )
        self._configure_graft(manager)

        with self.assertRaisesRegex(
            ProviderManagerError, "graft-project-root-invalid",
        ):
            manager.query("graft", "C:/not-a-project", "x", query_kind="ask")
        self.assertEqual(port.calls, [])

    def test_configure_holds_an_exclusive_machine_config_lock(self):
        from selfworkflow.v3.provider_manager import ProviderManagerError

        manager = self._manager()
        with manager._config_lock():
            with self.assertRaises(ProviderManagerError) as caught:
                self._configure(manager)
        self.assertEqual(caught.exception.reason, "provider-config-locked")
        self.assertFalse((self.root / "machine/providers.local.yaml").exists())

    def test_rollback_token_uses_postimage_cas_and_never_overwrites_concurrent_change(self):
        from selfworkflow.v3.provider_manager import ProviderManagerError

        manager = self._manager()
        original = self._configure(manager, "old.js")
        transaction = self._configure(
            manager, "install.js", replace_existing=True,
            issue_rollback_token=True,
        )
        concurrent = self._configure(manager, "concurrent.js", replace_existing=True)

        with self.assertRaises(ProviderManagerError) as caught:
            manager.rollback_config(transaction["rollbackToken"])
        self.assertEqual(
            caught.exception.reason, "provider-config-rollback-state-drift"
        )
        self.assertEqual(
            manager.list_providers()["providers"][0]["bindingHash"],
            concurrent["bindingHash"],
        )
        self.assertNotEqual(original["bindingHash"], concurrent["bindingHash"])

    def test_rollback_token_restores_preimage_once_under_the_config_lock(self):
        from selfworkflow.v3.provider_manager import ProviderManagerError

        manager = self._manager()
        original = self._configure(manager, "old.js")
        transaction = self._configure(
            manager, "install.js", replace_existing=True,
            issue_rollback_token=True,
        )

        result = manager.rollback_config(transaction["rollbackToken"])

        self.assertEqual(result["status"], "rolled-back")
        self.assertEqual(
            manager.list_providers()["providers"][0]["bindingHash"],
            original["bindingHash"],
        )
        with self.assertRaises(ProviderManagerError) as caught:
            manager.rollback_config(transaction["rollbackToken"])
        self.assertEqual(caught.exception.reason, "provider-config-rollback-invalid")

    def test_commit_token_discards_preimage_without_changing_configuration(self):
        from selfworkflow.v3.provider_manager import ProviderManagerError

        manager = self._manager()
        transaction = self._configure(manager, issue_rollback_token=True)
        configured = manager.list_providers()["providers"][0]["bindingHash"]

        result = manager.commit_config(transaction["rollbackToken"])

        self.assertEqual(result["status"], "committed")
        self.assertEqual(
            manager.list_providers()["providers"][0]["bindingHash"], configured
        )
        with self.assertRaises(ProviderManagerError) as caught:
            manager.rollback_config(transaction["rollbackToken"])
        self.assertEqual(caught.exception.reason, "provider-config-rollback-invalid")

    def test_if_issued_rollback_is_noop_when_configure_never_issued_token(self):
        manager = self._manager()

        result = manager.rollback_config("0" * 32, if_issued=True)

        self.assertEqual(result["status"], "not-issued")
        self.assertFalse((self.root / "machine/providers.local.yaml").exists())

    def test_transaction_record_failure_restores_config_before_releasing_lock(self):
        from selfworkflow.v3.provider_manager import ProviderManagerError

        manager = self._manager()
        self._configure(manager, "old.js")
        config = self.root / "machine/providers.local.yaml"
        original = config.read_bytes()

        def fail_transaction_replace(source, target):
            if Path(target).parent.name == ".provider-transactions":
                raise OSError("injected transaction failure")
            os.replace(source, target)

        failing = self._manager(replace_operation=fail_transaction_replace)
        with self.assertRaises(ProviderManagerError) as caught:
            self._configure(
                failing, "new.js", replace_existing=True,
                issue_rollback_token=True,
            )

        self.assertEqual(
            caught.exception.reason, "provider-config-transaction-write-failed"
        )
        self.assertEqual(config.read_bytes(), original)

    def test_interrupt_after_config_publish_has_write_ahead_preimage(self):
        manager = self._manager()
        self._configure(manager, "old.js")
        config = self.root / "machine/providers.local.yaml"
        original = config.read_bytes()
        real_write = manager._write_config

        def write_then_interrupt(value):
            real_write(value)
            raise SystemExit("injected-interrupt")

        manager._write_config = write_then_interrupt
        with self.assertRaises(SystemExit):
            self._configure(
                manager, "new.js", replace_existing=True,
                issue_rollback_token=True,
            )

        self.assertEqual(config.read_bytes(), original)
        transactions = list(
            (self.root / "machine/.provider-transactions").glob("*.json")
        )
        self.assertEqual(len(transactions), 1)
        transaction = json.loads(transactions[0].read_text(encoding="utf-8"))
        self.assertEqual(transaction["state"], "rolled-back")
        self.assertEqual(
            manager.rollback_config(
                transaction["rollbackToken"], if_issued=True,
            )["status"],
            "already-rolled-back",
        )

    def test_different_existing_binding_requires_explicit_replace(self):
        from selfworkflow.v3.provider_manager import ProviderManagerError

        manager = self._manager()
        self._configure(manager, "old.js")
        with self.assertRaises(ProviderManagerError) as caught:
            self._configure(manager, "new.js")
        self.assertEqual(caught.exception.reason, "provider-config-conflict")
        replaced = self._configure(manager, "new.js", replace_existing=True)
        self.assertEqual(replaced["status"], "configured")

    def test_production_diagnostics_are_disabled_until_atomic_launch_is_bound(self):
        from selfworkflow.v3.provider_manager import ProviderManagerError

        port = FakeCommandPort(
            self._result(stdout="1.3.1"),
            self._result(stdout="Usage: codegraph"),
            self._result(stdout='{"initialized":true,"revision":"r9"}'),
        )
        manager = self._manager(port=port)
        self._configure(manager)

        for operation in (
            lambda: manager.doctor("codegraph"),
            lambda: manager.status("codegraph", "C:/work/project"),
        ):
            with self.assertRaises(ProviderManagerError) as caught:
                operation()
            self.assertEqual(caught.exception.reason, "provider-operation-unverified")
        self.assertEqual(port.calls, [])

    def test_maintain_plan_only_does_not_execute_mutation(self):
        port = FakeCommandPort()
        manager = self._manager(port=port)
        self._configure(manager)

        plan = manager.maintain(
            "codegraph", "sync", "C:/work/project", plan_only=True
        )

        self.assertEqual(plan["sideEffectClass"], "local-write")
        self.assertEqual(plan["supportStatus"], "unverified")
        self.assertEqual(port.calls, [])

    def test_maintain_apply_is_disabled_until_production_safety_ports_exist(self):
        from selfworkflow.v3.provider_manager import ProviderManagerError

        port = FakeCommandPort(self._result(stdout='{"ok":true}'))
        manager = self._manager(port=port)
        self._configure(manager)
        plan = manager.maintain(
            "codegraph", "sync", "C:/work/project", plan_only=True
        )

        with self.assertRaises(ProviderManagerError) as caught:
            manager.maintain(
                "codegraph",
                "sync",
                "C:/work/project",
                plan_only=False,
                confirmed_plan_hash=plan["planHash"],
            )
        self.assertEqual(caught.exception.reason, "provider-maintenance-apply-unverified")
        self.assertEqual(port.calls, [])

    def test_maintain_rejects_hash_mismatch_before_command(self):
        from selfworkflow.v3.provider_manager import ProviderManagerError

        port = FakeCommandPort()
        manager = self._manager(port=port)
        self._configure(manager)

        with self.assertRaises(ProviderManagerError) as caught:
            manager.maintain(
                "codegraph",
                "sync",
                "C:/work/project",
                plan_only=False,
                confirmed_plan_hash="sha256:" + "0" * 64,
            )
        self.assertEqual(caught.exception.reason, "provider-maintenance-apply-unverified")
        self.assertEqual(port.calls, [])

    def test_maintain_plan_cannot_be_replayed_by_fresh_manager(self):
        from selfworkflow.v3.provider_manager import ProviderManagerError

        issuing = self._manager()
        self._configure(issuing)
        plan = issuing.maintain(
            "codegraph", "sync", "C:/work/project", plan_only=True
        )
        fresh_port = FakeCommandPort(self._result(stdout='{"ok":true}'))
        fresh = self._manager(port=fresh_port)

        with self.assertRaises(ProviderManagerError) as caught:
            fresh.maintain(
                "codegraph",
                "sync",
                "C:/work/project",
                plan_only=False,
                confirmed_plan_hash=plan["planHash"],
            )
        self.assertEqual(caught.exception.reason, "provider-maintenance-apply-unverified")
        self.assertEqual(fresh_port.calls, [])

    def test_source_identity_is_revalidated_before_every_maintenance_plan(self):
        from selfworkflow.v3.provider_manager import ProviderManagerError

        state = {"sourceHash": "sha256:" + "a" * 64}
        port = FakeCommandPort(self._result(stdout="1.3.1"))
        manager = self._manager(
            port=port,
            source_identity_resolver=lambda source_path: {
                "source": Path(source_path),
                "report": {
                    "version": "1.3.1-local", "commit": "b" * 40,
                    "sourceHash": state["sourceHash"], "dirty": True,
                },
            },
        )
        self._configure(manager)
        state["sourceHash"] = "sha256:" + "c" * 64

        with self.assertRaises(ProviderManagerError) as caught:
            manager.maintain(
                "codegraph", "sync", "C:/work/project", plan_only=True
            )
        self.assertEqual(caught.exception.reason, "provider-source-identity-drift")
        self.assertEqual(port.calls, [])

    def test_user_owned_provider_upgrade_is_always_rejected(self):
        from selfworkflow.v3.provider_manager import ProviderManagerError

        manager = self._manager()
        self._configure(manager)
        with self.assertRaises(ProviderManagerError) as caught:
            manager.maintain(
                "codegraph",
                "upgrade-managed-install",
                "C:/work/project",
                plan_only=True,
            )
        self.assertEqual(caught.exception.reason, "provider-user-owned-upgrade-forbidden")

    def test_failed_atomic_replace_restores_previous_config(self):
        manager = self._manager()
        self._configure(manager, "old.js")
        config = self.root / "machine" / "providers.local.yaml"
        old = config.read_bytes()
        calls = []

        def fail_config_replace(source, target):
            calls.append((Path(source), Path(target)))
            if Path(target) == config and sum(1 for _, item in calls if item == config) == 1:
                raise OSError("injected replace failure")
            os.replace(source, target)

        failing = self._manager(replace_operation=fail_config_replace)
        from selfworkflow.v3.provider_manager import ProviderManagerError
        with self.assertRaises(ProviderManagerError) as caught:
            self._configure(failing, "new.js", replace_existing=True)

        self.assertEqual(caught.exception.reason, "provider-config-write-failed")
        self.assertEqual(config.read_bytes(), old)
        self.assertTrue(config.with_suffix(".yaml.bak").exists())

    def test_failures_and_logs_never_expose_command_path_or_provider_output(self):
        from selfworkflow.v3.provider_manager import ProviderManagerError

        logger = RecordingLogger()
        secret = "credential-do-not-log"
        port = FakeCommandPort(self._result(9, stderr=secret))
        manager = self._manager(port=port, logger=logger)
        self._configure(manager, secret + ".js")

        with self.assertRaises(ProviderManagerError) as caught:
            manager.doctor("codegraph")

        serialized = json.dumps(logger.events)
        self.assertNotIn(secret, serialized)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn(secret, str(caught.exception))
        self.assertEqual(caught.exception.reason, "provider-operation-unverified")


if __name__ == "__main__":
    unittest.main()
