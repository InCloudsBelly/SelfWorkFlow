from pathlib import Path
import unittest


class GraftWorkflowContractTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_code_module_routes_agent_queries_to_official_mcp(self):
        text = (self.ROOT / "workflow/modules/code.md").read_text(encoding="utf-8")

        self.assertIn("官方 Graft MCP", text)
        self.assertIn("graft_check_freshness", text)
        self.assertIn("官方 MCP 是 Agent 查询入口", text)
        self.assertIn("不得运行裸 CLI 查询", text)
        self.assertIn("SelfWorkflow 不复制 Graft", text)

    def test_graft_doc_keeps_manual_cli_outside_formal_evidence(self):
        text = (self.ROOT / "docs/providers/graft.md").read_text(encoding="utf-8")

        self.assertIn("SelfWorkFlow 只负责安装、项目边界、能力门禁、任务路由和更新触发", text)
        self.assertIn("官方 MCP 是 Agent 的主查询入口", text)
        self.assertIn("Host CLI 仅用于安装、预检、显式维护和失败恢复", text)
        self.assertIn("provider graft-preflight", text)
        self.assertIn("provider query", text)

    def test_code_tasks_require_automatic_read_and_post_write_update(self):
        text = (self.ROOT / "workflow/modules/code.md").read_text(encoding="utf-8")

        self.assertIn("代码任务默认先检查官方 Graft MCP", text)
        self.assertIn("修改代码后由 SelfWorkflow 自动发送一次 `agent_write` 事件", text)
        self.assertIn("不启用额外 Watcher、daemon 或第二套图逻辑", text)

        doc = (self.ROOT / "docs/providers/graft.md").read_text(encoding="utf-8")
        self.assertIn("代码任务默认自动检查官方 MCP 和 freshness 并查询", doc)
        self.assertIn("代码写入完成后由 SelfWorkFlow 触发官方 Graft 结构更新", doc)

    def test_explicit_deep_uses_current_agent_binding_without_api_key(self):
        module = (self.ROOT / "workflow/modules/code.md").read_text(encoding="utf-8")
        doc = (self.ROOT / "docs/providers/graft.md").read_text(encoding="utf-8")

        self.assertIn("provider graft-deep", module)
        self.assertIn("model", module)
        self.assertIn("reasoning-effort", module)
        self.assertIn("codex exec", doc)
        self.assertIn("不需要 OpenAI API Key", doc)
        self.assertIn("graft/manifest.json", doc)


if __name__ == "__main__":
    unittest.main()
