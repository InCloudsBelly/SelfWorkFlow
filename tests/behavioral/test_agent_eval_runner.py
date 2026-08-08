import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class AgentEvalRunnerTests(unittest.TestCase):
    def _run(self, scenario_text, timeout=5):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            scenario = temporary_root / "scenario.yaml"
            scenario.write_text(scenario_text, encoding="utf-8")
            output = temporary_root / "output"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "selfworkflow.agent_eval",
                    "--agent-command",
                    str(ROOT / "tests/fixtures/agent-eval/fake-agent.py"),
                    "--scenario",
                    str(scenario),
                    "--schema",
                    str(ROOT / "schemas/agent-eval-result.schema.json"),
                    "--output-root",
                    str(output),
                    "--timeout-seconds",
                    str(timeout),
                    "--model",
                    "gpt-5.6-sol",
                    "--reasoning-effort",
                    "xhigh",
                    "--mode",
                    "baseline",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            evidence = None
            if result.returncode == 0:
                evidence = json.loads(Path(result.stdout.strip()).read_text(encoding="utf-8"))
            return result, evidence

    def test_fake_agent_happy_path_binds_model_effort_hashes_and_clean_tree(self):
        result, evidence = self._run("schemaVersion: 1\nfixtureMode: valid\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(evidence["model"], "gpt-5.6-sol")
        self.assertEqual(evidence["reasoningEffort"], "xhigh")
        self.assertRegex(evidence["scenarioHash"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(evidence["sandboxTreeHash"], r"^[0-9a-f]{40}$")

    def test_timeout_nonzero_invalid_and_tree_drift_fail_closed(self):
        cases = (("timeout", 1), ("nonzero", 5), ("invalid", 5), ("drift", 5))
        for fixture_mode, timeout in cases:
            with self.subTest(fixture_mode=fixture_mode):
                result, _ = self._run(
                    f"schemaVersion: 1\nfixtureMode: {fixture_mode}\n", timeout
                )
                self.assertEqual(result.returncode, 30)
                self.assertEqual(result.stderr, "SelfWorkFlow: agent-eval-failed\n")


if __name__ == "__main__":
    unittest.main()
