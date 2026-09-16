# Graft 写后更新模块

- Agent 修改代码后发送一次 `agent_write`，并用当前 `conversation-id` 调用 Worker；一次任务内合并重复事件，查询、Review 和纯读取不更新。缺少 `conversation-id` 必须失败关闭。Worker 先检查绑定 Topic 的 manifest/source hash：Topic stale 时先保留事件并让同一次 Host 调用执行原 scope Topic Deep，暂缓可能很慢的全局 Map；Topic fresh 时才尝试独立的全局非 Deep Code Map。全局 Map 不是 Topic Deep 的前置条件。
- Worker 返回的 `globalMap.deep` 必须为 `false`；`nextAction=run-graft-deep` 由同一次 Worker 流程继续执行，不要求主 Agent 另起无关调用。Topic Deep 必须使用同一 `conversation-id` 与返回的 `topicId`，不得把项目根 `graft/` 当作 Deep 目录；完成前必须收到 fresh 验证，`partial`/`unverified` 只表示可继续对话的明确待重试状态，不得结束为 Graft fresh。
- 全局 Map 与 Topic Deep 独立维护；无 Topic 绑定或本对话已选择 `no-deep-topic` 时只更新全局 Map，不触发 Deep。Topic Deep 只复用已绑定 scope，不扩大到全仓库。
- 全局 Map 更新失败或因 Topic 优先而延后时保留旧 Map、保留待处理事件并返回 `partial`/`retry-global-map`；这项维护不阻塞已绑定 Topic 或主任务。每次 Worker 调用最多尝试一次全局更新，不启动后台重试循环；后续安全 Worker 调用可继续消费队列。Topic 只以自身 context/`manifest.json`/source hash freshness 为依据；不检查、不要求、不等待项目根 `graft/manifest.json`。Topic 失败返回 `retry-topic-deep`，不得把部分缓存或未通过 Topic freshness 的结果称为可用。
- SelfWorkFlow 不实现第二套图、Watcher、daemon 或查询逻辑；缺少官方入口时标记 `unverified`，仅在明确报告后允许简单文本定位使用 `rg`，不得把它冒充 Graft 证据。Topic Deep 暂时失败时不得静默切换到 `rg`；可以继续非结构性对话，但必须保留 `retry-topic-deep` 和未验证标记。
