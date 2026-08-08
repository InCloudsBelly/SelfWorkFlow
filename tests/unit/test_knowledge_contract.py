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
            "runtimeSideEffects": ["oauth-refresh", "temporary-transaction"],
        })
        self.assertFalse(result["published"])
        with self.assertRaises(KnowledgeContractError):
            normalize_result("propose", {
                "status": "proposed", "published": True, "expectedBase": "rev-1",
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
        for payload in (
            {"status": "published", "confirmedByUser": False, "expectedBase": "rev-1", "actualBase": "rev-1", "reviewStatus": "passed"},
            {"status": "published", "confirmedByUser": True, "expectedBase": "rev-1", "actualBase": "rev-2", "reviewStatus": "passed"},
            {"status": "invented", "confirmedByUser": True, "expectedBase": "rev-1", "actualBase": "rev-1", "reviewStatus": "passed"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(KnowledgeContractError):
                    normalize_result("update", payload)

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


if __name__ == "__main__":
    unittest.main()
