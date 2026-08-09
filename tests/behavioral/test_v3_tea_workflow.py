import unittest
from pathlib import Path

import yaml

from selfworkflow.v3.catalog import compile_catalog
from selfworkflow.v3.pipeline import load_pipeline
from selfworkflow.v3.tea_adapter import eligible_workflows


class V3TeaWorkflowBehaviorTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_fixture_routes_only_the_expected_workflow_slice(self):
        fixture = yaml.safe_load(
            (self.ROOT / "tests/fixtures/v3/test-strategy-routing.yaml").read_text(encoding="utf-8")
        )
        for case in fixture["cases"]:
            actual = eligible_workflows(
                stage=case["stage"],
                test_level=case["testLevel"],
                acceptance_red=case.get("acceptanceRed", False),
            )
            self.assertEqual(actual, tuple(case["expected"]))

    def test_repository_catalog_and_pipeline_expose_bounded_stage_slots(self):
        catalog = compile_catalog().document["catalog"]
        pipeline = load_pipeline().document
        module_ids = {item["id"] for item in catalog["modules"]}
        self.assertTrue({"tea-test-design", "tea-atdd", "tea-test-review", "tea-trace", "tea-nfr"} <= module_ids)
        slots = {
            slot["id"]: (stage["id"], slot)
            for stage in pipeline["stages"]
            for slot in stage["slots"]
        }
        self.assertEqual(slots["test.quality.plan"][0], "planned")
        self.assertEqual(slots["test.quality.review"][0], "reviewed")
        self.assertEqual(slots["test.quality.verify"][0], "verified")
        self.assertTrue(all(
            slots[name][1]["selectionMode"] == "bounded-runtime"
            for name in (
                "test.quality.plan", "test.quality.implementation",
                "test.quality.review", "test.quality.verify",
            )
        ))

    def test_tea_behavior_support_matches_unverified_lock_and_adapter(self):
        catalog = compile_catalog().document["catalog"]
        tea_modules = [
            item for item in catalog["modules"] if item["id"].startswith("tea-")
        ]
        lock = yaml.safe_load(
            (self.ROOT / "dependencies/locks/tea.lock.yaml").read_text(encoding="utf-8")
        )
        adapter = yaml.safe_load(
            (self.ROOT / "overlays/tea/adapter.yaml").read_text(encoding="utf-8")
        )

        self.assertEqual(lock["status"]["behaviorEvidence"], "unverified")
        self.assertTrue(all(
            item["supportEvidence"]["behaviorEvidence"] == "unverified"
            for item in tea_modules
        ))
        self.assertTrue(all(
            item["support"]["behaviorEvidence"] == "unverified"
            for item in adapter["workflows"]
        ))


if __name__ == "__main__":
    unittest.main()
