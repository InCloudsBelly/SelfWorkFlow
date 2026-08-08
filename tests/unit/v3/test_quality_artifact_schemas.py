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
    def _diff(cls, final_diff_hash=None):
        document = {
            "schemaVersion": 3,
            "planHash": cls.HASH_A,
            "attemptRef": "attempt-1",
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
    def _strategy(cls, diff=None):
        diff = diff or cls._diff()
        document = {
            "schemaVersion": 3,
            "planHash": diff["planHash"],
            "attemptRef": diff["attemptRef"],
            "createdAt": "2026-08-09T01:05:03Z",
            "finalDiffHash": diff["finalDiffHash"],
            "diffSignalSetHash": diff["signalSetHash"],
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
            "dimensions": {
                "direct": ["obligation-direct"],
                "failure": [],
                "boundary": [],
                "state": [],
                "nfr": [],
            },
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
        document["strategyHash"] = cls._hash_document(document, "strategyHash")
        return document

    @classmethod
    def _invocation_evidence(cls, input_hash=None):
        evidence = {
            "executable": ".venv/Scripts/python.exe",
            "moduleId": "tests.unit.v3.test-quality-artifact-schemas",
            "argvHash": cls.HASH_A,
            "cwdHash": cls.HASH_B,
            "environmentHash": cls.HASH_C,
            "inputHash": input_hash or cls.HASH_D,
            "startedAt": "2026-08-09T01:05:30Z",
            "invocationHash": cls.HASH_A,
        }
        evidence["invocationHash"] = cls._hash_document(evidence, "invocationHash")
        return evidence

    @classmethod
    def _result_evidence(cls, invocation):
        evidence = {
            "invocationHash": invocation["invocationHash"],
            "exitCode": 0,
            "stdoutHash": cls.HASH_A,
            "stderrHash": cls.HASH_B,
            "completedAt": "2026-08-09T01:05:45Z",
            "resultHash": cls.HASH_C,
        }
        evidence["resultHash"] = cls._hash_document(evidence, "resultHash")
        return evidence

    @classmethod
    def _coverage(cls, diff=None, strategy=None, status="fulfilled"):
        diff = diff or cls._diff()
        strategy = strategy or cls._strategy(diff)
        item = {"obligationId": "obligation-direct", "status": status}
        if status == "fulfilled":
            invocation = cls._invocation_evidence(strategy["strategyHash"])
            item.update({
                "invocationEvidence": invocation,
                "resultEvidence": cls._result_evidence(invocation),
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

        return load_contract(name, json.dumps(document), **kwargs)

    def _assert_contract_error(self, name, document, reason, path, **kwargs):
        from selfworkflow.v3.contracts import ContractError

        with self.assertRaises(ContractError) as raised:
            self._load(name, document, **kwargs)
        self.assertEqual(raised.exception.reason, reason)
        self.assertEqual(raised.exception.path, path)

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
        del invalid["obligations"][0]["invocationEvidence"]
        invalid["resultHash"] = self._hash_document(invalid, "resultHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], invalid, "contract-schema-invalid", ("obligations", 0),
            diff_signal_set=diff, test_strategy=strategy,
        )

    def test_coverage_fulfilled_requires_closed_canonical_execution_evidence(self):
        diff = self._diff()
        strategy = self._strategy(diff)

        naked = self._coverage(diff, strategy)
        naked["obligations"][0] = {
            "obligationId": "obligation-direct", "status": "fulfilled",
            "invocationHash": self.HASH_A, "resultHash": self.HASH_B,
        }
        naked["resultHash"] = self._hash_document(naked, "resultHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], naked, "contract-schema-invalid", ("obligations", 0, "invocationHash"),
            diff_signal_set=diff, test_strategy=strategy,
        )

        invalid = self._coverage(diff, strategy)
        invalid["obligations"][0]["invocationEvidence"]["invocationHash"] = self.HASH_A
        invalid["resultHash"] = self._hash_document(invalid, "resultHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], invalid, "coverage-invocation-hash-invalid", ("obligations", 0, "invocationEvidence", "invocationHash"),
            diff_signal_set=diff, test_strategy=strategy,
        )

        invalid = self._coverage(diff, strategy)
        invalid["obligations"][0]["resultEvidence"]["resultHash"] = self.HASH_A
        invalid["resultHash"] = self._hash_document(invalid, "resultHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], invalid, "coverage-execution-result-hash-invalid", ("obligations", 0, "resultEvidence", "resultHash"),
            diff_signal_set=diff, test_strategy=strategy,
        )

    def test_coverage_execution_result_binds_invocation_time_and_success(self):
        diff = self._diff()
        strategy = self._strategy(diff)

        invalid = self._coverage(diff, strategy)
        result = invalid["obligations"][0]["resultEvidence"]
        result["invocationHash"] = self.HASH_A
        result["resultHash"] = self._hash_document(result, "resultHash")
        invalid["resultHash"] = self._hash_document(invalid, "resultHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], invalid, "coverage-result-invocation-mismatch", ("obligations", 0, "resultEvidence", "invocationHash"),
            diff_signal_set=diff, test_strategy=strategy,
        )

        invalid = self._coverage(diff, strategy)
        invocation = invalid["obligations"][0]["invocationEvidence"]
        invocation["inputHash"] = self.HASH_A
        invocation["invocationHash"] = self._hash_document(invocation, "invocationHash")
        result = invalid["obligations"][0]["resultEvidence"]
        result["invocationHash"] = invocation["invocationHash"]
        result["resultHash"] = self._hash_document(result, "resultHash")
        invalid["resultHash"] = self._hash_document(invalid, "resultHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], invalid, "coverage-invocation-input-mismatch", ("obligations", 0, "invocationEvidence", "inputHash"),
            diff_signal_set=diff, test_strategy=strategy,
        )

        invalid = self._coverage(diff, strategy)
        result = invalid["obligations"][0]["resultEvidence"]
        result["completedAt"] = "2026-08-09T01:05:29Z"
        result["resultHash"] = self._hash_document(result, "resultHash")
        invalid["resultHash"] = self._hash_document(invalid, "resultHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], invalid, "coverage-result-time-invalid", ("obligations", 0, "resultEvidence", "completedAt"),
            diff_signal_set=diff, test_strategy=strategy,
        )

        invalid = self._coverage(diff, strategy)
        result = invalid["obligations"][0]["resultEvidence"]
        result["exitCode"] = 1
        result["resultHash"] = self._hash_document(result, "resultHash")
        invalid["resultHash"] = self._hash_document(invalid, "resultHash")
        self._assert_contract_error(
            self.SCHEMA_NAMES[4], invalid, "coverage-result-exit-unsuccessful", ("obligations", 0, "resultEvidence", "exitCode"),
            diff_signal_set=diff, test_strategy=strategy,
        )

    def test_coverage_nonfulfilled_rejects_execution_evidence(self):
        diff = self._diff()
        strategy = self._strategy(diff)
        for status in ("unverified", "blocked"):
            invalid = self._coverage(diff, strategy, status=status)
            invocation = self._invocation_evidence()
            invalid["obligations"][0]["invocationEvidence"] = invocation
            invalid["obligations"][0]["resultEvidence"] = self._result_evidence(invocation)
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
        duplicate.pop("invocationEvidence")
        duplicate.pop("resultEvidence")
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
            self.SCHEMA_NAMES[4], coverage, "coverage-strategy-binding-mismatch", ("planHash",),
            test_strategy=strategy,
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
