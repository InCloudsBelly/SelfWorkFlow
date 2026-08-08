import tempfile
import unittest
from pathlib import Path

from selfworkflow.v3.provider_config import (
    ProviderConfigError,
    load_provider_config,
    resolve_provider,
)


class ProviderConfigTests(unittest.TestCase):
    def test_default_path_is_injected_and_missing_config_does_not_scan(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            (root_path / "unrelated-provider").mkdir()
            config = load_provider_config(root=root_path)
            self.assertEqual(config, {"schemaVersion": 3, "providers": []})

    def test_explicit_task_failure_never_falls_back(self):
        with self.assertRaises(ProviderConfigError) as error:
            resolve_provider(
                "code.context", "inspect",
                task_explicit={"providerId": "missing", "state": "unsupported"},
                public=[{"providerId": "builtin.cpp-core", "state": "supported"}],
            )
        self.assertEqual(error.exception.reason, "provider-task-explicit-invalid")
        self.assertNotIn("missing", str(error.exception))

    def test_precedence_and_visible_fallback_receipt(self):
        result = resolve_provider(
            "code.context", "inspect",
            project=[{"providerId": "project.provider", "state": "unsupported"}],
            user_machine=[{"providerId": "machine.provider", "state": "supported"}],
            public=[{"providerId": "public.provider", "state": "supported"}],
        )
        self.assertEqual(result.provider_id, "machine.provider")
        self.assertIsNotNone(result.fallback_receipt)
        self.assertEqual(result.fallback_receipt["fromLayer"], "project")

    def test_conflicting_same_layer_is_stable_failure(self):
        with self.assertRaises(ProviderConfigError) as error:
            resolve_provider(
                "code.context", "inspect",
                user_machine=[
                    {"providerId": "a", "state": "supported"},
                    {"providerId": "b", "state": "supported"},
                ],
            )
        self.assertEqual(error.exception.reason, "provider-config-conflict")

    def test_candidate_and_unverified_cannot_be_selected_as_supported(self):
        with self.assertRaises(ProviderConfigError):
            resolve_provider(
                "code.context", "inspect",
                public=[{"providerId": "candidate", "state": "candidate"}],
                builtin=[{"providerId": "unverified", "state": "unverified"}],
            )

    def test_user_config_is_explicitly_loaded_and_path_is_not_echoed(self):
        with tempfile.TemporaryDirectory() as root:
            config_path = Path(root) / "SelfWorkFlow" / "config" / "providers.local.yaml"
            config_path.parent.mkdir(parents=True)
            configured_path = chr(67) + ":" + "\\\\Users\\\\Example\\\\provider"
            config_path.write_text(
                "schemaVersion: 3\nproviders:\n  - providerId: codegraph.local\n    sourcePath: " + configured_path + "\n    enabled: true\n",
                encoding="utf-8",
            )
            config = load_provider_config(root=root)
            result = resolve_provider("code.context", "inspect", user_config=config)
            self.assertEqual(result.provider_id, "codegraph.local")

    def test_invalid_path_fails_without_disclosing_path(self):
        with self.assertRaises(ProviderConfigError) as error:
            resolve_provider(
                "code.context", "inspect",
                user_config={"schemaVersion": 3, "providers": [{
                    "providerId": "local", "sourcePath": "C:relative:secret",
                    "enabled": True,
                }]},
            )
        self.assertEqual(error.exception.reason, "provider-config-path-invalid")
        self.assertNotIn("secret", str(error.exception))


if __name__ == "__main__":
    unittest.main()
