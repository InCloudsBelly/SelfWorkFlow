import unittest
from pathlib import Path

from selfworkflow.v3.tea_adapter import (
    TeaAdapterError,
    eligible_workflows,
    load_jit_artifact,
    load_workflow_candidates,
)


class TeaAdapterTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[3]

    def test_t_levels_and_stages_are_strictly_partitioned(self):
        for level in ("T0", "T1"):
            for stage in ("plan", "implementation", "review", "verify", "release"):
                self.assertEqual(eligible_workflows(stage=stage, test_level=level), ())
        self.assertEqual(eligible_workflows(stage="plan", test_level="T2"), ("test-design",))
        self.assertEqual(eligible_workflows(stage="review", test_level="T2"), ("test-review",))
        self.assertEqual(eligible_workflows(stage="verify", test_level="T2"), ())
        self.assertEqual(eligible_workflows(stage="verify", test_level="T3"), ("trace", "nfr"))
        self.assertEqual(eligible_workflows(stage="release", test_level="T3"), ("trace", "nfr"))

    def test_atdd_needs_implementation_acceptance_red_and_grill_me_only_raises_floor(self):
        self.assertEqual(eligible_workflows(stage="implementation", test_level="T3"), ())
        self.assertEqual(
            eligible_workflows(stage="implementation", test_level="T2", acceptance_red=True),
            ("atdd",),
        )
        self.assertEqual(
            eligible_workflows(stage="plan", test_level="T0", grill_me_used=True),
            ("test-design",),
        )
        self.assertEqual(
            eligible_workflows(stage="verify", test_level="T0", grill_me_used=True),
            (),
        )

    def test_registry_has_nine_candidates_without_claiming_runtime_support(self):
        candidates = load_workflow_candidates(self.ROOT)
        self.assertEqual(len(candidates), 9)
        self.assertEqual(len({item["id"] for item in candidates}), 9)
        self.assertTrue(all(item["support"]["runtimeCapability"] == "unverified" for item in candidates))
        self.assertTrue(all(item["support"]["behaviorEvidence"] == "unverified" for item in candidates))

    def test_jit_reads_exactly_one_declared_file_and_rejects_escape_or_bulk_load(self):
        artifact = load_jit_artifact(
            self.ROOT,
            workflow_id="test-design",
            kind="step",
            relative_path="steps-c/step-03-risk-and-testability.md",
        )
        self.assertEqual(artifact["workflowId"], "test-design")
        self.assertRegex(artifact["contentHash"], r"^sha256:[0-9a-f]{64}$")
        self.assertIn("Risk Assessment", artifact["content"])
        for path in ("../LICENSE", "steps-c", "steps-c/../../LICENSE"):
            with self.subTest(path=path), self.assertRaisesRegex(
                TeaAdapterError, "tea-jit-path-invalid"
            ):
                load_jit_artifact(
                    self.ROOT, workflow_id="test-design", kind="step", relative_path=path
                )

    def test_unknown_route_inputs_fail_closed(self):
        for kwargs in (
            {"stage": "deploy", "test_level": "T2"},
            {"stage": "plan", "test_level": "T4"},
        ):
            with self.assertRaisesRegex(TeaAdapterError, "tea-route-invalid"):
                eligible_workflows(**kwargs)


if __name__ == "__main__":
    unittest.main()
