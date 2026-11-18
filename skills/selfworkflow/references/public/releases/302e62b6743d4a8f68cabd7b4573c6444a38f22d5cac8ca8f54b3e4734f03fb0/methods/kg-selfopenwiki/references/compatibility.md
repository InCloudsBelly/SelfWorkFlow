# 显式兼容协议

仅用户明确选择旧 external-agent 或 `legacy_provider` 时加载；默认读取、更新或 Viewer 失败不触发此引用。以实时 MCP schema 和本模块技术契约为准，只传已定义字段。

旧 external-agent：第一调用仍为 `openwiki_status`，须确认 schema 2、`external_agent`、`authRequired=false`、`externalAgent.ready=true`、恢复闭环，以及 verified 的 `update.external-agent.begin` 和 `update.external-agent.reviewed-finalize` 完整 capability 对。顺序是 Writer begin(start) → 只写候选 → prepare_review → 独立 Reviewer → reviewed finalize/publish。失败走冻结的 failure/resume，`needs_clarification` 获取关键确认后再继续。只接受真实结构化 published 事实，不猜 receipt/hash；外部模式不调用 OAuth、provider/model/reasoning 验证。

仅显式选择 `executionMode=legacy_provider` 才使用 `openwiki_setup/openwiki_query/openwiki_update/openwiki_set_default_model`；按实时 schema 携带 exact legacy discriminator 并核对其初始化/认证/模型证据。验证失败不降级或换 provider，不把 legacy 能力冒充默认能力，不虚构 external query。

复用入口的知识确认和 Git 授权边界；兼容协议不自动 commit/push。
