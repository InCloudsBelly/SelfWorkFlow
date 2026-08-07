import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path
import traceback
from types import MappingProxyType
import unittest

from jsonschema import Draft202012Validator
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VALID_FIXTURE = REPOSITORY_ROOT / "tests" / "fixtures" / "evidence" / "valid.json"
STALE_FIXTURE = REPOSITORY_ROOT / "tests" / "fixtures" / "evidence" / "stale.json"
RESULT_CONTENT = {
    "files": [
        {
            "path": "src/example.py",
            "sha256": "d" * 64,
        }
    ]
}


def _open_object_schema_paths(value):
    open_paths = []

    def visit(node, path):
        if isinstance(node, dict):
            if node.get("type") == "object":
                required = node.get("required")
                properties = node.get("properties")
                if (
                    node.get("additionalProperties") is not False
                    or not isinstance(required, list)
                    or not isinstance(properties, dict)
                    or len(required) != len(set(required))
                    or set(required) != set(properties)
                ):
                    open_paths.append(path)
            for key, nested in node.items():
                visit(nested, f"{path}.{key}")
        elif isinstance(node, list):
            for index, nested in enumerate(node):
                visit(nested, f"{path}[{index}]")

    visit(value, "$")
    return tuple(open_paths)


class EvidenceTests(unittest.TestCase):
    def test_existing_contract_and_fixture_parse_to_a_deeply_immutable_model(self):
        schema = json.loads(
            (REPOSITORY_ROOT / "schemas" / "evidence.schema.json").read_text(
                encoding="utf-8"
            )
        )
        contract = yaml.safe_load(
            (REPOSITORY_ROOT / "workflow" / "evidence.yaml").read_text(
                encoding="utf-8"
            )
        )
        fixture_text = VALID_FIXTURE.read_text(encoding="utf-8")
        fixture = json.loads(fixture_text)

        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(contract)
        self.assertEqual(_open_object_schema_paths(schema), ())
        self.assertEqual(
            set(fixture),
            {
                "classification",
                "capabilities",
                "selectedSkills",
                "acceptanceCriteria",
                "changes",
                "review",
                "verification",
                "skipped",
                "residualRisks",
            },
        )

        from selfworkflow.evidence import parse_evidence_json

        first = parse_evidence_json(fixture_text)
        second = parse_evidence_json(fixture_text)
        self.assertIsInstance(first, MappingProxyType)
        self.assertIsNot(first, second)
        self.assertIsNot(first["classification"], second["classification"])
        self.assertIsInstance(first["capabilities"], tuple)
        self.assertIsInstance(first["capabilities"][0], MappingProxyType)
        with self.assertRaises(TypeError):
            first["classification"] = {}
        with self.assertRaises(TypeError):
            first["classification"]["complexity"] = "C3"
        with self.assertRaises(AttributeError):
            first["verification"].append({})

    def test_fresh_passed_modification_evidence_is_completion_eligible(self):
        import selfworkflow.evidence as evidence_module

        self.assertTrue(
            callable(getattr(evidence_module, "canonical_content_hash", None)),
            "canonical content hashing is missing",
        )
        self.assertTrue(
            callable(getattr(evidence_module, "evaluate_completion", None)),
            "completion evaluation is missing",
        )
        canonical_content_hash = evidence_module.canonical_content_hash
        evaluate_completion = evidence_module.evaluate_completion
        parse_evidence_json = evidence_module.parse_evidence_json

        result_content = {
            "files": [
                {
                    "path": "src/example.py",
                    "sha256": "d" * 64,
                }
            ]
        }
        reordered_content = {
            "files": [
                {
                    "sha256": "d" * 64,
                    "path": "src/example.py",
                }
            ]
        }
        expected_hash = (
            "sha256:0721e8ed5ea90b709800b5134b3f7cfa"
            "28f749f11af24aa0516972e2c6eab7a5"
        )
        self.assertEqual(canonical_content_hash(result_content), expected_hash)
        self.assertEqual(canonical_content_hash(reordered_content), expected_hash)

        evidence = parse_evidence_json(VALID_FIXTURE.read_text(encoding="utf-8"))
        now = datetime(2026, 8, 8, 8, 30, tzinfo=timezone.utc)
        decision = evaluate_completion(evidence, result_content, now=now)

        self.assertTrue(decision.eligible)
        self.assertEqual(decision.code, "completion-eligible")
        self.assertEqual(
            decision.message,
            "The evidence satisfies the completion gate.",
        )
        self.assertEqual(decision.content_hash, expected_hash)
        self.assertEqual(decision.observed_at, "2026-08-08T08:30:00Z")
        with self.assertRaises(FrozenInstanceError):
            decision.eligible = False

    def test_nonpassing_verification_statuses_are_not_completion_eligible(self):
        from selfworkflow.evidence import evaluate_completion
        from selfworkflow.evidence import parse_evidence_json

        cases = (
            (
                "failed",
                "verification-failed",
                "A failed verification cannot satisfy the completion gate.",
            ),
            (
                "not-run",
                "verification-not-run",
                "A verification that was not run cannot satisfy the completion gate.",
            ),
            (
                "partial",
                "verification-partial",
                "A partial verification cannot satisfy the completion gate.",
            ),
        )
        for status, code, message in cases:
            fixture = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
            fixture["verification"][0].update(
                {"status": status, "reason": "Verification did not pass."}
            )
            decision = evaluate_completion(
                parse_evidence_json(json.dumps(fixture)),
                RESULT_CONTENT,
                now=datetime(2026, 8, 8, 8, 30, tzinfo=timezone.utc),
            )
            with self.subTest(status=status):
                self.assertFalse(decision.eligible)
                self.assertEqual(decision.code, code)
                self.assertEqual(decision.message, message)

    def test_stale_passed_verification_is_not_completion_eligible(self):
        from selfworkflow.evidence import evaluate_completion
        from selfworkflow.evidence import parse_evidence_json

        evidence = parse_evidence_json(STALE_FIXTURE.read_text(encoding="utf-8"))
        try:
            decision = evaluate_completion(
                evidence,
                RESULT_CONTENT,
                now=datetime(2026, 8, 8, 8, 30, tzinfo=timezone.utc),
            )
        except Exception:
            self.fail("stale evidence must return an ineligible decision")

        self.assertFalse(decision.eligible)
        self.assertEqual(decision.code, "verification-stale")
        self.assertEqual(
            decision.message,
            "Verification evidence outside its validity window is stale.",
        )

    def test_result_content_hash_mismatch_is_not_completion_eligible(self):
        from selfworkflow.evidence import evaluate_completion
        from selfworkflow.evidence import parse_evidence_json

        fixture = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
        fixture["changes"]["resultContentHash"] = "sha256:" + "0" * 64
        evidence = parse_evidence_json(json.dumps(fixture))
        try:
            decision = evaluate_completion(
                evidence,
                RESULT_CONTENT,
                now=datetime(2026, 8, 8, 8, 30, tzinfo=timezone.utc),
            )
        except Exception:
            self.fail("a result hash mismatch must return an ineligible decision")

        self.assertFalse(decision.eligible)
        self.assertEqual(decision.code, "result-content-hash-mismatch")
        self.assertEqual(
            decision.message,
            "The evidence is not bound to the current completion result.",
        )

    def test_verification_content_hash_mismatch_is_not_completion_eligible(self):
        from selfworkflow.evidence import evaluate_completion
        from selfworkflow.evidence import parse_evidence_json

        fixture = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
        fixture["verification"][0]["contentHash"] = "sha256:" + "0" * 64
        evidence = parse_evidence_json(json.dumps(fixture))
        try:
            decision = evaluate_completion(
                evidence,
                RESULT_CONTENT,
                now=datetime(2026, 8, 8, 8, 30, tzinfo=timezone.utc),
            )
        except Exception:
            self.fail(
                "a verification hash mismatch must return an ineligible decision"
            )

        self.assertFalse(decision.eligible)
        self.assertEqual(decision.code, "verification-content-hash-mismatch")
        self.assertEqual(
            decision.message,
            "A verification is not bound to the current completion result.",
        )

    def test_read_only_not_applicable_evidence_is_completion_eligible(self):
        from selfworkflow.evidence import evaluate_completion
        from selfworkflow.evidence import parse_evidence_json

        fixture = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
        fixture["classification"]["taskKind"] = "read-only"
        fixture["changes"]["taskKind"] = "read-only"
        fixture["changes"]["items"] = []
        fixture["acceptanceCriteria"][0].update(
            {
                "applicability": "not-applicable",
                "reason": "The task produces no changed artifact.",
            }
        )
        fixture["review"].update(
            {
                "status": "not-applicable",
                "level": "not-applicable",
                "reason": "The task only reads existing state.",
            }
        )
        fixture["verification"][0].update(
            {
                "status": "not-applicable",
                "reason": "The task produces no changed artifact.",
            }
        )
        evidence = parse_evidence_json(json.dumps(fixture))

        try:
            decision = evaluate_completion(
                evidence,
                RESULT_CONTENT,
                now=datetime(2026, 8, 8, 8, 30, tzinfo=timezone.utc),
            )
        except Exception:
            self.fail("valid read-only evidence must return a completion decision")

        self.assertTrue(decision.eligible)
        self.assertEqual(decision.code, "completion-eligible")

    def test_modification_cannot_use_not_applicable_verification(self):
        from selfworkflow.evidence import evaluate_completion
        from selfworkflow.evidence import parse_evidence_json

        fixture = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
        fixture["verification"][0].update(
            {
                "status": "not-applicable",
                "reason": "The check was declared unnecessary.",
            }
        )
        evidence = parse_evidence_json(json.dumps(fixture))
        try:
            decision = evaluate_completion(
                evidence,
                RESULT_CONTENT,
                now=datetime(2026, 8, 8, 8, 30, tzinfo=timezone.utc),
            )
        except Exception:
            self.fail(
                "modification not-applicable must return an ineligible decision"
            )

        self.assertFalse(decision.eligible)
        self.assertEqual(
            decision.code,
            "verification-not-applicable-for-modification",
        )
        self.assertEqual(
            decision.message,
            "Not-applicable verification is limited to read-only tasks.",
        )

    def test_every_acceptance_criterion_requires_real_verification_evidence(self):
        from selfworkflow.evidence import evaluate_completion
        from selfworkflow.evidence import parse_evidence_json

        fixture = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
        fixture["acceptanceCriteria"][0]["verificationIds"] = [
            "missing-verification"
        ]
        evidence = parse_evidence_json(json.dumps(fixture))
        decision = evaluate_completion(
            evidence,
            RESULT_CONTENT,
            now=datetime(2026, 8, 8, 8, 30, tzinfo=timezone.utc),
        )

        self.assertFalse(decision.eligible)
        self.assertEqual(decision.code, "acceptance-criterion-unverified")
        self.assertEqual(
            decision.message,
            "Every acceptance criterion must reference recorded verification evidence.",
        )

    def test_not_applicable_and_skipped_items_require_nonempty_reasons(self):
        from selfworkflow.evidence import WorkflowEvidenceError
        from selfworkflow.evidence import evaluate_completion
        from selfworkflow.evidence import parse_evidence_json

        def read_only_fixture():
            fixture = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
            fixture["classification"]["taskKind"] = "read-only"
            fixture["changes"].update({"taskKind": "read-only", "items": []})
            fixture["acceptanceCriteria"][0].update(
                {
                    "applicability": "not-applicable",
                    "reason": "No changed artifact exists.",
                }
            )
            fixture["review"].update(
                {
                    "status": "not-applicable",
                    "level": "not-applicable",
                    "reason": "No implementation review is applicable.",
                }
            )
            fixture["verification"][0].update(
                {
                    "status": "not-applicable",
                    "reason": "No changed artifact requires verification.",
                }
            )
            return fixture

        cases = []
        review_reason = read_only_fixture()
        review_reason["review"]["reason"] = "   "
        cases.append(review_reason)
        criterion_reason = read_only_fixture()
        criterion_reason["acceptanceCriteria"][0]["reason"] = ""
        cases.append(criterion_reason)
        verification_reason = read_only_fixture()
        verification_reason["verification"][0]["reason"] = ""
        cases.append(verification_reason)
        skipped_reason = read_only_fixture()
        skipped_reason["skipped"] = [{"item": "manual-check", "reason": ""}]
        cases.append(skipped_reason)

        for fixture in cases:
            evidence = parse_evidence_json(json.dumps(fixture))
            with self.subTest(case=len(fixture["skipped"])):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    evaluate_completion(
                        evidence,
                        RESULT_CONTENT,
                        now=datetime(2026, 8, 8, 8, 30, tzinfo=timezone.utc),
                    )
                self.assertEqual(caught.exception.code, "evidence-invalid")
                self.assertEqual(
                    caught.exception.message,
                    "The completion evidence structure is invalid.",
                )

    def test_time_inputs_require_aware_monotonic_observations(self):
        from selfworkflow.evidence import WorkflowEvidenceError
        from selfworkflow.evidence import evaluate_completion
        from selfworkflow.evidence import parse_evidence_json

        evidence = parse_evidence_json(VALID_FIXTURE.read_text(encoding="utf-8"))
        with self.assertRaises(WorkflowEvidenceError) as caught:
            evaluate_completion(
                evidence,
                RESULT_CONTENT,
                now=datetime(2026, 8, 8, 8, 30),
            )
        self.assertEqual(caught.exception.code, "evidence-time-invalid")
        self.assertEqual(
            caught.exception.message,
            "The completion evidence time is invalid.",
        )
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)

        rollback = evaluate_completion(
            evidence,
            RESULT_CONTENT,
            now=datetime(2026, 8, 8, 8, 30, tzinfo=timezone.utc),
            previous_observed_at=datetime(
                2026,
                8,
                8,
                8,
                31,
                tzinfo=timezone.utc,
            ),
        )
        self.assertFalse(rollback.eligible)
        self.assertEqual(rollback.code, "clock-rollback-detected")
        self.assertEqual(
            rollback.message,
            "The current observation time is earlier than a prior observation.",
        )

        future_fixture = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
        future_fixture["verification"][0]["verifiedAt"] = "2026-08-08T08:31:00Z"
        future = evaluate_completion(
            parse_evidence_json(json.dumps(future_fixture)),
            RESULT_CONTENT,
            now=datetime(2026, 8, 8, 8, 30, tzinfo=timezone.utc),
        )
        self.assertFalse(future.eligible)
        self.assertEqual(future.code, "verification-time-in-future")
        self.assertEqual(
            future.message,
            "Verification evidence cannot be newer than the observation time.",
        )

    def test_observation_timestamp_preserves_subsecond_precision(self):
        from selfworkflow.evidence import evaluate_completion
        from selfworkflow.evidence import parse_evidence_json

        decision = evaluate_completion(
            parse_evidence_json(VALID_FIXTURE.read_text(encoding="utf-8")),
            RESULT_CONTENT,
            now=datetime(
                2026,
                8,
                8,
                8,
                30,
                0,
                123456,
                tzinfo=timezone.utc,
            ),
        )
        self.assertEqual(decision.observed_at, "2026-08-08T08:30:00.123456Z")

    def test_canonical_inputs_are_deterministic_and_hostile_inputs_are_redacted(self):
        from selfworkflow.evidence import WorkflowEvidenceError
        from selfworkflow.evidence import canonical_content_hash
        from selfworkflow.evidence import parse_evidence_json

        self.assertEqual(
            canonical_content_hash({"number": -0.0}),
            canonical_content_hash({"number": 0}),
        )
        self.assertEqual(
            canonical_content_hash({"number": 1.0}),
            canonical_content_hash({"number": 1}),
        )

        secret = "TOP-SECRET-HOSTILE-EVIDENCE-INPUT"

        class HostileIterable:
            def __iter__(self):
                raise RuntimeError(secret)

        class HostileMapping(dict):
            def items(self):
                raise RuntimeError(secret)

        json_cases = (
            '{"duplicate": 1, "duplicate": 2, "secret": "' + secret + '"}',
            '{"number": NaN, "secret": "' + secret + '"}',
            '{"number": Infinity, "secret": "' + secret + '"}',
            '{"number": -Infinity, "secret": "' + secret + '"}',
            '{"number": 1e999, "secret": "' + secret + '"}',
        )
        for document in json_cases:
            with self.subTest(document=document[:20]):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    parse_evidence_json(document)
                error = caught.exception
                self.assertEqual(error.code, "evidence-json-invalid")
                self.assertIsNone(error.__cause__)
                self.assertTrue(error.__suppress_context__)
                self.assertNotIn(secret, str(error))
                self.assertNotIn(secret, "".join(traceback.format_exception(error)))

        content_cases = (
            {"unordered"},
            {"number": float("nan")},
            {"number": float("inf")},
            HostileIterable(),
            HostileMapping({"secret": secret}),
        )
        for content in content_cases:
            with self.subTest(content_type=type(content).__name__):
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    canonical_content_hash(content)
                error = caught.exception
                self.assertEqual(error.code, "result-content-invalid")
                self.assertIsNone(error.__cause__)
                self.assertTrue(error.__suppress_context__)
                self.assertNotIn(secret, str(error))
                self.assertNotIn(secret, "".join(traceback.format_exception(error)))

    def test_completion_boundary_redacts_hostile_nested_values(self):
        from selfworkflow.evidence import WorkflowEvidenceError
        from selfworkflow.evidence import evaluate_completion

        secret = "TOP-SECRET-HOSTILE-NESTED-VALUE"

        class HostileValue:
            def __ne__(self, other):
                raise RuntimeError(secret)

        fixture = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
        fixture["changes"]["taskKind"] = HostileValue()
        try:
            evaluate_completion(
                fixture,
                RESULT_CONTENT,
                now=datetime(2026, 8, 8, 8, 30, tzinfo=timezone.utc),
            )
        except Exception as error:
            self.assertIsInstance(error, WorkflowEvidenceError)
            caught_error = error
        else:
            self.fail("hostile nested evidence was accepted")

        self.assertEqual(caught_error.code, "evidence-invalid")
        self.assertEqual(
            caught_error.message,
            "The completion evidence structure is invalid.",
        )
        self.assertIsNone(caught_error.__cause__)
        self.assertTrue(caught_error.__suppress_context__)
        self.assertNotIn(secret, str(caught_error))
        self.assertNotIn(
            secret,
            "".join(traceback.format_exception(caught_error)),
        )

    def test_changes_review_and_verification_reject_empty_or_textual_claims(self):
        from selfworkflow.evidence import WorkflowEvidenceError
        from selfworkflow.evidence import evaluate_completion
        from selfworkflow.evidence import parse_evidence_json

        cases = []
        for path, replacement in (
            (("changes", "items"), []),
            (("changes", "items"), ["changed everything"]),
            (("review",), "review passed"),
            (("verification",), []),
            (("verification",), ["tests passed"]),
        ):
            fixture = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
            if len(path) == 1:
                fixture[path[0]] = replacement
            else:
                fixture[path[0]][path[1]] = replacement
            cases.append((path, fixture))

        for path, fixture in cases:
            with self.subTest(path=path):
                evidence = parse_evidence_json(json.dumps(fixture))
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    evaluate_completion(
                        evidence,
                        RESULT_CONTENT,
                        now=datetime(2026, 8, 8, 8, 30, tzinfo=timezone.utc),
                    )
                self.assertEqual(caught.exception.code, "evidence-invalid")

    def test_evidence_instance_contract_is_closed_and_complete(self):
        from selfworkflow.evidence import WorkflowEvidenceError
        from selfworkflow.evidence import evaluate_completion
        from selfworkflow.evidence import parse_evidence_json

        valid = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
        cases = []
        for field in tuple(valid):
            fixture = json.loads(json.dumps(valid))
            del fixture[field]
            cases.append((f"missing-{field}", fixture))
        extra = json.loads(json.dumps(valid))
        extra["claim"] = "complete"
        cases.append(("extra-top-level", extra))
        empty_capabilities = json.loads(json.dumps(valid))
        empty_capabilities["capabilities"] = []
        cases.append(("empty-capabilities", empty_capabilities))
        textual_capability = json.loads(json.dumps(valid))
        textual_capability["capabilities"] = ["filesystem-write supported"]
        cases.append(("textual-capability", textual_capability))
        textual_skills = json.loads(json.dumps(valid))
        textual_skills["selectedSkills"] = "one-skill"
        cases.append(("textual-skills", textual_skills))
        arbitrary_level = json.loads(json.dumps(valid))
        arbitrary_level["review"]["level"] = "independent enough"
        cases.append(("arbitrary-review-level", arbitrary_level))
        textual_risk = json.loads(json.dumps(valid))
        textual_risk["residualRisks"] = ["none"]
        cases.append(("textual-residual-risk", textual_risk))

        for label, fixture in cases:
            with self.subTest(case=label):
                evidence = parse_evidence_json(json.dumps(fixture))
                with self.assertRaises(WorkflowEvidenceError) as caught:
                    evaluate_completion(
                        evidence,
                        RESULT_CONTENT,
                        now=datetime(2026, 8, 8, 8, 30, tzinfo=timezone.utc),
                    )
                self.assertEqual(caught.exception.code, "evidence-invalid")
                self.assertEqual(
                    caught.exception.message,
                    "The completion evidence structure is invalid.",
                )


if __name__ == "__main__":
    unittest.main()
