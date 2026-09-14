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

    def test_installed_core_keeps_resolver_opt_in_and_resolves_explicit_requests(self):
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
            for relative in (
                "workflow/modes/light.md",
                "workflow/modes/full.md",
                "workflow/modes/deep.md",
                "workflow/modules/code.md",
                "workflow/modules/graft-read.md",
                "workflow/modules/graft-deep.md",
                "workflow/modules/graft-update.md",
                "workflow/modules/review.md",
                "workflow/modules/knowledge.md",
                "workflow/modules/artifacts.md",
            ):
                with self.subTest(snapshot_file=relative):
                    installed_file = snapshot / relative
                    source_file = self.ROOT / relative
                    self.assertTrue(installed_file.is_file())
                    self.assertEqual(installed_file.read_bytes(), source_file.read_bytes())
            installed_instruction = (codex / "AGENTS.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("普通任务直接遵循该策略", installed_instruction)
            self.assertIn("显式 contract-managed task", installed_instruction)
            self.assertNotIn("selfworkflow resolve", installed_instruction)

            cases = (
                ("implement", "C1", "R1", "implement-tdd"),
                ("implement", "C2", "R2", "review-code-review"),
                ("implement", "C1", "R1", "verify-execution"),
                ("document", "C1", "R1", "implement-documentation"),
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
                    if operation == "document":
                        from selfworkflow.ledger import (
                            new_ledger, record_gate_result, record_slot_result,
                            transition_stage, validate_ledger,
                        )

                        plan_graph = result["planGraph"]
                        snapshot_value = self._request(
                            operationType=operation,
                            complexity=complexity,
                            risk=risk,
                        )["capabilityEvidenceSnapshot"]
                        ledger = new_ledger(plan_graph)
                        visited = []
                        for stage_index, stage in enumerate(plan_graph["stages"], 1):
                            if stage["applicability"] != "applicable":
                                continue
                            visited.append(stage["stageId"])
                            attempt_ref = f"document-attempt-{stage_index}"
                            ledger = transition_stage(
                                ledger, plan_graph, stage["stageId"], "active",
                                capability_snapshot=snapshot_value,
                                attempt_ref=attempt_ref,
                            )
                            for slot in stage["slots"]:
                                gates = set(slot["gates"])
                                for module in slot["selectedModules"]:
                                    if module not in gates:
                                        ledger = record_slot_result(
                                            ledger, plan_graph, stage["stageId"], module,
                                            f"{attempt_ref}-{module}",
                                        )
                                for gate in slot["gates"]:
                                    ledger = record_gate_result(
                                        ledger, plan_graph, stage["stageId"], gate,
                                        f"{attempt_ref}-{gate}",
                                    )
                            ledger = transition_stage(
                                ledger, plan_graph, stage["stageId"], "passed",
                                capability_snapshot=snapshot_value,
                            )

                        self.assertEqual(ledger["status"], "completed")
                        self.assertTrue(
                            {"implemented", "reviewed", "verified", "completed"}
                            <= set(visited)
                        )
                        self.assertTrue(
                            validate_ledger(
                                ledger, plan_graph, snapshot_value
                            )["valid"]
                        )

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
                        writeTask=False,
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
