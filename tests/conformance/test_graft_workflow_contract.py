from pathlib import Path
import unittest


class GraftWorkflowContractTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_code_module_routes_agent_queries_to_official_mcp(self):
        text = (self.ROOT / "workflow/modules/code.md").read_text(encoding="utf-8")
        graft_read = (self.ROOT / "workflow/modules/graft-read.md").read_text(encoding="utf-8")
        text = f"{text}\n{graft_read}"

        self.assertIn("官方 Graft MCP", text)
        self.assertIn("graft_check_freshness", text)
        self.assertIn("SelfWorkflow 不复制 Graft", text)
        self.assertIn("官方 MCP 是 Agent 查询入口", text)
        self.assertIn("不得运行裸 CLI 查询", text)
        self.assertIn("SelfWorkflow 不复制 Graft", text)

    def test_graft_doc_keeps_manual_cli_outside_formal_evidence(self):
        text = (self.ROOT / "docs/providers/graft.md").read_text(encoding="utf-8")

        self.assertIn("SelfWorkflow 不复制 Graft", (self.ROOT / "workflow/modules/graft-read.md").read_text(encoding="utf-8"))
        self.assertIn("官方 Graft MCP 是代码阅读入口", text)
        self.assertIn("官方 Graft MCP 是代码阅读入口", text)
        self.assertIn("SelfWorkFlow 只负责项目边界、能力检查、任务路由、写后更新和显式 Deep", text)
        self.assertIn("Host CLI 仅用于安装、预检、事件、Worker、显式维护和失败恢复", text)
        self.assertIn("provider graft-event", text)
        self.assertIn("provider graft-worker", text)

    def test_code_tasks_require_automatic_read_and_post_write_update(self):
        text = (self.ROOT / "workflow/modules/code.md").read_text(encoding="utf-8")
        update = (self.ROOT / "workflow/modules/graft-update.md").read_text(encoding="utf-8")
        text = f"{text}\n{update}"

        self.assertIn("代码任务默认先检查官方 Graft MCP", text)
        self.assertIn("修改代码后由 SelfWorkflow 自动发送一次 `agent_write` 事件", text)
        self.assertIn("不启用额外 Watcher、daemon 或第二套图逻辑", text)

        doc = (self.ROOT / "docs/providers/graft.md").read_text(encoding="utf-8")
        self.assertIn("新代码任务检查官方 MCP 和 `graft_check_freshness`", doc)
        self.assertIn("Agent 修改代码后自动发送一次 `agent_write`", doc)

    def test_explicit_deep_uses_current_agent_binding_without_api_key(self):
        module = (self.ROOT / "workflow/modules/graft-deep.md").read_text(encoding="utf-8")
        doc = (self.ROOT / "docs/providers/graft.md").read_text(encoding="utf-8")

        self.assertIn("provider graft-deep", module)
        self.assertIn("model", module)
        self.assertIn("reasoning-effort", module)
        self.assertIn("codex exec", doc)
        self.assertIn("不需要 OpenAI API Key", doc)
        self.assertIn("topic-id", module)
        self.assertIn("--only-dir", module)
        self.assertIn("manifest.json", module)


if __name__ == "__main__":
    unittest.main()
