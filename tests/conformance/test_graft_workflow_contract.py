from pathlib import Path
import unittest


class GraftWorkflowContractTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_code_module_routes_agent_queries_to_official_mcp(self):
        text = (self.ROOT / "workflow/modules/code.md").read_text(encoding="utf-8")
        graft_read = (self.ROOT / "workflow/modules/graft-read.md").read_text(encoding="utf-8")
        text = f"{text}\n{graft_read}"

        self.assertIn("官方 Graft MCP", text)
        self.assertIn("全局非 Deep Code Map", text)
        self.assertIn("SelfWorkflow 不复制 Graft", text)
        self.assertIn("官方 MCP 是 Agent 查询入口", text)
        self.assertIn("不得运行裸 CLI 查询", text)
        self.assertIn("SelfWorkflow 不复制 Graft", text)
        self.assertIn("--context-dir", graft_read)
        self.assertIn("conversation-id", graft_read)
        self.assertIn("conversationId → topicId", graft_read)
        self.assertIn("topicStaleFiles", graft_read)
        self.assertIn("省略 `--scope-file` 复用", graft_read)
        self.assertIn("Topic 查询不得检查或读取项目根 `graft/`", graft_read)
        self.assertIn("provider graft-topics", graft_read)
        self.assertIn("provider graft-topic-select --topic-id", graft_read)
        self.assertIn("--disable", graft_read)
        self.assertIn("no-deep-topic", graft_read)

    def test_graft_doc_keeps_manual_cli_outside_formal_evidence(self):
        text = (self.ROOT / "docs/providers/graft.md").read_text(encoding="utf-8")

        self.assertIn("SelfWorkflow 不复制 Graft", (self.ROOT / "workflow/modules/graft-read.md").read_text(encoding="utf-8"))
        self.assertIn("官方 Graft MCP 是代码阅读入口", text)
        self.assertIn("官方 Graft MCP 是代码阅读入口", text)
        self.assertIn("SelfWorkFlow 只负责项目边界、能力检查、任务路由、写后更新和显式 Deep", text)
        self.assertIn("Host CLI 仅用于安装、预检、事件、Worker、显式维护和失败恢复", text)
        self.assertIn("provider graft-event", text)
        self.assertIn("provider graft-worker", text)
        self.assertIn("topicRefresh", text)
        self.assertIn("`rg` 不是默认阅读入口", text)

    def test_code_tasks_require_automatic_read_and_post_write_update(self):
        text = (self.ROOT / "workflow/modules/code.md").read_text(encoding="utf-8")
        update = (self.ROOT / "workflow/modules/graft-update.md").read_text(encoding="utf-8")
        text = f"{text}\n{update}"

        self.assertIn("代码任务优先使用官方 Graft MCP 的全局非 Deep Code Map", text)
        self.assertIn("修改代码后由 SelfWorkflow 自动发送一次 `agent_write` 事件", text)
        self.assertIn("conversation-id", text)
        self.assertIn("全局非 Deep Code Map", text)
        self.assertIn("Topic Deep", text)
        self.assertIn("同一次 Host", text)
        self.assertIn("retry-topic-deep", text)
        self.assertIn("不启用额外 Watcher、daemon 或第二套图逻辑", text)

        doc = (self.ROOT / "docs/providers/graft.md").read_text(encoding="utf-8")
        self.assertIn("新代码任务优先按需使用官方 MCP 的全局非 Deep Code Map", doc)
        self.assertIn("Agent 修改代码后自动发送一次 `agent_write`", doc)
        self.assertIn("topicRefresh", doc)
        self.assertIn("--conversation-id", doc)
        self.assertIn("全局 Map", doc)
        self.assertIn("Topic Deep", doc)
        self.assertIn("`rg` 不是默认阅读入口", doc)

    def test_explicit_deep_uses_current_agent_binding_without_api_key(self):
        module = (self.ROOT / "workflow/modules/graft-deep.md").read_text(encoding="utf-8")
        doc = (self.ROOT / "docs/providers/graft.md").read_text(encoding="utf-8")

        self.assertIn("provider graft-deep", module)
        self.assertIn("model", module)
        self.assertIn("reasoning-effort", module)
        self.assertIn("codex exec", doc)
        self.assertIn("不需要 OpenAI API Key", doc)
        self.assertIn("topic-id", module)
        self.assertIn("conversation-id", module)
        self.assertIn("绑定写入项目", module)
        self.assertIn("新对话先发现已有 Topic", module)
        self.assertIn("no-deep-topic", module)
        self.assertIn("conversationId=<当前对话 ID> → topicId=<绑定专题>", module)
        self.assertIn("复用该 Topic manifest 的 scope", module)
        self.assertIn("--only-dir", module)
        self.assertIn("manifest.json", module)
        self.assertIn("quoted local `#include`", module)
        self.assertIn("`.inl`", module)
        self.assertIn("--concurrency 1", module)

    def test_topic_model_metadata_is_explicitly_historical(self):
        module = (self.ROOT / "workflow/modules/graft-deep.md").read_text(encoding="utf-8")
        doc = (self.ROOT / "docs/providers/graft.md").read_text(encoding="utf-8")
        readme = (self.ROOT / "README.md").read_text(encoding="utf-8")
        text = f"{module}\n{doc}\n{readme}"

        self.assertIn("`lastRun.model`/`lastRun.reasoningEffort`", text)
        self.assertIn("只表示上次执行", text)
        self.assertIn("不得覆盖本次当前 Host 模型", text)
        self.assertIn("they are not defaults", text)

    def test_deep_model_is_host_context_not_user_configuration(self):
        module = (self.ROOT / "workflow/modules/graft-deep.md").read_text(encoding="utf-8")
        doc = (self.ROOT / "docs/providers/graft.md").read_text(encoding="utf-8")
        readme = (self.ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("模型不是用户输入", module)
        self.assertIn("SELFWORKFLOW_HOST_CURRENT_MODEL", module)
        self.assertIn("SELFWORKFLOW_HOST_CURRENT_REASONING_EFFORT", module)
        self.assertIn("自动注入当前 conversation", doc)
        self.assertIn("users do not choose them", readme)
        self.assertIn("fails closed", readme)


if __name__ == "__main__":
    unittest.main()
