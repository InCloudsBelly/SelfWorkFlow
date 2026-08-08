import unittest

from selfworkflow.v3.plan_graph import PlanGraphArtifact
from selfworkflow.v3.selector import (
    SelectionInput,
    SelectionPaused,
    SelectorError,
    select_modules,
)


def _plan(slot, *, stage="reviewed", plan_hash=None, specs=()):
    document = {
        "schemaVersion": 3,
        "planHash": plan_hash,
        "requestHash": "sha256:" + "b" * 64,
        "capabilitySnapshotHash": "sha256:" + "c" * 64,
        "pipelineHash": "sha256:" + "d" * 64,
        "policyHash": "sha256:" + "e" * 64,
        "catalogHash": "sha256:" + "f" * 64,
        "providerPreferenceHash": "sha256:" + "0" * 64,
        "providerBindingHash": "sha256:" + "1" * 64,
        "executionPolicyHash": "sha256:" + "2" * 64,
        "stages": [{"stageId": stage, "ordinal": 1, "applicability": "applicable", "slots": [slot]}],
    }
    if plan_hash is None:
        material = dict(document)
        material.pop("planHash")
        import hashlib, json
        plan_hash = "sha256:" + hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        document["planHash"] = plan_hash
    return PlanGraphArtifact(document, specs)


def _slot(*, mode="bounded-runtime", cardinality="exactly-one", eligible=None,
          selected=None, obligations=(), policy_hash="sha256:" + "3" * 64):
    eligible = list(eligible or [])
    return {
        "slotId": "review.primary",
        "ordinal": 1,
        "cardinality": cardinality,
        "selectionMode": mode,
        "selectedModules": list(selected or []),
        "eligibleModules": eligible,
        "selectionPolicyRef": "review.primary",
        "selectionPolicyHash": policy_hash,
        "coverageObligations": list(obligations),
        "gates": [],
        "applicability": "applicable",
    }


class SelectorTests(unittest.TestCase):
    def _input(self, *, candidates=None, preferred=(), context=100, execution=100,
               requested=()):
        return SelectionInput(
            artifact_id="review-signal",
            artifact_hash="sha256:" + "4" * 64,
            candidate_module_ids=None if candidates is None else tuple(candidates),
            preferred_module_ids=tuple(preferred),
            signal_evidence_refs=("signal.review",),
            context_budget=context,
            execution_budget=execution,
            requested_module_ids=tuple(requested),
        )

    def test_deterministic_bounded_selection_receipt_is_schema_valid_and_bound(self):
        graph = _plan(
            _slot(eligible=["review-b", "review-a"], obligations=["review.coverage"]),
            specs=(
                {"id": "review-a", "dependencies": (), "conflicts": (), "contextCost": 10, "executionCost": 5},
                {"id": "review-b", "dependencies": (), "conflicts": (), "contextCost": 20, "executionCost": 5},
            ),
        )
        result = select_modules(graph, "reviewed", "review.primary", "attempt-1", self._input())
        self.assertEqual(result.status, "selected")
        self.assertEqual(result.receipt.document["eligibleModuleIds"], ["review-b", "review-a"])
        self.assertEqual(result.receipt.document["selectedModuleIds"], ["review-a"])
        self.assertEqual(result.receipt.document["estimatedContextCost"], 10)
        self.assertEqual(
            result.receipt.document["coverageDecisions"],
            [{"obligationId": "review.coverage", "decision": "fulfilled", "evidenceRefs": []}],
        )
        self.assertEqual(result.receipt.selection_policy_hash, "sha256:" + "3" * 64)
        self.assertTrue(result.receipt.document["receiptHash"].startswith("sha256:"))
        self.assertEqual(result.receipt.document, select_modules(
            graph, "reviewed", "review.primary", "attempt-1", self._input()
        ).receipt.document)

    def test_selector_rejects_candidates_outside_plan_duplicate_and_conflict(self):
        graph = _plan(
            _slot(eligible=["review-a", "review-b"]),
            specs=(
                {"id": "review-a", "dependencies": (), "conflicts": ("review-b",), "contextCost": 1, "executionCost": 1},
                {"id": "review-b", "dependencies": (), "conflicts": ("review-a",), "contextCost": 1, "executionCost": 1},
            ),
        )
        with self.assertRaisesRegex(SelectorError, "outside-eligible"):
            select_modules(graph, "reviewed", "review.primary", "attempt-1", self._input(candidates=["review-a", "other"]))
        with self.assertRaisesRegex(SelectorError, "duplicate"):
            select_modules(graph, "reviewed", "review.primary", "attempt-1", self._input(candidates=["review-a", "review-a"]))

        result = select_modules(
            graph, "reviewed", "review.primary", "attempt-1",
            self._input(preferred=("review-a", "review-b")),
        )
        self.assertEqual(result.status, "selected")
        self.assertEqual(result.receipt.document["selectedModuleIds"], ["review-a"])

    def test_budget_boundary_and_required_missing_return_structured_paused(self):
        graph = _plan(
            _slot(eligible=["review-a"], obligations=["review.coverage"]),
            specs=({"id": "review-a", "dependencies": (), "conflicts": (), "contextCost": 10, "executionCost": 5},),
        )
        result = select_modules(
            graph, "reviewed", "review.primary", "attempt-1",
            self._input(context=9),
        )
        self.assertEqual(result.status, "paused")
        self.assertEqual(result.reason, "context-budget-exceeded")
        self.assertIsNone(result.receipt)

        optional_graph = _plan(_slot(cardinality="zero-or-one", eligible=["review-a"]), specs=(
            {"id": "review-a", "dependencies": (), "conflicts": (), "contextCost": 10, "executionCost": 5},
        ))
        optional = select_modules(
            optional_graph, "reviewed", "review.primary", "attempt-1", self._input(context=9)
        )
        self.assertEqual(optional.status, "selected")
        self.assertEqual(optional.receipt.document["selectedModuleIds"], [])

        empty_graph = _plan(_slot(eligible=[]), specs=())
        empty = select_modules(
            empty_graph, "reviewed", "review.primary", "attempt-1", self._input()
        )
        self.assertEqual(empty.status, "paused")
        self.assertEqual(empty.reason, "required-module-unavailable")

    def test_outside_request_returns_next_stage_request_without_mutating_plan(self):
        graph = _plan(_slot(eligible=["review-a"]), specs=(
            {"id": "review-a", "dependencies": (), "conflicts": (), "contextCost": 1, "executionCost": 1},
            {"id": "review-extra", "dependencies": (), "conflicts": (), "contextCost": 1, "executionCost": 1},
        ))
        result = select_modules(
            graph, "reviewed", "review.primary", "attempt-1",
            self._input(requested=("review-extra",)),
        )
        self.assertEqual(result.status, "next-stage-request")
        self.assertEqual(result.next_stage_request["requestedModuleIds"], ["review-extra"])
        self.assertEqual(graph.document["stages"][0]["slots"][0]["eligibleModules"], ["review-a"])

    def test_dependency_closure_is_selected_only_when_dependency_is_eligible(self):
        graph = _plan(
            _slot(cardinality="zero-or-many", eligible=["review-a", "review-dependency"]),
            specs=(
                {"id": "review-a", "dependencies": ("review-dependency",), "conflicts": (), "contextCost": 2, "executionCost": 1},
                {"id": "review-dependency", "dependencies": (), "conflicts": (), "contextCost": 1, "executionCost": 1},
            ),
        )
        result = select_modules(
            graph, "reviewed", "review.primary", "attempt-1",
            self._input(preferred=("review-a",)),
        )
        self.assertEqual(result.status, "selected")
        self.assertEqual(
            result.receipt.document["selectedModuleIds"],
            ["review-a", "review-dependency"],
        )


if __name__ == "__main__":
    unittest.main()
