from copy import deepcopy
from pathlib import Path
import unittest

from selfworkflow.pipeline import PipelineError, load_pipeline


class PipelineTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_pipeline_has_fixed_order_unique_slots_and_generic_knowledge_hooks(self):
        pipeline = load_pipeline(
            self.ROOT / "workflow/pipeline.yaml",
            self.ROOT / "schemas/pipeline.schema.json",
        )

        self.assertEqual(
            tuple(stage["id"] for stage in pipeline.document["stages"]),
            (
                "discovered", "capability-checked", "classified", "designed",
                "planned", "implemented", "reviewed", "verified", "completed",
            ),
        )
        slots = [
            slot["id"]
            for stage in pipeline.document["stages"]
            for slot in stage["slots"]
        ]
        self.assertEqual(len(slots), len(set(slots)))
        self.assertIn("knowledge.read", slots)
        self.assertIn("knowledge.propose", slots)
        self.assertIn("knowledge.update", slots)
        self.assertNotIn("knowledge", tuple(stage["id"] for stage in pipeline.document["stages"]))
        implemented = next(
            stage for stage in pipeline.document["stages"]
            if stage["id"] == "implemented"
        )
        method = next(slot for slot in implemented["slots"] if slot["id"] == "implement.method")
        self.assertEqual(method["allowedInvocationKinds"], ("agent-native", "skill"))
        self.assertRegex(pipeline.pipeline_hash, r"^sha256:[0-9a-f]{64}$")

    def test_pipeline_hash_is_deterministic(self):
        first = load_pipeline(self.ROOT / "workflow/pipeline.yaml", self.ROOT / "schemas/pipeline.schema.json")
        second = load_pipeline(self.ROOT / "workflow/pipeline.yaml", self.ROOT / "schemas/pipeline.schema.json")
        self.assertEqual(first.pipeline_hash, second.pipeline_hash)

    def test_semantic_validation_rejects_duplicate_slots_and_unknown_conditions(self):
        valid = load_pipeline(self.ROOT / "workflow/pipeline.yaml", self.ROOT / "schemas/pipeline.schema.json")
        duplicate = deepcopy(valid.mutable_document())
        duplicate["stages"][1]["slots"][0]["id"] = duplicate["stages"][0]["slots"][0]["id"]
        with self.assertRaises(PipelineError) as raised:
            load_pipeline(duplicate, self.ROOT / "schemas/pipeline.schema.json")
        self.assertEqual(raised.exception.code, "pipeline-slot-duplicate")

        unknown = deepcopy(valid.mutable_document())
        unknown["stages"][0]["slots"][0]["condition"] = {"regex": ["operationType", ".*"]}
        with self.assertRaises(PipelineError):
            load_pipeline(unknown, self.ROOT / "schemas/pipeline.schema.json")


if __name__ == "__main__":
    unittest.main()
