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
            "schemaVersion": 2,
            "planHash": "sha256:" + "1" * 64,
            "requestHash": "sha256:" + "2" * 64,
            "capabilitySnapshotHash": "sha256:" + "3" * 64,
            "status": "active",
            "stages": [
                {
                    "stageId": "designed", "status": "active",
                    "attempts": [{"attemptRef": "attempt-1", "ordinal": 1, "previousAttemptRef": None}],
                    "slotResults": [{"attemptRef": "attempt-1", "moduleId": "design-light", "resultRef": "result-1"}],
                    "gateResults": [],
                    "runtimeSkips": [{
                        "attemptRef": "attempt-1", "slotId": "design.specialists",
                        "evidenceRef": "e:" + "x" * 254,
                    }],
                },
                {"stageId": "planned", "status": "pending", "attempts": [], "slotResults": [], "gateResults": [], "runtimeSkips": []},
            ],
        }
        self.assertEqual(list(validator.iter_errors(ledger)), [])

        two_active = deepcopy(ledger)
        two_active["stages"][1].update({
            "status": "active",
            "attempts": [{"attemptRef": "attempt-2", "ordinal": 1, "previousAttemptRef": None}],
        })
        self.assertTrue(list(validator.iter_errors(two_active)))

        legacy = deepcopy(ledger)
        legacy["schemaVersion"] = 1
        self.assertTrue(list(validator.iter_errors(legacy)))

        open_record = deepcopy(ledger)
        open_record["stages"][0]["attempts"][0]["unexpected"] = True
        self.assertTrue(list(validator.iter_errors(open_record)))

    @staticmethod
    def _decision_record(mode="independent-subagent", independence="independent"):
        return {
            "schemaVersion": 1,
            "decisionId": "decision-1",
            "question": "Choose the local parser helper.",
            "alternatives": [
                {"id": "a", "summary": "Reuse the bounded helper."},
                {"id": "b", "summary": "Add a local equivalent."},
            ],
            "recommendationId": "a",
            "selectedId": "a",
            "rationaleSummary": "The existing helper preserves one local invariant.",
            "impact": {
                "scope": "local-component", "rollback": "easy",
                "compatibility": "unchanged", "security": "unchanged",
                "externalSideEffects": False, "uncertainty": "low",
            },
            "reviewContext": {
                "mode": mode, "contextId": "review-context-1",
                "independence": independence,
            },
            "verificationRefs": [
                {"id": "test-1", "kind": "test", "sha256": "a" * 64, "sizeBytes": 12}
            ],
        }

    def test_decision_record_schema_and_semantics_are_closed(self):
        from selfworkflow.decision_record import validate_decision_record

        validator = self._validator("decision-record.schema.json")
        for record in (
            self._decision_record(),
            self._decision_record("structured-self-review", "unverified"),
        ):
            with self.subTest(mode=record["reviewContext"]["mode"]):
                self.assertEqual(list(validator.iter_errors(record)), [])
                normalized = validate_decision_record(record)
                self.assertEqual(normalized, record)
                self.assertIsNot(normalized, record)

        invalid_records = []
        unknown = self._decision_record(); unknown["secret"] = "do-not-echo"; invalid_records.append(unknown)
        duplicate = self._decision_record(); duplicate["alternatives"][1]["id"] = "a"; invalid_records.append(duplicate)
        dangling = self._decision_record(); dangling["recommendationId"] = "missing"; invalid_records.append(dangling)
        deviated = self._decision_record(); deviated["selectedId"] = "b"; invalid_records.append(deviated)
        false_independence = self._decision_record("structured-self-review", "independent"); invalid_records.append(false_independence)
        too_many = self._decision_record(); too_many["alternatives"] *= 3; invalid_records.append(too_many)
        oversized = self._decision_record(); oversized["question"] = "sensitive-value-" + "x" * 1024; invalid_records.append(oversized)

        for record in invalid_records:
            with self.subTest(record=record.get("decisionId")):
                before = deepcopy(record)
                with self.assertRaisesRegex(ValueError, "decision-record-invalid") as raised:
                    validate_decision_record(record)
                self.assertEqual(record, before)
                self.assertNotIn("sensitive-value", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
