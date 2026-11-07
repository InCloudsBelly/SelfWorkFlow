import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from selfworkflow.v3.codegraph_lifecycle import CodeGraphProjectError, CodeGraphProjectLifecycle
from selfworkflow.v3.providers.codegraph import CodeGraphAdapter, CommandResult


class NativeUeReconcileTest(unittest.TestCase):
    def test_backend_profile_authorizes_native_route_after_a_large_config_hint_is_skipped(self):
        calls = []

        class Port:
            def run(self, argv, *, cwd=None):
                calls.append(argv[1])
                if argv[1] == "status":
                    return CommandResult(0, json.dumps({
                        "initialized": True, "ueProfile": True,
                        "index": {"state": "complete"}, "pendingChanges": None,
                    }))
                assert argv[1] == "reconcile-ue"
                return CommandResult(0, json.dumps({
                    "protocol": 1, "status": "fresh", "revision": "a" * 64,
                    "text": "verified UE result",
                    "changes": {"filesAdded": 0, "filesModified": 0, "filesRemoved": 0, "filesChecked": 0},
                }))

        with TemporaryDirectory() as directory, patch.dict(os.environ, {"CODEGRAPH_DIR": ""}):
            root = Path(directory)
            (root / ".codegraph").mkdir()
            (root / ".codegraph/indexing.json").write_text(
                '{"ueEngine":{"plugins":[]}}' + ' ' * (1024 * 1024), encoding="utf-8",
            )
            adapter = CodeGraphAdapter(command_port=Port(), command_prefix=("codegraph",),
                                       ownership="user-local", allow_ue_reconcile=True)
            result = CodeGraphProjectLifecycle(adapter).query(str(root), "Symbol")
            self.assertEqual(result["data"], "verified UE result")
            self.assertEqual(calls, ["status", "reconcile-ue"])

    def test_backend_not_applicable_routes_to_guarded_ordinary_query(self):
        calls = []

        class Port:
            def run(self, argv, *, cwd=None):
                command = argv[1]
                calls.append(command)
                if command == "reconcile-ue":
                    return CommandResult(0, '{"protocol":1,"status":"not-applicable"}')
                if command == "status":
                    return CommandResult(0, '{"initialized":true,"index":{"state":"complete"},"ueProfile":false}')
                return CommandResult(0, "ordinary graph result" if command == "explore" else "")

        cases = [(".codegraph", ["reconcile-ue"])]
        if os.name == "nt":
            cases.append((".codegraph-wsl", []))
        for index_dir, native_calls in cases:
            with self.subTest(index_dir=index_dir), TemporaryDirectory() as directory, patch.dict(os.environ, {"CODEGRAPH_DIR": ""}):
                calls.clear()
                root = Path(directory)
                config = root / index_dir / "indexing.json"
                config.parent.mkdir()
                config.write_text('{"ueEngine":{"plugins":[]}}', encoding="utf-8")
                adapter = CodeGraphAdapter(command_port=Port(), command_prefix=("codegraph",),
                                           ownership="user-local", allow_ue_reconcile=True)
                result = CodeGraphProjectLifecycle(adapter).query(str(root), "Symbol")
                self.assertEqual(result["data"], "ordinary graph result")
                self.assertEqual(calls, native_calls + ["status", "sync", "status", "status", "explore"])

    def test_query_and_edit_each_use_one_verified_native_dispatch(self):
        calls = []
        reply = {
            "protocol": 1,
            "status": "fresh",
            "revision": "a" * 64,
            "changes": {"filesAdded": 0, "filesModified": 1, "filesRemoved": 0, "filesChecked": 1},
        }

        class Port:
            def run(self, argv, *, cwd=None):
                calls.append(argv[1:])
                body = reply | ({"text": "indexed answer"} if any(arg.startswith("--query=") for arg in argv) else {})
                return CommandResult(0, json.dumps(body))

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".codegraph").mkdir()
            (root / ".codegraph/indexing.json").write_text('{"ueEngine":{"plugins":[]}}', encoding="utf-8")
            lifecycle = CodeGraphProjectLifecycle(CodeGraphAdapter(
                command_port=Port(), command_prefix=("codegraph",), ownership="user-local",
                allow_ue_reconcile=True,
            ))
            self.assertEqual(lifecycle.query(str(root), "--status")["data"], "indexed answer")
            self.assertEqual(lifecycle.sync(str(root), ["Engine/a.cpp"])["changedPathCount"], 1)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][0], "reconcile-ue")
            self.assertIn("--query=--status", calls[0])
            self.assertIn("--changed-path=Engine/a.cpp", calls[1])
            count = 2
            if os.name == "nt":
                paths = [f"Engine/{'n' * 250}/{i}.cpp" for i in range(300)]
                self.assertEqual(lifecycle.sync(str(root), paths)["changedPathCount"], len(paths))
                self.assertFalse(any(arg.startswith("--changed-path=") for arg in calls[2]))
                count += 1

            reply["status"] = "unverified"
            reply["reason"] = "index-incomplete"
            with self.assertRaisesRegex(CodeGraphProjectError, "codegraph-index-state-not-complete"):
                lifecycle.query(str(root), "next")
            self.assertEqual(len(calls), count + 1)
            (root / ".codegraph.publication.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(CodeGraphProjectError, "codegraph-publication-recovery-required"):
                lifecycle.query(str(root), "next")
            self.assertEqual(len(calls), count + 1)
