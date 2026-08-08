from copy import deepcopy
import unittest

from selfworkflow.v3.contracts import ContractError
from selfworkflow.v3.test_strategy import (
    TestStrategyError,
    issue_coverage_result,
    issue_test_strategy,
)
from tests.unit.v3.test_quality_artifact_schemas import QualityArtifactSchemaTests


class TestStrategyIssuerTests(unittest.TestCase):
    def _context(self):
        fixture = QualityArtifactSchemaTests
        plan = fixture._plan()
        ledger = fixture._ledger(plan)
        diff = fixture._diff()
        material = fixture._strategy(diff)
        material.pop("strategyHash")
        risk = material["risks"][0]
        risk.pop("priority")
        risk.update({"probability": 3, "impact": 2, "residualStatus": "unverified"})
        return fixture, plan, ledger, diff, material

    def test_strategy_derives_risk_score_priority_residuals_and_content_hash(self):
        _, plan, ledger, diff, material = self._context()
        material["acceptanceConditions"][0]["description"] = "拒绝空值输入"
        issued = issue_test_strategy(
            material, plan_graph=plan, run_ledger=ledger, diff_signal_set=diff
        )
        self.assertEqual(issued["risks"][0]["score"], 6)
        self.assertEqual(issued["risks"][0]["priority"], "P1")
        self.assertEqual(issued["residualUnverified"], ["risk-null"])
        self.assertRegex(issued["strategyHash"], r"^sha256:[0-9a-f]{64}$")
        reordered = deepcopy(material)
        issued_again = issue_test_strategy(
            reordered, plan_graph=plan, run_ledger=ledger, diff_signal_set=diff
        )
        self.assertEqual(issued_again["strategyHash"], issued["strategyHash"])

    def test_strategy_rejects_unknown_fields_invalid_px_i_and_duplicate_risks(self):
        _, plan, ledger, diff, material = self._context()
        cases = []
        unknown = deepcopy(material)
        unknown["invented"] = True
        cases.append(unknown)
        invalid = deepcopy(material)
        invalid["risks"][0]["probability"] = 4
        cases.append(invalid)
        duplicate = deepcopy(material)
        duplicate["risks"].append(deepcopy(duplicate["risks"][0]))
        cases.append(duplicate)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(TestStrategyError):
                issue_test_strategy(
                    value, plan_graph=plan, run_ledger=ledger, diff_signal_set=diff
                )

    def test_coverage_fulfilled_requires_real_collector_receipt(self):
        fixture, plan, ledger, diff, material = self._context()
        strategy = issue_test_strategy(
            material, plan_graph=plan, run_ledger=ledger, diff_signal_set=diff
        )
        coverage = fixture._coverage(diff, strategy)
        coverage.pop("resultHash")
        with self.assertRaisesRegex(ContractError, "coverage-verification-resolver-required"):
            issue_coverage_result(
                coverage,
                diff_signal_set=diff,
                test_strategy=strategy,
                run_ledger=ledger,
            )
        receipt = fixture._execution_receipt(diff, strategy)
        issued = issue_coverage_result(
            coverage,
            diff_signal_set=diff,
            test_strategy=strategy,
            run_ledger=ledger,
            verification_receipt_resolver=lambda ref: receipt if ref == "collector-receipt-1" else None,
        )
        self.assertTrue(issued["passed"])
        self.assertRegex(issued["resultHash"], r"^sha256:[0-9a-f]{64}$")

    def test_tea_design_reference_cannot_substitute_for_execution_evidence(self):
        _, plan, ledger, diff, material = self._context()
        strategy = issue_test_strategy(
            material, plan_graph=plan, run_ledger=ledger, diff_signal_set=diff
        )
        coverage = {
            "schemaVersion": 3,
            "planHash": diff["planHash"],
            "attemptRef": diff["attemptRef"],
            "createdAt": "2026-08-09T01:06:03Z",
            "finalDiffHash": diff["finalDiffHash"],
            "diffSignalSetHash": diff["signalSetHash"],
            "strategyHash": strategy["strategyHash"],
            "obligations": [{
                "obligationId": "obligation-direct",
                "status": "fulfilled",
                "executionReceiptRef": "tea-design-output",
                "executionReceiptHash": "sha256:" + "a" * 64,
            }],
            "passed": True,
        }
        with self.assertRaises(ContractError):
            issue_coverage_result(
                coverage,
                diff_signal_set=diff,
                test_strategy=strategy,
                run_ledger=ledger,
                verification_receipt_resolver=lambda ref: None,
            )


if __name__ == "__main__":
    unittest.main()
