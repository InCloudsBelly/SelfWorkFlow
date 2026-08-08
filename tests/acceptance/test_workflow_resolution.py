from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from selfworkflow.adapters import build_runtime
from selfworkflow.cli import main
from selfworkflow.installer import apply_install_plan, create_install_plan


class WorkflowResolutionAcceptanceTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    @staticmethod
    def _request(**overrides):
        names = (
            "filesystem-read", "filesystem-write", "skill-discovery",
            "test-execution", "independent-context", "user-confirmation",
        )
        evidence = [
            {
                "name": name, "provider": "acceptance-host",
                "subject": {"kind": "host", "id": "fixture", "version": "1", "build": "1", "sourceLock": "sha256:" + "1" * 64},
                "state": "supported", "observedAt": "2020-01-01T00:00:00Z", "validUntil": "2099-01-01T00:00:00Z",
                "evidenceRef": "fixture:" + name, "evidenceHash": "sha256:" + "1" * 64,
            }
            for name in names
        ]
        value = {
            "schemaVersion": 2, "operationType": "implement", "complexity": "C1", "risk": "R1",
            "writeTask": True, "ambiguity": False, "explicitModuleIds": [], "projectDefaultModuleIds": [],
            "projectMinimums": {"strength": "Light"},
            "capabilityEvidenceSnapshot": {"schemaVersion": 1, "capturedAt": "2020-01-01T00:00:00Z", "evidence": evidence},
        }
        value.update(overrides)
        return value

    def test_installed_core_resolves_implement_review_and_verify_stages(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = root / "runtime"
            agents, codex, state = root / "agents", root / "codex", root / "state"
            build_runtime(self.ROOT, artifact, "0.1.0.dev0")
            plan = create_install_plan(artifact, agents, codex, state, "0.1.0.dev0")
            apply_install_plan(plan, plan["planHash"])
            pointer = json.loads(
                (agents / "selfworkflow/current.json").read_text(encoding="utf-8")
            )
            snapshot = Path(pointer["snapshot"])
            catalog = snapshot / "catalog.json"
            self.assertTrue(
                (snapshot / "workflow/resolve-request.example.json").is_file()
            )
            self.assertIn(
                "selfworkflow resolve",
                (codex / "AGENTS.md").read_text(encoding="utf-8"),
            )

            cases = (
                ("implement", "C1", "R1", "implement-tdd"),
                ("implement", "C2", "R2", "review-independent"),
                ("implement", "C1", "R1", "verify-execution"),
            )
            for index, (operation, complexity, risk, expected_module) in enumerate(cases):
                with self.subTest(expected_module=expected_module):
                    request = root / f"request-{index}.json"
                    request.write_text(
                        json.dumps(self._request(operationType=operation, complexity=complexity, risk=risk)),
                        encoding="utf-8",
                    )
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = main([
                            "resolve",
                            "--catalog", str(catalog),
                            "--request", str(request),
                        ])
                    self.assertEqual(code, 0)
                    result = json.loads(output.getvalue())
                    self.assertEqual(result["status"], "active")
                    selected = [
                        module
                        for stage in result["planGraph"]["stages"]
                        for slot in stage["slots"]
                        for module in slot["selectedModules"]
                    ]
                    self.assertIn(expected_module, selected)

    def test_cli_rejects_duplicate_request_keys_without_echoing_values(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            artifact = root / "runtime"
            build_runtime(self.ROOT, artifact, "0.1.0.dev0")
            request = root / "duplicate.json"
            request.write_text(
                """{
  "schemaVersion": 1,
  "stage": "implemented",
  "operationType": "implement",
  "complexity": "C1",
  "risk": "R1",
  "writeTask": false,
  "writeTask": true,
  "superpowersSourceStatus": "supported",
  "capabilityStates": {"filesystem-read": "supported", "filesystem-write": "supported"},
  "semanticTerms": ["must-not-appear"],
  "semanticTerms": []
}""",
                encoding="utf-8",
            )
            output = io.StringIO()
            errors = io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                code = main([
                    "resolve",
                    "--catalog", str(artifact / "catalog.json"),
                    "--request", str(request),
                ])
            self.assertEqual(code, 50)
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(errors.getvalue(), "SelfWorkFlow: resolve-failed\n")
            self.assertNotIn("must-not-appear", errors.getvalue())

    def test_runtime_without_grill_pauses_an_explicit_grill_request(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            build_runtime(
                self.ROOT,
                runtime,
                "0.1.0.dev0",
                include_grill_me=False,
            )
            request = root / "request.json"
            request.write_text(
                json.dumps(
                    self._request(
                        operationType="design", complexity="C2", risk="R2",
                        explicitModuleIds=["design-grill-me"],
                    )
                ),
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "resolve",
                        "--catalog",
                        str(runtime / "catalog.json"),
                        "--request",
                        str(request),
                    ]
                )

            self.assertEqual(code, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "paused")
            selected = [module for stage in result["planGraph"]["stages"] for slot in stage["slots"] for module in slot["selectedModules"]]
            self.assertNotIn("design-grill-me", selected)
            self.assertIn("explicit-selection-invalid", result["reasonCodes"])


if __name__ == "__main__":
    unittest.main()
