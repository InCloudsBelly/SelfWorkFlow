"""Review-specific model selection has been removed, not silently ignored."""

import io
from contextlib import redirect_stderr, redirect_stdout
import unittest


class ReviewModelInheritanceTests(unittest.TestCase):
    def test_cli_no_longer_advertises_review_model_commands(self):
        from selfworkflow.cli import main

        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as caught:
            main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertNotIn("review-model", output.getvalue())

    def test_legacy_config_command_cannot_create_a_new_override(self):
        from selfworkflow.cli import main

        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            main(["review-model", "set", "--agent", "codex", "--model", "other",
                  "--reasoning-effort", "max", "--confirm"])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
