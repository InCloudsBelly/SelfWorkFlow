from copy import deepcopy
from pathlib import Path
import hashlib
import json
import unittest


class QualityArtifactSchemaTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[3]
    SCHEMA_NAMES = (
        "diff-signal-set.schema.json",
        "review-finding.schema.json",
        "review-aggregate.schema.json",
        "test-strategy.schema.json",
        "coverage-result.schema.json",
    )

    HASH_A = "sha256:" + "a" * 64
    HASH_B = "sha256:" + "b" * 64
    HASH_C = "sha256:" + "c" * 64
    HASH_D = "sha256:" + "d" * 64

    @classmethod
    def _hash_document(cls, document, field):
        material = deepcopy(document)
        material.pop(field)
        payload = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def _hash_value(cls, value):
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def _plan(cls):
        document = {
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
                }
            ],
        }
        document["planHash"] = cls._hash_document(document, "planHash")
        return document

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
                }
            ],
        }

    @classmethod
    def _diff(cls, final_diff_hash=None):
        plan = cls._plan()
        document = {
            "schemaVersion": 3,
            "planHash": plan["planHash"],
            "attemptRef": "attempt-a-1",
            "createdAt": "2026-08-09T01:02:03Z",
            "finalDiffHash": final_diff_hash or cls.HASH_B,
            "files": [
                {"path": "src/example.py", "status": "modified", "language": "python"}
            ],
            "languages": ["python"],
            "boundarySignals": [],
            "stateSignals": ["stateful"],
            "concurrencySignals": [],
            "securitySignals": ["untrusted-input"],
            "performanceSignals": [],
            "evidenceRefs": ["diff-evidence-1"],
            "signalSetHash": cls.HASH_C,
        }
        document["signalSetHash"] = cls._hash_document(document, "signalSetHash")
        return document

    @classmethod
    def _finding(cls, diff=None, fingerprint="fp-null-check", finding_hash=None):
        diff = diff or cls._diff()
        document = {
            "schemaVersion": 3,
            "planHash": diff["planHash"],
            "attemptRef": diff["attemptRef"],
            "createdAt": "2026-08-09T01:03:03Z",
            "finalDiffHash": diff["finalDiffHash"],
            "diffSignalSetHash": diff["signalSetHash"],
            "fingerprint": fingerprint,
            "severity": "high",
            "rootCauseOwner": "implemented",
            "detectionPoint": "review.null-check",
            "evidenceLocations": [
                {"evidenceRef": "review-evidence-1", "path": "src/example.py", "line": 10}
            ],
            "failurePath": ["implemented", "reviewed", "verified"],
            "status": "open",
            "findingHash": finding_hash or cls.HASH_D,
        }
        document["findingHash"] = cls._hash_document(document, "findingHash")
        return document

    @classmethod
    def _aggregate(cls, diff=None, findings=None):
        diff = diff or cls._diff()
        findings = findings or [cls._finding(diff)]
        grouped = {}
        for finding in findings:
            grouped.setdefault(finding["fingerprint"], []).append(finding)
        dedup_groups = [
            {
                "fingerprint": fingerprint,
                "findingHashes": [item["findingHash"] for item in items],
                "representativeFindingHash": items[0]["findingHash"],
            }
            for fingerprint, items in grouped.items()
        ]
        finding_by_hash = {item["findingHash"]: item for item in findings}
        coverage_by_owner = {}
        for group in dedup_groups:
            representative = group["representativeFindingHash"]
            owner = finding_by_hash[representative]["rootCauseOwner"]
            coverage_by_owner.setdefault(owner, []).append(representative)
        document = {
            "schemaVersion": 3,
            "planHash": diff["planHash"],
            "attemptRef": diff["attemptRef"],
            "createdAt": "2026-08-09T01:04:03Z",
            "finalDiffHash": diff["finalDiffHash"],
            "diffSignalSetHash": diff["signalSetHash"],
            "findingHashes": [item["findingHash"] for item in findings],
            "dedupGroups": dedup_groups,
            "conflictAdjudications": [],
            "rootCauseCoverage": [
                {"rootCauseOwner": owner, "findingHashes": hashes}
                for owner, hashes in coverage_by_owner.items()
            ],
            "residualRisks": [],
            "aggregateHash": cls.HASH_A,
        }
        document["aggregateHash"] = cls._hash_document(document, "aggregateHash")
        return document

    @classmethod
    def _strategy(cls, diff=None, basis_kind="diff"):
        diff = diff or cls._diff()
        document = {
            "schemaVersion": 3,
            "planHash": diff["planHash"],
            "attemptRef": diff["attemptRef"],
            "createdAt": "2026-08-09T01:05:03Z",
            "basisKind": basis_kind,
            "testLevel": "T2",
            "testLevelFloor": "T2",
            "source": "builtin",
            "grillMeImplementation": True,
            "risks": [
                {"riskId": "risk-null", "priority": "P1", "acceptanceConditionIds": ["accept-null"]}
            ],
            "acceptanceConditions": [
                {"conditionId": "accept-null", "description": "null input is rejected"}
            ],
            "dimensions": [
                {"dimensionId": "direct", "obligationIds": ["obligation-direct"]},
                {"dimensionId": "failure", "obligationIds": []},
                {"dimensionId": "boundary", "obligationIds": []},
                {"dimensionId": "state", "obligationIds": []},
                {"dimensionId": "nfr", "obligationIds": []},
            ],
            "techniques": [
                {"techniqueId": "tech-unit", "name": "unit", "rationale": "direct behavior"}
            ],
            "authorizationRequirements": [],
            "coverageObligations": [
                {
                    "obligationId": "obligation-direct",
                    "riskId": "risk-null",
                    "dimension": "direct",
                    "techniqueIds": ["tech-unit"],
                    "acceptanceConditionIds": ["accept-null"],
                    "authorizationRequired": False,
                }
            ],
            "strategyHash": cls.HASH_B,
        }
        if basis_kind == "diff":
            document["finalDiffHash"] = diff["finalDiffHash"]
            document["diffSignalSetHash"] = diff["signalSetHash"]
        document["strategyHash"] = cls._hash_document(document, "strategyHash")
        return document

    @classmethod
    def _execution_receipt(cls, diff=None, strategy=None, obligation_ids=None):
        diff = diff or cls._diff()
        strategy = strategy or cls._strategy(diff)
        invocation = {
            "executable": ".venv/Scripts/python.exe",
            "moduleId": "tests.unit.v3.test-quality-artifact-schemas",
            "argvHash": cls.HASH_A,
            "cwdHash": cls.HASH_B,
            "environmentHash": cls.HASH_C,
            "inputHash": strategy["strategyHash"],
            "startedAt": "2026-08-09T01:05:30Z",
        }
        invocation_hash = cls._hash_value(invocation)
        result = {
            "invocationHash": invocation_hash,
            "exitCode": 0,
            "status": "passed",
            "stdoutHash": cls.HASH_A,
            "stderrHash": cls.HASH_B,
            "completedAt": "2026-08-09T01:05:45Z",
        }
        receipt = {
            "schemaVersion": 3,
            "planHash": diff["planHash"],
            "attemptRef": diff["attemptRef"],
            "strategyHash": strategy["strategyHash"],
            "diffSignalSetHash": diff["signalSetHash"],
            "verificationId": "verification-1",
            "obligationIds": obligation_ids or ["obligation-direct"],
            "invocationEnvelope": invocation,
            "invocationHash": invocation_hash,
            "resultEnvelope": result,
            "resultHash": cls._hash_value(result),
            "collectorAttestationHash": cls.HASH_D,
            "receiptHash": cls.HASH_A,
        }
        receipt["receiptHash"] = cls._hash_document(receipt, "receiptHash")
        return receipt

    @classmethod
    def _coverage(cls, diff=None, strategy=None, status="fulfilled"):
        diff = diff or cls._diff()
        strategy = strategy or cls._strategy(diff)
        item = {"obligationId": "obligation-direct", "status": status}
        if status == "fulfilled":
            receipt = cls._execution_receipt(diff, strategy)
            item.update({
                "executionReceiptRef": "collector-receipt-1",
                "executionReceiptHash": receipt["receiptHash"],
            })
        else:
            item["reason"] = "not executed"
        document = {
            "schemaVersion": 3,
            "planHash": diff["planHash"],
            "attemptRef": diff["attemptRef"],
            "createdAt": "2026-08-09T01:06:03Z",
            "finalDiffHash": diff["finalDiffHash"],
            "diffSignalSetHash": diff["signalSetHash"],
            "strategyHash": strategy["strategyHash"],
            "obligations": [item],
            "passed": status == "fulfilled",
            "resultHash": cls.HASH_A,
        }
        document["resultHash"] = cls._hash_document(document, "resultHash")
        return document

    def _load(self, name, document, **kwargs):
        from selfworkflow.v3.contracts import load_contract

        plan = self._plan()
        kwargs.setdefault("plan_graph", plan)
        kwargs.setdefault("run_ledger", self._ledger(plan))
        if name == self.SCHEMA_NAMES[4] and "verification_receipt_resolver" not in kwargs:
            diff = kwargs.get("diff_signal_set")
            strategy = kwargs.get("test_strategy")
            if diff is not None and strategy is not None:
                receipt = self._execution_receipt(diff, strategy)
                kwargs["verification_receipt_resolver"] = (
                    lambda reference, value=receipt:
                    deepcopy(value) if reference == "collector-receipt-1" else None
                )
        return load_contract(name, json.dumps(document), **kwargs)

    def _assert_contract_error(self, name, document, reason, path, **kwargs):
        from selfworkflow.v3.contracts import ContractError

        with self.assertRaises(ContractError) as raised:
            self._load(name, document, **kwargs)
        self.assertEqual(raised.exception.reason, reason)
        self.assertEqual(raised.exception.path, path)

    def test_quality_loads_fail_closed_without_required_context(self):
        from selfworkflow.v3.contracts import ContractError, load_contract

        diff = self._diff()
        finding = self._finding(diff)
        aggregate = self._aggregate(diff, [finding])
        strategy = self._strategy(diff)
        coverage = self._coverage(diff, strategy)
        cases = (
            (self.SCHEMA_NAMES[0], diff, {}, "diff-signal-set-plan-required"),
            (self.SCHEMA_NAMES[1], finding, {}, "review-finding-diff-required"),
            (self.SCHEMA_NAMES[2], aggregate, {}, "review-aggregate-diff-required"),
            (self.SCHEMA_NAMES[3], strategy, {}, "test-strategy-plan-required"),
            (self.SCHEMA_NAMES[4], coverage, {}, "coverage-strategy-required"),
        )
        for name, document, kwargs, reason in cases:
            with self.subTest(name=name):
                with self.assertRaises(ContractError) as raised:
                    load_contract(name, json.dumps(document), **kwargs)
                self.assertEqual(raised.exception.reason, reason)

    def test_dedicated_quality_validators_fail_closed_without_context(self):
        from selfworkflow.v3.contracts import (
            ContractError,
            validate_coverage_result,
            validate_diff_signal_set,
            validate_review_aggregate,
            validate_review_finding,
            validate_test_strategy,
        )

        diff = self._diff()
        finding = self._finding(diff)
        aggregate = self._aggregate(diff, [finding])
        strategy = self._strategy(diff)
        coverage = self._coverage(diff, strategy)
        cases = (
            (validate_diff_signal_set, diff, "diff-signal-set-plan-required"),
            (validate_review_finding, finding, "review-finding-diff-required"),
            (validate_review_aggregate, aggregate, "review-aggregate-diff-required"),
            (validate_test_strategy, strategy, "test-strategy-plan-required"),
            (validate_coverage_result, coverage, "coverage-strategy-required"),
        )
        for validator, document, reason in cases:
            with self.subTest(validator=validator.__name__):
                with self.assertRaises(ContractError) as raised:
                    validator(document)
                self.assertEqual(raised.exception.reason, reason)

    def test_diff_signal_set_rejects_stale_and_non_current_attempt(self):
        plan = self._plan()
        ledger = self._ledger(plan)
        ledger["stages"][0]["attempts"][0]["completedAt"] = "2026-08-09T00:01:00Z"
        ledger["stages"][0]["attempts"].append({
            "attemptRef": "attempt-a-2",
            "ordinal": 2,
            "previousAttemptRef": "attempt-a-1",
            "startedAt": "2026-08-09T00:02:00Z",
        })
        self._assert_contract_error(
            self.SCHEMA_NAMES[0], self._diff(),
            "diff-signal-set-attempt-not-current", ("attemptRef",),
            plan_graph=plan, run_ledger=ledger,
        )

    def test_test_strategy_plan_and_diff_basis_require_exact_context(self):
        plan = self._plan()
        ledger = self._ledger(plan)
        diff = self._diff()
        plan_strategy = self._strategy(diff, basis_kind="plan")
        self._load(
            self.SCHEMA_NAMES[3], plan_strategy,
            plan_graph=plan, run_ledger=ledger,
        )
        self._assert_contract_error(
            self.SCHEMA_NAMES[3], self._strategy(diff),
            "test-strategy-diff-required", (),
            plan_graph=plan, run_ledger=ledger, diff_signal_set=None,
        )

    def test_coverage_only_accepts_diff_basis_strategy(self):
        diff = self._diff()
        plan_strategy = self._strategy(diff, basis_kind="plan")
        coverage = self._coverage(diff, plan_strategy)
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], coverage,
            "coverage-strategy-basis-invalid", ("basisKind",),
            diff_signal_set=diff, test_strategy=plan_strategy,
        )

    def test_each_minimal_quality_schema_is_valid_through_contract_entrypoint(self):
        diff = self._diff()
        finding = self._finding(diff)
        aggregate = self._aggregate(diff, [finding])
        strategy = self._strategy(diff)
        coverage = self._coverage(diff, strategy)
        documents = {
            self.SCHEMA_NAMES[0]: diff,
            self.SCHEMA_NAMES[1]: finding,
            self.SCHEMA_NAMES[2]: aggregate,
            self.SCHEMA_NAMES[3]: strategy,
            self.SCHEMA_NAMES[4]: coverage,
        }
        for name, document in documents.items():
            with self.subTest(name=name):
                kwargs = {}
                if name == self.SCHEMA_NAMES[1]:
                    kwargs = {"diff_signal_set": diff}
                elif name == self.SCHEMA_NAMES[2]:
                    kwargs = {"diff_signal_set": diff, "findings": (finding,)}
                elif name == self.SCHEMA_NAMES[3]:
                    kwargs = {"diff_signal_set": diff}
                elif name == self.SCHEMA_NAMES[4]:
                    kwargs = {"diff_signal_set": diff, "test_strategy": strategy}
                self._load(name, document, **kwargs)

    def test_each_quality_schema_rejects_unknown_field(self):
        diff = self._diff()
        finding = self._finding(diff)
        aggregate = self._aggregate(diff, [finding])
        strategy = self._strategy(diff)
        coverage = self._coverage(diff, strategy)
        documents = [diff, finding, aggregate, strategy, coverage]
        for name, document in zip(self.SCHEMA_NAMES, documents):
            invalid = {**document, "unexpected": True}
            self._assert_contract_error(name, invalid, "contract-schema-invalid", ("unexpected",))

    def test_each_quality_schema_rejects_wrong_version(self):
        diff = self._diff()
        finding = self._finding(diff)
        aggregate = self._aggregate(diff, [finding])
        strategy = self._strategy(diff)
        coverage = self._coverage(diff, strategy)
        documents = [diff, finding, aggregate, strategy, coverage]
        for name, document in zip(self.SCHEMA_NAMES, documents):
            invalid = {**document, "schemaVersion": 2}
            self._assert_contract_error(name, invalid, "contract-schema-invalid", ("schemaVersion",))

    def test_each_quality_schema_rejects_its_specific_invalid_value(self):
        diff = self._diff()
        finding = self._finding(diff)
        aggregate = self._aggregate(diff, [finding])
        strategy = self._strategy(diff)
        coverage = self._coverage(diff, strategy)
        cases = (
            (self.SCHEMA_NAMES[0], {**diff, "finalDiffHash": "not-a-hash"}, ("finalDiffHash",)),
            (self.SCHEMA_NAMES[1], {**finding, "severity": "urgent"}, ("severity",)),
            (self.SCHEMA_NAMES[2], {**aggregate, "findingHashes": [self.HASH_A, self.HASH_A]}, ("findingHashes",)),
            (self.SCHEMA_NAMES[3], {**strategy, "source": "custom"}, ("source",)),
            (self.SCHEMA_NAMES[4], {**coverage, "obligations": [{"obligationId": "obligation-direct", "status": "fulfilled"}]}, ("obligations", 0)),
        )
        for name, document, path in cases:
            self._assert_contract_error(name, document, "contract-schema-invalid", path)

    def test_all_quality_hashes_exclude_their_own_final_hash(self):
        diff = self._diff()
        finding = self._finding(diff)
        aggregate = self._aggregate(diff, [finding])
        strategy = self._strategy(diff)
        coverage = self._coverage(diff, strategy)
        expected = (
            (self.SCHEMA_NAMES[0], diff, "signalSetHash"),
            (self.SCHEMA_NAMES[1], finding, "findingHash"),
            (self.SCHEMA_NAMES[2], aggregate, "aggregateHash"),
            (self.SCHEMA_NAMES[3], strategy, "strategyHash"),
            (self.SCHEMA_NAMES[4], coverage, "resultHash"),
        )
        for name, document, field in expected:
            with self.subTest(name=name):
                broken = {**document, field: self.HASH_A}
                reasons = {
                    "signalSetHash": "diff-signal-set-hash-invalid",
                    "findingHash": "review-finding-hash-invalid",
                    "aggregateHash": "review-aggregate-hash-invalid",
                    "strategyHash": "test-strategy-hash-invalid",
                    "resultHash": "coverage-result-hash-invalid",
                }
                self._assert_contract_error(name, broken, reasons[field], (field,))

    def test_grill_me_implementation_requires_t2_floor(self):
        diff = self._diff()
        strategy = self._strategy(diff)
        strategy["testLevel"] = "T1"
        strategy["testLevelFloor"] = "T1"
        strategy["strategyHash"] = self._hash_document(strategy, "strategyHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[3], strategy, "test-strategy-grill-me-floor-invalid", ("testLevel",),
            diff_signal_set=diff,
        )

    def test_test_strategy_dimensions_are_a_closed_unique_complete_partition(self):
        diff = self._diff()
        cases = []

        unknown = self._strategy(diff)
        unknown["dimensions"][0]["dimensionId"] = "security"
        cases.append((unknown, "contract-schema-invalid", ("dimensions", 0, "dimensionId")))

        duplicate = self._strategy(diff)
        duplicate["dimensions"][1]["dimensionId"] = "direct"
        duplicate["strategyHash"] = self._hash_document(duplicate, "strategyHash")
        cases.append((duplicate, "test-strategy-dimension-id-duplicate", ("dimensions", 1, "dimensionId")))

        missing_dimension = self._strategy(diff)
        missing_dimension["dimensions"].pop()
        missing_dimension["strategyHash"] = self._hash_document(missing_dimension, "strategyHash")
        cases.append((missing_dimension, "test-strategy-dimension-set-mismatch", ("dimensions",)))

        missing_obligation = self._strategy(diff)
        missing_obligation["dimensions"][0]["obligationIds"] = []
        missing_obligation["strategyHash"] = self._hash_document(missing_obligation, "strategyHash")
        cases.append((missing_obligation, "test-strategy-dimension-incomplete", ("dimensions",)))

        overlap = self._strategy(diff)
        overlap["dimensions"][1]["obligationIds"] = ["obligation-direct"]
        overlap["strategyHash"] = self._hash_document(overlap, "strategyHash")
        cases.append((overlap, "test-strategy-dimension-overlap", ("dimensions", 1, "obligationIds", 0)))

        for strategy, reason, path in cases:
            with self.subTest(reason=reason):
                self._assert_contract_error(
                    self.SCHEMA_NAMES[3], strategy, reason, path,
                    diff_signal_set=diff,
                )

    def test_test_strategy_obligations_require_technique_and_acceptance(self):
        diff = self._diff()
        for field in ("techniqueIds", "acceptanceConditionIds"):
            strategy = self._strategy(diff)
            strategy["coverageObligations"][0][field] = []
            strategy["strategyHash"] = self._hash_document(strategy, "strategyHash")
            with self.subTest(field=field):
                self._assert_contract_error(
                    self.SCHEMA_NAMES[3], strategy,
                    "contract-schema-invalid", ("coverageObligations", 0, field),
                    diff_signal_set=diff,
                )

    def test_test_strategy_authorization_references_are_exact(self):
        diff = self._diff()

        missing = self._strategy(diff)
        missing["coverageObligations"][0]["authorizationRequired"] = True
        missing["strategyHash"] = self._hash_document(missing, "strategyHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[3], missing, "contract-schema-invalid",
            ("coverageObligations", 0), diff_signal_set=diff,
        )

        forbidden = self._strategy(diff)
        forbidden["coverageObligations"][0]["authorizationRequirementIds"] = ["auth-1"]
        forbidden["strategyHash"] = self._hash_document(forbidden, "strategyHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[3], forbidden, "contract-schema-invalid",
            ("coverageObligations", 0), diff_signal_set=diff,
        )

        unknown = self._strategy(diff)
        unknown["coverageObligations"][0].update({
            "authorizationRequired": True,
            "authorizationRequirementIds": ["auth-missing"],
        })
        unknown["strategyHash"] = self._hash_document(unknown, "strategyHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[3], unknown,
            "test-strategy-authorization-requirement-unknown",
            ("coverageObligations", 0, "authorizationRequirementIds", 0),
            diff_signal_set=diff,
        )

        unused = self._strategy(diff)
        unused["authorizationRequirements"] = [{
            "authorizationId": "auth-1", "required": True, "reason": "network access",
        }]
        unused["strategyHash"] = self._hash_document(unused, "strategyHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[3], unused,
            "test-strategy-authorization-requirement-unused",
            ("authorizationRequirements", 0, "authorizationId"),
            diff_signal_set=diff,
        )

        duplicate = self._strategy(diff)
        duplicate["authorizationRequirements"] = [
            {"authorizationId": "auth-1", "required": True, "reason": "network access"},
            {"authorizationId": "auth-1", "required": True, "reason": "network access"},
        ]
        duplicate["coverageObligations"][0].update({
            "authorizationRequired": True,
            "authorizationRequirementIds": ["auth-1"],
        })
        duplicate["strategyHash"] = self._hash_document(duplicate, "strategyHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[3], duplicate,
            "test-strategy-authorization-requirement-duplicate",
            ("authorizationRequirements", 1, "authorizationId"),
            diff_signal_set=diff,
        )

        valid = self._strategy(diff)
        valid["authorizationRequirements"] = [{
            "authorizationId": "auth-1", "required": True, "reason": "network access",
        }]
        valid["coverageObligations"][0].update({
            "authorizationRequired": True,
            "authorizationRequirementIds": ["auth-1"],
        })
        valid["strategyHash"] = self._hash_document(valid, "strategyHash")
        self._load(self.SCHEMA_NAMES[3], valid, diff_signal_set=diff)

    def test_review_finding_rejects_stale_diff(self):
        diff = self._diff()
        finding = self._finding(diff)
        stale = self._diff(self.HASH_D)
        self._assert_contract_error(
            self.SCHEMA_NAMES[1], finding, "review-finding-final-diff-mismatch", ("finalDiffHash",),
            diff_signal_set=stale,
        )

    def test_review_aggregate_rejects_finding_from_old_diff(self):
        current = self._diff()
        stale = self._diff(self.HASH_D)
        old_finding = self._finding(stale)
        aggregate = self._aggregate(current, [old_finding])
        self._assert_contract_error(
            self.SCHEMA_NAMES[2], aggregate, "review-aggregate-finding-binding-mismatch", ("findingHashes", 0),
            diff_signal_set=current, findings=(old_finding,),
        )

    def test_review_aggregate_dedup_groups_are_complete_and_fingerprint_bound(self):
        diff = self._diff()
        first = self._finding(diff, "fp-same")
        second = self._finding(diff, "fp-same")
        second["evidenceLocations"][0]["line"] = 11
        second["findingHash"] = self.HASH_D
        second["findingHash"] = self._hash_document(second, "findingHash")
        aggregate = self._aggregate(diff, [first, second])
        self._load(
            self.SCHEMA_NAMES[2], aggregate,
            diff_signal_set=diff, findings=(first, second),
        )

        other = self._finding(diff, "fp-other")
        other["evidenceLocations"][0]["line"] = 12
        other["findingHash"] = self._hash_document(other, "findingHash")
        aggregate = self._aggregate(diff, [first, other])
        aggregate["dedupGroups"][0]["findingHashes"].append(other["findingHash"])
        aggregate["dedupGroups"].pop()
        aggregate["aggregateHash"] = self._hash_document(aggregate, "aggregateHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[2], aggregate, "review-aggregate-dedup-fingerprint-mismatch", ("dedupGroups", 0, "findingHashes", 1),
            diff_signal_set=diff, findings=(first, other),
        )

        aggregate = self._aggregate(diff, [first, other])
        aggregate["dedupGroups"].pop()
        aggregate["aggregateHash"] = self._hash_document(aggregate, "aggregateHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[2], aggregate, "review-aggregate-dedup-incomplete", ("dedupGroups",),
            diff_signal_set=diff, findings=(first, other),
        )

        aggregate = self._aggregate(diff, [first])
        aggregate["dedupGroups"].append(deepcopy(aggregate["dedupGroups"][0]))
        aggregate["aggregateHash"] = self._hash_document(aggregate, "aggregateHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[2], aggregate, "review-aggregate-dedup-overlap", ("dedupGroups", 1, "findingHashes", 0),
            diff_signal_set=diff, findings=(first,),
        )

        aggregate = self._aggregate(diff, [first])
        aggregate["dedupGroups"][0]["representativeFindingHash"] = self.HASH_A
        aggregate["aggregateHash"] = self._hash_document(aggregate, "aggregateHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[2], aggregate, "review-aggregate-dedup-representative-invalid", ("dedupGroups", 0, "representativeFindingHash"),
            diff_signal_set=diff, findings=(first,),
        )

    def test_review_aggregate_root_cause_coverage_is_exact_and_owner_unique(self):
        diff = self._diff()
        first = self._finding(diff, "fp-first")
        second = self._finding(diff, "fp-second")
        second["rootCauseOwner"] = "design"
        second["evidenceLocations"][0]["line"] = 12
        second["findingHash"] = self._hash_document(second, "findingHash")

        same_owner = self._finding(diff, "fp-same-owner")
        same_owner["evidenceLocations"][0]["line"] = 13
        same_owner["findingHash"] = self._hash_document(same_owner, "findingHash")
        aggregate = self._aggregate(diff, [first, same_owner])
        moved_hash = aggregate["rootCauseCoverage"][0]["findingHashes"].pop()
        aggregate["rootCauseCoverage"].append({
            "rootCauseOwner": "implemented", "findingHashes": [moved_hash],
        })
        aggregate["aggregateHash"] = self._hash_document(aggregate, "aggregateHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[2], aggregate, "review-aggregate-root-cause-owner-duplicate", ("rootCauseCoverage", 1, "rootCauseOwner"),
            diff_signal_set=diff, findings=(first, same_owner),
        )

        aggregate = self._aggregate(diff, [first, second])
        aggregate["rootCauseCoverage"].pop()
        aggregate["aggregateHash"] = self._hash_document(aggregate, "aggregateHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[2], aggregate, "review-aggregate-root-cause-incomplete", ("rootCauseCoverage",),
            diff_signal_set=diff, findings=(first, second),
        )

        aggregate = self._aggregate(diff, [first, second])
        aggregate["rootCauseCoverage"][1]["findingHashes"].append(first["findingHash"])
        aggregate["aggregateHash"] = self._hash_document(aggregate, "aggregateHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[2], aggregate, "review-aggregate-root-cause-overlap", ("rootCauseCoverage", 1, "findingHashes", 1),
            diff_signal_set=diff, findings=(first, second),
        )

        aggregate = self._aggregate(diff, [first])
        aggregate["rootCauseCoverage"][0]["rootCauseOwner"] = "design"
        aggregate["aggregateHash"] = self._hash_document(aggregate, "aggregateHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[2], aggregate, "review-aggregate-root-cause-owner-mismatch", ("rootCauseCoverage", 0, "rootCauseOwner"),
            diff_signal_set=diff, findings=(first,),
        )

    def test_review_aggregate_conflicts_are_closed_and_unique(self):
        diff = self._diff()
        findings = []
        for index, fingerprint in enumerate(("fp-first", "fp-second", "fp-third"), start=10):
            finding = self._finding(diff, fingerprint)
            finding["evidenceLocations"][0]["line"] = index
            finding["findingHash"] = self._hash_document(finding, "findingHash")
            findings.append(finding)
        aggregate = self._aggregate(diff, findings)
        hashes = [item["findingHash"] for item in findings]
        aggregate["conflictAdjudications"] = [
            {"conflictId": "conflict-1", "findingHashes": hashes[:2], "decision": "accepted", "evidenceRefs": ["evidence-1"]},
            {"conflictId": "conflict-1", "findingHashes": hashes[1:], "decision": "rejected", "evidenceRefs": ["evidence-2"]},
        ]
        aggregate["aggregateHash"] = self._hash_document(aggregate, "aggregateHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[2], aggregate, "review-aggregate-conflict-id-duplicate", ("conflictAdjudications", 1, "conflictId"),
            diff_signal_set=diff, findings=tuple(findings),
        )

        aggregate["conflictAdjudications"][1]["conflictId"] = "conflict-2"
        aggregate["aggregateHash"] = self._hash_document(aggregate, "aggregateHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[2], aggregate, "review-aggregate-conflict-overlap", ("conflictAdjudications", 1, "findingHashes", 0),
            diff_signal_set=diff, findings=tuple(findings),
        )

        for participants in ([hashes[0]], [hashes[0], hashes[0]]):
            invalid = self._aggregate(diff, findings)
            invalid["conflictAdjudications"] = [{
                "conflictId": "conflict-1", "findingHashes": participants,
                "decision": "accepted", "evidenceRefs": ["evidence-1"],
            }]
            invalid["aggregateHash"] = self._hash_document(invalid, "aggregateHash")
            self._assert_contract_error(
                self.SCHEMA_NAMES[2], invalid, "contract-schema-invalid", ("conflictAdjudications", 0, "findingHashes"),
                diff_signal_set=diff, findings=tuple(findings),
            )

        invalid = self._aggregate(diff, findings)
        invalid["conflictAdjudications"] = [{
            "conflictId": "conflict-1", "findingHashes": [hashes[0], self.HASH_A],
            "decision": "accepted", "evidenceRefs": ["evidence-1"],
        }]
        invalid["aggregateHash"] = self._hash_document(invalid, "aggregateHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[2], invalid, "review-aggregate-conflict-finding-unknown", ("conflictAdjudications", 0, "findingHashes", 1),
            diff_signal_set=diff, findings=tuple(findings),
        )

        invalid = self._aggregate(diff, findings)
        invalid["conflictAdjudications"] = [{
            "conflictId": "conflict-1", "findingHashes": hashes[:2],
            "decision": "pending", "evidenceRefs": ["evidence-1"],
        }]
        invalid["aggregateHash"] = self._hash_document(invalid, "aggregateHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[2], invalid, "review-aggregate-conflict-unadjudicated", ("conflictAdjudications", 0, "decision"),
            diff_signal_set=diff, findings=tuple(findings),
        )

    def test_coverage_obligations_must_exactly_match_strategy(self):
        diff = self._diff()
        strategy = self._strategy(diff)
        coverage = self._coverage(diff, strategy)
        coverage["obligations"][0]["obligationId"] = "missing-obligation"
        coverage["resultHash"] = self._hash_document(coverage, "resultHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], coverage, "coverage-obligations-mismatch", ("obligations",),
            diff_signal_set=diff, test_strategy=strategy,
        )
        coverage = self._coverage(diff, strategy)
        coverage["obligations"].append({"obligationId": "extra-obligation", "status": "blocked", "reason": "not planned"})
        coverage["resultHash"] = self._hash_document(coverage, "resultHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], coverage, "coverage-obligations-mismatch", ("obligations",),
            diff_signal_set=diff, test_strategy=strategy,
        )

    def test_coverage_passed_cannot_include_unverified_and_fulfilled_needs_evidence(self):
        diff = self._diff()
        strategy = self._strategy(diff)
        coverage = self._coverage(diff, strategy, status="unverified")
        coverage["passed"] = True
        coverage["resultHash"] = self._hash_document(coverage, "resultHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], coverage, "coverage-passed-with-unfulfilled", ("passed",),
            diff_signal_set=diff, test_strategy=strategy,
        )
        invalid = self._coverage(diff, strategy)
        del invalid["obligations"][0]["executionReceiptRef"]
        invalid["resultHash"] = self._hash_document(invalid, "resultHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], invalid, "contract-schema-invalid", ("obligations", 0),
            diff_signal_set=diff, test_strategy=strategy,
        )

    def test_coverage_fulfilled_requires_trusted_receipt_resolver(self):
        diff = self._diff()
        strategy = self._strategy(diff)
        coverage = self._coverage(diff, strategy)
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], coverage,
            "coverage-verification-resolver-required", (),
            diff_signal_set=diff, test_strategy=strategy,
            verification_receipt_resolver=None,
        )
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], coverage,
            "coverage-execution-receipt-unknown", ("obligations", 0, "executionReceiptRef"),
            diff_signal_set=diff, test_strategy=strategy,
            verification_receipt_resolver=lambda reference: None,
        )

    def test_coverage_recomputes_receipt_invocation_and_result_hashes(self):
        diff = self._diff()
        strategy = self._strategy(diff)
        coverage = self._coverage(diff, strategy)
        receipt = self._execution_receipt(diff, strategy)
        receipt["receiptHash"] = self.HASH_A
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], coverage,
            "coverage-execution-receipt-hash-invalid", ("obligations", 0, "executionReceiptRef"),
            diff_signal_set=diff, test_strategy=strategy,
            verification_receipt_resolver=lambda reference: receipt,
        )

        for field, reason in (
            ("invocationHash", "coverage-execution-receipt-invocation-hash-invalid"),
            ("resultHash", "coverage-execution-receipt-result-hash-invalid"),
        ):
            receipt = self._execution_receipt(diff, strategy)
            receipt[field] = self.HASH_A
            receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
            coverage["obligations"][0]["executionReceiptHash"] = receipt["receiptHash"]
            coverage["resultHash"] = self._hash_document(coverage, "resultHash")
            with self.subTest(field=field):
                self._assert_contract_error(
                    self.SCHEMA_NAMES[4], coverage, reason,
                    ("obligations", 0, "executionReceiptRef"),
                    diff_signal_set=diff, test_strategy=strategy,
                    verification_receipt_resolver=lambda reference, value=receipt: value,
                )

    def test_coverage_receipt_binds_plan_attempt_strategy_diff_and_obligation(self):
        diff = self._diff()
        strategy = self._strategy(diff)
        cases = (
            ("planHash", self.HASH_A, "coverage-execution-receipt-plan-mismatch"),
            ("attemptRef", "attempt-a-2", "coverage-execution-receipt-attempt-mismatch"),
            ("strategyHash", self.HASH_A, "coverage-execution-receipt-strategy-mismatch"),
            ("diffSignalSetHash", self.HASH_A, "coverage-execution-receipt-diff-mismatch"),
        )
        for field, value, reason in cases:
            receipt = self._execution_receipt(diff, strategy)
            receipt[field] = value
            receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
            coverage = self._coverage(diff, strategy)
            coverage["obligations"][0]["executionReceiptHash"] = receipt["receiptHash"]
            coverage["resultHash"] = self._hash_document(coverage, "resultHash")
            with self.subTest(field=field):
                self._assert_contract_error(
                    self.SCHEMA_NAMES[4], coverage, reason,
                    ("obligations", 0, "executionReceiptRef"),
                    diff_signal_set=diff, test_strategy=strategy,
                    verification_receipt_resolver=lambda reference, item=receipt: item,
                )

        receipt = self._execution_receipt(diff, strategy, ["obligation-other"])
        coverage = self._coverage(diff, strategy)
        coverage["obligations"][0]["executionReceiptHash"] = receipt["receiptHash"]
        coverage["resultHash"] = self._hash_document(coverage, "resultHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], coverage,
            "coverage-execution-receipt-obligation-mismatch",
            ("obligations", 0, "executionReceiptRef"),
            diff_signal_set=diff, test_strategy=strategy,
            verification_receipt_resolver=lambda reference: receipt,
        )

    def test_coverage_receipt_binds_invocation_time_and_success_status(self):
        diff = self._diff()
        strategy = self._strategy(diff)
        mutations = (
            (
                lambda receipt: receipt["resultEnvelope"].update(invocationHash=self.HASH_A),
                "coverage-execution-receipt-invocation-mismatch",
            ),
            (
                lambda receipt: receipt["invocationEnvelope"].update(inputHash=self.HASH_A),
                "coverage-execution-receipt-input-mismatch",
            ),
            (
                lambda receipt: receipt["resultEnvelope"].update(completedAt="2026-08-09T01:05:29Z"),
                "coverage-execution-receipt-time-invalid",
            ),
            (
                lambda receipt: receipt["resultEnvelope"].update(exitCode=1),
                "coverage-execution-receipt-exit-unsuccessful",
            ),
            (
                lambda receipt: receipt["resultEnvelope"].update(status="failed"),
                "coverage-execution-receipt-status-unsuccessful",
            ),
        )
        for mutate, reason in mutations:
            receipt = self._execution_receipt(diff, strategy)
            mutate(receipt)
            receipt["invocationHash"] = self._hash_value(receipt["invocationEnvelope"])
            if reason != "coverage-execution-receipt-invocation-mismatch":
                receipt["resultEnvelope"]["invocationHash"] = receipt["invocationHash"]
            receipt["resultHash"] = self._hash_value(receipt["resultEnvelope"])
            receipt["receiptHash"] = self._hash_document(receipt, "receiptHash")
            coverage = self._coverage(diff, strategy)
            coverage["obligations"][0]["executionReceiptHash"] = receipt["receiptHash"]
            coverage["resultHash"] = self._hash_document(coverage, "resultHash")
            with self.subTest(reason=reason):
                self._assert_contract_error(
                    self.SCHEMA_NAMES[4], coverage, reason,
                    ("obligations", 0, "executionReceiptRef"),
                    diff_signal_set=diff, test_strategy=strategy,
                    verification_receipt_resolver=lambda reference, item=receipt: item,
                )

    def test_coverage_shared_receipt_declaration_exactly_matches_references(self):
        diff = self._diff()
        strategy = self._strategy(diff)
        strategy["dimensions"][1]["obligationIds"] = ["obligation-failure"]
        strategy["coverageObligations"].append({
            "obligationId": "obligation-failure",
            "riskId": "risk-null",
            "dimension": "failure",
            "techniqueIds": ["tech-unit"],
            "acceptanceConditionIds": ["accept-null"],
            "authorizationRequired": False,
        })
        strategy["strategyHash"] = self._hash_document(strategy, "strategyHash")
        receipt = self._execution_receipt(
            diff, strategy, ["obligation-direct", "obligation-failure"],
        )
        coverage = self._coverage(diff, strategy)
        coverage["obligations"][0]["executionReceiptHash"] = receipt["receiptHash"]
        coverage["obligations"].append({
            "obligationId": "obligation-failure",
            "status": "fulfilled",
            "executionReceiptRef": "collector-receipt-1",
            "executionReceiptHash": receipt["receiptHash"],
        })
        coverage["resultHash"] = self._hash_document(coverage, "resultHash")

        class Resolver:
            def resolve_verification_receipt(self, reference):
                return deepcopy(receipt) if reference == "collector-receipt-1" else None

        self._load(
            self.SCHEMA_NAMES[4], coverage,
            diff_signal_set=diff, test_strategy=strategy,
            verification_receipt_resolver=Resolver(),
        )

        coverage["obligations"][1] = {
            "obligationId": "obligation-failure",
            "status": "blocked",
            "reason": "not executed",
        }
        coverage["passed"] = False
        coverage["resultHash"] = self._hash_document(coverage, "resultHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], coverage,
            "coverage-execution-receipt-obligations-mismatch",
            ("obligations", 0, "executionReceiptRef"),
            diff_signal_set=diff, test_strategy=strategy,
            verification_receipt_resolver=Resolver(),
        )

    def test_coverage_nonfulfilled_rejects_execution_evidence(self):
        diff = self._diff()
        strategy = self._strategy(diff)
        for status in ("unverified", "blocked"):
            invalid = self._coverage(diff, strategy, status=status)
            receipt = self._execution_receipt(diff, strategy)
            invalid["obligations"][0]["executionReceiptRef"] = "collector-receipt-1"
            invalid["obligations"][0]["executionReceiptHash"] = receipt["receiptHash"]
            invalid["resultHash"] = self._hash_document(invalid, "resultHash")
            with self.subTest(status=status):
                self._assert_contract_error(
                    self.SCHEMA_NAMES[4], invalid, "contract-schema-invalid", ("obligations", 0),
                    diff_signal_set=diff, test_strategy=strategy,
                )

    def test_coverage_requires_strategy_and_unique_obligation_ids(self):
        diff = self._diff()
        strategy = self._strategy(diff)
        coverage = self._coverage(diff, strategy)
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], coverage, "coverage-strategy-required", (),
            diff_signal_set=diff,
        )

        duplicate = deepcopy(coverage["obligations"][0])
        duplicate["status"] = "blocked"
        duplicate.pop("executionReceiptRef")
        duplicate.pop("executionReceiptHash")
        duplicate["reason"] = "duplicate result"
        coverage["obligations"].append(duplicate)
        coverage["passed"] = False
        coverage["resultHash"] = self._hash_document(coverage, "resultHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], coverage, "coverage-obligation-id-duplicate", ("obligations", 1, "obligationId"),
            diff_signal_set=diff, test_strategy=strategy,
        )

    def test_coverage_binds_strategy_plan_attempt_and_diff_identity(self):
        diff = self._diff()
        strategy = self._strategy(diff)
        coverage = self._coverage(diff, strategy)
        coverage["planHash"] = self.HASH_D
        coverage["resultHash"] = self._hash_document(coverage, "resultHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], coverage, "coverage-result-plan-mismatch", ("planHash",),
            diff_signal_set=diff, test_strategy=strategy,
        )

    def test_quality_artifacts_reject_plan_attempt_and_diff_hash_drift(self):
        diff = self._diff()
        finding = self._finding(diff)
        aggregate = self._aggregate(diff, [finding])
        strategy = self._strategy(diff)
        coverage = self._coverage(diff, strategy)
        changed = self._diff()
        changed["planHash"] = self.HASH_D
        changed["attemptRef"] = "attempt-2"
        changed["signalSetHash"] = self._hash_document(changed, "signalSetHash")
        for name, document, reason, kwargs in (
            (self.SCHEMA_NAMES[1], finding, "review-finding-plan-mismatch", {"diff_signal_set": changed}),
            (self.SCHEMA_NAMES[2], aggregate, "review-aggregate-plan-mismatch", {"diff_signal_set": changed, "findings": (finding,)}),
            (self.SCHEMA_NAMES[3], strategy, "test-strategy-plan-mismatch", {"diff_signal_set": changed}),
            (self.SCHEMA_NAMES[4], coverage, "coverage-result-plan-mismatch", {"diff_signal_set": changed, "test_strategy": strategy}),
        ):
            with self.subTest(name=name):
                self._assert_contract_error(name, document, reason, ("planHash",), **kwargs)

    def test_each_quality_schema_requires_stable_id_hash_and_utc_shapes(self):
        diff = self._diff()
        finding = self._finding(diff)
        aggregate = self._aggregate(diff, [finding])
        strategy = self._strategy(diff)
        coverage = self._coverage(diff, strategy)
        documents = [diff, finding, aggregate, strategy, coverage]
        for name, document in zip(self.SCHEMA_NAMES, documents):
            with self.subTest(name=name, field="attemptRef"):
                invalid = {**document, "attemptRef": "Attempt-1"}
                self._assert_contract_error(name, invalid, "contract-schema-invalid", ("attemptRef",))
            with self.subTest(name=name, field="createdAt"):
                invalid = {**document, "createdAt": "2026-08-09T01:02:03+08:00"}
                self._assert_contract_error(name, invalid, "contract-schema-invalid", ("createdAt",))

    def test_quality_artifact_schema_files_are_registered(self):
        for name in self.SCHEMA_NAMES:
            with self.subTest(name=name):
                self.assertTrue(
                    (self.ROOT / "schemas" / "v3" / name).is_file(),
                    f"v3-schema-not-found:{name}",
                )
