import copy
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import traceback
import tracemalloc
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


def _verification_invocation(verification_id="unit-tests", **overrides):
    from selfworkflow.evidence import ExecutionInvocation

    values = {
        "executable": "python",
        "module": "unittest",
        "argv": ("-m", "unittest", verification_id),
        "cwd": ".",
        "environment": {"PYTHONPATH": "src"},
        "input_hash": "sha256:" + "0" * 64,
    }
    return ExecutionInvocation(**(values | overrides))


def _invocation_envelope(invocation):
    return dict(invocation.envelope)


def _default_pre_verification_subject(
    *,
    task_nonce="task-3-operation-1",
    required_criterion_ids=("criterion-tests",),
    required_verification_ids=("unit-tests",),
):
    from selfworkflow.evidence import (
        canonical_content_hash,
        pre_verification_subject_hash,
    )

    base_hashes = {path: _file_hash(content) for path, content in BASE_MANIFEST.items()}
    final_hashes = {path: _file_hash(content) for path, content in FINAL_MANIFEST.items()}
    criteria = tuple(
        {
            "id": criterion_id,
            "description": "Task tests pass.",
            "applicability": "applicable",
            "reason": "",
            "verificationIds": required_verification_ids,
        }
        for criterion_id in required_criterion_ids
    )
    return pre_verification_subject_hash(
        task_nonce=task_nonce,
        base_manifest_hash=canonical_content_hash(base_hashes),
        final_manifest_hash=canonical_content_hash(final_hashes),
        derived_changes=(
            {
                "path": "src/example.py",
                "operation": "modified",
                "contentHash": final_hashes["src/example.py"],
            },
        ),
        acceptance_graph=criteria,
        result_content_hash=canonical_content_hash(RESULT_CONTENT),
    )


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
        "task_nonce": "task-3-operation-1",
        "artifact_freshness_seconds": 3600,
    }
    values.update(overrides)
    if "expected_verification_invocations" not in overrides:
        pre_subject = _default_pre_verification_subject(
            task_nonce=values["task_nonce"],
            required_criterion_ids=values["required_criterion_ids"],
            required_verification_ids=values["required_verification_ids"],
        )
        values["expected_verification_invocations"] = tuple(
            (
                verification_id,
                _verification_invocation(
                    verification_id, input_hash=pre_subject
                ).invocation_hash,
            )
            for verification_id in values["required_verification_ids"]
        )
    return CompletionPolicy(**values)


def _put_artifact(store, artifact):
    from selfworkflow.evidence import canonical_content_hash

    artifact_hash = canonical_content_hash(artifact)
    store[artifact_hash] = artifact
    return artifact_hash


def _trusted_artifact_store(records, invocations=None):
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
                provider=attributes["provider"],
                receipt_id=attributes["receiptId"],
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
                output_content={
                    "decision": attributes["decision"],
                    "level": attributes["level"],
                },
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
                invocation=(
                    (invocations or {}).get(attributes["verificationId"])
                    or _verification_invocation(
                        attributes["verificationId"],
                        input_hash=attributes["invocation"]["inputHash"],
                    )
                ),
                output_content={
                    "status": artifact["status"],
                    "verificationId": attributes["verificationId"],
                },
                check_type=attributes["checkType"],
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
    from selfworkflow.evidence import (
        canonical_content_hash,
        pre_verification_subject_hash,
    )

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
                "provider": "test-capability-provider",
                "receiptId": f"capability-{name}",
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
    pre_verification_subject = pre_verification_subject_hash(
        task_nonce=governing_policy.task_nonce,
        base_manifest_hash=evidence["changes"]["baseManifestHash"],
        final_manifest_hash=evidence["changes"]["finalManifestHash"],
        derived_changes=tuple(evidence["changes"]["items"]),
        acceptance_graph=tuple(criteria),
        result_content_hash=result_hash,
    )
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
        invocation = _verification_invocation(
            verification_id, input_hash=pre_verification_subject
        )
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
                "invocation": _invocation_envelope(invocation),
                "invocationHash": invocation.invocation_hash,
                "checkType": "unit-test",
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


def _refresh_policy_and_invocations_for_current_input(case):
    from selfworkflow.evidence import (
        CompletionPolicy,
        pre_verification_subject_hash,
    )

    evidence = case["evidence"]
    old_policy = case["policy"]
    pre_subject = pre_verification_subject_hash(
        task_nonce=old_policy.task_nonce,
        base_manifest_hash=evidence["changes"]["baseManifestHash"],
        final_manifest_hash=evidence["changes"]["finalManifestHash"],
        derived_changes=tuple(evidence["changes"]["items"]),
        acceptance_graph=tuple(evidence["acceptanceCriteria"]),
        result_content_hash=evidence["changes"]["resultContentHash"],
    )
    invocations = {
        verification_id: _verification_invocation(
            verification_id, input_hash=pre_subject
        )
        for verification_id in old_policy.required_verification_ids
    }
    values = {
        field: getattr(old_policy, field)
        for field in old_policy.__dataclass_fields__
    }
    values["expected_verification_invocations"] = tuple(
        (verification_id, invocations[verification_id].invocation_hash)
        for verification_id in old_policy.required_verification_ids
    )
    new_policy = CompletionPolicy(**values)
    case["policy"] = new_policy
    evidence["classification"]["policyHash"] = new_policy.policy_hash

    for capability in evidence["capabilities"]:
        _replace_artifact(
            case,
            capability,
            lambda artifact: (
                artifact.update({"subjectHash": new_policy.policy_hash}),
                artifact["attributes"].update(
                    {"policyHash": new_policy.policy_hash}
                ),
            ),
        )
    for verification in evidence["verification"]:
        invocation = invocations[verification["id"]]
        _replace_artifact(
            case,
            verification,
            lambda artifact, current=invocation: artifact["attributes"].update(
                {
                    "invocation": _invocation_envelope(current),
                    "invocationHash": current.invocation_hash,
                }
            ),
        )
    _rebind_completion_receipts(case)


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
    def test_pre_verification_subject_hash_excludes_policy_and_binds_current_input(self):
        from selfworkflow.evidence import (
            canonical_content_hash,
            pre_verification_subject_hash,
        )

        fields = {
            "task_nonce": "task-nonce",
            "base_manifest_hash": "sha256:" + "1" * 64,
            "final_manifest_hash": "sha256:" + "2" * 64,
            "derived_changes": (
                {
                    "path": "src/example.py",
                    "operation": "modified",
                    "contentHash": "sha256:" + "3" * 64,
                },
            ),
            "acceptance_graph": (
                {
                    "id": "criterion-tests",
                    "description": "Tests pass.",
                    "applicability": "applicable",
                    "reason": "",
                    "verificationIds": ("unit-tests",),
                },
            ),
            "result_content_hash": "sha256:" + "4" * 64,
        }
        expected = canonical_content_hash(
            {
                "taskNonce": fields["task_nonce"],
                "baseManifestHash": fields["base_manifest_hash"],
                "finalManifestHash": fields["final_manifest_hash"],
                "derivedChanges": fields["derived_changes"],
                "acceptanceGraph": fields["acceptance_graph"],
                "resultContentHash": fields["result_content_hash"],
            }
        )
        self.assertEqual(pre_verification_subject_hash(**fields), expected)

    def test_execution_invocation_rejects_noncanonical_external_cwd(self):
        from selfworkflow.evidence import ExecutionInvocation, WorkflowEvidenceError

        for cwd in (
            "C:/outside",
            "/outside",
            "../outside",
            "src/../outside",
            "src\\tests",
            "CON",
            "tools/AUX.txt",
            "tools/segment. ",
        ):
            with self.subTest(cwd=cwd):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    ExecutionInvocation(
                        executable="python",
                        module="unittest",
                        argv=("-m", "unittest"),
                        cwd=cwd,
                        environment={},
                        input_hash="sha256:" + "1" * 64,
                    )
                self.assertEqual(caught.exception.code, "artifact-collector-invalid")

    def test_task_nonce_and_trusted_freshness_block_replay_future_and_stale_receipts(self):
        first_policy = _policy(task_nonce="task-nonce-a")
        first = _case(policy=first_policy)
        self.assertTrue(_evaluate(first).eligible)

        replay_policy = _policy(task_nonce="task-nonce-b")
        replay = dict(first)
        replay["policy"] = replay_policy
        self.assertEqual(_evaluate(replay).code, "completion-policy-mismatch")

        for target, recorded_at, code in (
            ("capabilities", "2026-08-08T09:00:00Z", "capability-time-in-future"),
            ("capabilities", "2026-08-08T06:00:00Z", "capability-stale"),
            ("review", "2026-08-08T09:00:00Z", "review-time-in-future"),
            ("review", "2026-08-08T06:00:00Z", "review-stale"),
        ):
            case = _case()
            record = (
                case["evidence"][target][0]
                if target == "capabilities"
                else case["evidence"][target]
            )
            _replace_artifact(
                case,
                record,
                lambda artifact, value=recorded_at: artifact.update(
                    {"recordedAt": value}
                ),
            )
            with self.subTest(target=target):
                self.assertEqual(_evaluate(case).code, code)

    def test_policy_requires_the_exact_expected_verification_invocation(self):
        expected = _verification_invocation(
            input_hash=_default_pre_verification_subject()
        )
        policy = _policy(
            expected_verification_invocations=(
                ("unit-tests", expected.invocation_hash),
            )
        )
        self.assertTrue(_evaluate(_case(policy=policy)).eligible)

        no_op = _verification_invocation(
            executable="python",
            module=None,
            argv=("-c", "pass"),
            input_hash=_default_pre_verification_subject(),
        )
        wrong_policy = _policy(
            expected_verification_invocations=(
                ("unit-tests", no_op.invocation_hash),
            )
        )
        self.assertEqual(
            _evaluate(_case(policy=wrong_policy)).code,
            "verification-invocation-mismatch",
        )

        for label, actual in (
            (
                "wrong-command",
                _verification_invocation(
                    executable="pytest",
                    module=None,
                    argv=("tests/unit",),
                    input_hash=_default_pre_verification_subject(),
                ),
            ),
            ("no-op", no_op),
        ):
            case = _case()
            record = case["evidence"]["verification"][0]
            _replace_artifact(
                case,
                record,
                lambda artifact, invocation=actual: artifact["attributes"].update(
                    {
                        "invocation": _invocation_envelope(invocation),
                        "invocationHash": invocation.invocation_hash,
                    }
                ),
            )
            store = _trusted_artifact_store(
                case["artifacts"], {"unit-tests": actual}
            )
            with self.subTest(label=label):
                self.assertEqual(
                    _evaluate(case, artifact_store=store).code,
                    "verification-invocation-mismatch",
                )

    def test_execution_invocation_is_frozen_and_hashes_actual_inputs(self):
        from selfworkflow.evidence import ExecutionInvocation

        environment = {"PYTHONPATH": "src", "MODE": "test"}
        invocation = ExecutionInvocation(
            executable="python",
            module="unittest",
            argv=("-m", "unittest", "tests.unit"),
            cwd=".",
            environment=environment,
            input_hash="sha256:" + "1" * 64,
        )
        environment["MODE"] = "changed-after-construction"

        self.assertEqual(invocation.environment_keys, ("MODE", "PYTHONPATH"))
        self.assertRegex(invocation.environment_hash, r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(invocation.input_hash, r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(invocation.invocation_hash, r"^sha256:[0-9a-f]{64}$")
        self.assertNotEqual(
            invocation.invocation_hash,
            ExecutionInvocation(
                executable="python",
                module="unittest",
                argv=("-m", "unittest", "tests.unit"),
                cwd=".",
                environment={"PYTHONPATH": "src", "MODE": "test"},
                input_hash="sha256:" + "2" * 64,
            ).invocation_hash,
        )
        with self.assertRaises(FrozenInstanceError):
            invocation.cwd = "other"

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
    def test_l1_fallback_rejects_same_actor_and_implementation_context(self):
        from selfworkflow.evidence import ReviewFallbackAuthorization
        from selfworkflow.model import CapabilityState, Complexity, Risk

        policy = _policy(
            complexity=Complexity.C2,
            risk=Risk.R2,
            review_fallback=ReviewFallbackAuthorization(
                capability_name="independent-context",
                capability_state=CapabilityState.UNSUPPORTED,
                user_prompted=True,
                user_authorized=True,
                authorization_id="user-authorization-1",
            ),
        )
        case = _case(policy=policy, review_level="L1")
        _replace_artifact(
            case,
            case["evidence"]["review"],
            lambda artifact: artifact.update(
                {
                    "actorId": policy.implementation_actor,
                    "contextId": policy.implementation_context,
                }
            ),
        )
        self.assertEqual(_evaluate(case).code, "review-independence-required")

    def test_l1_fallback_allows_same_actor_in_new_context(self):
        from selfworkflow.evidence import ReviewFallbackAuthorization
        from selfworkflow.model import CapabilityState, Complexity, Risk

        policy = _policy(
            complexity=Complexity.C2,
            risk=Risk.R2,
            review_fallback=ReviewFallbackAuthorization(
                capability_name="independent-context",
                capability_state=CapabilityState.UNSUPPORTED,
                user_prompted=True,
                user_authorized=True,
                authorization_id="user-authorization-1",
            ),
        )
        case = _case(policy=policy, review_level="L1")
        _replace_artifact(
            case,
            case["evidence"]["review"],
            lambda artifact: artifact.update(
                {
                    "actorId": policy.implementation_actor,
                    "contextId": "fallback-review-context",
                }
            ),
        )
        self.assertEqual(_evaluate(case).code, "completion-eligible")

    def test_l1_fallback_requires_trusted_unavailable_prompted_authorization(self):
        from selfworkflow.evidence import (
            ReviewFallbackAuthorization,
            WorkflowEvidenceError,
        )
        from selfworkflow.model import CapabilityState, Complexity, Risk

        authorization = ReviewFallbackAuthorization(
            capability_name="independent-context",
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
            "capability_name": "independent-context",
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
    def test_public_gate_recomputes_invocation_envelope_hash(self):
        from selfworkflow.evidence import (
            TrustedArtifactStore,
            WorkflowEvidenceError,
            canonical_content_hash,
        )

        def thaw(value):
            if type(value) is type(MappingProxyType({})):
                return {key: thaw(item) for key, item in value.items()}
            if type(value) is tuple:
                return [thaw(item) for item in value]
            return value

        for label, mutate in (
            (
                "envelope",
                lambda attributes: attributes["invocation"].update(
                    {"executable": "different-runner"}
                ),
            ),
            (
                "hash",
                lambda attributes: attributes.update(
                    {"invocationHash": "sha256:" + "0" * 64}
                ),
            ),
        ):
            case = _case()
            valid_store = _trusted_artifact_store(case["artifacts"])
            old_reference = case["evidence"]["verification"][0]["artifactHash"]
            records = {
                reference: thaw(artifact)
                for reference, artifact in valid_store._records.items()
            }
            artifact = records.pop(old_reference)
            mutate(artifact["attributes"])
            new_reference = canonical_content_hash(artifact)
            records[new_reference] = artifact
            case["evidence"]["verification"][0]["artifactHash"] = new_reference

            forged_store = object.__new__(TrustedArtifactStore)
            object.__setattr__(forged_store, "_records", MappingProxyType(records))
            object.__setattr__(forged_store, "_seal", valid_store._seal)
            with self.subTest(label=label):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    _evaluate(case, artifact_store=forged_store)
                self.assertEqual(caught.exception.code, "artifact-store-invalid")

    def test_old_invocation_input_cannot_be_replayed_after_final_or_result_changes(self):
        from selfworkflow.evidence import canonical_content_hash

        final_changed = _case()
        final_changed["final"]["src/example.py"] = "different final\n"
        final_hash = _file_hash("different final\n")
        final_changed["evidence"]["changes"].update(
            {
                "finalManifestHash": canonical_content_hash(
                    {"src/example.py": final_hash}
                ),
                "items": [
                    {
                        "path": "src/example.py",
                        "operation": "modified",
                        "contentHash": final_hash,
                    }
                ],
            }
        )
        _rebind_completion_receipts(final_changed)

        result_changed = _case()
        result_changed["result"] = {"files": [], "summary": "different result"}
        result_changed["evidence"]["changes"]["resultContentHash"] = (
            canonical_content_hash(result_changed["result"])
        )
        _rebind_completion_receipts(result_changed)

        for label, case in (("final", final_changed), ("result", result_changed)):
            with self.subTest(label=label):
                self.assertEqual(
                    _evaluate(case).code,
                    "verification-invocation-input-mismatch",
                )

    def test_sealed_execution_receipt_exposes_canonical_invocation_envelope(self):
        case = _case()
        store = _trusted_artifact_store(case["artifacts"])
        reference = case["evidence"]["verification"][0]["artifactHash"]
        attributes = store._records[reference]["attributes"]

        self.assertEqual(
            tuple(attributes["invocation"]),
            (
                "executable",
                "module",
                "argv",
                "cwd",
                "environmentKeys",
                "environmentHash",
                "inputHash",
            ),
        )
        self.assertEqual(attributes["invocation"]["executable"], "python")
        self.assertEqual(attributes["invocation"]["module"], "unittest")
        self.assertEqual(
            attributes["invocation"]["argv"],
            ("-m", "unittest", "unit-tests"),
        )
        self.assertEqual(attributes["invocation"]["cwd"], ".")
        self.assertEqual(attributes["invocation"]["environmentKeys"], ("PYTHONPATH",))
        self.assertRegex(
            attributes["invocation"]["environmentHash"],
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertRegex(
            attributes["invocation"]["inputHash"],
            r"^sha256:[0-9a-f]{64}$",
        )
        with self.assertRaises(TypeError):
            attributes["invocation"]["cwd"] = "outside"

    def test_collector_derives_attestation_input_and_output_hashes(self):
        from selfworkflow.evidence import ArtifactCollector, canonical_content_hash

        subject = canonical_content_hash({"subject": "completion"})
        output = {"decision": "passed", "level": "L2"}
        collector = ArtifactCollector()
        reference = collector.record_attestation(
            kind="review",
            subject_id="completion-review",
            subject_hash=subject,
            actor_id="reviewer",
            context_id="review-context",
            recorded_at="2026-08-08T08:00:00Z",
            provider="fake-review-provider",
            receipt_id="review-1",
            output_content=output,
            decision="passed",
            level="L2",
            implementation_actor="implementer",
            implementation_context="implementation-context",
        )
        artifact = collector.seal()._records[reference]
        self.assertEqual(artifact["attributes"]["inputHash"], subject)
        self.assertEqual(
            artifact["attributes"]["outputHash"], canonical_content_hash(output)
        )

    def test_attestation_output_must_match_the_declared_receipt_result(self):
        from selfworkflow.evidence import (
            ArtifactCollector,
            WorkflowEvidenceError,
            canonical_content_hash,
        )

        with self.assertRaises(WorkflowEvidenceError) as caught:
            ArtifactCollector().record_attestation(
                kind="review",
                subject_id="completion-review",
                subject_hash=canonical_content_hash({"subject": "completion"}),
                actor_id="reviewer",
                context_id="review-context",
                recorded_at="2026-08-08T08:00:00Z",
                provider="fake-review-provider",
                receipt_id="review-1",
                output_content={"decision": "failed", "level": "L2"},
                decision="passed",
                level="L2",
                implementation_actor="implementer",
                implementation_context="implementation-context",
            )
        self.assertEqual(caught.exception.code, "artifact-collector-invalid")

    def test_collector_derives_receipt_hashes_from_invocation_and_output(self):
        from selfworkflow.evidence import (
            ArtifactCollector,
            ExecutionInvocation,
            canonical_content_hash,
        )

        subject = canonical_content_hash({"subject": "completion"})
        invocation = ExecutionInvocation(
            executable="python",
            module="unittest",
            argv=("-m", "unittest", "tests.unit"),
            cwd=".",
            environment={"PYTHONPATH": "src"},
            input_hash="sha256:" + "1" * 64,
        )

        def collect(output_content):
            collector = ArtifactCollector()
            reference = collector.record_execution(
                kind="verification",
                status="passed",
                subject_id="unit-tests",
                subject_hash=subject,
                actor_id="runner",
                context_id="verification-context",
                related_ids=("criterion-tests",),
                recorded_at="2026-08-08T08:00:00Z",
                provider="fake-executor",
                receipt_id="execution-1",
                invocation=invocation,
                output_content=output_content,
                check_type="unit-test",
                exit_code=0,
                verification_id="unit-tests",
                valid_for_seconds=3600,
            )
            return reference, collector.seal()

        first_reference, first_store = collect(b"1 passed\n")
        second_reference, _ = collect(b"no tests ran\n")
        self.assertNotEqual(first_reference, second_reference)
        artifact = first_store._records[first_reference]
        self.assertEqual(artifact["attributes"]["inputHash"], subject)
        self.assertEqual(
            artifact["attributes"]["invocationHash"],
            invocation.invocation_hash,
        )
        self.assertEqual(
            artifact["attributes"]["outputHash"],
            "sha256:" + hashlib.sha256(b"1 passed\n").hexdigest(),
        )

    def test_collector_rejects_non_tuple_and_hostile_related_ids_without_leak(self):
        from selfworkflow.evidence import (
            ArtifactCollector,
            WorkflowEvidenceError,
            canonical_content_hash,
        )

        secret = "HOSTILE-RELATED-IDS-SECRET"

        class HostileRelatedIds:
            def __iter__(self):
                raise RuntimeError(secret)

        subject = canonical_content_hash({"subject": "completion"})
        for related_ids in (["criterion-tests"], HostileRelatedIds()):
            with self.subTest(payload=type(related_ids).__name__):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    ArtifactCollector().record_execution(
                        kind="verification",
                        status="passed",
                        subject_id="unit-tests",
                        subject_hash=subject,
                        actor_id="runner",
                        context_id="verification-context",
                        related_ids=related_ids,
                        recorded_at="2026-08-08T08:00:00Z",
                        provider="execution-provider",
                        receipt_id="execution-1",
                        invocation=_verification_invocation(),
                        output_content={"status": "passed"},
                        check_type="unit-test",
                        exit_code=0,
                        verification_id="unit-tests",
                        valid_for_seconds=3600,
                    )
                self.assertEqual(caught.exception.code, "artifact-collector-invalid")
                self.assertNotIn(
                    secret,
                    "".join(traceback.format_exception(caught.exception)),
                )

    def test_collector_rejects_provider_receipt_reuse_across_kinds(self):
        from selfworkflow.evidence import (
            ArtifactCollector,
            WorkflowEvidenceError,
            canonical_content_hash,
        )

        subject = canonical_content_hash({"subject": "shared-receipt"})
        collector = ArtifactCollector()
        collector.record_attestation(
            kind="review",
            subject_id="completion-review",
            subject_hash=subject,
            actor_id="reviewer",
            context_id="review-context",
            recorded_at="2026-08-08T08:00:00Z",
            provider="shared-provider",
            receipt_id="shared-receipt",
            output_content={"decision": "passed", "level": "L2"},
            decision="passed",
            level="L2",
            implementation_actor="implementer",
            implementation_context="implementation-context",
        )
        with self.assertRaises(WorkflowEvidenceError) as caught:
            collector.record_attestation(
                kind="owner-confirmation",
                subject_id="protected-rules-change",
                subject_hash=subject,
                actor_id="owner",
                context_id="owner-context",
                recorded_at="2026-08-08T08:00:00Z",
                provider="shared-provider",
                receipt_id="shared-receipt",
                output_content={
                    "decision": "authorized",
                    "scope": "replace-protected-rules",
                },
                decision="authorized",
                scope="replace-protected-rules",
            )
        self.assertEqual(caught.exception.code, "artifact-collector-invalid")

    def test_capability_receipts_participate_in_global_replay_detection(self):
        from selfworkflow.evidence import ArtifactCollector, WorkflowEvidenceError
        from selfworkflow.model import CapabilityState

        policy = _policy()
        collector = ArtifactCollector()
        collector.record_capability(
            name="filesystem-write",
            state=CapabilityState.SUPPORTED,
            policy_hash=policy.policy_hash,
            actor_id="probe",
            context_id="task-3",
            recorded_at="2026-08-08T08:00:00Z",
            provider="shared-provider",
            receipt_id="shared-receipt",
        )
        with self.assertRaises(WorkflowEvidenceError) as caught:
            collector.record_attestation(
                kind="review",
                subject_id="completion-review",
                subject_hash=policy.policy_hash,
                actor_id="reviewer",
                context_id="review-context",
                recorded_at="2026-08-08T08:00:00Z",
                provider="shared-provider",
                receipt_id="shared-receipt",
                output_content={"decision": "passed", "level": "L2"},
                decision="passed",
                level="L2",
                implementation_actor="implementer",
                implementation_context="task-3",
            )
        self.assertEqual(caught.exception.code, "artifact-collector-invalid")

    def test_collector_budget_and_hostile_output_fail_closed(self):
        from selfworkflow.evidence import (
            ArtifactCollector,
            WorkflowEvidenceError,
            canonical_content_hash,
        )
        from selfworkflow.model import CapabilityState

        policy_hash = canonical_content_hash({"policy": "bounded"})
        collector = ArtifactCollector()
        for index in range(2048):
            collector.record_capability(
                name=f"capability-{index}",
                state=CapabilityState.SUPPORTED,
                policy_hash=policy_hash,
                actor_id="probe",
                context_id="context",
                recorded_at="2026-08-08T08:00:00Z",
                provider="probe-provider",
                receipt_id=f"receipt-{index}",
            )
        with self.assertRaises(WorkflowEvidenceError) as budget:
            collector.record_capability(
                name="capability-over-budget",
                state=CapabilityState.SUPPORTED,
                policy_hash=policy_hash,
                actor_id="probe",
                context_id="context",
                recorded_at="2026-08-08T08:00:00Z",
                provider="probe-provider",
                receipt_id="receipt-over-budget",
            )
        self.assertEqual(budget.exception.code, "artifact-collector-invalid")

        secret = "HOSTILE-OUTPUT-SECRET"

        class HostileOutput(dict):
            def items(self):
                raise RuntimeError(secret)

        with self.assertRaises(WorkflowEvidenceError) as hostile:
            ArtifactCollector().record_attestation(
                kind="review",
                subject_id="review",
                subject_hash=policy_hash,
                actor_id="reviewer",
                context_id="review-context",
                recorded_at="2026-08-08T08:00:00Z",
                provider="review-provider",
                receipt_id="review-receipt",
                output_content=HostileOutput(),
                decision="passed",
                level="L2",
                implementation_actor="implementer",
                implementation_context="implementation-context",
            )
        self.assertEqual(hostile.exception.code, "artifact-collector-invalid")
        self.assertNotIn(secret, "".join(traceback.format_exception(hostile.exception)))

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
            "output_content": {"decision": "passed"},
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
                invocation=_verification_invocation(),
                output_content={"status": "passed"},
                check_type=Text("unit-test"),
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
                output_content={"decision": "authorized"},
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
        _refresh_policy_and_invocations_for_current_input(case)
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
    def test_verification_window_cannot_exceed_the_trusted_policy_window(self):
        case = _case()
        verification = case["evidence"]["verification"][0]
        verification["validForSeconds"] = 7200
        _replace_artifact(
            case,
            verification,
            lambda artifact: artifact["attributes"].update(
                {"validForSeconds": 7200}
            ),
        )
        self.assertEqual(_evaluate(case).code, "artifact-binding-mismatch")

    def test_nonpassing_stale_and_mismatched_verification_cannot_complete(self):
        from selfworkflow.evidence import canonical_content_hash

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
                artifact["attributes"]["outputHash"] = canonical_content_hash(
                    {"status": value, "verificationId": "unit-tests"}
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
                artifact["attributes"].update(
                    {
                        "exitCode": None,
                        "outputHash": canonical_content_hash(
                            {
                                "status": "not-applicable",
                                "verificationId": "unit-tests",
                            }
                        ),
                    }
                ),
            ),
        )
        _refresh_policy_and_invocations_for_current_input(case)
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


class ResourceBudgetTests(unittest.TestCase):
    def test_canonical_string_budget_rejects_before_utf8_allocation(self):
        from selfworkflow.evidence import WorkflowEvidenceError, canonical_content_hash

        payload = "x" * (16 * 1024 * 1024)
        tracemalloc.start()
        try:
            with self.assertRaises(WorkflowEvidenceError) as caught:
                canonical_content_hash(payload)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(caught.exception.code, "result-content-budget-exceeded")
        self.assertLess(peak, 4 * 1024 * 1024)

    def test_large_mapping_budget_rejects_before_entry_materialization(self):
        from selfworkflow._evidence_values import freeze_json
        from selfworkflow.evidence import WorkflowEvidenceError, canonical_content_hash

        payload = {f"key-{index}": index for index in range(100_000)}
        attacks = (
            (canonical_content_hash, "result-content-budget-exceeded"),
            (freeze_json, "evidence-budget-exceeded"),
        )
        for operation, expected_code in attacks:
            tracemalloc.start()
            try:
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    operation(payload)
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            with self.subTest(operation=operation.__name__):
                self.assertEqual(caught.exception.code, expected_code)
                self.assertLess(peak, 2 * 1024 * 1024)

    def test_collector_string_output_budget_rejects_before_utf8_allocation(self):
        from selfworkflow.evidence import ArtifactCollector, WorkflowEvidenceError

        payload = "x" * (16 * 1024 * 1024)
        invocation = _verification_invocation(input_hash="sha256:" + "1" * 64)
        tracemalloc.start()
        try:
            with self.assertRaises(WorkflowEvidenceError) as caught:
                ArtifactCollector().record_execution(
                    kind="verification",
                    status="passed",
                    subject_id="unit-tests",
                    subject_hash="sha256:" + "2" * 64,
                    actor_id="test-runner",
                    context_id="test-context",
                    related_ids=("criterion-tests",),
                    recorded_at="2026-08-08T08:00:00Z",
                    provider="test-provider",
                    receipt_id="test-receipt",
                    invocation=invocation,
                    output_content=payload,
                    check_type="unit-test",
                    exit_code=0,
                    verification_id="unit-tests",
                    valid_for_seconds=3600,
                )
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(caught.exception.code, "artifact-collector-invalid")
        self.assertLess(peak, 4 * 1024 * 1024)

    def test_direct_evidence_text_fields_have_a_shared_budget(self):
        from selfworkflow.evidence import WorkflowEvidenceError

        oversized = "x" * (2 * 1024 * 1024)
        mutations = (
            ("skill", lambda evidence: evidence["selectedSkills"].append(oversized)),
            (
                "criterion-description",
                lambda evidence: evidence["acceptanceCriteria"][0].update(
                    {"description": oversized}
                ),
            ),
            ("review-reason", lambda evidence: evidence["review"].update({"reason": oversized})),
            (
                "skipped-reason",
                lambda evidence: evidence["skipped"].append(
                    {
                        "targetType": "skill",
                        "targetId": "optional-skill",
                        "applicability": "optional",
                        "reason": oversized,
                    }
                ),
            ),
            (
                "verification-reason",
                lambda evidence: evidence["verification"][0].update(
                    {"reason": oversized}
                ),
            ),
            (
                "residual-risk",
                lambda evidence: evidence["residualRisks"].append(
                    {"risk": oversized, "disposition": "accepted"}
                ),
            ),
        )
        for label, mutate in mutations:
            case = _case()
            mutate(case["evidence"])
            with self.subTest(field=label):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    _evaluate(case)
                self.assertEqual(caught.exception.code, "evidence-budget-exceeded")

    def test_completion_policy_rejects_oversized_groups_and_identifiers(self):
        from selfworkflow.evidence import WorkflowEvidenceError

        attacks = (
            {
                "required_capabilities": tuple(
                    f"capability-{index}" for index in range(65)
                )
            },
            {
                "required_criterion_ids": ("x" * (2 * 1024 * 1024),),
                "expected_verification_invocations": (
                    ("unit-tests", "sha256:" + "1" * 64),
                ),
            },
            {"required_verification_ids": tuple(
                f"verification-{index}" for index in range(513)
            ),
             "expected_verification_invocations": tuple(
                 (f"verification-{index}", "sha256:" + "1" * 64)
                 for index in range(513)
             )},
        )
        for values in attacks:
            with self.subTest(fields=tuple(values)):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    _policy(**values)
                self.assertEqual(caught.exception.code, "completion-policy-invalid")

    def test_public_gate_rejects_oversized_list_before_materializing_it(self):
        from selfworkflow.evidence import WorkflowEvidenceError, evaluate_completion

        case = _case()
        case["evidence"]["selectedSkills"] = [None] * 1_000_000
        store = _trusted_artifact_store(case["artifacts"])
        tracemalloc.start()
        try:
            with self.assertRaises(WorkflowEvidenceError) as caught:
                evaluate_completion(
                    case["policy"],
                    case["evidence"],
                    case["result"],
                    artifact_store=store,
                    base_manifest=case["base"],
                    final_manifest=case["final"],
                    now=NOW,
                )
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(caught.exception.code, "evidence-budget-exceeded")
        self.assertLess(peak, 4 * 1024 * 1024)

    def test_manifest_character_budget_rejects_before_utf8_allocation(self):
        from selfworkflow.evidence import WorkflowEvidenceError, evaluate_completion

        case = _case()
        case["final"]["large.bin"] = "x" * (8 * 1024 * 1024 + 1)
        store = _trusted_artifact_store(case["artifacts"])
        tracemalloc.start()
        try:
            with self.assertRaises(WorkflowEvidenceError) as caught:
                evaluate_completion(
                    case["policy"],
                    case["evidence"],
                    case["result"],
                    artifact_store=store,
                    base_manifest=case["base"],
                    final_manifest=case["final"],
                    now=NOW,
                )
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(caught.exception.code, "manifest-budget-exceeded")
        self.assertLess(peak, 4 * 1024 * 1024)

    def test_canonical_content_rejects_an_oversized_mapping_key(self):
        from selfworkflow.evidence import WorkflowEvidenceError, canonical_content_hash

        with self.assertRaises(WorkflowEvidenceError) as caught:
            canonical_content_hash({"k" * (1024 * 1024 + 1): "value"})
        self.assertEqual(caught.exception.code, "result-content-budget-exceeded")

    def test_json_input_budget_counts_utf8_bytes_before_parsing(self):
        from selfworkflow.evidence import WorkflowEvidenceError, parse_evidence_json

        oversized = '{"value":"' + ("é" * 600_000) + '"}'
        with self.assertRaises(WorkflowEvidenceError) as caught:
            parse_evidence_json(oversized)
        self.assertEqual(caught.exception.code, "evidence-budget-exceeded")
        self.assertNotIn("é" * 100, str(caught.exception))

    def test_canonical_content_rejects_single_string_over_budget(self):
        from selfworkflow.evidence import WorkflowEvidenceError, canonical_content_hash

        oversized = "x" * (1024 * 1024 + 1)
        with self.assertRaises(WorkflowEvidenceError) as caught:
            canonical_content_hash(oversized)
        self.assertEqual(caught.exception.code, "result-content-budget-exceeded")
        self.assertNotIn(oversized[:100], str(caught.exception))

    def test_public_gate_rejects_twenty_thousand_selected_skills(self):
        from selfworkflow.evidence import WorkflowEvidenceError

        case = _case()
        case["evidence"]["selectedSkills"] = [
            f"skill-{index}" for index in range(20_000)
        ]
        with self.assertRaises(WorkflowEvidenceError) as caught:
            _evaluate(case)
        self.assertEqual(caught.exception.code, "evidence-budget-exceeded")

    def test_public_gate_rejects_single_manifest_file_over_budget(self):
        from selfworkflow.evidence import WorkflowEvidenceError

        case = _case()
        case["final"]["large.bin"] = "x" * (8 * 1024 * 1024 + 1)
        with self.assertRaises(WorkflowEvidenceError) as caught:
            _evaluate(case)
        self.assertEqual(caught.exception.code, "manifest-budget-exceeded")


class ManifestPathTests(unittest.TestCase):
    def test_public_gate_rejects_windows_invalid_and_reserved_paths(self):
        from selfworkflow.evidence import WorkflowEvidenceError

        reserved = (
            "CON",
            "prn.txt",
            "AUX.log",
            "nul",
            *(f"COM{index}.txt" for index in range(1, 10)),
            *(f"lpt{index}" for index in range(1, 10)),
        )
        invalid_paths = (
            ".",
            "",
            "src//file.py",
            "src/./file.py",
            "../file.py",
            "/absolute.py",
            "C:/absolute.py",
            "src\\file.py",
            "file.txt:stream",
            "control\u0001.txt",
            "bad<name>.txt",
            "bad|name.txt",
            "trailing.",
            "trailing ",
            "x" * 256,
            ("a/" * 512) + "x",
            *reserved,
        )
        for path in invalid_paths:
            case = _case()
            case["base"] = {path: "old"}
            case["final"] = {path: "new"}
            with self.subTest(path=path[:32]):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    _evaluate(case)
                self.assertEqual(caught.exception.code, "manifest-invalid")

    def test_public_gate_rejects_casefold_and_nfc_path_aliases(self):
        from selfworkflow.evidence import WorkflowEvidenceError

        attacks = (
            (
                {"README.md": "one", "readme.md": "two"},
                {"README.md": "new", "readme.md": "two"},
            ),
            ({"e\u0301.txt": "old"}, {"e\u0301.txt": "new"}),
            ({"README.md": "old"}, {"readme.md": "new"}),
        )
        for base, final in attacks:
            case = _case()
            case["base"] = base
            case["final"] = final
            with self.subTest(paths=(tuple(base), tuple(final))):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    _evaluate(case)
                self.assertEqual(caught.exception.code, "manifest-invalid")


if __name__ == "__main__":
    unittest.main()
