from pathlib import Path
import json
import unittest

from jsonschema import Draft202012Validator
import yaml

from selfworkflow.knowledge import (
    KnowledgeContractError,
    KnowledgeRequest,
    execute_knowledge,
    normalize_result,
)


class KnowledgeContractTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_checked_in_contract_is_closed_and_vendor_neutral(self):
        document = yaml.safe_load(
            (self.ROOT / "extensions/knowledge/contract.yaml").read_text(encoding="utf-8")
        )
        schema = json.loads(
            (self.ROOT / "schemas/knowledge-contract.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(document)
        self.assertNotIn("c7", json.dumps(document).casefold())
        self.assertEqual(
            document["defaultRouting"],
            {
                "profile": "knowledge",
                "backend": "selfopenwiki",
                "intents": [
                    "wiki-visualize",
                    "wiki-summary",
                    "wiki-organize",
                    "wiki-update",
                ],
                "fallback": "forbidden",
            },
        )

    def test_read_requires_source_revision_hash_and_verification(self):
        result = normalize_result("read", {
            "status": "ok",
            "knowledge": [{
                "content": "Owner-first repair.", "sourceId": "source-1",
                "revision": "rev-1", "contentHash": "sha256:" + "a" * 64,
                "verificationStatus": "verified",
            }],
        })
        self.assertEqual(result["status"], "ok")
        with self.assertRaises(KnowledgeContractError):
            normalize_result("read", {"status": "ok", "knowledge": [{"content": "missing evidence"}]})

    def test_propose_never_publishes_but_may_disclose_runtime_side_effects(self):
        result = normalize_result("propose", {
            "status": "proposed", "published": False, "expectedBase": "rev-1",
            "proposal": "Candidate knowledge.",
            "contentHash": "sha256:" + "a" * 64,
            "runtimeSideEffects": ["oauth-refresh", "temporary-transaction"],
        })
        self.assertFalse(result["published"])
        self.assertEqual(result["proposal"], "Candidate knowledge.")
        with self.assertRaises(KnowledgeContractError):
            normalize_result("propose", {
                "status": "proposed", "published": True, "expectedBase": "rev-1",
                "proposal": "Candidate knowledge.",
                "contentHash": "sha256:" + "a" * 64,
                "runtimeSideEffects": [],
            })

    def test_update_requires_literal_confirmation_and_cas_terminal_state(self):
        request = KnowledgeRequest(
            action="update", confirmed_by_user=True, expected_base="rev-1"
        )
        result = normalize_result("update", {
            "status": "published", "confirmedByUser": request.confirmed_by_user,
            "expectedBase": request.expected_base, "actualBase": "rev-1",
            "reviewStatus": "passed",
        })
        self.assertEqual(result["status"], "published")
        conflict = normalize_result("update", {
            "status": "conflict", "confirmedByUser": True,
            "expectedBase": "rev-1", "actualBase": "rev-2",
            "reviewStatus": "not-run",
        })
        self.assertEqual(conflict["actualBase"], "rev-2")
        follow_up = normalize_result("update", {
            "status": "published-with-follow-up", "confirmedByUser": True,
            "expectedBase": "rev-1", "actualBase": "rev-1",
            "reviewStatus": "follow-up",
            "nativeResult": {"status": "published_with_follow_up"},
        })
        self.assertEqual(follow_up["reviewStatus"], "follow-up")
        self.assertEqual(
            follow_up["nativeResult"]["status"], "published_with_follow_up"
        )
        for payload in (
            {"status": "published", "confirmedByUser": False, "expectedBase": "rev-1", "actualBase": "rev-1", "reviewStatus": "passed"},
            {"status": "conflict", "confirmedByUser": True, "expectedBase": "rev-1", "actualBase": "rev-1", "reviewStatus": "not-run"},
            {"status": "invented", "confirmedByUser": True, "expectedBase": "rev-1", "actualBase": "rev-1", "reviewStatus": "passed"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(KnowledgeContractError):
                    normalize_result("update", payload)

    def test_execution_rejects_update_receipt_bound_to_another_request_base(self):
        class WrongBaseBackend:
            def execute(self, request):
                return {"status": "published", "confirmedByUser": True,
                        "expectedBase": "rev-2", "actualBase": "rev-2", "reviewStatus": "passed"}

        request = KnowledgeRequest(action="update", confirmed_by_user=True, expected_base="rev-1")
        self.assertEqual(execute_knowledge(WrongBaseBackend(), request, code_task=False)["status"], "failed")
        self.assertEqual(execute_knowledge(WrongBaseBackend(), request, code_task=True)["status"], "knowledge-sync-todo")

    def test_update_receipt_requires_valid_bases_and_review_for_publication(self):
        valid = {"status": "published", "confirmedByUser": True,
                 "expectedBase": "rev-1", "actualBase": "rev-1", "reviewStatus": "passed"}
        for change in (
            {"reviewStatus": "not-run"},
            {"reviewStatus": "follow-up"},
            {"status": "published-with-follow-up"},
            {"status": "review-requires-attention"},
            {"expectedBase": "", "actualBase": ""},
            {"status": "conflict", "actualBase": None, "reviewStatus": "not-run"},
        ):
            with self.subTest(change=change), self.assertRaises(KnowledgeContractError):
                normalize_result("update", {**valid, **change})

    def test_missing_backend_does_not_block_code_delivery_and_private_reasoning_is_rejected(self):
        class MissingBackend:
            def execute(self, request):
                raise RuntimeError("offline")

        result = execute_knowledge(
            MissingBackend(), KnowledgeRequest(action="read"), code_task=True
        )
        self.assertEqual(result["status"], "knowledge-sync-todo")
        with self.assertRaises(KnowledgeContractError):
            normalize_result("read", {
                "status": "ok", "knowledge": [], "privateReasoning": "hidden"
            })

    def test_generic_execution_preserves_bounded_structured_remote_failure(self):
        class StructuredFailure(RuntimeError):
            error = {
                "code": "capability_unverified",
                "details": {"lock": "wiki", "paths": ["docs/page.md"]},
                "message": "Capability evidence is stale.",
                "retryable": False,
            }
            recovery = {"action": "verify_capabilities"}

        class FailingBackend:
            def execute(self, request):
                raise StructuredFailure("remote")

        result = execute_knowledge(
            FailingBackend(), KnowledgeRequest(action="read"), code_task=True
        )

        self.assertEqual(result["status"], "knowledge-sync-todo")
        self.assertEqual(result["error"], StructuredFailure.error)
        self.assertEqual(result["recovery"], StructuredFailure.recovery)

    def test_generic_failure_details_preserve_only_current_bounded_backend_diagnostics(self):
        def execute(details):
            class StructuredFailure(RuntimeError):
                error = {
                    "code": "process_failure",
                    "details": details,
                    "message": "The isolated model result could not be consumed.",
                    "retryable": False,
                }
                recovery = {"action": "retry"}

            class FailingBackend:
                def execute(self, request):
                    raise StructuredFailure("remote")

            return execute_knowledge(
                FailingBackend(), KnowledgeRequest(action="read"), code_task=True
            )

        stages = (
            "result_missing",
            "result_json_invalid",
            "result_schema_invalid",
            "result_binding_mismatch",
        )
        for stage in stages:
            with self.subTest(stage=stage):
                details = {"diagnostic": "x", "failureStage": stage}
                self.assertEqual(execute(details)["error"]["details"], details)
        diagnostic = "x" * 4_096
        self.assertEqual(
            execute({"diagnostic": diagnostic})["error"]["details"]["diagnostic"],
            diagnostic,
        )
        for details in (
            {"diagnostic": ""},
            {"diagnostic": "   "},
            {"diagnostic": 1},
            {"diagnostic": "x" * 4_097},
            {"failureStage": "unknown"},
            {"failureStage": []},
            {"failureStage": {}},
            {"unknown": "field"},
        ):
            with self.subTest(invalid=details):
                self.assertNotIn("error", execute(details))


if __name__ == "__main__":
    unittest.main()
