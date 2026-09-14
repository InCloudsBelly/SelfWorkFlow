from io import StringIO
from pathlib import Path
import os
import subprocess
from tempfile import TemporaryDirectory
from unittest import mock
import unittest

from selfworkflow.cli import main


class _Manager:
    def __init__(self):
        self.calls = []

    def list_providers(self):
        return {"providers": []}

    def doctor(self, provider_id):
        from selfworkflow.v3.provider_manager import ProviderManagerError
        raise ProviderManagerError("provider-operation-unverified")

    def status(self, provider_id, project_root):
        from selfworkflow.v3.provider_manager import ProviderManagerError
        raise ProviderManagerError("provider-operation-unverified")

    def maintain(self, provider_id, action, project_root, *, plan_only, confirmed_plan_hash=None):
        self.calls.append((provider_id, action, project_root, plan_only, confirmed_plan_hash))
        if plan_only:
            return {
                "providerId": provider_id,
                "action": action,
                "supportStatus": "unverified",
                "planHash": "sha256:" + "a" * 64,
            }
        from selfworkflow.v3.provider_manager import ProviderManagerError
        raise ProviderManagerError("provider-maintenance-apply-unverified")

    def rollback_config(self, rollback_token, *, if_issued=False):
        self.calls.append(("rollback", rollback_token, if_issued))
        return {"status": "rolled-back"}

    def commit_config(self, rollback_token):
        self.calls.append(("commit", rollback_token))
        return {"status": "committed"}


class V3ProviderWorkflowAcceptanceTests(unittest.TestCase):
    def test_list_is_available_but_unverified_diagnostics_fail_closed(self):
        manager = _Manager()
        output = StringIO()
        with mock.patch(
            "selfworkflow.cli._provider_manager", return_value=manager
        ), mock.patch("sys.stdout", output):
            self.assertEqual(main(["provider", "list"]), 0)
            self.assertIn("providers", output.getvalue())
        for arguments in (
            ["provider", "doctor"],
            ["provider", "status", "--project-root", "C:/work/project"],
        ):
            with self.subTest(arguments=arguments), mock.patch(
                "selfworkflow.cli._provider_manager", return_value=manager
            ), mock.patch("sys.stderr", StringIO()):
                self.assertEqual(main(arguments), 70)

    def test_maintenance_prints_plan_and_requires_exact_confirmation(self):
        manager = _Manager()
        base = [
            "provider", "maintain", "--action", "sync",
            "--project-root", "C:/work/project",
        ]
        with mock.patch("selfworkflow.cli._provider_manager", return_value=manager):
            with mock.patch("sys.stdout", StringIO()):
                self.assertEqual(main(base + ["--plan-only"]), 0)
            with mock.patch("sys.stderr", StringIO()):
                self.assertEqual(main(base), 70)
            with mock.patch("sys.stderr", StringIO()):
                self.assertEqual(
                    main(base + ["--confirm-plan-hash", "sha256:" + "a" * 64]),
                    70,
                )
        self.assertEqual(manager.calls[-1][-1], "sha256:" + "a" * 64)

    def test_graft_deep_failure_has_nonzero_process_exit(self):
        manager = _Manager()
        manager.graft_deep = mock.Mock(return_value={
            "status": "failed",
            "reason": "graft-deep-not-fresh",
        })
        arguments = [
            "provider", "graft-deep", "--project-root", "C:/work/project",
            "--model", "gpt-5.6-luna", "--reasoning-effort", "xhigh",
        ]
        with mock.patch(
            "selfworkflow.cli._provider_manager", return_value=manager
        ), mock.patch("sys.stdout", StringIO()):
            self.assertEqual(main(arguments), 71)

    def test_graft_deep_success_keeps_zero_process_exit(self):
        manager = _Manager()
        manager.graft_deep = mock.Mock(return_value={
            "status": "succeeded",
            "freshness": "fresh",
        })
        arguments = [
            "provider", "graft-deep", "--project-root", "C:/work/project",
            "--model", "gpt-5.6-luna", "--reasoning-effort", "xhigh",
        ]
        with mock.patch(
            "selfworkflow.cli._provider_manager", return_value=manager
        ), mock.patch("sys.stdout", StringIO()):
            self.assertEqual(main(arguments), 0)

    def test_configure_uses_explicit_path_helper_only(self):
        manager = _Manager()
        configured = {"providerId": "codegraph", "status": "configured"}
        with mock.patch(
            "selfworkflow.cli._provider_manager", return_value=manager
        ), mock.patch(
            "selfworkflow.cli._configure_codegraph", return_value=configured
        ) as configure, mock.patch("sys.stdout", StringIO()):
            self.assertEqual(
                main(["provider", "configure", "--codegraph-path", "C:/explicit"]),
                0,
            )
        configure.assert_called_once_with(
            manager, "C:/explicit", replace_existing=False,
            expected_source_hash=None,
            rollback_token=None,
        )

    def test_configure_and_transaction_commands_forward_exact_rollback_token(self):
        manager = _Manager()
        token = "a" * 32
        configured = {
            "providerId": "codegraph", "status": "configured",
            "rollbackToken": token,
        }
        with mock.patch(
            "selfworkflow.cli._provider_manager", return_value=manager
        ), mock.patch(
            "selfworkflow.cli._configure_codegraph", return_value=configured
        ) as configure, mock.patch("sys.stdout", StringIO()):
            self.assertEqual(main([
                "provider", "configure", "--codegraph-path", "C:/explicit",
                "--rollback-token", token,
            ]), 0)
            self.assertEqual(main([
                "provider", "rollback-config", "--rollback-token", token,
                "--if-issued",
            ]), 0)
            self.assertEqual(main([
                "provider", "commit-config", "--rollback-token", token,
            ]), 0)

        configure.assert_called_once_with(
            manager, "C:/explicit", replace_existing=False,
            expected_source_hash=None, rollback_token=token,
        )
        self.assertEqual(manager.calls[-2:], [
            ("rollback", token, True), ("commit", token),
        ])

    def test_configure_rejects_source_drift_before_machine_write(self):
        from selfworkflow.cli import _configure_codegraph

        manager = mock.Mock()
        observation = {
            "source": "C:/source",
            "script": "C:/source/dist/bin/codegraph.js",
            "report": {
                "version": "1", "commit": "a" * 40, "dirty": False,
                "sourceHash": "sha256:" + "b" * 64,
            },
        }
        with mock.patch(
            "selfworkflow.cli._inspect_codegraph_source", return_value=observation
        ), self.assertRaisesRegex(ValueError, "codegraph-source-drift"):
            _configure_codegraph(
                manager, "C:/source",
                expected_source_hash="sha256:" + "c" * 64,
            )
        manager.configure.assert_not_called()

    def test_runtime_manager_uses_non_executing_source_identity_inspection(self):
        from selfworkflow import cli

        with mock.patch(
            "selfworkflow.v3.provider_manager.ProviderManager"
        ) as manager_type:
            cli._provider_manager(None)

        self.assertIs(
            manager_type.call_args.kwargs["source_identity_resolver"],
            cli._inspect_provider_source_identity,
        )

    def test_identity_inspection_disables_git_helpers_and_provider_execution(self):
        from selfworkflow import cli

        with TemporaryDirectory() as temporary:
            source = Path(temporary).resolve()
            script = source / "dist/bin/codegraph.js"
            script.parent.mkdir(parents=True)
            script.write_text("do-not-execute\n", encoding="utf-8")
            calls = []

            def fake_run(argv, **kwargs):
                calls.append((tuple(argv), dict(kwargs)))
                arguments = tuple(argv)
                if "--show-toplevel" in arguments:
                    output = (str(source) + "\n").encode()
                elif "HEAD^{tree}" in arguments:
                    output = ("b" * 40 + "\n").encode()
                elif "rev-parse" in arguments:
                    output = ("a" * 40 + "\n").encode()
                else:
                    output = b""
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr=b"")

            with mock.patch("selfworkflow.cli.subprocess.run", side_effect=fake_run):
                report = cli._inspect_codegraph_source_identity(str(source))["report"]

        self.assertRegex(report["sourceHash"], r"^sha256:[0-9a-f]{64}$")
        self.assertTrue(all(
            kwargs["env"]["GIT_CONFIG_NOSYSTEM"] == "1"
            and kwargs["env"]["GIT_CONFIG_GLOBAL"] == os.devnull
            and "core.fsmonitor=false" in argv
            for argv, kwargs in calls
        ))
        diff_call = next(argv for argv, _ in calls if "diff" in argv)
        self.assertIn("--no-ext-diff", diff_call)
        self.assertIn("--no-textconv", diff_call)

    def test_public_cli_rejects_provider_config_outside_machine_root(self):
        from selfworkflow.cli import _provider_config_file

        with TemporaryDirectory() as temporary, self.assertRaisesRegex(
            ValueError, "provider-config-path-outside-machine-root"
        ):
            _provider_config_file(str(Path(temporary).resolve() / "providers.json"))


if __name__ == "__main__":
    unittest.main()
