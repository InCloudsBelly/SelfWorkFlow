import json
from pathlib import Path
import subprocess
import tempfile
import unittest


class WorkArtifactCliTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

    def _run(self, *args):
        return subprocess.run(
            [str(self.PYTHON), "-m", "selfworkflow.cli", *map(str, args)],
            cwd=self.ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def _git(self, root, *args):
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    def test_cli_transition_and_dry_run_are_bounded_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._git(root, "init", "-q")
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            self._git(root, "add", "README.md")
            self._git(root, "-c", "user.name=Tests", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "base")
            source = root / "artifacts.json"
            source.write_text(json.dumps({"artifacts": [{"id": "design", "kind": "design", "content": "# Design\n"}]}), encoding="utf-8")
            captured = self._run(
                "artifact", "transition", "--project-root", root, "--task-id", "cli",
                "--event", "documents-captured", "--expected-content-generation", "0",
                "--expected-state-revision", "0", "--operation-nonce", "capture", "--artifacts", source,
            )
            self.assertEqual(captured.returncode, 0, captured.stderr)
            result = json.loads(captured.stdout)
            self.assertEqual(result["taskState"], "active")
            dry = self._run(
                "artifact", "reconcile", "--project-root", root, "--task-id", "cli",
                "--mode", "dry-run", "--expected-content-generation", result["contentGeneration"],
                "--expected-state-revision", result["stateRevision"], "--expected-manifest-hash", result["manifestHash"],
            )
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertEqual(json.loads(dry.stdout)["status"], "dry-run")

    def test_cli_errors_do_not_echo_sensitive_document_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._git(root, "init", "-q")
            source = root / "artifacts.json"
            secret = "-----BEGIN PRIVATE KEY-----secret-value"
            source.write_text(json.dumps({"artifacts": [{"id": "design", "kind": "design", "content": secret}]}), encoding="utf-8")
            result = self._run(
                "artifact", "transition", "--project-root", root, "--task-id", "cli",
                "--event", "documents-captured", "--expected-content-generation", "0",
                "--expected-state-revision", "0", "--operation-nonce", "secret", "--artifacts", source,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("sensitive-content", result.stdout)
            self.assertNotIn("secret-value", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
