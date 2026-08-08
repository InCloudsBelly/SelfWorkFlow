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
            "moduleConstraints": [
                {
                    "moduleId": "module-a",
                    "stageId": "stage-a",
                    "slotId": "slot-a",
                    "dependencies": [],
                    "conflicts": [],
                    "estimatedContextCost": 1,
                    "estimatedExecutionCost": 2,
                },
                {
                    "moduleId": "module-b",
                    "stageId": "stage-b",
                    "slotId": "slot-b",
                    "dependencies": [],
                    "conflicts": [],
                    "estimatedContextCost": 10,
                    "estimatedExecutionCost": 20,
                },
            ],
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
                            "coverageObligations": ["coverage-b"],
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
            "selectionPolicyHash": cls.HASH_B,
            "eligibleModuleIds": ["module-b"],
            "selectedModuleIds": ["module-b"],
            "selectionReasons": ["diff-signal"],
            "signalEvidenceRefs": ["signal-b"],
            "estimatedContextCost": 10,
            "estimatedExecutionCost": 20,
            "coverageDecisions": [
                {
                    "obligationId": "coverage-b",
                    "decision": "fulfilled",
                    "evidenceRefs": ["signal-b"],
                }
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
            kwargs = {"plan_graph": self._plan()} if schema_name == "run-ledger.schema.json" else {}
            load_contract(schema_name, json.dumps(document), **kwargs)
        self.assertEqual(raised.exception.reason, reason)
        self.assertEqual(raised.exception.path, path)
        self.assertEqual(raised.exception.validator, "semantic")

    def _assert_schema_only_error(self, filename, document, path, validator):
        self._assert_schema_error(filename, document, path, validator)

    def _assert_ledger_error(
        self, ledger, plan, reason, path, receipts=(), successor=None,
    ):
        from selfworkflow.v3.contracts import ContractError, validate_run_ledger

        with self.assertRaises(ContractError) as raised:
            validate_run_ledger(
                ledger, plan, receipts,
                expected_successor_plan_hash=successor,
            )
        self.assertEqual(raised.exception.reason, reason)
        self.assertEqual(raised.exception.path, path)

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

    def test_plan_graph_requires_self_contained_module_constraints(self):
        from selfworkflow.v3.contracts import ContractError, validate_plan_graph

        missing = self._plan()
        missing.pop("moduleConstraints")
        self._assert_schema_only_error(
            "plan-graph.schema.json", missing, (), "required",
        )

        invalid = self._plan()
        invalid["moduleConstraints"][1]["dependencies"] = ["module-missing"]
        invalid["planHash"] = self._hash_document(invalid, "planHash")
        with self.assertRaises(ContractError) as raised:
            validate_plan_graph(invalid)
        self.assertEqual(
            raised.exception.reason, "plan-module-dependency-unknown",
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
            {
                "attemptRef": "attempt-b-1", "ordinal": 1,
                "previousAttemptRef": None, "startedAt": "2026-08-09T00:00:00Z",
            }
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

    def test_selection_receipt_binds_existing_stage_and_slot(self):
        from selfworkflow.v3.contracts import ContractError, validate_selection_receipt

        plan = self._plan()
        cases = (
            ("missing-stage", "slot-b", "selection-receipt-stage-mismatch", ("stageId",)),
            ("stage-b", "missing-slot", "selection-receipt-slot-mismatch", ("slotId",)),
        )
        for stage_id, slot_id, reason, path in cases:
            receipt = self._receipt(plan)
            receipt["stageId"] = stage_id
            receipt["slotId"] = slot_id
            receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
            with self.subTest(reason=reason), self.assertRaises(ContractError) as raised:
                validate_selection_receipt(receipt, plan)
            self.assertEqual(raised.exception.reason, reason)
            self.assertEqual(raised.exception.path, path)

    def test_selection_receipt_requires_exact_plan_eligible_set(self):
        from selfworkflow.v3.contracts import ContractError, validate_selection_receipt

        plan = self._plan()
        receipt = self._receipt(plan)
        receipt["eligibleModuleIds"] = []
        receipt["selectedModuleIds"] = []
        receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
        with self.assertRaises(ContractError) as raised:
            validate_selection_receipt(receipt, plan)
        self.assertEqual(raised.exception.reason, "selection-receipt-eligible-set-mismatch")
        self.assertEqual(raised.exception.path, ("eligibleModuleIds",))

    def test_selection_receipt_static_selection_matches_plan(self):
        from selfworkflow.v3.contracts import ContractError, validate_selection_receipt

        plan = self._plan()
        receipt = self._receipt(plan)
        receipt.update({
            "stageId": "stage-a", "slotId": "slot-a", "attemptRef": "attempt-a-1",
            "selectionPolicyHash": self.HASH_A,
            "eligibleModuleIds": ["module-a"], "selectedModuleIds": [],
        })
        receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
        with self.assertRaises(ContractError) as raised:
            validate_selection_receipt(receipt, plan)
        self.assertEqual(raised.exception.reason, "selection-receipt-static-selection-mismatch")
        self.assertEqual(raised.exception.path, ("selectedModuleIds",))

    def test_selection_receipt_enforces_each_cardinality(self):
        from selfworkflow.v3.contracts import ContractError, validate_selection_receipt

        cases = (
            ("exactly-one", [], "selection-receipt-cardinality-invalid"),
            ("zero-or-one", ["module-b", "module-c"], "selection-receipt-cardinality-invalid"),
            ("zero-or-many", ["module-outside"], "selection-receipt-selected-module-ineligible"),
            ("gate", [], "selection-receipt-cardinality-invalid"),
        )
        for cardinality, selected, reason in cases:
            plan = self._plan()
            slot = plan["stages"][1]["slots"][0]
            slot["cardinality"] = cardinality
            slot["eligibleModules"] = ["module-b", "module-c"]
            plan["moduleConstraints"].append({
                "moduleId": "module-c",
                "stageId": "stage-b",
                "slotId": "slot-b",
                "dependencies": [],
                "conflicts": [],
                "estimatedContextCost": 1,
                "estimatedExecutionCost": 1,
            })
            plan["planHash"] = self._hash_document(plan, "planHash")
            receipt = self._receipt(plan)
            receipt["eligibleModuleIds"] = ["module-b", "module-c"]
            receipt["selectedModuleIds"] = selected
            receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
            with self.subTest(cardinality=cardinality), self.assertRaises(ContractError) as raised:
                validate_selection_receipt(receipt, plan)
            self.assertEqual(raised.exception.reason, reason)

    def test_run_ledger_preserves_old_attempt_receipt_for_retry_history(self):
        plan = self._plan()
        ledger = self._ledger(plan)
        ledger["stages"][0]["attempts"].append(
            {
                "attemptRef": "attempt-a-2", "ordinal": 2,
                "previousAttemptRef": "attempt-a-1",
                "startedAt": "2026-08-10T00:00:00Z",
            }
        )
        ledger["stages"][0]["attempts"][0]["completedAt"] = "2026-08-09T01:00:00Z"
        receipt = self._receipt(plan)
        receipt["stageId"] = "stage-a"
        receipt["slotId"] = "slot-a"
        receipt["selectionPolicyHash"] = self.HASH_A
        receipt["attemptRef"] = "attempt-a-1"
        receipt["eligibleModuleIds"] = ["module-a"]
        receipt["selectedModuleIds"] = ["module-a"]
        receipt["estimatedContextCost"] = 1
        receipt["estimatedExecutionCost"] = 2
        receipt["coverageDecisions"] = [{
            "obligationId": "coverage-a",
            "decision": "fulfilled",
            "evidenceRefs": ["signal-b"],
        }]
        receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
        ledger["stages"][0]["selectionReceiptRefs"] = [
            {"attemptRef": "attempt-a-1", "receiptHash": receipt["receiptHash"]}
        ]
        from selfworkflow.v3.contracts import validate_run_ledger

        self.assertIsNone(validate_run_ledger(ledger, plan, (receipt,)))

    def test_run_ledger_rejects_receipt_plan_stage_slot_and_attempt_mismatch(self):
        from selfworkflow.v3.contracts import ContractError, validate_run_ledger

        plan = self._plan()
        cases = (
            ("plan", "ledger-receipt-plan-mismatch", ("stages", 0, "selectionReceiptRefs", 0, "receiptHash")),
            ("stage", "ledger-receipt-stage-mismatch", ("stages", 0, "selectionReceiptRefs", 0, "receiptHash")),
            ("slot", "ledger-receipt-slot-mismatch", ("stages", 0, "selectionReceiptRefs", 0, "receiptHash")),
            ("attempt", "ledger-receipt-attempt-mismatch", ("stages", 0, "selectionReceiptRefs", 0, "attemptRef")),
        )
        for kind, reason, path in cases:
            ledger = self._ledger(plan)
            receipt = self._receipt(plan)
            receipt.update({
                "stageId": "stage-a", "slotId": "slot-a", "attemptRef": "attempt-a-1",
                "selectionPolicyHash": self.HASH_A,
                "eligibleModuleIds": ["module-a"], "selectedModuleIds": ["module-a"],
            })
            if kind == "plan":
                receipt["planHash"] = self.HASH_A
            elif kind == "stage":
                receipt.update({"stageId": "stage-b", "slotId": "slot-b", "eligibleModuleIds": ["module-b"], "selectedModuleIds": ["module-b"]})
            elif kind == "slot":
                receipt["slotId"] = "missing-slot"
            elif kind == "attempt":
                receipt["attemptRef"] = "attempt-other"
            receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
            ledger["stages"][0]["selectionReceiptRefs"] = [
                {"attemptRef": "attempt-a-1", "receiptHash": receipt["receiptHash"]}
            ]
            with self.subTest(kind=kind), self.assertRaises(ContractError) as raised:
                validate_run_ledger(ledger, plan, (receipt,))
            self.assertEqual(raised.exception.reason, reason)
            self.assertEqual(raised.exception.path, path)

    def test_run_ledger_old_attempt_result_does_not_complete_current_attempt(self):
        plan = self._plan()
        ledger = self._ledger(plan)
        ledger["status"] = "completed"
        stage = ledger["stages"][0]
        stage["status"] = "passed"
        stage["attempts"].append(
            {
                "attemptRef": "attempt-a-2", "ordinal": 2,
                "previousAttemptRef": "attempt-a-1",
                "startedAt": "2026-08-10T00:00:00Z",
                "completedAt": "2026-08-10T01:00:00Z",
            }
        )
        stage["attempts"][0]["completedAt"] = "2026-08-09T01:00:00Z"
        stage["slotResults"] = [
            {
                "attemptRef": "attempt-a-1", "slotId": "slot-a",
                "moduleId": "module-a", "artifactHash": self.HASH_A,
            }
        ]
        ledger["stages"][1]["status"] = "skipped"
        from selfworkflow.v3.contracts import ContractError, validate_run_ledger

        with self.assertRaises(ContractError) as raised:
            validate_run_ledger(ledger, plan)
        self.assertEqual(raised.exception.reason, "ledger-current-attempt-incomplete")
        self.assertEqual(raised.exception.path, ("stages", 0, "slotResults"))

    def test_run_ledger_registered_loader_path_accepts_valid_ledger(self):
        from selfworkflow.v3.contracts import load_contract

        ledger = self._ledger()
        self.assertEqual(
            load_contract(
                "run-ledger.schema.json", json.dumps(ledger),
                plan_graph=self._plan(),
            ),
            ledger,
        )

    def test_run_ledger_registered_reference_path_validates_receipt(self):
        from selfworkflow.v3.contracts import load_contract, validate_run_ledger

        plan = self._plan()
        receipt = self._receipt(plan)
        receipt.update({
            "stageId": "stage-a", "slotId": "slot-a",
            "selectionPolicyHash": self.HASH_A,
            "attemptRef": "attempt-a-1", "eligibleModuleIds": ["module-a"],
            "selectedModuleIds": ["module-a"],
            "estimatedContextCost": 1,
            "estimatedExecutionCost": 2,
            "coverageDecisions": [{
                "obligationId": "coverage-a",
                "decision": "fulfilled",
                "evidenceRefs": ["signal-b"],
            }],
        })
        receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
        ledger = self._ledger(plan)
        ledger["stages"][0]["selectionReceiptRefs"] = [{
            "attemptRef": "attempt-a-1", "receiptHash": receipt["receiptHash"],
        }]
        loaded = load_contract(
            "run-ledger.schema.json", json.dumps(ledger), plan_graph=plan,
            receipts=(receipt,),
        )
        self.assertIsNone(validate_run_ledger(loaded, plan, (receipt,)))

    def test_selection_receipt_rejects_policy_hash_tamper(self):
        from selfworkflow.v3.contracts import ContractError, validate_selection_receipt

        plan = self._plan()
        receipt = self._receipt(plan)
        receipt["selectionPolicyHash"] = self.HASH_A
        receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
        with self.assertRaises(ContractError) as raised:
            validate_selection_receipt(receipt, plan)
        self.assertEqual(
            raised.exception.reason, "selection-receipt-policy-mismatch",
        )
        self.assertEqual(raised.exception.path, ("selectionPolicyHash",))

    def test_selection_receipt_plan_constraints_enforce_dependency_and_conflict(self):
        from selfworkflow.v3.contracts import ContractError, validate_selection_receipt

        plan = self._plan()
        slot = plan["stages"][1]["slots"][0]
        slot["cardinality"] = "zero-or-many"
        slot["eligibleModules"] = ["module-b", "module-dependency"]
        module_b = next(
            item for item in plan["moduleConstraints"]
            if item["moduleId"] == "module-b"
        )
        module_b["dependencies"] = ["module-dependency"]
        plan["moduleConstraints"].append({
            "moduleId": "module-dependency",
            "stageId": "stage-b",
            "slotId": "slot-b",
            "dependencies": [],
            "conflicts": [],
            "estimatedContextCost": 3,
            "estimatedExecutionCost": 4,
        })
        plan["planHash"] = self._hash_document(plan, "planHash")
        receipt = self._receipt(plan)
        receipt["eligibleModuleIds"] = ["module-b", "module-dependency"]
        receipt["selectedModuleIds"] = ["module-b"]
        receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
        with self.assertRaises(ContractError) as raised:
            validate_selection_receipt(receipt, plan)
        self.assertEqual(
            raised.exception.reason,
            "selection-receipt-selected-dependency-open",
        )

        receipt["selectedModuleIds"] = ["module-b", "module-dependency"]
        receipt["estimatedContextCost"] = 13
        receipt["estimatedExecutionCost"] = 24
        receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
        module_b["conflicts"] = ["module-dependency"]
        plan["moduleConstraints"][-1]["conflicts"] = ["module-b"]
        plan["planHash"] = self._hash_document(plan, "planHash")
        receipt["planHash"] = plan["planHash"]
        receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
        with self.assertRaises(ContractError) as raised:
            validate_selection_receipt(receipt, plan)
        self.assertEqual(
            raised.exception.reason, "selection-receipt-selected-conflict",
        )

    def test_selection_receipt_costs_must_match_plan_constraints(self):
        from selfworkflow.v3.contracts import ContractError, validate_selection_receipt

        plan = self._plan()
        receipt = self._receipt(plan)
        receipt["estimatedContextCost"] += 1
        receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
        with self.assertRaises(ContractError) as raised:
            validate_selection_receipt(receipt, plan)
        self.assertEqual(
            raised.exception.reason, "selection-receipt-context-cost-mismatch",
        )

    def test_selection_receipt_coverage_is_exact_and_fulfilled_needs_evidence(self):
        from selfworkflow.v3.contracts import ContractError, validate_selection_receipt

        plan = self._plan()
        cases = []
        missing = self._receipt(plan)
        missing["coverageDecisions"] = []
        cases.append((missing, "selection-receipt-coverage-obligations-mismatch"))
        extra = self._receipt(plan)
        extra["coverageDecisions"].append({
            "obligationId": "coverage-extra",
            "decision": "blocked",
            "evidenceRefs": [],
        })
        cases.append((extra, "selection-receipt-coverage-obligations-mismatch"))
        duplicate = self._receipt(plan)
        duplicate["coverageDecisions"].append({
            "obligationId": "coverage-b",
            "decision": "unverified",
            "evidenceRefs": [],
        })
        cases.append((duplicate, "selection-receipt-coverage-obligation-duplicate"))
        no_evidence = self._receipt(plan)
        no_evidence["coverageDecisions"][0]["evidenceRefs"] = []
        cases.append((no_evidence, "selection-receipt-coverage-evidence-required"))
        for receipt, reason in cases:
            receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
            with self.subTest(reason=reason):
                with self.assertRaises(ContractError) as raised:
                    validate_selection_receipt(receipt, plan)
                self.assertEqual(raised.exception.reason, reason)

    def test_selection_receipt_standalone_rejects_fulfilled_without_evidence(self):
        from selfworkflow.v3.contracts import ContractError, validate_selection_receipt

        receipt = self._receipt()
        receipt["coverageDecisions"][0]["evidenceRefs"] = []
        receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
        with self.assertRaises(ContractError) as raised:
            validate_selection_receipt(receipt)
        self.assertEqual(
            raised.exception.reason,
            "selection-receipt-coverage-evidence-required",
        )

    def test_run_ledger_reuses_receipt_coverage_validation(self):
        from selfworkflow.v3.contracts import ContractError, validate_run_ledger

        plan = self._plan()
        receipt = self._receipt(plan)
        receipt["coverageDecisions"][0]["evidenceRefs"] = []
        receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
        ledger = self._ledger(plan)
        ledger["stages"][0].update({"status": "skipped", "attempts": []})
        ledger["stages"][1].update({
            "status": "active",
            "attempts": [{
                "attemptRef": "attempt-b-1",
                "ordinal": 1,
                "previousAttemptRef": None,
                "startedAt": "2026-08-09T00:00:00Z",
            }],
            "selectionReceiptRefs": [{
                "attemptRef": "attempt-b-1",
                "receiptHash": receipt["receiptHash"],
            }],
        })
        with self.assertRaises(ContractError) as raised:
            validate_run_ledger(ledger, plan, (receipt,))
        self.assertEqual(
            raised.exception.reason,
            "selection-receipt-coverage-evidence-required",
        )
        self.assertEqual(
            raised.exception.path,
            ("coverageDecisions", 0, "evidenceRefs"),
        )

    def test_run_ledger_rejects_fake_stage_slot_module_gate_and_skip(self):
        plan = self._plan()
        cases = []
        fake_stage = self._ledger(plan)
        fake_stage["stages"][1]["stageId"] = "fake-stage"
        cases.append((fake_stage, "ledger-stage-unknown", ("stages", 1, "stageId"), ()))
        fake_slot = self._ledger(plan)
        fake_slot["stages"][0]["slotResults"] = [{
            "attemptRef": "attempt-a-1", "slotId": "fake-slot",
            "moduleId": "module-a", "artifactHash": self.HASH_A,
        }]
        cases.append((fake_slot, "ledger-slot-unknown", ("stages", 0, "slotResults", 0, "slotId"), ()))
        fake_module = self._ledger(plan)
        fake_module["stages"][0]["slotResults"] = [{
            "attemptRef": "attempt-a-1", "slotId": "slot-a",
            "moduleId": "fake-module", "artifactHash": self.HASH_A,
        }]
        cases.append((fake_module, "ledger-module-not-selected", ("stages", 0, "slotResults", 0, "moduleId"), ()))
        fake_gate = self._ledger(plan)
        fake_gate["stages"][0]["gateResults"] = [{
            "attemptRef": "attempt-a-1", "gateId": "fake-gate",
            "outcome": "passed", "artifactHash": self.HASH_A,
        }]
        cases.append((fake_gate, "ledger-gate-unknown", ("stages", 0, "gateResults", 0, "gateId"), ()))
        bad_skip = self._ledger(plan)
        bad_skip["stages"][0]["runtimeSkips"] = [{
            "attemptRef": "attempt-a-1", "slotId": "slot-a",
            "reasonCode": "not-needed", "evidenceHash": self.HASH_A,
        }]
        cases.append((bad_skip, "ledger-runtime-skip-not-optional", ("stages", 0, "runtimeSkips", 0, "slotId"), ()))
        for ledger, reason, path, receipts in cases:
            with self.subTest(reason=reason):
                self._assert_ledger_error(ledger, plan, reason, path, receipts)

    def test_run_ledger_bounded_module_requires_same_attempt_receipt(self):
        plan = self._plan()
        ledger = self._ledger(plan)
        ledger["stages"][0].update({"status": "skipped", "attempts": []})
        stage = ledger["stages"][1]
        stage.update({
            "status": "active",
            "attempts": [{
                "attemptRef": "attempt-b-1", "ordinal": 1,
                "previousAttemptRef": None, "startedAt": "2026-08-09T00:00:00Z",
            }],
            "slotResults": [{
                "attemptRef": "attempt-b-1", "slotId": "slot-b",
                "moduleId": "module-a", "artifactHash": self.HASH_A,
            }],
        })
        receipt = self._receipt(plan)
        receipt["attemptRef"] = "attempt-b-other"
        receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
        self._assert_ledger_error(
            ledger, plan, "ledger-module-selection-receipt-missing",
            ("stages", 1, "slotResults", 0, "moduleId"), (receipt,),
        )

    def test_run_ledger_rejects_each_top_level_status_violation(self):
        plan = self._plan()
        cases = []
        for status, reason in (
            ("pending", "ledger-status-pending-invalid"),
            ("superseded", "ledger-status-superseded-invalid"),
        ):
            ledger = self._ledger(plan)
            ledger["status"] = status
            if status == "superseded":
                ledger["supersededByPlanHash"] = self.HASH_A
            cases.append((ledger, reason, ("status",), self.HASH_A if status == "superseded" else None))
        for status, reason in (
            ("active", "ledger-status-active-invalid"),
            ("paused", "ledger-status-paused-invalid"),
            ("failed", "ledger-status-failed-invalid"),
            ("completed", "ledger-status-completed-invalid"),
        ):
            ledger = self._ledger(plan)
            ledger["status"] = status
            ledger["stages"][0].update({"status": "pending", "attempts": []})
            cases.append((ledger, reason, ("status",), None))
        for ledger, reason, path, successor in cases:
            with self.subTest(reason=reason):
                self._assert_ledger_error(ledger, plan, reason, path, successor=successor)

    def test_run_ledger_skipped_stage_cannot_carry_execution(self):
        plan = self._plan()
        ledger = self._ledger(plan)
        ledger["status"] = "pending"
        ledger["stages"][0]["status"] = "skipped"
        self._assert_ledger_error(
            ledger, plan, "ledger-skipped-stage-has-execution",
            ("stages", 0),
        )

    def test_run_ledger_superseded_successor_is_explicit_and_exact(self):
        plan = self._plan()
        successor = self.HASH_A
        ledger = self._ledger(plan)
        ledger["status"] = "superseded"
        ledger["stages"][0].update({"status": "paused", "attempts": []})
        ledger["supersededByPlanHash"] = successor
        for expected, reason in (
            (None, "ledger-successor-plan-required"),
            (self.HASH_B, "ledger-successor-plan-mismatch"),
        ):
            with self.subTest(reason=reason):
                self._assert_ledger_error(ledger, plan, reason, ("supersededByPlanHash",), successor=expected)
        active = self._ledger(plan)
        self._assert_ledger_error(
            active, plan, "ledger-successor-plan-unexpected", (),
            successor=successor,
        )

    def test_run_ledger_schema_forbids_successor_on_non_superseded(self):
        from selfworkflow.v3.contracts import ContractError, load_contract

        ledger = self._ledger()
        ledger["supersededByPlanHash"] = self.HASH_A
        with self.assertRaises(ContractError) as raised:
            load_contract("run-ledger.schema.json", json.dumps(ledger))
        self.assertEqual(raised.exception.reason, "contract-schema-invalid")

    def test_run_ledger_attempt_time_invariants(self):
        plan = self._plan()
        missing = self._ledger(plan)
        missing["stages"][0]["attempts"][0].pop("startedAt")
        backwards = self._ledger(plan)
        backwards["stages"][0]["attempts"][0]["completedAt"] = "2026-08-08T00:00:00Z"
        non_active = self._ledger(plan)
        non_active["status"] = "paused"
        non_active["stages"][0]["status"] = "paused"
        active_completed = self._ledger(plan)
        active_completed["stages"][0]["attempts"][0]["completedAt"] = "2026-08-10T00:00:00Z"
        cases = (
            (missing, "contract-schema-invalid", ("stages", 0, "attempts", 0)),
            (backwards, "ledger-attempt-time-invalid", ("stages", 0, "attempts", 0, "completedAt")),
            (non_active, "ledger-attempt-incomplete", ("stages", 0, "attempts", 0, "completedAt")),
            (active_completed, "ledger-active-attempt-completed", ("stages", 0, "attempts", 0, "completedAt")),
        )
        from selfworkflow.v3.contracts import ContractError, validate_run_ledger
        for ledger, reason, path in cases:
            with self.subTest(reason=reason), self.assertRaises(ContractError) as raised:
                validate_run_ledger(ledger, plan)
            self.assertEqual(raised.exception.reason, reason)
            self.assertEqual(raised.exception.path, path)

    def test_run_ledger_stage_list_exactly_matches_plan(self):
        plan = self._plan()
        duplicate = self._ledger(plan)
        duplicate["stages"][1]["stageId"] = "stage-a"
        missing = self._ledger(plan)
        missing["stages"].pop()
        reordered = self._ledger(plan)
        reordered["stages"].reverse()
        extra = self._ledger(plan)
        extra["stages"].append({
            "stageId": "extra-stage", "status": "pending", "attempts": [],
            "slotResults": [], "gateResults": [], "runtimeSkips": [],
            "selectionReceiptRefs": [], "reviewAggregateHashes": [],
            "coverageResultHashes": [], "artifactHashes": [],
        })
        cases = (
            (duplicate, "ledger-stage-id-duplicate", ("stages", 1, "stageId")),
            (missing, "ledger-stage-list-mismatch", ("stages",)),
            (reordered, "ledger-stage-order-mismatch", ("stages",)),
            (extra, "ledger-stage-unknown", ("stages", 2, "stageId")),
        )
        for ledger, reason, path in cases:
            with self.subTest(reason=reason):
                self._assert_ledger_error(ledger, plan, reason, path)

    def test_run_ledger_state_machine_rejects_sequence_contradictions(self):
        plan = self._plan()
        cases = []

        pending = self._ledger(plan)
        pending["status"] = "pending"
        pending["stages"][0]["status"] = "passed"
        cases.append((pending, "ledger-status-pending-invalid"))

        active = self._ledger(plan)
        active["stages"][0].update({"status": "pending", "attempts": []})
        active["stages"][1].update({
            "status": "active",
            "attempts": [{
                "attemptRef": "attempt-b-1", "ordinal": 1,
                "previousAttemptRef": None, "startedAt": "2026-08-09T00:00:00Z",
            }],
        })
        cases.append((active, "ledger-status-active-invalid"))

        active_failed = self._ledger(plan)
        active_failed["stages"][1]["status"] = "failed"
        cases.append((active_failed, "ledger-status-active-invalid"))

        paused = self._ledger(plan)
        paused["status"] = "paused"
        paused["stages"][0].update({"status": "pending", "attempts": []})
        paused["stages"][1]["status"] = "paused"
        cases.append((paused, "ledger-status-paused-invalid"))

        paused_failed = deepcopy(paused)
        paused_failed["stages"][0]["status"] = "failed"
        cases.append((paused_failed, "ledger-status-paused-invalid"))

        failed = self._ledger(plan)
        failed["status"] = "failed"
        failed["stages"][0].update({"status": "pending", "attempts": []})
        failed["stages"][1]["status"] = "failed"
        cases.append((failed, "ledger-status-failed-invalid"))

        multi_failed = deepcopy(failed)
        multi_failed["stages"][0]["status"] = "failed"
        cases.append((multi_failed, "ledger-status-failed-invalid"))

        completed = self._ledger(plan)
        completed["status"] = "completed"
        completed["stages"][0].update({"status": "passed"})
        cases.append((completed, "ledger-status-completed-invalid"))

        for ledger, reason in cases:
            with self.subTest(reason=reason):
                self._assert_ledger_error(ledger, plan, reason, ("status",))

    def test_run_ledger_superseded_allows_frozen_terminal_mix(self):
        plan = self._plan()
        successor = self.HASH_A
        ledger = self._ledger(plan)
        ledger.update({"status": "superseded", "supersededByPlanHash": successor})
        ledger["stages"][0]["status"] = "paused"
        ledger["stages"][0]["attempts"][0]["completedAt"] = "2026-08-09T01:00:00Z"
        self.assertIsNone(
            __import__("selfworkflow.v3.contracts", fromlist=["validate_run_ledger"])
            .validate_run_ledger(
                ledger, plan, expected_successor_plan_hash=successor,
            )
        )

    def test_load_contract_run_ledger_requires_semantic_context(self):
        from selfworkflow.v3.contracts import ContractError, load_contract

        plan = self._plan()
        ledger = self._ledger(plan)
        with self.assertRaises(ContractError) as missing:
            load_contract("run-ledger.schema.json", json.dumps(ledger))
        self.assertEqual(missing.exception.reason, "ledger-plan-required")

        self.assertEqual(
            load_contract(
                "run-ledger.schema.json", json.dumps(ledger),
                plan_graph=plan,
            ),
            ledger,
        )
        with self.assertRaises(ContractError) as unexpected:
            load_contract(
                "run-ledger.schema.json", json.dumps(ledger),
                plan_graph=plan, expected_successor_plan_hash=self.HASH_A,
            )
        self.assertEqual(unexpected.exception.reason, "ledger-successor-plan-unexpected")

    def test_load_contract_superseded_requires_exact_successor_context(self):
        from selfworkflow.v3.contracts import ContractError, load_contract

        plan = self._plan()
        successor = self.HASH_A
        ledger = self._ledger(plan)
        ledger.update({"status": "superseded", "supersededByPlanHash": successor})
        ledger["stages"][0]["status"] = "paused"
        ledger["stages"][0]["attempts"][0]["completedAt"] = "2026-08-09T01:00:00Z"
        self.assertEqual(
            load_contract(
                "run-ledger.schema.json", json.dumps(ledger),
                plan_graph=plan, expected_successor_plan_hash=successor,
            ),
            ledger,
        )
        for expected, reason in (
            (None, "ledger-successor-plan-required"),
            (self.HASH_B, "ledger-successor-plan-mismatch"),
        ):
            kwargs = {"plan_graph": plan}
            if expected is not None:
                kwargs["expected_successor_plan_hash"] = expected
            with self.subTest(reason=reason), self.assertRaises(ContractError) as raised:
                load_contract("run-ledger.schema.json", json.dumps(ledger), **kwargs)
            self.assertEqual(raised.exception.reason, reason)


if __name__ == "__main__":
    unittest.main()
