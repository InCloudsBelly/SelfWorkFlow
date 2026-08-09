from io import StringIO
from unittest import mock
import unittest

from selfworkflow.cli import main


class _Manager:
    def __init__(self):
        self.calls = []

    def list_providers(self):
        return {"providers": []}

    def doctor(self, provider_id):
        return {"providerId": provider_id, "status": "healthy", "supportStatus": "unverified"}

    def status(self, provider_id, project_root):
        return {"providerId": provider_id, "initialized": False, "supportStatus": "unverified"}

    def maintain(self, provider_id, action, project_root, *, plan_only, confirmed_plan_hash=None):
        self.calls.append((provider_id, action, project_root, plan_only, confirmed_plan_hash))
        if plan_only:
            return {
                "providerId": provider_id,
                "action": action,
                "supportStatus": "unverified",
                "planHash": "sha256:" + "a" * 64,
            }
        return {"providerId": provider_id, "status": "succeeded"}


class V3ProviderWorkflowAcceptanceTests(unittest.TestCase):
    def test_list_and_readonly_diagnostics_are_exposed_by_cli(self):
        manager = _Manager()
        for arguments, expected in (
            (["provider", "list"], "providers"),
            (["provider", "doctor"], "unverified"),
            (["provider", "status", "--project-root", "C:/work/project"], "initialized"),
        ):
            output = StringIO()
            with self.subTest(arguments=arguments), mock.patch(
                "selfworkflow.cli._provider_manager", return_value=manager
            ), mock.patch("sys.stdout", output):
                self.assertEqual(main(arguments), 0)
                self.assertIn(expected, output.getvalue())

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
            with mock.patch("sys.stdout", StringIO()):
                self.assertEqual(
                    main(base + ["--confirm-plan-hash", "sha256:" + "a" * 64]),
                    0,
                )
        self.assertEqual(manager.calls[-1][-1], "sha256:" + "a" * 64)

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
        )

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


if __name__ == "__main__":
    unittest.main()
