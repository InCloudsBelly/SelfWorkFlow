from pathlib import Path
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout


class ReviewModelConfigTests(unittest.TestCase):
    def test_missing_agent_requires_user_configuration(self):
        from selfworkflow.review_models import resolve_review_model

        with tempfile.TemporaryDirectory() as directory:
            result = resolve_review_model("claude", Path(directory) / "review.yaml")

        self.assertEqual(result.status, "needs_user_configuration")
        self.assertIsNone(result.selection)
        self.assertEqual(result.agent_id, "claude")

    def test_loads_agent_selection_without_alias_mapping(self):
        from selfworkflow.review_models import resolve_review_model

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.yaml"
            path.write_text(
                """
schemaVersion: 1
agents:
  codex:
    review:
      model: gpt-5.6-sol
      reasoningEffort: xhigh
""",
                encoding="utf-8",
            )
            result = resolve_review_model("codex", path)

        self.assertEqual(result.status, "configured")
        self.assertEqual(result.selection.model, "gpt-5.6-sol")
        self.assertEqual(result.selection.reasoning_effort, "xhigh")

    def test_null_review_is_treated_as_missing_not_as_default(self):
        from selfworkflow.review_models import resolve_review_model

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.yaml"
            path.write_text(
                "schemaVersion: 1\nagents:\n  claude:\n    review: null\n",
                encoding="utf-8",
            )
            result = resolve_review_model("claude", path)

        self.assertEqual(result.status, "needs_user_configuration")
        self.assertIsNone(result.selection)

    def test_invalid_reasoning_effort_is_rejected(self):
        from selfworkflow.review_models import ReviewModelConfigError, resolve_review_model

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.yaml"
            path.write_text(
                """
schemaVersion: 1
agents:
  codex:
    review:
      model: gpt-5.6-sol
      reasoningEffort: Xmax
""",
                encoding="utf-8",
            )
            with self.assertRaises(ReviewModelConfigError):
                resolve_review_model("codex", path)

    def test_save_requires_confirmation_and_preserves_other_agents(self):
        from selfworkflow.review_models import (
            ReviewModelConfigError,
            resolve_review_model,
            save_review_model,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.yaml"
            save_review_model(
                path, "codex", "gpt-5.6-sol", "max", confirmed=True,
            )
            with self.assertRaises(ReviewModelConfigError):
                save_review_model(
                    path, "claude", "claude-sonnet", "high", confirmed=False,
                )
            save_review_model(
                path, "claude", "claude-sonnet", "high", confirmed=True,
            )
            codex = resolve_review_model("codex", path)
            claude = resolve_review_model("claude", path)

        self.assertEqual(codex.selection.model, "gpt-5.6-sol")
        self.assertEqual(claude.selection.model, "claude-sonnet")

    def test_one_time_override_is_not_written_to_config(self):
        from selfworkflow.review_models import (
            ReviewModelConfigError,
            one_time_review_model,
            resolve_review_model,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.yaml"
            override = one_time_review_model("codex", "gpt-5.6-sol", "max")
            self.assertEqual(override["selectionMode"], "one-time")
            self.assertEqual(
                resolve_review_model("codex", path).status,
                "needs_user_configuration",
            )
            with self.assertRaises(ReviewModelConfigError):
                one_time_review_model("codex", "gpt-5.6-sol", "Xmax")

    def test_payload_accepts_mapping_and_requires_exact_selection_mode(self):
        from selfworkflow.review_models import (
            ReviewModelConfigError,
            normalize_review_model_payload,
        )

        payload = normalize_review_model_payload({
            "agentId": "codex",
            "model": "gpt-5.6-sol",
            "reasoningEffort": "max",
            "selectionMode": "one-time",
        })
        self.assertEqual(payload["selectionMode"], "one-time")
        with self.assertRaises(ReviewModelConfigError):
            normalize_review_model_payload({
                **dict(payload), "unexpected": True,
            })

    def test_cli_can_show_and_save_machine_local_default(self):
        from selfworkflow.cli import main

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.yaml"
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main([
                    "review-model", "set", "--agent", "codex",
                    "--model", "gpt-5.6-sol", "--reasoning-effort", "max",
                    "--config-file", str(path), "--confirm",
                ])
            self.assertEqual(exit_code, 0)
            saved = json.loads(output.getvalue())
            self.assertEqual(saved["status"], "configured")

            output = io.StringIO()
            error = io.StringIO()
            with redirect_stdout(output), redirect_stderr(error):
                exit_code = main([
                    "review-model", "status", "--agent", "codex",
                    "--config-file", str(path),
                ])
            self.assertEqual(exit_code, 0)
            self.assertEqual(error.getvalue(), "")
            status = json.loads(output.getvalue())
            self.assertEqual(status["review"]["model"], "gpt-5.6-sol")
            self.assertEqual(status["review"]["reasoningEffort"], "max")

    def test_cli_set_without_confirmation_fails_closed(self):
        from selfworkflow.cli import main

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.yaml"
            error = io.StringIO()
            with redirect_stderr(error):
                exit_code = main([
                    "review-model", "set", "--agent", "codex",
                    "--model", "gpt-5.6-sol", "--reasoning-effort", "max",
                    "--config-file", str(path),
                ])

        self.assertEqual(exit_code, 54)
        self.assertIn("review-model-confirmation-required", error.getvalue())


if __name__ == "__main__":
    unittest.main()
