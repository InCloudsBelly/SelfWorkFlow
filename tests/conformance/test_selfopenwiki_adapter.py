from pathlib import Path
import json
import tempfile
import unittest

import yaml

from selfworkflow.adapters import build_runtime
from selfworkflow import selfopenwiki
from selfworkflow.selfopenwiki import (
    EXTERNAL_CAPABILITIES,
    SelfOpenWikiAdapter,
    SelfOpenWikiError,
    validate_external_status,
)


class _FakeClient:
    def __init__(self, response):
        self.responses = list(response) if isinstance(response, list) else [response]
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.responses.pop(0)


class SelfOpenWikiAdapterTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    @staticmethod
    def status(**overrides):
        value = {
            "ok": True,
            "executionMode": "external_agent",
            "authRequired": False,
            "version": {"contractSchema": 2},
            "externalAgent": {"ready": True, "activeTransaction": None},
            "paths": {
                "openWikiRoot": "D:/SelfOpenWiki/.work/openwiki",
                "runtimeRoot": "D:/wiki_zxh.selfopenwiki",
                "wikiRoot": "D:/wiki_zxh",
            },
            "capabilities": [
                {"id": capability}
                for capability in sorted(EXTERNAL_CAPABILITIES)
            ],
        }
        value.update(overrides)
        return value

    def repo(self, root):
        (root / "Setup.bat").write_text("@echo off\n", encoding="utf-8")
        (root / "Install.bat").write_text("@echo off\n", encoding="utf-8")
        visualizer = root / ".work/openwiki/dist/cli/cli.js"
        visualizer.parent.mkdir(parents=True)
        visualizer.write_text("// fixture\n", encoding="utf-8")

    def test_status_is_first_call_and_requires_external_pair(self):
        client = _FakeClient(self.status())
        result = SelfOpenWikiAdapter(client).status()
        self.assertEqual(result["version"]["contractSchema"], 2)
        self.assertEqual(client.calls, [("openwiki_status", {})])

        for response in (
            self.status(executionMode="legacy_provider"),
            self.status(authRequired=True),
            self.status(capabilities=[{"id": "update.external-agent.begin"}]),
            self.status(externalAgent={"ready": False, "activeTransaction": None}),
        ):
            with self.assertRaises(SelfOpenWikiError):
                validate_external_status(response)

    def test_personal_status_requires_v2_capabilities(self):
        self.assertTrue(hasattr(SelfOpenWikiAdapter, "personal_status"))
        required = set(selfopenwiki.PERSONAL_CAPABILITIES)
        ready = self.status(
            capabilities=[
                {"id": capability}
                for capability in sorted(EXTERNAL_CAPABILITIES | required)
            ]
        )
        client = _FakeClient(ready)
        result = SelfOpenWikiAdapter(client).personal_status()
        self.assertEqual(result["version"]["contractSchema"], 2)
        self.assertEqual(client.calls, [("openwiki_status", {})])
        self.assertEqual(
            SelfOpenWikiAdapter(_FakeClient(ready)).override_wiki_root(),
            "D:/wiki_zxh",
        )

        missing = self.status(
            capabilities=[
                {"id": capability}
                for capability in sorted(EXTERNAL_CAPABILITIES)
            ]
        )
        with self.assertRaisesRegex(SelfOpenWikiError, "personal-capability-missing"):
            selfopenwiki.validate_personal_status(missing)

    def test_personal_call_accepts_only_v2_protocol_and_tool_status(self):
        self.assertTrue(hasattr(SelfOpenWikiAdapter, "personal_call"))
        status = self.status(
            capabilities=[
                {"id": capability}
                for capability in sorted(EXTERNAL_CAPABILITIES | set(selfopenwiki.PERSONAL_CAPABILITIES))
            ]
        )
        result = {
            "ok": True,
            "protocol": "selfopenwiki:personal-openwiki-v1",
            "status": "planning",
        }
        client = _FakeClient([status, result])
        self.assertEqual(
            SelfOpenWikiAdapter(client).personal_call("openwiki_begin", {"mode": "update"}),
            result,
        )
        self.assertEqual(
            client.calls,
            [
                ("openwiki_status", {}),
                ("openwiki_begin", {"mode": "update", "wikiRoot": "D:/wiki_zxh"}),
            ],
        )
        mismatch_client = _FakeClient([status])
        with self.assertRaisesRegex(SelfOpenWikiError, "personal-wiki-root-mismatch"):
            SelfOpenWikiAdapter(mismatch_client).personal_call(
                "openwiki_begin", {"wikiRoot": "D:/other-wiki"}
            )
        with self.assertRaisesRegex(SelfOpenWikiError, "personal-result-invalid"):
            selfopenwiki.validate_personal_result(
                "openwiki_begin", {**result, "protocol": "wrong"}
            )
        with self.assertRaisesRegex(SelfOpenWikiError, "personal-result-invalid"):
            selfopenwiki.validate_personal_result(
                "openwiki_finish", result
            )
        self.assertEqual(
            selfopenwiki.validate_personal_result(
                "openwiki_finish",
                {
                    "ok": False,
                    "error": {
                        "code": "busy",
                        "message": "Busy.",
                        "retryable": True,
                    },
                    "recovery": {"action": "retry"},
                },
            )["ok"],
            False,
        )
        with self.assertRaisesRegex(SelfOpenWikiError, "personal-tool-invalid"):
            selfopenwiki.validate_personal_result("openwiki_status", result)

    def test_external_active_transaction_is_structurally_bound(self):
        active = {
            "transactionId": "tx-1",
            "generation": 1,
            "state": "review_ready",
            "nextAction": "retry_review",
        }
        result = validate_external_status(
            self.status(externalAgent={"ready": True, "activeTransaction": active})
        )
        self.assertEqual(result["externalAgent"]["activeTransaction"], active)
        with self.assertRaisesRegex(SelfOpenWikiError, "external-status-invalid"):
            validate_external_status(
                self.status(
                    externalAgent={
                        "ready": True,
                        "activeTransaction": {**active, "generation": True},
                    }
                )
            )

    def test_install_requires_confirmations_and_does_not_create_or_mutate_wiki(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            repo = root / "SelfOpenWiki"
            wiki = root / "wiki"
            repo.mkdir()
            wiki.mkdir()
            self.repo(repo)
            before = sorted(path.relative_to(wiki).as_posix() for path in wiki.rglob("*"))
            adapter = SelfOpenWikiAdapter(_FakeClient(self.status()))

            with self.assertRaisesRegex(SelfOpenWikiError, "confirm-data-safety-required"):
                adapter.install_command(repo, wiki, confirmed_data_safety=False)
            self.assertEqual(
                before,
                sorted(path.relative_to(wiki).as_posix() for path in wiki.rglob("*")),
            )
            command = adapter.install_command(
                repo, wiki, confirmed_data_safety=True
            )
            self.assertEqual(
                command,
                [str((repo / "Install.bat").resolve()), "--wiki-root",
                 str(wiki.resolve()), "--confirm-data-safety"],
            )
            self.assertFalse((wiki / ".selfopenwiki").exists())

    def test_git_wiki_requires_explicit_git_authorization(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            repo = root / "SelfOpenWiki"
            wiki = root / "wiki"
            repo.mkdir()
            wiki.mkdir()
            (wiki / ".git").mkdir()
            self.repo(repo)
            adapter = SelfOpenWikiAdapter(_FakeClient(self.status()))
            with self.assertRaisesRegex(
                SelfOpenWikiError, "confirm-git-authorization-required"
            ):
                adapter.install_command(repo, wiki, confirmed_data_safety=True)
            command = adapter.install_command(
                repo,
                wiki,
                confirmed_data_safety=True,
                confirmed_git_authorization=True,
            )
            self.assertEqual(command[-1], "--confirm-git-authorization")

    def test_setup_and_visualizer_commands_are_exact_and_nonexecuting(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            repo = root / "SelfOpenWiki"
            wiki = root / "wiki"
            repo.mkdir()
            wiki.mkdir()
            self.repo(repo)
            adapter = SelfOpenWikiAdapter(_FakeClient(self.status()))
            self.assertEqual(
                adapter.setup_command(repo, with_mcp=True),
                [str((repo / "Setup.bat").resolve()), "--with-mcp"],
            )
            self.assertEqual(
                adapter.visualizer_command(repo, wiki),
                [
                    "node",
                    str((repo / ".work/openwiki/dist/cli/cli.js").resolve()),
                    "visualize",
                    str(wiki.resolve()),
                    "--port",
                    "4321",
                    "--no-open",
                ],
            )
            with self.assertRaisesRegex(SelfOpenWikiError, "visualizer-port-invalid"):
                adapter.visualizer_command(repo, wiki, port=0)

    def test_contract_and_knowledge_runtime_contain_no_machine_specific_evidence(self):
        adapter = yaml.safe_load(
            (self.ROOT / "extensions/knowledge/selfopenwiki/adapter.yaml")
            .read_text(encoding="utf-8")
        )
        contract = json.loads(
            (self.ROOT / "extensions/knowledge/selfopenwiki/tool-contract.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(adapter["personalWiki"]["requiredExternalRoot"], True)
        self.assertEqual(contract["status"]["required"]["version.contractSchema"], 2)
        self.assertEqual(contract["externalUpdate"]["legacyFallback"], False)
        self.assertEqual(
            adapter["mcp"]["personalLifecycle"]["protocol"],
            "selfopenwiki:personal-openwiki-v1",
        )
        self.assertEqual(
            adapter["mcp"]["personalLifecycle"]["tools"],
            list(selfopenwiki.PERSONAL_TOOL_NAMES),
        )
        self.assertEqual(
            set(adapter["mcp"]["personalLifecycle"]["requiredCapabilities"]),
            set(selfopenwiki.PERSONAL_CAPABILITIES),
        )
        self.assertEqual(
            adapter["personalWiki"]["overrideRouting"]["source"],
            "openwiki_status.paths.wikiRoot",
        )
        self.assertEqual(
            adapter["hostBinding"],
            {
                "entrypoint": "selfworkflow.selfopenwiki:SelfOpenWikiAdapter",
                "callBoundary": "personal_call",
                "statusBoundary": "personal_status",
            },
        )
        self.assertEqual(
            contract["personalLifecycle"]["tools"],
            list(selfopenwiki.PERSONAL_TOOL_NAMES),
        )
        self.assertEqual(
            set(contract["personalLifecycle"]["requiredCapabilities"]),
            set(selfopenwiki.PERSONAL_CAPABILITIES),
        )
        self.assertEqual(
            contract["personalLifecycle"]["overrideRouting"]["source"],
            "openwiki_status.paths.wikiRoot",
        )
        self.assertIn("openwiki_finish", contract["personalLifecycle"]["sequence"])
        for path in (
            self.ROOT / "extensions/knowledge/selfopenwiki/adapter.yaml",
            self.ROOT / "extensions/knowledge/selfopenwiki/tool-contract.json",
            self.ROOT / "skills/kg-selfopenwiki/SKILL.md",
        ):
            content = path.read_text(encoding="utf-8").casefold()
            self.assertNotIn("credentials.json", content)
            self.assertNotIn("verified-capabilities", content)
            self.assertNotIn("c:\\users\\", content)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            runtime = build_runtime(
                self.ROOT, Path(temporary) / "knowledge", "0.1.0.dev0", profile="knowledge"
            )
            self.assertEqual(runtime["profile"], "knowledge")
            self.assertTrue(
                (Path(temporary) / "knowledge/extensions/knowledge/selfopenwiki/adapter.yaml").is_file()
            )
            self.assertTrue(
                (Path(temporary) / "knowledge/skills/kg-selfopenwiki/SKILL.md").is_file()
            )


if __name__ == "__main__":
    unittest.main()
