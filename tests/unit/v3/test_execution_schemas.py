import unittest
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


class ExecutionSchemaTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[3]
    SCHEMA_NAMES = (
        "resolve-result.schema.json",
        "plan-graph.schema.json",
        "selection-receipt.schema.json",
        "run-ledger.schema.json",
    )

    HASH_A = "sha256:" + "a" * 64
    HASH_B = "sha256:" + "b" * 64
    HASH_C = "sha256:" + "c" * 64

    @classmethod
    def _hash_document(cls, document, field):
        material = deepcopy(document)
        material.pop(field)
        payload = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def _plan(cls):
        plan = {
            "schemaVersion": 3,
            "planHash": cls.HASH_A,
            "requestHash": cls.HASH_B,
            "capabilitySnapshotHash": cls.HASH_C,
            "pipelineHash": cls.HASH_A,
            "policyHash": cls.HASH_B,
            "catalogHash": cls.HASH_C,
            "providerPreferenceHash": cls.HASH_A,
            "providerBindingHash": cls.HASH_B,
            "executionPolicyHash": cls.HASH_C,
            "stages": [
                {
                    "stageId": "stage-a",
                    "ordinal": 1,
                    "applicability": "applicable",
                    "slots": [
                        {
                            "slotId": "slot-a",
                            "ordinal": 1,
                            "cardinality": "exactly-one",
                            "selectionMode": "static",
                            "selectedModules": ["module-a"],
                            "eligibleModules": ["module-a"],
                            "selectionPolicyRef": "policy-a",
                            "selectionPolicyHash": cls.HASH_A,
                            "coverageObligations": ["coverage-a"],
                            "gates": [],
                            "applicability": "applicable",
                        }
                    ],
                },
                {
                    "stageId": "stage-b",
                    "ordinal": 2,
                    "applicability": "applicable",
                    "slots": [
                        {
                            "slotId": "slot-b",
                            "ordinal": 1,
                            "cardinality": "zero-or-one",
                            "selectionMode": "bounded-runtime",
                            "selectedModules": [],
                            "eligibleModules": ["module-b"],
                            "selectionPolicyRef": "policy-b",
                            "selectionPolicyHash": cls.HASH_B,
                            "coverageObligations": [],
                            "gates": [],
                            "applicability": "applicable",
                        }
                    ],
                },
            ],
        }
        plan["planHash"] = cls._hash_document(plan, "planHash")
        return plan

    @classmethod
    def _receipt(cls, plan=None):
        plan = plan or cls._plan()
        receipt = {
            "schemaVersion": 3,
            "planHash": plan["planHash"],
            "stageId": "stage-b",
            "slotId": "slot-b",
            "attemptRef": "attempt-b-1",
            "selectorModuleId": "selector-b",
            "selectorSourceHash": cls.HASH_A,
            "inputArtifactId": "artifact-input-b",
            "inputArtifactHash": cls.HASH_B,
            "eligibleModuleIds": ["module-b"],
            "selectedModuleIds": ["module-b"],
            "selectionReasons": ["diff-signal"],
            "signalEvidenceRefs": ["signal-b"],
            "estimatedContextCost": 10,
            "estimatedExecutionCost": 20,
            "coverageDecisions": [
                {"obligationId": "coverage-b", "decision": "fulfilled"}
            ],
            "receiptHash": cls.HASH_C,
        }
        receipt["receiptHash"] = cls._hash_document(receipt, "receiptHash")
        return receipt

    @classmethod
    def _ledger(cls, plan=None):
        plan = plan or cls._plan()
        return {
            "schemaVersion": 3,
            "planHash": plan["planHash"],
            "requestHash": plan["requestHash"],
            "capabilitySnapshotHash": plan["capabilitySnapshotHash"],
            "status": "active",
            "stages": [
                {
                    "stageId": "stage-a",
                    "status": "active",
                    "attempts": [
                        {
                            "attemptRef": "attempt-a-1",
                            "ordinal": 1,
                            "previousAttemptRef": None,
                            "startedAt": "2026-08-09T00:00:00Z",
                        }
                    ],
                    "slotResults": [],
                    "gateResults": [],
                    "runtimeSkips": [],
                    "selectionReceiptRefs": [],
                    "reviewAggregateHashes": [],
                    "coverageResultHashes": [],
                    "artifactHashes": [],
                },
                {
                    "stageId": "stage-b",
                    "status": "pending",
                    "attempts": [],
                    "slotResults": [],
                    "gateResults": [],
                    "runtimeSkips": [],
                    "selectionReceiptRefs": [],
                    "reviewAggregateHashes": [],
                    "coverageResultHashes": [],
                    "artifactHashes": [],
                },
            ],
        }

    def _validator(self, filename):
        schema_root = self.ROOT / "schemas" / "v3"
        schemas = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in schema_root.glob("*.schema.json")
        }
        resources = []
        for schema in schemas.values():
            Draft202012Validator.check_schema(schema)
            resources.append((schema["$id"], Resource.from_contents(schema)))
        return Draft202012Validator(
            schemas[filename],
            registry=Registry().with_resources(resources),
            format_checker=FormatChecker(),
        )

    def _assert_schema_error(self, filename, document, path, validator):
        errors = list(self._validator(filename).iter_errors(document))
        self.assertEqual(len(errors), 1)
        self.assertEqual(tuple(errors[0].absolute_path), path)
        self.assertEqual(errors[0].validator, validator)

    def _assert_contract_error(self, schema_name, document, reason, path):
        from selfworkflow.v3.contracts import ContractError, load_contract

        with self.assertRaises(ContractError) as raised:
            load_contract(schema_name, json.dumps(document))
        self.assertEqual(raised.exception.reason, reason)
        self.assertEqual(raised.exception.path, path)
        self.assertEqual(raised.exception.validator, "semantic")

    def _assert_schema_only_error(self, filename, document, path, validator):
        self._assert_schema_error(filename, document, path, validator)

    def test_execution_schema_paths_exist(self):
        for name in self.SCHEMA_NAMES:
            with self.subTest(name=name):
                self.assertTrue(
                    (self.ROOT / "schemas" / "v3" / name).is_file(),
                    f"v3-schema-not-found:{name}",
                )

    def test_each_minimal_execution_schema_is_valid(self):
        documents = {
            "resolve-result.schema.json": {
                "schemaVersion": 3,
                "status": "active",
                "reasonCodes": [],
                "diagnostics": [],
                "planGraph": self._plan(),
            },
            "plan-graph.schema.json": self._plan(),
            "selection-receipt.schema.json": self._receipt(),
            "run-ledger.schema.json": self._ledger(),
        }
        for filename, document in documents.items():
            with self.subTest(filename=filename):
                self.assertEqual(list(self._validator(filename).iter_errors(document)), [])

    def test_each_execution_schema_rejects_unknown_field(self):
        documents = {
            "resolve-result.schema.json": {
                "schemaVersion": 3, "status": "paused", "reasonCodes": ["blocked"],
                "diagnostics": [], "planGraph": None,
            },
            "plan-graph.schema.json": self._plan(),
            "selection-receipt.schema.json": self._receipt(),
            "run-ledger.schema.json": self._ledger(),
        }
        for filename, document in documents.items():
            invalid = {**document, "unexpected": True}
            with self.subTest(filename=filename):
                self._assert_schema_error(filename, invalid, (), "additionalProperties")

    def test_each_execution_schema_rejects_wrong_version(self):
        documents = {
            "resolve-result.schema.json": {
                "schemaVersion": 3, "status": "paused", "reasonCodes": ["blocked"],
                "diagnostics": [], "planGraph": None,
            },
            "plan-graph.schema.json": self._plan(),
            "selection-receipt.schema.json": self._receipt(),
            "run-ledger.schema.json": self._ledger(),
        }
        for filename, document in documents.items():
            invalid = {**document, "schemaVersion": 2}
            with self.subTest(filename=filename):
                self._assert_schema_error(filename, invalid, ("schemaVersion",), "const")

    def test_resolve_result_requires_reason_for_paused(self):
        invalid = {
            "schemaVersion": 3, "status": "paused", "reasonCodes": [],
            "diagnostics": [], "planGraph": None,
        }
        self._assert_schema_error("resolve-result.schema.json", invalid, ("reasonCodes",), "minItems")

    def test_resolve_result_active_requires_executable_plan(self):
        invalid = {
            "schemaVersion": 3, "status": "active", "reasonCodes": [],
            "diagnostics": [], "planGraph": None,
        }
        self._assert_contract_error(
            "resolve-result.schema.json", invalid,
            "resolve-active-plan-missing", ("planGraph",),
        )

    def test_plan_graph_rejects_selected_module_outside_eligible_set(self):
        invalid = self._plan()
        invalid["stages"][0]["slots"][0]["selectedModules"] = ["module-outside"]
        invalid["planHash"] = self._hash_document(invalid, "planHash")
        self._assert_contract_error(
            "plan-graph.schema.json", invalid,
            "plan-selected-module-ineligible",
            ("stages", 0, "slots", 0, "selectedModules", 0),
        )

    def test_plan_graph_requires_closed_static_cardinality(self):
        invalid = self._plan()
        invalid["stages"][0]["slots"][0]["selectedModules"] = []
        invalid["planHash"] = self._hash_document(invalid, "planHash")
        self._assert_contract_error(
            "plan-graph.schema.json", invalid,
            "plan-static-cardinality-invalid",
            ("stages", 0, "slots", 0, "selectedModules"),
        )

    def test_plan_graph_rejects_stale_immutable_hash(self):
        invalid = self._plan()
        invalid["planHash"] = self.HASH_A
        self._assert_contract_error(
            "plan-graph.schema.json", invalid,
            "plan-hash-invalid", ("planHash",),
        )

    def test_plan_graph_rejects_runtime_exactly_one_without_candidates(self):
        invalid = self._plan()
        slot = invalid["stages"][1]["slots"][0]
        slot["cardinality"] = "exactly-one"
        slot["eligibleModules"] = []
        invalid["planHash"] = self._hash_document(invalid, "planHash")
        self._assert_contract_error(
            "plan-graph.schema.json", invalid,
            "plan-runtime-cardinality-invalid",
            ("stages", 1, "slots", 0, "eligibleModules"),
        )

    def test_plan_graph_rejects_duplicate_active_stage(self):
        ledger = self._ledger()
        ledger["stages"][1]["status"] = "active"
        ledger["stages"][1]["attempts"] = [
            {"attemptRef": "attempt-b-1", "ordinal": 1, "previousAttemptRef": None}
        ]
        self._assert_contract_error(
            "run-ledger.schema.json", ledger,
            "multiple-active-stages", ("stages", 1, "status"),
        )

    def test_run_ledger_superseded_requires_new_plan_hash(self):
        invalid = self._ledger()
        invalid["status"] = "superseded"
        self._assert_schema_error(
            "run-ledger.schema.json", invalid,
            (), "required",
        )

    def test_run_ledger_rejects_invalid_utc_and_attempt_shape(self):
        invalid_utc = self._ledger()
        invalid_utc["stages"][0]["attempts"][0]["startedAt"] = "2026-08-09T08:00:00+08:00"
        self._assert_schema_only_error(
            "run-ledger.schema.json", invalid_utc,
            ("stages", 0, "attempts", 0, "startedAt"), "pattern",
        )
        invalid_attempt = self._ledger()
        invalid_attempt["stages"][0]["attempts"][0]["ordinal"] = 0
        self._assert_schema_only_error(
            "run-ledger.schema.json", invalid_attempt,
            ("stages", 0, "attempts", 0, "ordinal"), "minimum",
        )

    def test_selection_receipt_rejects_selected_module_outside_eligible_set(self):
        receipt = self._receipt()
        receipt["selectedModuleIds"] = ["module-outside"]
        receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
        self._assert_contract_error(
            "selection-receipt.schema.json", receipt,
            "selection-receipt-selected-module-ineligible",
            ("selectedModuleIds", 0),
        )

    def test_selection_receipt_rejects_stale_hash(self):
        receipt = self._receipt()
        receipt["receiptHash"] = self.HASH_A
        self._assert_contract_error(
            "selection-receipt.schema.json", receipt,
            "selection-receipt-hash-invalid", ("receiptHash",),
        )

    def test_run_ledger_rejects_old_attempt_receipt_mismatch(self):
        plan = self._plan()
        ledger = self._ledger(plan)
        ledger["stages"][0]["attempts"].append(
            {
                "attemptRef": "attempt-a-2", "ordinal": 2,
                "previousAttemptRef": "attempt-a-1",
            }
        )
        ledger["stages"][0]["selectionReceiptRefs"] = [
            {"attemptRef": "attempt-a-1", "receiptHash": self.HASH_A}
        ]
        receipt = self._receipt(plan)
        receipt["stageId"] = "stage-a"
        receipt["slotId"] = "slot-a"
        receipt["attemptRef"] = "attempt-a-1"
        receipt["eligibleModuleIds"] = ["module-a"]
        receipt["selectedModuleIds"] = ["module-a"]
        receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
        from selfworkflow.v3.contracts import validate_run_ledger

        with self.assertRaises(Exception) as raised:
            validate_run_ledger(ledger, plan, (receipt,))
        self.assertEqual(raised.exception.reason, "ledger-receipt-attempt-stale")
        self.assertEqual(raised.exception.path, ("stages", 0, "selectionReceiptRefs", 0, "attemptRef"))

    def test_run_ledger_old_attempt_result_does_not_complete_current_attempt(self):
        plan = self._plan()
        ledger = self._ledger(plan)
        stage = ledger["stages"][0]
        stage["status"] = "passed"
        stage["attempts"].append(
            {
                "attemptRef": "attempt-a-2", "ordinal": 2,
                "previousAttemptRef": "attempt-a-1",
            }
        )
        stage["slotResults"] = [
            {
                "attemptRef": "attempt-a-1", "slotId": "slot-a",
                "moduleId": "module-a", "artifactHash": self.HASH_A,
            }
        ]
        from selfworkflow.v3.contracts import ContractError, validate_run_ledger

        with self.assertRaises(ContractError) as raised:
            validate_run_ledger(ledger, plan)
        self.assertEqual(raised.exception.reason, "ledger-current-attempt-incomplete")
        self.assertEqual(raised.exception.path, ("stages", 0, "slotResults"))


if __name__ == "__main__":
    unittest.main()
