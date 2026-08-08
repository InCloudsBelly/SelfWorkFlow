from pathlib import Path
import unittest

from selfworkflow.catalog import compile_catalog


class TaskResolverTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    @classmethod
    def setUpClass(cls):
        cls.catalog = compile_catalog(cls.ROOT / "catalog").content

    @staticmethod
    def _request(**overrides):
        request = {
            "schemaVersion": 1,
            "stage": "implemented",
            "operationType": "implement",
            "complexity": "C1",
            "risk": "R1",
            "writeTask": True,
            "ambiguity": False,
            "explicitGrill": False,
            "superpowersSourceStatus": "supported",
            "capabilityStates": {
                "filesystem-read": "supported",
                "filesystem-write": "supported",
            },
            "fileExtensions": [".py"],
            "semanticTerms": [],
            "explicitSkills": [],
            "contextBudget": 4096,
        }
        request.update(overrides)
        return request

    def test_implement_plan_composes_core_stage_skill_and_minimum_requirements(self):
        from selfworkflow.resolver import resolve_task

        result = resolve_task(self.catalog, self._request())

        self.assertEqual(result["status"], "active")
        self.assertEqual(
            result["selectedSkills"],
            ("workflow-core", "test-driven-development"),
        )
        self.assertEqual(result["classification"]["complexity"], "C1")
        self.assertEqual(result["requirements"]["review"]["minimumIsolation"], "L0")
        self.assertEqual(result["requirements"]["verification"]["required"], True)

    def test_full_design_review_pauses_without_independent_context(self):
        from selfworkflow.resolver import resolve_task

        result = resolve_task(
            self.catalog,
            self._request(
                stage="reviewed",
                operationType="review",
                complexity="C2",
                risk="R2",
            ),
        )

        self.assertEqual(result["status"], "paused")
        self.assertEqual(
            result["capabilityGate"]["missingCapabilities"],
            ("independent-context",),
        )
        self.assertEqual(result["requirements"]["review"]["minimumIsolation"], "L2")

    def test_missing_superpowers_pauses_write_without_silent_degradation(self):
        from selfworkflow.resolver import resolve_task

        result = resolve_task(
            self.catalog,
            self._request(superpowersSourceStatus="unselected"),
        )

        self.assertEqual(result["status"], "paused")
        self.assertEqual(result["superpowers"]["status"], "paused")
        self.assertIn("superpowers", result["issues"])

    def test_explicit_grill_keeps_brainstorming_cross_review(self):
        from selfworkflow.resolver import resolve_task

        result = resolve_task(
            self.catalog,
            self._request(
                stage="designed",
                operationType="design",
                complexity="C2",
                risk="R2",
                explicitGrill=True,
                capabilityStates={
                    "filesystem-read": "supported",
                    "filesystem-write": "supported",
                    "independent-context": "supported",
                },
            ),
        )

        self.assertEqual(result["status"], "active")
        self.assertEqual(
            result["superpowers"]["selectedSkills"],
            ("grill-me", "brainstorming"),
        )
        self.assertEqual(
            result["superpowers"]["postGrillReview"]["independentContextRequired"],
            True,
        )

    def test_explicit_grill_pauses_when_independent_cross_review_is_unavailable(self):
        from selfworkflow.resolver import resolve_task

        result = resolve_task(
            self.catalog,
            self._request(
                stage="designed",
                operationType="design",
                complexity="C1",
                risk="R1",
                explicitGrill=True,
            ),
        )

        self.assertEqual(result["status"], "paused")
        self.assertEqual(
            result["capabilityGate"]["missingCapabilities"],
            ("independent-context",),
        )

    def test_read_only_task_continues_without_superpowers_or_write_capability(self):
        from selfworkflow.resolver import resolve_task

        result = resolve_task(
            self.catalog,
            self._request(
                stage="discovered",
                operationType="read-only",
                complexity="C0",
                risk="R0",
                writeTask=False,
                superpowersSourceStatus="unselected",
                capabilityStates={"filesystem-read": "supported"},
                fileExtensions=[],
            ),
        )

        self.assertEqual(result["status"], "active")
        self.assertEqual(result["selectedSkills"], ())
        self.assertEqual(result["requirements"]["review"]["required"], False)

    def test_invalid_request_fails_with_stable_redacted_error(self):
        from selfworkflow.resolver import ResolveError, resolve_task

        request = self._request()
        request["secret-value"] = "must-not-appear"
        with self.assertRaises(ResolveError) as raised:
            resolve_task(self.catalog, request)
        self.assertEqual(raised.exception.code, "resolve-input-invalid")
        self.assertEqual(str(raised.exception), "resolve-failed")
        self.assertNotIn("must-not-appear", str(raised.exception))

    def test_plan_binds_normalized_request_identity(self):
        from selfworkflow.resolver import resolve_task

        first = resolve_task(self.catalog, self._request())
        repeat = resolve_task(self.catalog, self._request())
        changed = resolve_task(self.catalog, self._request(risk="R2"))

        self.assertRegex(first["requestHash"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(first["requestHash"], repeat["requestHash"])
        self.assertNotEqual(first["requestHash"], changed["requestHash"])
        self.assertEqual(
            first["task"],
            {
                "stage": "implemented",
                "operationType": "implement",
                "writeTask": True,
                "superpowersSourceStatus": "supported",
            },
        )


if __name__ == "__main__":
    unittest.main()
