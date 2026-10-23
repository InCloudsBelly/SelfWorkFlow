import hashlib
import json
from pathlib import Path
import unittest

from selfworkflow.catalog import compile_catalog
from selfworkflow.router import RouteRequest, route_skills


ROOT = Path(__file__).resolve().parents[2]


class WorkflowTriggerBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = compile_catalog(ROOT / "catalog").content
        envelope = json.loads(cls.catalog)
        # Exercise the checked-in selectors even while this adapter is unverified.
        # Only its availability changes in this fixture; production status stays intact.
        quality = next(
            entry for entry in envelope["catalog"]["entries"]
            if entry["id"] == "workflow-quality"
        )
        quality["supportStatus"] = "supported"
        payload = json.dumps(
            envelope["catalog"], ensure_ascii=False, separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")
        envelope["catalogHash"] = "sha256:" + hashlib.sha256(payload).hexdigest()
        cls.quality_supported_catalog = envelope

    def _route(self, *, stage, operation, terms=(), extensions=(), explicit=(),
               quality_supported=False, test_execution="supported"):
        catalog = self.quality_supported_catalog if quality_supported else self.catalog
        return route_skills(catalog, RouteRequest(
            stage=stage,
            operation_type=operation,
            file_extensions=extensions,
            semantic_terms=terms,
            explicit_skills=explicit,
            capability_states={
                "filesystem-read": "supported",
                "filesystem-write": "supported",
                "skill-discovery": "supported",
                "test-execution": test_execution,
                "independent-context": "supported",
                "user-confirmation": "supported",
            },
        ))

    def test_non_behavior_operations_do_not_require_testing_methods(self):
        cases = (
            ("implemented", "implement", ("file change",), (".yaml",)),
            ("implemented", "debug", (), (".log",)),
            ("reviewed", "review", ("independent review", "review evidence"), ()),
            ("verified", "verify", ("completion evidence", "verification evidence"), ()),
        )
        for stage, operation, terms, extensions in cases:
            with self.subTest(operation=operation):
                result = self._route(
                    stage=stage, operation=operation, terms=terms, extensions=extensions,
                    test_execution="unsupported",
                )
                self.assertEqual(result.status, "routed")
                self.assertNotIn("testing-review-quality", result.selected)
                self.assertNotIn("test-execution", result.missing_capabilities)

    def test_behavior_and_test_evidence_intents_select_testing_methods(self):
        cases = (
            ("implemented", "implement", "behavior change"),
            ("implemented", "debug", "tdd"),
            ("planned", "plan", "test design"),
            ("reviewed", "review", "test evidence validation"),
            ("verified", "verify", "test evidence validation"),
        )
        for stage, operation, term in cases:
            with self.subTest(stage=stage, intent=term):
                result = self._route(stage=stage, operation=operation, terms=(term,))
                self.assertEqual(result.status, "routed")
                self.assertIn("testing-review-quality", result.selected)
                self.assertIn("workflow-core", result.selected)

    def test_explicit_testing_selection_keeps_its_capability_gate(self):
        for explicit in ("testing-review-quality", "testing-review-gate"):
            with self.subTest(explicit=explicit):
                result = self._route(stage="reviewed", operation="review", explicit=(explicit,))
                self.assertEqual(result.status, "routed")
                self.assertIn("testing-review-quality", result.selected)
        unavailable = self._route(
            stage="reviewed", operation="review", explicit=("testing-review-quality",),
            test_execution="unsupported",
        )
        self.assertEqual(unavailable.status, "paused")
        self.assertIn("test-execution", unavailable.missing_capabilities)

    def test_stage_names_and_generic_evidence_do_not_select_workflow_quality(self):
        cases = (
            ("implemented", "implement", ()),
            ("implemented", "debug", ()),
            ("reviewed", "review", ("independent review", "review evidence")),
            ("verified", "verify", ("completion evidence", "verification evidence")),
        )
        for stage, operation, terms in cases:
            with self.subTest(operation=operation):
                result = self._route(
                    stage=stage, operation=operation, terms=terms, quality_supported=True,
                )
                self.assertEqual(result.status, "routed")
                self.assertNotIn("workflow-quality", result.selected)

    def test_mutation_intents_select_workflow_quality(self):
        cases = (
            ("implemented", "implement", ("file change",)),
            ("implemented", "debug", ("side effect",)),
            ("verified", "verify", ("persisted change validation",)),
            ("implemented", "install", ()),
            ("implemented", "publish", ()),
        )
        for stage, operation, terms in cases:
            with self.subTest(operation=operation, intent=terms):
                result = self._route(
                    stage=stage, operation=operation, terms=terms, quality_supported=True,
                )
                self.assertEqual(result.status, "routed")
                self.assertIn("workflow-quality", result.selected)


if __name__ == "__main__":
    unittest.main()
