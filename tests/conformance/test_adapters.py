from pathlib import Path
import json
import unittest

from jsonschema import Draft202012Validator
import yaml

from selfworkflow.adapters import load_adapters


class AdapterContractTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_supported_adapter_contracts_are_closed_and_do_not_override_core(self):
        adapters = load_adapters(self.ROOT / "adapters", self.ROOT / "schemas/adapter.schema.json")
        self.assertEqual(
            {item["id"]: item["supportStatus"] for item in adapters},
            {
                "claude-code": "experimental-unverified",
                "codex": "experimental-unverified",
                "copilot": "instructions-only",
                "cursor": "experimental-unverified",
                "opencode": "experimental-unverified",
                "unknown": "bootstrap-only",
            },
        )
        self.assertTrue(all(item["coreOverride"] == "forbidden" for item in adapters))
        for item in adapters:
            self.assertTrue((self.ROOT / "adapters" / item["id"] / item["entryFile"]).is_file())

    def test_codex_declares_full_target_capabilities_without_claiming_native_support(self):
        adapters = {item["id"]: item for item in load_adapters(
            self.ROOT / "adapters", self.ROOT / "schemas/adapter.schema.json"
        )}
        codex = adapters["codex"]
        self.assertIn("global-instructions", codex["capabilities"])
        self.assertIn("skill-discovery", codex["capabilities"])
        self.assertEqual(codex["supportStatus"], "experimental-unverified")
        self.assertEqual(codex["overrideBehavior"], "pause-and-confirm-target")

    def test_vendor_entries_expose_the_optional_stateless_resolver(self):
        adapters = load_adapters(
            self.ROOT / "adapters",
            self.ROOT / "schemas/adapter.schema.json",
        )
        for adapter in adapters:
            with self.subTest(adapter=adapter["id"]):
                content = (
                    self.ROOT / "adapters" / adapter["id"] / adapter["entryFile"]
                ).read_text(encoding="utf-8")
                self.assertIn("selfworkflow resolve", content)
                for phrase in (
                    "paused", "PlanGraph", "RunLedger", "current-stage",
                    "critical decisions", "agent-policy", "Knowledge",
                    "C7OpenWiki execution is deferred",
                ):
                    self.assertIn(phrase, content)
                self.assertNotIn("is a conforming Host", content)


if __name__ == "__main__":
    unittest.main()
