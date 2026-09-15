# Graft 写后更新模块

- Agent 修改代码后发送一次 `agent_write`，并用当前 `conversation-id` 调用 Worker；一次任务内合并重复事件，查询、Review 和纯读取不更新。缺少 `conversation-id` 必须失败关闭。固定链路是：`agent_write → global structural Map → conversation-id → bound Topic status →（stale 时）同一次 Host 调用自动用当前模型执行原 scope Topic Deep → 分别复核 global/Topic freshness`。
- Worker 返回的 `globalMap.deep` 必须为 `false`；`nextAction=run-graft-deep` 由 Worker 内部继续执行，不要求主 Agent 另起调用。Topic Deep 必须使用同一 `conversation-id` 与返回的 `topicId`，不得把项目根 `graft/` 当作 Deep 目录；完成前必须收到 fresh 验证，`partial`/`unverified` 只表示可继续对话的明确待重试状态，不得结束为 Graft fresh。
- 全局 Map 与 Topic Deep 独立维护；无 Topic 绑定或本对话已选择 `no-deep-topic` 时只更新全局 Map，不触发 Deep。Topic Deep 只复用已绑定 scope，不扩大到全仓库。
- 更新前后校验项目根目录、文件边界和官方 MCP capability。失败保留旧图并报告 `stale`/`failed`；不得把部分缓存、无 manifest 或未通过 freshness 的结果称为可用。
- SelfWorkFlow 不实现第二套图、Watcher、daemon 或查询逻辑；缺少官方入口时标记 `unverified`，仅在明确报告后允许简单文本定位使用 `rg`，不得把它冒充 Graft 证据。Topic Deep 暂时失败时不得静默切换到 `rg`；可以继续非结构性对话，但必须保留 `retry-topic-deep` 和未验证标记。
