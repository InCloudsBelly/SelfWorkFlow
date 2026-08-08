import hashlib
import json
import unittest

from selfworkflow.v3.plan_graph import build_plan_graph
from selfworkflow.v3.selector import (
    SelectionInput,
    SelectionPaused,
    SelectorError,
    select_modules,
)
from tests.unit.v3.artifact_fixtures import load_test_artifacts


REQUEST = {
    "schemaVersion": 3,
    "operationType": "review",
    "complexity": "C2",
    "risk": "R2",
    "writeTask": False,
    "ambiguity": False,
    "explicitModuleIds": [],
    "projectDefaultModuleIds": [],
    "projectMinimums": {"strength": "Full"},
    "capabilityEvidenceSnapshot": {
        "schemaVersion": 1,
        "capturedAt": "2026-08-09T00:00:00Z",
        "evidence": [],
    },
    "taskArchetype": "bounded-feature",
    "requirementsMaturity": "approved",
    "scopeShape": "single-module",
    "durableSpec": True,
    "classificationConfidence": 1.0,
    "classificationEvidence": [{
        "evidenceRef": "classification-1",
        "evidenceHash": "sha256:" + "a" * 64,
        "classifierVersion": "classifier-v1",
        "classifierHash": "sha256:" + "b" * 64,
    }],
    "testLevelFloor": "T2",
}


def _canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()


def _hash(value):
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _review_slot(graph):
    stage = next(
        item for item in graph.document["stages"]
        if item["stageId"] == "reviewed"
    )
    return next(
        item for item in stage["slots"] if item["slotId"] == "review.primary"
    )


def _plan(slot, *, stage="reviewed", plan_hash=None, specs=()):
    del plan_hash
    eligible = set(slot["eligibleModules"])
    modules = []
    for spec in specs:
        module_id = spec["id"]
        support = {
            "sourceIntegrity": "supported",
            "adapterSupport": "supported" if module_id in eligible else "unsupported",
            "runtimeCapability": "supported",
            "behaviorEvidence": "supported",
        }
        modules.append({
            "schemaVersion": 3,
            "id": module_id,
            "sourceHash": "sha256:" + "a" * 64,
            "stage": stage,
            "slot": slot["slotId"],
            "selectionMode": slot["selectionMode"],
            "invocation": {"kind": "agent-native", "ref": module_id},
            "dependencies": list(spec.get("dependencies", ())),
            "conflicts": list(spec.get("conflicts", ())),
            "contextCost": {
                "estimatedContextCost": spec.get("contextCost", 0),
                "estimatedExecutionCost": spec.get("executionCost", 0),
            },
            "supportEvidence": support,
        })
    if stage != "reviewed" or slot["slotId"] != "review.primary":
        raise AssertionError("selector fixture only supports the reviewed test slot")
    policy = {
        "coverageObligationsBySlot": {
            slot["slotId"]: slot["coverageObligations"],
        }
    }
    catalog, pipeline = load_test_artifacts(
        modules,
        cardinality=slot["cardinality"],
        mode=slot["selectionMode"],
    )
    return build_plan_graph(REQUEST, catalog, pipeline, policy_snapshot=policy)


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
        self.assertEqual(result.receipt.document["eligibleModuleIds"], ["review-a", "review-b"])
        self.assertEqual(result.receipt.document["selectedModuleIds"], ["review-a"])
        self.assertEqual(result.receipt.document["estimatedContextCost"], 10)
        self.assertEqual(
            result.receipt.document["coverageDecisions"],
            [{"obligationId": "review.coverage", "decision": "unverified", "evidenceRefs": []}],
        )
        policy_hash = _review_slot(graph)["selectionPolicyHash"]
        self.assertEqual(result.receipt.selection_policy_hash, policy_hash)
        self.assertEqual(
            result.receipt.document["selectionPolicyHash"],
            policy_hash,
        )
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

        empty_graph = _plan(_slot(eligible=["review-a"]), specs=(
            {"id": "review-a", "dependencies": (), "conflicts": (), "contextCost": 1, "executionCost": 1},
        ))
        empty = select_modules(
            empty_graph, "reviewed", "review.primary", "attempt-1",
            self._input(candidates=[]),
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
        self.assertEqual(_review_slot(graph)["eligibleModules"], ["review-a"])

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

    def test_selector_rejects_plain_mapping_and_detects_artifact_tamper(self):
        graph = _plan(
            _slot(eligible=["review-a"]),
            specs=({"id": "review-a", "dependencies": (), "conflicts": (), "contextCost": 1, "executionCost": 1},),
        )
        with self.assertRaisesRegex(SelectorError, "typed"):
            select_modules(
                graph.document, "reviewed", "review.primary", "attempt-1",
                self._input(),
            )
        exposed = graph.document
        next(
            item for item in exposed["stages"] if item["stageId"] == "reviewed"
        )["slots"][0]["selectionPolicyHash"] = "sha256:" + "9" * 64
        select_modules(
            graph, "reviewed", "review.primary", "attempt-1", self._input(),
        )
        internal = object.__getattribute__(
            graph, "_PlanGraphArtifact__document",
        )
        next(
            item for item in internal["stages"] if item["stageId"] == "reviewed"
        )["slots"][0]["selectionPolicyHash"] = "sha256:" + "9" * 64
        with self.assertRaisesRegex(SelectorError, "plan"):
            select_modules(
                graph, "reviewed", "review.primary", "attempt-1", self._input(),
            )

    def test_coverage_requires_obligation_specific_non_reused_evidence(self):
        graph = _plan(
            _slot(
                eligible=["review-a"],
                obligations=["review.correctness", "review.security"],
            ),
            specs=({"id": "review-a", "dependencies": (), "conflicts": (), "contextCost": 1, "executionCost": 1},),
        )
        missing = SelectionInput.from_mapping({
            "artifactId": "review-signal",
            "artifactHash": "sha256:" + "4" * 64,
            "signalEvidenceRefs": ["evidence.correctness", "evidence.security"],
            "coverageEvidenceByObligation": {},
        })
        result = select_modules(
            graph, "reviewed", "review.primary", "attempt-1", missing,
        )
        self.assertEqual(
            [item["decision"] for item in result.receipt.document["coverageDecisions"]],
            ["unverified", "unverified"],
        )

        wrong = SelectionInput.from_mapping({
            "artifactId": "review-signal",
            "artifactHash": "sha256:" + "4" * 64,
            "signalEvidenceRefs": ["evidence.correctness"],
            "coverageEvidenceByObligation": {
                "review.correctness": ["evidence.not-declared"],
            },
        })
        with self.assertRaisesRegex(SelectorError, "coverage-evidence"):
            select_modules(
                graph, "reviewed", "review.primary", "attempt-1", wrong,
            )

        reused = SelectionInput.from_mapping({
            "artifactId": "review-signal",
            "artifactHash": "sha256:" + "4" * 64,
            "signalEvidenceRefs": ["evidence.shared"],
            "coverageEvidenceByObligation": {
                "review.correctness": ["evidence.shared"],
                "review.security": ["evidence.shared"],
            },
        })
        with self.assertRaisesRegex(SelectorError, "coverage-evidence-reused"):
            select_modules(
                graph, "reviewed", "review.primary", "attempt-1", reused,
            )

    def test_paused_and_next_stage_results_are_content_addressed_and_bound(self):
        graph = _plan(
            _slot(eligible=["review-a"]),
            specs=(
                {"id": "review-a", "dependencies": (), "conflicts": (), "contextCost": 10, "executionCost": 1},
                {"id": "review-extra", "dependencies": (), "conflicts": (), "contextCost": 1, "executionCost": 1},
            ),
        )
        paused = select_modules(
            graph, "reviewed", "review.primary", "attempt-1",
            self._input(context=0),
        )
        next_stage = select_modules(
            graph, "reviewed", "review.primary", "attempt-1",
            self._input(requested=("review-extra",)),
        )
        for result in (paused, next_stage):
            document = result.as_dict()
            self.assertEqual(document["planHash"], graph.plan_hash)
            self.assertEqual(document["attemptRef"], "attempt-1")
            self.assertEqual(document["inputArtifactHash"], "sha256:" + "4" * 64)
            self.assertEqual(
                document["selectionPolicyHash"],
                _review_slot(graph)["selectionPolicyHash"],
            )
            self.assertTrue(document["resultHash"].startswith("sha256:"))
            material = dict(document)
            result_hash = material.pop("resultHash")
            self.assertEqual(result_hash, _hash(material))
            document["requestedModuleIds"].append("tamper")
            self.assertNotIn("tamper", result.as_dict()["requestedModuleIds"])


if __name__ == "__main__":
    unittest.main()
