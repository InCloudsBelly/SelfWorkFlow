import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from selfworkflow.graft_models import (
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    GraftModelConfigError,
    resolve_graft_model,
    save_graft_model,
)


class GraftModelTests(unittest.TestCase):
    def test_missing_config_uses_v1_default(self):
        with tempfile.TemporaryDirectory() as directory:
            result = resolve_graft_model(Path(directory) / "graft-model.local.yaml")
        self.assertEqual(result.status, "defaulted")
        self.assertEqual(result.selection.model, DEFAULT_MODEL)
        self.assertEqual(result.selection.reasoning_effort, DEFAULT_REASONING_EFFORT)

    def test_save_and_resolve_machine_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graft-model.local.yaml"
            saved = save_graft_model(path, "gpt-6-astra", "medium", confirmed=True)
            loaded = resolve_graft_model(path)
        self.assertEqual(saved.status, "configured")
        self.assertEqual(loaded.selection.model, "gpt-6-astra")
        self.assertEqual(loaded.selection.reasoning_effort, "medium")

    def test_save_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                GraftModelConfigError, "graft-model-confirmation-required"
            ):
                save_graft_model(
                    Path(directory) / "graft-model.local.yaml",
                    "gpt-6-astra", "medium", confirmed=False,
                )

    def test_invalid_config_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graft-model.local.yaml"
            path.write_text(json.dumps({"schemaVersion": 1, "unexpected": True}))
            with self.assertRaisesRegex(
                GraftModelConfigError, "graft-model-config-invalid"
            ):
                resolve_graft_model(path)

    def test_machine_config_is_not_replaced_by_host_model(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graft-model.local.yaml"
            save_graft_model(path, "gpt-6-astra", "medium", confirmed=True)
            with patch.dict(
                "os.environ",
                {
                    "SELFWORKFLOW_HOST_CURRENT_MODEL": "gpt-5.6-luna",
                    "SELFWORKFLOW_HOST_CURRENT_REASONING_EFFORT": "xhigh",
                },
                clear=False,
            ):
                loaded = resolve_graft_model(path)
        self.assertEqual(loaded.selection.model, "gpt-6-astra")
        self.assertEqual(loaded.selection.reasoning_effort, "medium")

    def test_provider_context_uses_machine_config_before_host_context(self):
        from selfworkflow.v3.provider_manager import _current_graft_deep_model_context

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graft-model.local.yaml"
            save_graft_model(path, "gpt-6-astra", "medium", confirmed=True)
            with patch.dict(
                "os.environ",
                {
                    "SELFWORKFLOW_HOST_CURRENT_MODEL": "gpt-5.6-luna",
                    "SELFWORKFLOW_HOST_CURRENT_REASONING_EFFORT": "xhigh",
                },
                clear=False,
            ):
                context = _current_graft_deep_model_context(path)
        self.assertEqual(context, ("gpt-6-astra", "medium"))
