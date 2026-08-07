import copy
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import traceback
from types import MappingProxyType
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VALID_FIXTURE = REPOSITORY_ROOT / "tests/fixtures/evidence/valid.json"
STALE_FIXTURE = REPOSITORY_ROOT / "tests/fixtures/evidence/stale.json"
RESULT_CONTENT = {
    "files": [{"path": "src/example.py", "sha256": "d" * 64}]
}
BASE_MANIFEST = {"src/example.py": "old content\n"}
FINAL_MANIFEST = {"src/example.py": "new content\n"}
NOW = datetime(2026, 8, 8, 8, 30, tzinfo=timezone.utc)


def _file_hash(content):
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _policy(**overrides):
    from selfworkflow.evidence import CompletionPolicy
    from selfworkflow.model import Complexity, Risk

    values = {
        "task_kind": "modification",
        "complexity": Complexity.C1,
        "risk": Risk.R1,
        "required_capabilities": ("filesystem-write",),
        "required_criterion_ids": ("criterion-tests",),
        "required_verification_ids": ("unit-tests",),
        "implementation_actor": "implementer",
        "implementation_context": "task-3",
    }
    return CompletionPolicy(**(values | overrides))


def _put_artifact(store, artifact):
    from selfworkflow.evidence import canonical_content_hash

    artifact_hash = canonical_content_hash(artifact)
    store[artifact_hash] = artifact
    return artifact_hash


def _trusted_artifact_store(records):
    from selfworkflow.evidence import ArtifactCollector
    from selfworkflow.model import CapabilityState

    collector = ArtifactCollector()
    for artifact in records.values():
        attributes = artifact["attributes"]
        if artifact["kind"] == "capability":
            collector.record_capability(
                name=attributes["name"],
                state=CapabilityState(attributes["state"]),
                policy_hash=attributes["policyHash"],
                actor_id=artifact["actorId"],
                context_id=artifact["contextId"],
                recorded_at=artifact["recordedAt"],
            )
        elif artifact["kind"] == "review":
            collector.record_attestation(
                kind="review",
                subject_id=artifact["subjectId"],
                subject_hash=artifact["subjectHash"],
                actor_id=artifact["actorId"],
                context_id=artifact["contextId"],
                recorded_at=artifact["recordedAt"],
                provider=attributes["provider"],
                receipt_id=attributes["receiptId"],
                input_hash=attributes["inputHash"],
                output_hash=attributes["outputHash"],
                decision=attributes["decision"],
                level=attributes["level"],
                implementation_actor=attributes["implementationActor"],
                implementation_context=attributes["implementationContext"],
            )
        elif artifact["kind"] == "verification":
            collector.record_execution(
                kind="verification",
                status=artifact["status"],
                subject_id=artifact["subjectId"],
                subject_hash=artifact["subjectHash"],
                actor_id=artifact["actorId"],
                context_id=artifact["contextId"],
                related_ids=tuple(artifact["relatedIds"]),
                recorded_at=artifact["recordedAt"],
                provider=attributes["provider"],
                receipt_id=attributes["receiptId"],
                input_hash=attributes["inputHash"],
                output_hash=attributes["outputHash"],
                check_type=attributes["checkType"],
                command_type=attributes["commandType"],
                exit_code=attributes["exitCode"],
                verification_id=attributes["verificationId"],
                valid_for_seconds=attributes["validForSeconds"],
            )
        else:
            raise AssertionError("unexpected test artifact kind")
    return collector.seal()


def _replace_artifact(case, record, mutate):
    old_hash = record["artifactHash"]
    artifact = copy.deepcopy(case["artifacts"].pop(old_hash))
    mutate(artifact)
    record["artifactHash"] = _put_artifact(case["artifacts"], artifact)
    return artifact


def _case(*, policy=None, review_level=None, stale=False):
    from selfworkflow.evidence import canonical_content_hash

    governing_policy = policy or _policy()
    fixture = STALE_FIXTURE if stale else VALID_FIXTURE
    evidence = json.loads(fixture.read_text(encoding="utf-8"))
    result_hash = canonical_content_hash(RESULT_CONTENT)
    base_hashes = {path: _file_hash(content) for path, content in BASE_MANIFEST.items()}
    final_hashes = {
        path: _file_hash(content) for path, content in FINAL_MANIFEST.items()
    }
    evidence["classification"] = {
        "taskKind": governing_policy.task_kind,
        "complexity": governing_policy.complexity.value,
        "risk": governing_policy.risk.value,
        "policyHash": governing_policy.policy_hash,
    }
    evidence["changes"].update(
        {
            "taskKind": governing_policy.task_kind,
            "resultContentHash": result_hash,
            "baseManifestHash": canonical_content_hash(base_hashes),
            "finalManifestHash": canonical_content_hash(final_hashes),
            "items": [
                {
                    "path": "src/example.py",
                    "operation": "modified",
                    "contentHash": final_hashes["src/example.py"],
                }
            ],
        }
    )
    artifacts = {}
    capabilities = []
    for name in governing_policy.required_capabilities:
        artifact = {
            "kind": "capability",
            "status": "passed",
            "subjectId": name,
            "subjectHash": governing_policy.policy_hash,
            "actorId": "capability-probe",
            "contextId": "task-3",
            "relatedIds": [],
            "recordedAt": "2026-08-08T08:00:00Z",
            "attributes": {
                "name": name,
                "state": "supported",
                "policyHash": governing_policy.policy_hash,
            },
        }
        capabilities.append(
            {
                "name": name,
                "state": "supported",
                "artifactHash": _put_artifact(artifacts, artifact),
            }
        )
    evidence["capabilities"] = capabilities

    criteria = [
        {
            "id": criterion_id,
            "description": "Task tests pass.",
            "applicability": "applicable",
            "reason": "",
            "verificationIds": list(governing_policy.required_verification_ids),
        }
        for criterion_id in governing_policy.required_criterion_ids
    ]
    evidence["acceptanceCriteria"] = criteria
    completion_subject = canonical_content_hash(
        {
            "policyHash": governing_policy.policy_hash,
            "baseManifestHash": evidence["changes"]["baseManifestHash"],
            "finalManifestHash": evidence["changes"]["finalManifestHash"],
            "derivedChanges": evidence["changes"]["items"],
            "acceptanceGraph": criteria,
            "resultContentHash": result_hash,
        }
    )

    level = review_level
    if level is None:
        highest = max(
            int(governing_policy.complexity.value[1]),
            int(governing_policy.risk.value[1]),
        )
        level = "L2" if highest >= 2 else "L0"
    review_artifact = {
        "kind": "review",
        "status": "passed",
        "subjectId": "completion-review",
        "subjectHash": completion_subject,
        "actorId": "reviewer",
        "contextId": "review-task-3",
        "relatedIds": [],
        "recordedAt": "2026-08-08T08:00:00Z",
        "attributes": {
            "provider": "test-review-provider",
            "receiptId": "review-receipt-1",
            "inputHash": completion_subject,
            "outputHash": canonical_content_hash(
                {"decision": "passed", "level": level}
            ),
            "decision": "passed",
            "level": level,
            "implementationActor": governing_policy.implementation_actor,
            "implementationContext": governing_policy.implementation_context,
        },
    }
    evidence["review"] = {
        "id": "completion-review",
        "status": "passed",
        "level": level,
        "artifactHash": _put_artifact(artifacts, review_artifact),
        "reason": "",
    }

    verifications = []
    recorded_at = "2026-08-08T06:00:00Z" if stale else "2026-08-08T08:00:00Z"
    for verification_id in governing_policy.required_verification_ids:
        artifact = {
            "kind": "verification",
            "status": "passed",
            "subjectId": verification_id,
            "subjectHash": completion_subject,
            "actorId": "test-runner",
            "contextId": "test-task-3",
            "relatedIds": list(governing_policy.required_criterion_ids),
            "recordedAt": recorded_at,
            "attributes": {
                "provider": "test-execution-provider",
                "receiptId": f"execution-{verification_id}",
                "inputHash": completion_subject,
                "outputHash": canonical_content_hash(
                    {"status": "passed", "verificationId": verification_id}
                ),
                "checkType": "unit-test",
                "commandType": "python-module",
                "exitCode": 0,
                "verificationId": verification_id,
                "validForSeconds": 3600,
            },
        }
        verifications.append(
            {
                "id": verification_id,
                "status": "passed",
                "artifactHash": _put_artifact(artifacts, artifact),
                "verifiedAt": recorded_at,
                "validForSeconds": 3600,
                "reason": "",
            }
        )
    evidence["verification"] = verifications
    return {
        "policy": governing_policy,
        "evidence": evidence,
        "artifacts": artifacts,
        "base": dict(BASE_MANIFEST),
        "final": dict(FINAL_MANIFEST),
        "result": RESULT_CONTENT,
    }


def _rebind_completion_receipts(case):
    from selfworkflow.evidence import canonical_content_hash

    evidence = case["evidence"]
    subject_hash = canonical_content_hash(
        {
            "policyHash": evidence["classification"]["policyHash"],
            "baseManifestHash": evidence["changes"]["baseManifestHash"],
            "finalManifestHash": evidence["changes"]["finalManifestHash"],
            "derivedChanges": evidence["changes"]["items"],
            "acceptanceGraph": evidence["acceptanceCriteria"],
            "resultContentHash": evidence["changes"]["resultContentHash"],
        }
    )
    records = (evidence["review"], *evidence["verification"])
    for record in records:
        if record["artifactHash"] is None:
            continue
        _replace_artifact(
            case,
            record,
            lambda artifact: (
                artifact.update({"subjectHash": subject_hash}),
                artifact["attributes"].update({"inputHash": subject_hash}),
            ),
        )


def _evaluate(case, **overrides):
    from selfworkflow.evidence import evaluate_completion

    arguments = {
        "artifact_store": _trusted_artifact_store(case["artifacts"]),
        "base_manifest": case["base"],
        "final_manifest": case["final"],
        "now": NOW,
    }
    return evaluate_completion(
        case["policy"],
        case["evidence"],
        case["result"],
        **(arguments | overrides),
    )


class CompletionPolicyTests(unittest.TestCase):
    def test_policy_is_typed_ordered_and_deeply_immutable(self):
        from selfworkflow.evidence import CompletionPolicy, WorkflowEvidenceError
        from selfworkflow.model import Complexity, Risk

        policy = _policy(
            required_capabilities=("filesystem-read", "filesystem-write")
        )
        self.assertEqual(
            policy.required_capabilities,
            ("filesystem-read", "filesystem-write"),
        )
        self.assertRegex(policy.policy_hash, r"^sha256:[0-9a-f]{64}$")
        with self.assertRaises(FrozenInstanceError):
            policy.task_kind = "read-only"

        class Text(str):
            pass

        invalid = (
            {"required_capabilities": ["filesystem-read"]},
            {"required_capabilities": (Text("filesystem-read"),)},
            {"required_capabilities": ("filesystem-read", "filesystem-read")},
            {"complexity": "C1"},
            {"risk": "R1"},
        )
        for override in invalid:
            with self.subTest(override=tuple(override)):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    _policy(**override)
                self.assertEqual(caught.exception.code, "completion-policy-invalid")

        for complexity, risk in (
            (Complexity.C0, Risk.R1),
            (Complexity.C1, Risk.R0),
        ):
            with self.subTest(complexity=complexity, risk=risk):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    _policy(complexity=complexity, risk=risk)
                self.assertEqual(caught.exception.code, "completion-policy-invalid")

    def test_fixture_has_exact_nine_fields_and_parses_deeply_immutable(self):
        from selfworkflow.evidence import parse_evidence_json

        expected = {
            "classification",
            "capabilities",
            "selectedSkills",
            "acceptanceCriteria",
            "changes",
            "review",
            "verification",
            "skipped",
            "residualRisks",
        }
        parsed = parse_evidence_json(VALID_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(set(parsed), expected)
        self.assertIs(type(parsed), type(MappingProxyType({})))
        with self.assertRaises(TypeError):
            parsed["classification"]["risk"] = "R3"
        self.assertEqual(_case()["evidence"], json.loads(VALID_FIXTURE.read_text()))


class CompletionGateTests(unittest.TestCase):
    def test_l1_fallback_requires_trusted_unavailable_prompted_authorization(self):
        from selfworkflow.evidence import (
            ReviewFallbackAuthorization,
            WorkflowEvidenceError,
        )
        from selfworkflow.model import CapabilityState, Complexity, Risk

        authorization = ReviewFallbackAuthorization(
            capability_name="independent-review-context",
            capability_state=CapabilityState.UNSUPPORTED,
            user_prompted=True,
            user_authorized=True,
            authorization_id="user-authorization-1",
        )
        policy = _policy(
            complexity=Complexity.C2,
            risk=Risk.R2,
            review_fallback=authorization,
        )
        self.assertEqual(
            _evaluate(_case(policy=policy, review_level="L1")).code,
            "completion-eligible",
        )
        self.assertEqual(
            _evaluate(_case(policy=policy, review_level="L0")).code,
            "review-level-insufficient",
        )
        level_three = _policy(
            complexity=Complexity.C3,
            risk=Risk.R3,
            review_fallback=authorization,
        )
        self.assertEqual(
            _evaluate(_case(policy=level_three, review_level="L1")).code,
            "review-level-insufficient",
        )
        self.assertEqual(
            _evaluate(
                _case(
                    policy=_policy(complexity=Complexity.C2, risk=Risk.R2),
                    review_level="L1",
                )
            ).code,
            "review-level-insufficient",
        )

        invalid = (
            {"capability_state": CapabilityState.SUPPORTED},
            {"capability_state": "unsupported"},
            {"user_prompted": 1},
            {"user_authorized": False},
        )
        values = {
            "capability_name": "independent-review-context",
            "capability_state": CapabilityState.UNSUPPORTED,
            "user_prompted": True,
            "user_authorized": True,
            "authorization_id": "user-authorization-1",
        }
        for override in invalid:
            with self.subTest(override=override):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    ReviewFallbackAuthorization(**(values | override))
                self.assertEqual(
                    caught.exception.code,
                    "review-fallback-authorization-invalid",
                )

    def test_fresh_fully_bound_modification_is_eligible(self):
        decision = _evaluate(_case())
        self.assertTrue(decision.eligible)
        self.assertEqual(decision.code, "completion-eligible")

    def test_capability_set_and_state_are_exactly_policy_governed(self):
        attacks = []
        missing = _case()
        missing["evidence"]["capabilities"] = []
        attacks.append((missing, "required-capability-missing"))

        reordered = _case(
            policy=_policy(
                required_capabilities=("filesystem-read", "filesystem-write")
            )
        )
        reordered["evidence"]["capabilities"].reverse()
        attacks.append((reordered, "capability-set-mismatch"))

        for state, code in (
            ("unsupported", "required-capability-unsupported"),
            ("unverified", "required-capability-unverified"),
        ):
            case = _case()
            record = case["evidence"]["capabilities"][0]
            record["state"] = state
            _replace_artifact(
                case,
                record,
                lambda artifact, value=state: artifact["attributes"].update(
                    {"state": value}
                ),
            )
            attacks.append((case, code))

        for case, code in attacks:
            with self.subTest(code=code):
                decision = _evaluate(case)
                self.assertFalse(decision.eligible)
                self.assertEqual(decision.code, code)

    def test_policy_classification_and_review_matrix_cannot_be_self_declared(self):
        mismatch = _case()
        mismatch["evidence"]["classification"]["risk"] = "R2"
        self.assertEqual(_evaluate(mismatch).code, "completion-policy-mismatch")

        from selfworkflow.model import Complexity, Risk

        for complexity, risk, level in (
            (Complexity.C2, Risk.R1, "L1"),
            (Complexity.C1, Risk.R2, "L1"),
            (Complexity.C3, Risk.R3, "L0"),
        ):
            case = _case(
                policy=_policy(complexity=complexity, risk=risk),
                review_level=level,
            )
            with self.subTest(complexity=complexity, risk=risk, level=level):
                decision = _evaluate(case)
                self.assertFalse(decision.eligible)
                self.assertEqual(decision.code, "review-level-insufficient")

        l0 = _case(review_level="L0")
        self.assertEqual(_evaluate(l0).code, "completion-eligible")

    def test_l2_review_requires_actor_and_context_isolation(self):
        from selfworkflow.model import Complexity, Risk

        for field, value in (
            ("actorId", "implementer"),
            ("contextId", "task-3"),
        ):
            case = _case(
                policy=_policy(complexity=Complexity.C2, risk=Risk.R2)
            )
            _replace_artifact(
                case,
                case["evidence"]["review"],
                lambda artifact, key=field, replacement=value: artifact.update(
                    {key: replacement}
                ),
            )
            with self.subTest(field=field):
                self.assertEqual(
                    _evaluate(case).code,
                    "review-independence-required",
                )


class ArtifactAndManifestTests(unittest.TestCase):
    def test_collector_receipts_require_exact_typed_audit_fields(self):
        from selfworkflow.evidence import (
            ArtifactCollector,
            WorkflowEvidenceError,
            canonical_content_hash,
        )

        class Text(str):
            pass

        subject = canonical_content_hash({"subject": "completion"})
        common = {
            "subject_id": "completion-review",
            "subject_hash": subject,
            "actor_id": "reviewer",
            "context_id": "review-context",
            "recorded_at": "2026-08-08T08:00:00Z",
            "provider": "review-provider",
            "receipt_id": "receipt-1",
            "input_hash": subject,
            "output_hash": canonical_content_hash({"decision": "passed"}),
        }
        attacks = (
            lambda collector: collector.record_attestation(
                kind="review",
                decision=Text("passed"),
                level="L2",
                implementation_actor="implementer",
                implementation_context="implementation-context",
                **common,
            ),
            lambda collector: collector.record_execution(
                kind="verification",
                status="passed",
                subject_id="unit-tests",
                subject_hash=subject,
                actor_id="runner",
                context_id="verification-context",
                related_ids=("criterion-tests",),
                recorded_at="2026-08-08T08:00:00Z",
                provider="execution-provider",
                receipt_id="receipt-2",
                input_hash=subject,
                output_hash=canonical_content_hash({"status": "passed"}),
                check_type=Text("unit-test"),
                command_type="python-module",
                exit_code=0,
                verification_id="unit-tests",
                valid_for_seconds=3600,
            ),
            lambda collector: collector.record_attestation(
                kind="owner-confirmation",
                subject_id="protected-rules-change",
                subject_hash=subject,
                actor_id="owner",
                context_id="owner-context",
                recorded_at="2026-08-08T08:00:00Z",
                provider="owner-provider",
                receipt_id="receipt-3",
                input_hash=subject,
                output_hash=canonical_content_hash({"decision": "authorized"}),
                decision="authorized",
                scope=Text("replace-protected-rules"),
            ),
        )
        for attack in attacks:
            with self.subTest(attack=attack):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    attack(ArtifactCollector())
                self.assertEqual(caught.exception.code, "artifact-collector-invalid")

    def test_completion_subject_blocks_manifest_and_acceptance_graph_replay(self):
        from selfworkflow.evidence import canonical_content_hash

        manifest_replay = _case()
        manifest_replay["final"]["src/example.py"] = "replayed content\n"
        final_hash = _file_hash("replayed content\n")
        manifest_replay["evidence"]["changes"]["finalManifestHash"] = (
            canonical_content_hash({"src/example.py": final_hash})
        )
        manifest_replay["evidence"]["changes"]["items"][0]["contentHash"] = final_hash

        graph_replay = _case()
        graph_replay["evidence"]["acceptanceCriteria"][0]["description"] = (
            "A materially different acceptance requirement."
        )

        for label, case in (
            ("manifest", manifest_replay),
            ("acceptance-graph", graph_replay),
        ):
            with self.subTest(label=label):
                decision = _evaluate(case)
                self.assertFalse(decision.eligible)
                self.assertEqual(decision.code, "artifact-binding-mismatch")

    def test_public_gate_requires_collector_sealed_trusted_store(self):
        from selfworkflow.evidence import TrustedArtifactStore, WorkflowEvidenceError

        case = _case()
        with self.assertRaises(WorkflowEvidenceError) as caught:
            _evaluate(case, artifact_store=case["artifacts"])
        self.assertEqual(caught.exception.code, "trusted-artifact-store-required")

        with self.assertRaises(WorkflowEvidenceError) as caught:
            TrustedArtifactStore()
        self.assertEqual(
            caught.exception.code,
            "trusted-artifact-store-construction-denied",
        )

        manually_allocated = object.__new__(TrustedArtifactStore)
        with self.assertRaises(WorkflowEvidenceError) as caught:
            _evaluate(case, artifact_store=manually_allocated)
        self.assertEqual(caught.exception.code, "trusted-artifact-store-required")
        self.assertTrue(_evaluate(case).eligible)

    def test_every_reference_resolves_and_recomputes_without_zero_special_case(self):
        unresolved = _case()
        old = unresolved["evidence"]["capabilities"][0]["artifactHash"]
        del unresolved["artifacts"][old]
        unresolved["evidence"]["capabilities"][0]["artifactHash"] = (
            "sha256:" + "0" * 64
        )
        self.assertEqual(_evaluate(unresolved).code, "artifact-unresolved")

        mismatch = _case()
        reference = mismatch["evidence"]["review"]["artifactHash"]
        mismatch["artifacts"][reference]["actorId"] = "different-reviewer"
        self.assertEqual(_evaluate(mismatch).code, "artifact-unresolved")

    def test_manifest_derivation_rejects_nonexistent_or_fake_changes(self):
        for mutation in (
            lambda item: item.update({"path": "src/missing.py"}),
            lambda item: item.update({"contentHash": "sha256:" + "0" * 64}),
        ):
            case = _case()
            mutation(case["evidence"]["changes"]["items"][0])
            with self.subTest(item=case["evidence"]["changes"]["items"][0]):
                self.assertEqual(
                    _evaluate(case).code,
                    "changes-manifest-mismatch",
                )

        case = _case()
        case["base"] = {
            "deleted.txt": "gone",
            "src/example.py": "old content\n",
        }
        case["final"] = {
            "added.txt": "new",
            "src/example.py": "new content\n",
        }
        from selfworkflow.evidence import canonical_content_hash

        base_hashes = {key: _file_hash(value) for key, value in case["base"].items()}
        final_hashes = {key: _file_hash(value) for key, value in case["final"].items()}
        case["evidence"]["changes"].update(
            {
                "baseManifestHash": canonical_content_hash(base_hashes),
                "finalManifestHash": canonical_content_hash(final_hashes),
                "items": [
                    {
                        "path": "added.txt",
                        "operation": "added",
                        "contentHash": final_hashes["added.txt"],
                    },
                    {
                        "path": "deleted.txt",
                        "operation": "deleted",
                        "contentHash": base_hashes["deleted.txt"],
                    },
                    {
                        "path": "src/example.py",
                        "operation": "modified",
                        "contentHash": final_hashes["src/example.py"],
                    },
                ],
            }
        )
        _rebind_completion_receipts(case)
        self.assertTrue(_evaluate(case).eligible)

    def test_criterion_verification_links_are_bidirectional(self):
        case = _case()
        _replace_artifact(
            case,
            case["evidence"]["verification"][0],
            lambda artifact: artifact.update({"relatedIds": []}),
        )
        self.assertEqual(
            _evaluate(case).code,
            "acceptance-criterion-unverified",
        )

    def test_required_review_verification_or_criterion_cannot_be_skipped(self):
        for target_type, target_id in (
            ("review", "completion-review"),
            ("verification", "unit-tests"),
            ("criterion", "criterion-tests"),
        ):
            case = _case()
            case["evidence"]["skipped"] = [
                {
                    "targetType": target_type,
                    "targetId": target_id,
                    "applicability": "optional",
                    "reason": "Unavailable in this context.",
                }
            ]
            with self.subTest(target_type=target_type):
                self.assertEqual(_evaluate(case).code, "required-item-skipped")

        optional = _case()
        optional["evidence"]["skipped"] = [
            {
                "targetType": "skill",
                "targetId": "optional-lint",
                "applicability": "optional",
                "reason": "Not selected by the governing policy.",
            }
        ]
        self.assertTrue(_evaluate(optional).eligible)

    def test_duplicate_artifact_identities_and_hostile_stores_are_redacted(self):
        from selfworkflow.evidence import WorkflowEvidenceError

        duplicate = _case()
        artifact = copy.deepcopy(next(iter(duplicate["artifacts"].values())))
        artifact["recordedAt"] = "2026-08-08T08:00:01Z"
        _put_artifact(duplicate["artifacts"], artifact)
        with self.assertRaises(WorkflowEvidenceError) as caught:
            _evaluate(duplicate)
        self.assertEqual(caught.exception.code, "artifact-collector-invalid")

        secret = "HOSTILE-STORE-SECRET"

        class HostileStore(dict):
            def items(self):
                raise RuntimeError(secret)

        case = _case()
        with self.assertRaises(WorkflowEvidenceError) as caught:
            _evaluate(case, artifact_store=HostileStore(case["artifacts"]))
        self.assertEqual(caught.exception.code, "trusted-artifact-store-required")
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertNotIn(secret, "".join(traceback.format_exception(caught.exception)))


class VerificationTests(unittest.TestCase):
    def test_nonpassing_stale_and_mismatched_verification_cannot_complete(self):
        for status, code in (
            ("failed", "verification-failed"),
            ("not-run", "verification-not-run"),
            ("partial", "verification-partial"),
            ("not-applicable", "verification-not-applicable-for-modification"),
        ):
            case = _case()
            record = case["evidence"]["verification"][0]
            record.update({"status": status, "reason": "Verification did not pass."})
            def set_status(artifact, value=status):
                artifact["status"] = value
                artifact["attributes"]["exitCode"] = (
                    1 if value == "failed" else None
                )

            _replace_artifact(case, record, set_status)
            with self.subTest(status=status):
                self.assertEqual(_evaluate(case).code, code)

        self.assertEqual(_evaluate(_case(stale=True)).code, "verification-stale")

        result_mismatch = _case()
        result_mismatch["evidence"]["changes"]["resultContentHash"] = (
            "sha256:" + "0" * 64
        )
        self.assertEqual(
            _evaluate(result_mismatch).code,
            "result-content-hash-mismatch",
        )

        verification_mismatch = _case()
        _replace_artifact(
            verification_mismatch,
            verification_mismatch["evidence"]["verification"][0],
            lambda artifact: (
                artifact.update({"subjectHash": "sha256:" + "0" * 64}),
                artifact["attributes"].update(
                    {"inputHash": "sha256:" + "0" * 64}
                ),
            ),
        )
        self.assertEqual(
            _evaluate(verification_mismatch).code,
            "verification-content-hash-mismatch",
        )

    def test_time_is_aware_monotonic_and_bound_to_artifact(self):
        from selfworkflow.evidence import WorkflowEvidenceError

        case = _case()
        with self.assertRaises(WorkflowEvidenceError) as caught:
            _evaluate(case, now=datetime(2026, 8, 8, 8, 30))
        self.assertEqual(caught.exception.code, "evidence-time-invalid")

        rollback = _evaluate(
            _case(),
            previous_observed_at=datetime(
                2026, 8, 8, 8, 31, tzinfo=timezone.utc
            ),
        )
        self.assertEqual(rollback.code, "clock-rollback-detected")

        future = _case()
        record = future["evidence"]["verification"][0]
        record["verifiedAt"] = "2026-08-08T09:00:00Z"
        _replace_artifact(
            future,
            record,
            lambda artifact: artifact.update(
                {"recordedAt": "2026-08-08T09:00:00Z"}
            ),
        )
        self.assertEqual(_evaluate(future).code, "verification-time-in-future")

        time_mismatch = _case()
        time_mismatch["evidence"]["verification"][0]["verifiedAt"] = (
            "2026-08-08T08:00:01Z"
        )
        self.assertEqual(_evaluate(time_mismatch).code, "artifact-binding-mismatch")

        window_mismatch = _case()
        window_mismatch["evidence"]["verification"][0]["validForSeconds"] = 7200
        self.assertEqual(
            _evaluate(window_mismatch).code,
            "artifact-binding-mismatch",
        )

    def test_read_only_not_applicable_requires_no_changes_and_real_artifact(self):
        from selfworkflow.model import Complexity, Risk

        policy = _policy(
            task_kind="read-only",
            complexity=Complexity.C0,
            risk=Risk.R0,
            required_capabilities=("filesystem-read",),
        )
        case = _case(policy=policy)
        case["final"] = dict(case["base"])
        from selfworkflow.evidence import canonical_content_hash

        manifest_hashes = {
            path: _file_hash(content) for path, content in case["base"].items()
        }
        case["evidence"]["changes"].update(
            {
                "baseManifestHash": canonical_content_hash(manifest_hashes),
                "finalManifestHash": canonical_content_hash(manifest_hashes),
                "items": [],
            }
        )
        case["artifacts"].pop(case["evidence"]["review"]["artifactHash"])
        case["evidence"]["review"] = {
            "id": "completion-review",
            "status": "not-applicable",
            "level": "not-applicable",
            "artifactHash": None,
            "reason": "The task is pure read-only work.",
        }
        case["evidence"]["acceptanceCriteria"][0].update(
            {
                "applicability": "not-applicable",
                "reason": "No changed result requires a test.",
            }
        )
        verification = case["evidence"]["verification"][0]
        verification.update(
            {
                "status": "not-applicable",
                "reason": "The read-only result has no changed artifact.",
            }
        )
        _replace_artifact(
            case,
            verification,
            lambda artifact: (
                artifact.update({"status": "not-applicable"}),
                artifact["attributes"].update({"exitCode": None}),
            ),
        )
        _rebind_completion_receipts(case)
        self.assertTrue(_evaluate(case).eligible)

        case["final"]["added.txt"] = "change"
        self.assertFalse(_evaluate(case).eligible)


class InputHardeningTests(unittest.TestCase):
    def test_output_types_and_unknown_error_codes_fail_closed(self):
        from selfworkflow.evidence import (
            CompletionDecision,
            MergedRule,
            MergedRules,
            WorkflowEvidenceError,
        )

        constructors = (
            lambda: CompletionDecision(False, "x", "x", "x", "x"),
            lambda: MergedRule("x", "x", "x", "x", "x", "x", False),
            lambda: MergedRules((), "1.0.0"),
        )
        for construct in constructors:
            with self.subTest(construct=construct):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    construct()
                self.assertEqual(caught.exception.code, "output-construction-denied")

        secret = "UNKNOWN-SECRET-CODE"
        error = WorkflowEvidenceError(secret)
        self.assertEqual(error.code, "workflow-error-code-invalid")
        self.assertEqual(error.message, "The workflow error code is invalid.")
        self.assertNotIn(secret, str(error))

    def test_duplicate_json_keys_nan_and_hostile_inputs_are_fixed_and_redacted(self):
        from selfworkflow.evidence import (
            WorkflowEvidenceError,
            canonical_content_hash,
            parse_evidence_json,
        )

        for document in ('{"x":1,"x":2}', '{"x":NaN}', '[1,2]'):
            with self.subTest(document=document):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    parse_evidence_json(document)
                self.assertEqual(caught.exception.code, "evidence-json-invalid")

        with self.assertRaises(WorkflowEvidenceError) as caught:
            canonical_content_hash({"value": float("inf")})
        self.assertEqual(caught.exception.code, "result-content-invalid")

        secret = "HOSTILE-INPUT-SECRET"

        class Hostile(dict):
            def items(self):
                raise RuntimeError(secret)

        with self.assertRaises(WorkflowEvidenceError) as caught:
            canonical_content_hash(Hostile())
        self.assertEqual(caught.exception.code, "result-content-invalid")
        self.assertNotIn(secret, "".join(traceback.format_exception(caught.exception)))

    def test_structure_is_closed_and_empty_claims_cannot_pass(self):
        from selfworkflow.evidence import WorkflowEvidenceError

        malformed = (
            lambda evidence: evidence.update({"extra": "claim"}),
            lambda evidence: evidence.update({"review": "passed"}),
            lambda evidence: evidence["skipped"].append(
                {
                    "targetType": "skill",
                    "targetId": "optional",
                    "applicability": "optional",
                    "reason": "",
                }
            ),
        )
        for mutate in malformed:
            case = _case()
            mutate(case["evidence"])
            with self.subTest(evidence=case["evidence"]):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    _evaluate(case)
                self.assertEqual(caught.exception.code, "evidence-invalid")

        for mutate in (
            lambda evidence: evidence["changes"].update({"items": []}),
            lambda evidence: evidence.update({"verification": []}),
        ):
            case = _case()
            mutate(case["evidence"])
            self.assertFalse(_evaluate(case).eligible)


if __name__ == "__main__":
    unittest.main()
