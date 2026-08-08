from pathlib import Path
import json
import tempfile
import unittest

from selfworkflow.c7_openwiki import (
    C7OpenWikiAdapter,
    C7OpenWikiError,
    check_contract_drift,
    load_tool_contract,
)


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        response = self.responses[name]
        return response() if callable(response) else response


class C7OpenWikiAdapterTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_snapshot_exposes_exact_seven_tools_and_update_guard(self):
        contract = load_tool_contract(
            self.ROOT / "extensions/knowledge/c7-openwiki/tool-contract.json"
        )
        self.assertEqual(
            [item["name"] for item in contract["tools"]],
            [
                "openwiki_status", "openwiki_setup", "openwiki_prepare_sources",
                "openwiki_list_skills", "openwiki_query", "openwiki_update",
                "openwiki_set_default_model",
            ],
        )
        update = next(item for item in contract["tools"] if item["name"] == "openwiki_update")
        self.assertEqual(update["confirmedByUser"], {"const": True, "purpose": "misoperation-guard-not-authentication"})
        self.assertTrue(update["annotations"]["destructiveHint"])

    def test_status_is_called_first_and_bound_sources_are_atomic(self):
        client = FakeClient({
            "openwiki_status": {"ok": True, "status": "status", "initialized": True},
            "openwiki_prepare_sources": {
                "ok": True, "status": "sources_prepared", "sourceManifestId": "manifest-123",
                "confirmation": "confirm-123", "manifestHash": "sha256:" + "a" * 64,
            },
            "openwiki_query": {"ok": True, "status": "answered", "answer": "result"},
        })
        adapter = C7OpenWikiAdapter(client)
        prepared = adapter.prepare_sources([r"C:\project\doc.md"])
        answer = adapter.query(
            "summarize", source_manifest_id=prepared["sourceManifestId"],
            source_confirmation=prepared["confirmation"], skills=["cpp-quality"],
        )
        self.assertEqual(answer["status"], "answered")
        self.assertEqual(client.calls[0][0], "openwiki_status")
        self.assertEqual(client.calls[2][0], "openwiki_status")
        with self.assertRaises(C7OpenWikiError):
            adapter.query("bad", source_manifest_id="manifest-123")

    def test_propose_never_updates_and_discloses_runtime_side_effects(self):
        client = FakeClient({
            "openwiki_status": {"ok": True, "status": "status", "initialized": True},
            "openwiki_query": {"ok": True, "status": "answered", "answer": "candidate"},
        })
        result = C7OpenWikiAdapter(client).propose("candidate update")
        self.assertFalse(result["published"])
        self.assertEqual(result["runtimeSideEffects"], ["oauth-refresh", "temporary-transaction"])
        self.assertNotIn("openwiki_update", [name for name, _ in client.calls])
        self.assertEqual(result["casStatus"], "unverified-contract-gap")

    def test_update_requires_confirmation_and_accepts_only_real_terminal_states(self):
        response = {
            "ok": True, "status": "published_with_follow_up", "published": True,
            "followUp": [{"severity": "provisional"}],
        }
        client = FakeClient({
            "openwiki_status": {"ok": True, "status": "status", "initialized": True},
            "openwiki_update": response,
        })
        adapter = C7OpenWikiAdapter(client)
        with self.assertRaises(C7OpenWikiError):
            adapter.update("write", confirmed_by_user=False)
        result = adapter.update("write", confirmed_by_user=True)
        self.assertEqual(result["status"], "published_with_follow_up")
        self.assertTrue(client.calls[-1][1]["confirmedByUser"])

        client.responses["openwiki_update"] = {"ok": True, "status": "invented"}
        with self.assertRaises(C7OpenWikiError):
            adapter.update("write", confirmed_by_user=True)

    def test_contract_hash_drift_is_detected_without_overwriting_snapshot(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            contract = Path(temporary) / "contracts.ts"
            contract.write_text("version one\n", encoding="utf-8")
            expected = "sha256:" + __import__("hashlib").sha256(contract.read_bytes()).hexdigest()
            self.assertEqual(check_contract_drift(contract, expected), "current")
            contract.write_text("version two\n", encoding="utf-8")
            self.assertEqual(check_contract_drift(contract, expected), "contract-drift")


if __name__ == "__main__":
    unittest.main()
