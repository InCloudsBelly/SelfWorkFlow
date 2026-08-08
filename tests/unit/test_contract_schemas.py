from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator


class ContractSchemaTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def _validator(self, name):
        schema = json.loads((self.ROOT / "schemas" / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema)

    @staticmethod
    def _artifact():
        return {"id": "artifact-1", "kind": "diff", "sha256": "a" * 64, "sizeBytes": 12}

    def test_stage_result_uses_typed_hash_bound_references(self):
        validator = self._validator("stage-result.schema.json")
        valid = {
            "schemaVersion": 1,
            "status": "passed",
            "summary": "verified",
            "typedArtifacts": [self._artifact()],
            "typedEvidenceRefs": [{"id": "evidence-1", "kind": "test", "sha256": "b" * 64, "sizeBytes": 42}],
            "issues": [],
            "nextStageRequest": None,
        }
        self.assertEqual(list(validator.iter_errors(valid)), [])
        invalid = deepcopy(valid)
        invalid["typedEvidenceRefs"][0]["path"] = "C:/untrusted/result.log"
        self.assertTrue(list(validator.iter_errors(invalid)))

    def test_plan_graph_requires_all_bound_hashes(self):
        validator = self._validator("plan-graph.schema.json")
        graph = {
            "schemaVersion": 2,
            "requestHash": "sha256:" + "1" * 64,
            "capabilitySnapshotHash": "sha256:" + "2" * 64,
            "pipelineHash": "sha256:" + "3" * 64,
            "policyHash": "sha256:" + "4" * 64,
            "catalogHash": "sha256:" + "5" * 64,
            "planHash": "sha256:" + "6" * 64,
            "strength": "Light",
            "stages": [],
        }
        self.assertEqual(list(validator.iter_errors(graph)), [])
        del graph["catalogHash"]
        self.assertTrue(list(validator.iter_errors(graph)))

    def test_run_ledger_rejects_two_active_stages(self):
        validator = self._validator("run-ledger.schema.json")
        ledger = {
            "schemaVersion": 1,
            "planHash": "sha256:" + "1" * 64,
            "requestHash": "sha256:" + "2" * 64,
            "capabilitySnapshotHash": "sha256:" + "3" * 64,
            "status": "active",
            "stages": [
                {"stageId": "designed", "status": "active", "attempts": [], "slotResults": [], "gateResults": [], "runtimeSkips": []},
                {"stageId": "planned", "status": "active", "attempts": [], "slotResults": [], "gateResults": [], "runtimeSkips": []},
            ],
        }
        self.assertTrue(list(validator.iter_errors(ledger)))


if __name__ == "__main__":
    unittest.main()
