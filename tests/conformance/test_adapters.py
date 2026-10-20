from pathlib import Path
import json
import tempfile
import unittest

from jsonschema import Draft202012Validator
import yaml

from selfworkflow.adapters import compose_adapter_policy, load_adapters
from tests.installer.support import write_adapter


class AdapterContractTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_adapter_contracts_are_schema_valid_and_do_not_override_core(self):
        adapters = load_adapters(self.ROOT / "adapters", self.ROOT / "schemas/adapter.schema.json")
        actual = {item["id"]: item["supportStatus"] for item in adapters}
        expected = {
                "claude-code": "experimental-unverified",
                "codex": "experimental-unverified",
                "copilot": "instructions-only",
                "cursor": "experimental-unverified",
                "dsh": "experimental-unverified",
                "opencode": "experimental-unverified",
                "unknown": "bootstrap-only",
        }
        for adapter_id, status in expected.items():
            with self.subTest(adapter=adapter_id):
                self.assertEqual(actual.get(adapter_id), status)
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

    def test_dsh_declares_async_review_and_mcp_boundaries(self):
        adapters = {item["id"]: item for item in load_adapters(
            self.ROOT / "adapters", self.ROOT / "schemas/adapter.schema.json"
        )}
        dsh = adapters["dsh"]
        self.assertEqual(dsh["supportStatus"], "experimental-unverified")
        self.assertIn("global-instructions", dsh["capabilities"])
        self.assertIn("skill-discovery", dsh["capabilities"])
        self.assertIn("independent-context", dsh["capabilities"])
        self.assertIn("mcp-tools", dsh["capabilities"])
        content = (self.ROOT / "adapters/dsh" / dsh["entryFile"]).read_text(encoding="utf-8")
        self.assertIn("send_message", content)
        self.assertIn("mcp__codegraph__", content)
        self.assertIn("subagent_fork", content)

    def test_vendor_entries_keep_the_resolver_optional_for_ordinary_tasks(self):
        adapters = load_adapters(
            self.ROOT / "adapters",
            self.ROOT / "schemas/adapter.schema.json",
        )
        for adapter in adapters:
            with self.subTest(adapter=adapter["id"]):
                content = compose_adapter_policy(self.ROOT / "adapters", adapter["id"])
                self.assertNotEqual(content, "")
                self.assertIn("selfworkflow resolve", content)
                self.assertIn("ordinary tasks", content)
                self.assertIn("follow", content)
                self.assertIn("WORKFLOW.md", content)
                self.assertIn("do not create a PlanGraph or RunLedger", content)
                self.assertIn("explicitly contract-managed", content)
                self.assertIn("conforming Host", content)
                for phrase in (
                    "current-stage", "agent-policy", "workflow/modules/review.md",
                    "actual tool schemas", "not proof", "unverified",
                ):
                    self.assertIn(phrase, content)
                self.assertNotIn("This adapter is a conforming Host", content)

        core = (self.ROOT / "workflow/core.md").read_text(encoding="utf-8")
        self.assertIn("显式契约管理模式", core)
        self.assertIn("普通轻量模式", core)
        self.assertNotIn("修正保持在当前阶段并创建新的 RunLedger", core)

    def test_shared_policy_is_the_single_source_for_portable_text(self):
        shared = (self.ROOT / "adapters/shared/policy.md").read_text(encoding="utf-8")
        self.assertIn("{support-claim}", shared)
        for adapter in load_adapters(
            self.ROOT / "adapters", self.ROOT / "schemas/adapter.schema.json"
        ):
            with self.subTest(adapter=adapter["id"]):
                entry = (
                    self.ROOT / "adapters" / adapter["id"] / adapter["entryFile"]
                ).read_text(encoding="utf-8")
                self.assertNotIn("For ordinary tasks", entry)
                self.assertNotIn("{support-claim}", entry)
                self.assertNotIn("The Reviewer reads only", entry)

    def test_new_host_needs_only_data_not_code_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            schema = Path(temporary) / "schemas/adapter.schema.json"
            schema.parent.mkdir()
            schema.write_bytes((self.ROOT / "schemas/adapter.schema.json").read_bytes())
            root = Path(temporary) / "adapters"
            (root / "shared").mkdir(parents=True)
            (root / "shared" / "policy.md").write_text(
                (self.ROOT / "adapters/shared/policy.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            host = root / "future-host"
            host.mkdir()
            (host / "adapter.yaml").write_text(
                "schemaVersion: 1\nid: future-host\nsupportStatus: experimental-unverified\n"
                "entryFile: FUTURE.managed.md\ncapabilities: [project-instructions]\n"
                "coreOverride: forbidden\noverrideBehavior: managed-file\n",
                encoding="utf-8",
            )
            (host / "FUTURE.managed.md").write_text(
                "Host note.\n", encoding="utf-8"
            )
            self.assertEqual(
                [item["id"] for item in load_adapters(root, schema)], ["future-host"]
            )
            composed = compose_adapter_policy(root, "future-host")
            self.assertIn("Host note.", composed)
            self.assertIn("agent-policy", composed)
            self.assertNotIn("{support-claim}", composed)

    def test_unknown_host_and_bad_input_stay_fail_closed(self):
        self.assertEqual(compose_adapter_policy(self.ROOT / "adapters", "no-such-host"), "")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "broken").mkdir()
            (root / "broken" / "adapter.yaml").write_text(
                "schemaVersion: 1\nid: broken\nsupportStatus: retired\n"
                "entryFile: X.md\ncapabilities: []\ncoreOverride: forbidden\n"
                "overrideBehavior: managed-file\n",
                encoding="utf-8",
            )
            (root / "broken" / "X.md").write_text("note\n", encoding="utf-8")
            (root / "shared").mkdir()
            (root / "shared" / "policy.md").write_text(
                "{support-claim}\n", encoding="utf-8"
            )
            self.assertEqual(compose_adapter_policy(root, "broken"), "")

    def test_composition_rejects_invalid_declarations_before_reading_host_notes(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary)
            entry = write_adapter(artifact, "future-host", "Host note.\n")
            metadata = entry.parent / "adapter.yaml"
            valid = yaml.safe_load(metadata.read_text(encoding="utf-8"))
            for change in (
                {"supportStatus": []},
                {"entryFile": "../../outside.md"},
                {"entryFile": ["HOST.md"]},
                {"coreOverride": "allowed"},
                {"id": "different-host"},
                {"schemaVersion": 2},
                {"capabilities": "independent-context"},
            ):
                with self.subTest(change=change):
                    metadata.write_text(yaml.safe_dump(valid | change), encoding="utf-8")
                    reads = []

                    def read(path):
                        reads.append(path)
                        return path.read_text(encoding="utf-8")

                    self.assertEqual(compose_adapter_policy(
                        artifact / "adapters", "future-host", read=read,
                    ), "")
                    self.assertNotIn(entry, reads)

            metadata.write_text(yaml.safe_dump(valid), encoding="utf-8")
            reads = []
            self.assertEqual(compose_adapter_policy(
                artifact / "adapters", "../future-host", read=read,
            ), "")
            self.assertEqual(reads, [])


if __name__ == "__main__":
    unittest.main()
