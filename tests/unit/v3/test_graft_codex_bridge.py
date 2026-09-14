import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch


class CodexGraftBridgeTests(unittest.TestCase):
    def _request(self, model="gpt-5.6-luna"):
        return {
            "model": model,
            "messages": [
                {"role": "system", "content": "Summarize the supplied code."},
                {"role": "user", "content": "File: src/main.cpp\n\nint main() {}"},
            ],
            "tools": [{
                "type": "function",
                "function": {
                    "name": "record_graph",
                    "description": "Record graph nodes.",
                    "parameters": {"type": "object"},
                },
            }],
            "tool_choice": {
                "type": "function",
                "function": {"name": "record_graph"},
            },
        }

    def test_bridge_preserves_tool_response_and_binds_model_effort(self):
        from selfworkflow.v3.graft_codex_bridge import CodexGraftBridge

        calls = []

        def codex_runner(prompt, project_root, model, reasoning_effort):
            calls.append({
                "prompt": prompt,
                "model": model,
                "reasoning_effort": reasoning_effort,
                "project_root": project_root,
            })
            return {
                "content": "",
                "tool_calls": [{
                    "id": "call-1",
                    "name": "record_graph",
                    "arguments": {"nodes": []},
                }],
            }

        bridge = CodexGraftBridge(
            project_root=Path("C:/repo"),
            model="gpt-5.6-luna",
            reasoning_effort="xhigh",
            codex_runner=codex_runner,
        )

        response = bridge.complete(self._request())

        self.assertEqual(calls[0]["model"], "gpt-5.6-luna")
        self.assertEqual(calls[0]["reasoning_effort"], "xhigh")
        self.assertIn("record_graph", calls[0]["prompt"])
        self.assertIn("copy only the exact text between 'id=' and the first ' |'", calls[0]["prompt"])
        self.assertEqual(response["choices"][0]["message"]["tool_calls"][0]["function"], {
            "name": "record_graph",
            "arguments": '{"nodes":[]}',
        })
        self.assertEqual(response["model"], "gpt-5.6-luna")

    def test_bridge_rejects_missing_or_mismatched_model(self):
        from selfworkflow.v3.graft_codex_bridge import BridgeError, CodexGraftBridge

        bridge = CodexGraftBridge(
            project_root=Path("C:/repo"),
            model="gpt-5.6-luna",
            reasoning_effort="xhigh",
            codex_runner=lambda *args: {},
        )
        request = self._request(model="gpt-5.6-sol")

        with self.assertRaisesRegex(BridgeError, "graft-bridge-model-mismatch"):
            bridge.complete(request)

        request.pop("model")
        with self.assertRaisesRegex(BridgeError, "graft-bridge-request-invalid"):
            bridge.complete(request)

    def test_bridge_rejects_malformed_codex_result(self):
        from selfworkflow.v3.graft_codex_bridge import BridgeError, CodexGraftBridge

        bridge = CodexGraftBridge(
            project_root=Path("C:/repo"),
            model="gpt-5.6-luna",
            reasoning_effort="xhigh",
            codex_runner=lambda *args: {"content": "not enough"},
        )

        with self.assertRaisesRegex(BridgeError, "codex-output-invalid"):
            bridge.complete(self._request())

    def test_production_codex_command_receives_model_and_reasoning_effort(self):
        from selfworkflow.v3.graft_codex_bridge import _invoke_codex

        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = tuple(argv)
            schema = json.loads(Path(argv[argv.index("--output-schema") + 1]).read_text(encoding="utf-8"))
            arguments_schema = schema["properties"]["tool_calls"]["items"]["properties"]["arguments"]
            self.assertEqual(arguments_schema["type"], "string")
            self.assertEqual(arguments_schema["maxLength"], 4 * 1024 * 1024)
            output = Path(argv[argv.index("--output-last-message") + 1])
            output.write_text(
                json.dumps({"content": "ok", "tool_calls": []}),
                encoding="utf-8",
            )
            return type("Result", (), {"returncode": 0})()

        with patch(
            "selfworkflow.v3.graft_codex_bridge.subprocess.run",
            side_effect=fake_run,
        ):
            result = _invoke_codex(
                "prompt", Path("C:/repo"), "gpt-5.6-luna", "xhigh",
            )

        self.assertEqual(result["content"], "ok")
        self.assertIn("--model", captured["argv"])
        self.assertEqual(captured["argv"][captured["argv"].index("--model") + 1], "gpt-5.6-luna")
        self.assertIn('model_reasoning_effort="xhigh"', captured["argv"])
        self.assertIn("--sandbox", captured["argv"])
        self.assertIn("read-only", captured["argv"])
        self.assertIn("--ephemeral", captured["argv"])

    def test_bridge_parses_json_encoded_tool_arguments(self):
        from selfworkflow.v3.graft_codex_bridge import CodexGraftBridge

        bridge = CodexGraftBridge(
            project_root=Path("C:/repo"),
            model="gpt-5.6-luna",
            reasoning_effort="xhigh",
            codex_runner=lambda *args: {
                "content": "",
                "tool_calls": [{
                    "id": "call-1",
                    "name": "record_graph",
                    "arguments": '{"nodes":[]}',
                }],
            },
        )

        response = bridge.complete(self._request())

        self.assertEqual(
            response["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"],
            '{"nodes":[]}',
        )

    def test_http_bridge_is_loopback_and_token_bound(self):
        from selfworkflow.v3.graft_codex_bridge import CodexGraftBridge

        bridge = CodexGraftBridge(
            project_root=Path("C:/repo"),
            model="gpt-5.6-luna",
            reasoning_effort="xhigh",
            codex_runner=lambda *args: {
                "content": "",
                "tool_calls": [{
                    "id": "call-1", "name": "record_graph", "arguments": {},
                }],
            },
        )
        bridge.start()
        self.addCleanup(bridge.close)
        self.assertTrue(bridge.base_url.startswith("http://127.0.0.1:"))

        body = json.dumps(self._request()).encode("utf-8")
        bad = Request(
            bridge.base_url + "/chat/completions",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer wrong"},
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(bad, timeout=2)
        self.assertEqual(caught.exception.code, 401)
        caught.exception.close()

        good = Request(
            bridge.base_url + "/chat/completions",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {bridge.token}",
            },
        )
        with urlopen(good, timeout=2) as response:
            payload = json.load(response)
        self.assertIsNone(payload["choices"][0]["message"]["content"])
        self.assertEqual(payload["choices"][0]["finish_reason"], "tool_calls")

    def test_deep_run_forwards_dynamic_binding_and_requires_fresh_check(self):
        from selfworkflow.v3.graft_codex_bridge import run_codex_graft_deep

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            source = root / "Source" / "main.cpp"
            source.parent.mkdir()
            source.write_text("int main() {}", encoding="utf-8")
            calls = []

            def process_runner(argv, *, cwd, env, input_text, timeout):
                calls.append({"argv": tuple(argv), "cwd": cwd, "env": env, "input": input_text})
                if "build" in argv:
                    self.assertEqual(env["GRAFT_MODEL"], "gpt-5.6-luna")
                    self.assertEqual(env["GRAFT_BASE_URL"].split("://")[0], "http")
                    body = json.dumps(self._request()).encode("utf-8")
                    request = Request(
                        env["GRAFT_BASE_URL"] + "/chat/completions",
                        data=body,
                        method="POST",
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {env['GRAFT_API_KEY']}",
                        },
                    )
                    with urlopen(request, timeout=2) as response:
                        self.assertEqual(json.load(response)["choices"][0]["finish_reason"], "tool_calls")
                    context = Path(argv[argv.index("--dir") + 1])
                    (context / "manifest.json").parent.mkdir(parents=True, exist_ok=True)
                    (context / "manifest.json").write_text("{}", encoding="utf-8")
                    return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
                return type("Result", (), {
                    "returncode": 0,
                    "stdout": json.dumps({
                        "context": {"ok": True, "missing": False},
                        "graph": {"ok": True, "missing": False},
                    }),
                    "stderr": "",
                })()

            result = run_codex_graft_deep(
                graft_command=("node", "C:/graft/dist/cli.js"),
                project_root=root,
                model="gpt-5.6-luna",
                reasoning_effort="xhigh",
                topic_id="kgpr-coverage",
                scope_files=("Source/main.cpp",),
                process_runner=process_runner,
                codex_runner=lambda *args: {
                    "content": "",
                    "tool_calls": [{
                        "id": "call-1", "name": "record_graph", "arguments": {},
                    }],
                },
            )

        self.assertEqual(result["status"], "succeeded")
        self.assertIn("--deep", calls[0]["argv"])
        self.assertEqual(Path(calls[0]["cwd"]).resolve(), root.resolve())
        self.assertIn("--dir", calls[0]["argv"])
        self.assertNotEqual(Path(calls[0]["argv"][calls[0]["argv"].index("--dir") + 1]).resolve(), (root / "graft").resolve())
        self.assertEqual(
            calls[0]["argv"][calls[0]["argv"].index("--only-dir") + 1],
            "Source/main.cpp",
        )
        self.assertEqual(result["topicId"], "kgpr-coverage")
        self.assertEqual(result["scopeFiles"], ["Source/main.cpp"])
        self.assertNotIn("OPENAI_API_KEY", calls[0]["env"])

    def test_deep_run_never_reports_success_for_stale_check(self):
        from selfworkflow.v3.graft_codex_bridge import run_codex_graft_deep

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            source = root / "Source" / "main.cpp"
            source.parent.mkdir()
            source.write_text("int main() {}", encoding="utf-8")

            def process_runner(argv, **_kwargs):
                if "build" in argv:
                    return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
                return type("Result", (), {
                    "returncode": 1,
                    "stdout": json.dumps({
                        "context": {"ok": True, "missing": False},
                        "graph": {"ok": False, "missing": False},
                    }),
                    "stderr": "",
                })()

            result = run_codex_graft_deep(
                graft_command=("node", "C:/graft/dist/cli.js"),
                project_root=root,
                model="gpt-5.6-luna",
                reasoning_effort="xhigh",
                topic_id="kgpr-coverage",
                scope_files=("Source/main.cpp",),
                process_runner=process_runner,
                codex_runner=lambda *args: {"content": "ok", "tool_calls": []},
            )

        self.assertEqual(result, {
            "status": "failed",
            "reason": "graft-deep-not-fresh",
            "retryable": True,
        })

    def test_deep_run_rejects_unbounded_or_unsafe_topic_scope(self):
        from selfworkflow.v3.graft_codex_bridge import BridgeError, run_codex_graft_deep

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            source = root / "Source" / "main.cpp"
            source.parent.mkdir()
            source.write_text("int main() {}", encoding="utf-8")
            cases = (
                {"topic_id": "", "scope_files": ("Source/main.cpp",)},
                {"topic_id": "../all", "scope_files": ("Source/main.cpp",)},
                {"topic_id": "topic", "scope_files": ()},
                {"topic_id": "topic", "scope_files": ("../outside.cpp",)},
                {"topic_id": "topic", "scope_files": ("missing.cpp",)},
            )
            for case in cases:
                with self.subTest(case=case), self.assertRaises(BridgeError):
                    run_codex_graft_deep(
                        graft_command=("node", "C:/graft/dist/cli.js"),
                        project_root=root,
                        model="gpt-5.6-luna",
                        reasoning_effort="xhigh",
                        process_runner=lambda *args, **kwargs: None,
                        codex_runner=lambda *args: {},
                        **case,
                    )

    def test_deep_run_does_not_publish_topic_manifest_when_scope_drifts(self):
        from selfworkflow.v3.graft_codex_bridge import run_codex_graft_deep

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            source = root / "Source" / "main.cpp"
            source.parent.mkdir()
            source.write_text("int main() {}", encoding="utf-8")

            def process_runner(argv, **_kwargs):
                if "build" in argv:
                    source.write_text("int main() { return 1; }", encoding="utf-8")
                    context = Path(argv[argv.index("--dir") + 1])
                    context.mkdir(parents=True, exist_ok=True)
                    (context / "manifest.json").write_text("{}", encoding="utf-8")
                    return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
                return type("Result", (), {
                    "returncode": 0,
                    "stdout": json.dumps({
                        "context": {"ok": True}, "graph": {"ok": True},
                    }),
                    "stderr": "",
                })()

            result = run_codex_graft_deep(
                graft_command=("node", "C:/graft/dist/cli.js"),
                project_root=root,
                model="gpt-5.6-luna",
                reasoning_effort="xhigh",
                topic_id="kgpr-coverage",
                scope_files=("Source/main.cpp",),
                process_runner=process_runner,
                codex_runner=lambda *args: {"content": "ok", "tool_calls": []},
            )
            topic_manifest = root / ".selfworkflow/graft-deep/kgpr-coverage/selfworkflow-topic.json"
            self.assertFalse(topic_manifest.exists())

        self.assertEqual(result["reason"], "graft-deep-source-changed")


if __name__ == "__main__":
    unittest.main()
