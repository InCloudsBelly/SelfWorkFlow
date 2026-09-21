# Graft 写后更新模块

## 固定调用顺序

未绑定 `Deep Topic` 或已选择 `no-deep-topic`：不调用本模块。已绑定：修改后只调用一次 `graft-sync`，由它完成写入事件、Topic Deep、全局非 Deep Code Map 和 freshness 校验；主 Agent 不拆分、不追加 Worker。

- 收集本次实际变更路径，调用固定入口：`%LOCALAPPDATA%/SelfWorkFlow/bin/selfworkflow.cmd provider graft-sync --project-root <project-root> --conversation-id <current-conversation-id> --changed-path <path>`。缺少身份或路径必须在入队前失败关闭；查询、Review 和纯读取不更新。不得临时拼接 `graft-event`/`graft-worker`，也不得把只读 MCP 当作 Worker。
- Worker 返回的 `globalMap.deep` 必须为 `false`；`nextAction=run-graft-deep` 由同一次 Worker 流程继续执行，不要求主 Agent 另起无关调用。Topic Deep 必须使用同一 `conversation-id` 与返回的 `topicId`，不得把项目根 `graft/` 当作 Deep 目录；完成前必须收到 fresh 验证，`partial`/`unverified` 只表示可继续对话的明确待重试状态，不得结束为 Graft fresh。
- 全局 Map 与 Topic Deep 独立维护，但只有绑定 Topic 的 conversation 才能触发这两层维护。Topic Deep 只复用已绑定 scope，不扩大到全仓库；全局 Map 不是 Topic Deep 的替代入口，也不是未绑定对话的回退入口。
- 全局 Map 更新失败或因 Topic 优先而延后时保留旧 Map、保留待处理事件并返回 `partial`/`retry-global-map`；这项维护不阻塞已绑定 Topic 或主任务。每次 Worker 调用最多尝试一次全局更新，不启动后台重试循环；后续安全 Worker 调用可继续消费队列。Topic 只以自身 context/`manifest.json`/source hash freshness 为依据；不检查、不要求、不等待项目根 `graft/manifest.json`。Topic 失败返回 `retry-topic-deep`，不得把部分缓存或未通过 Topic freshness 的结果称为可用。
- `graft-ensure` 与 `graft-sync` 都在成功前重新检查 Topic 与全局 Map freshness；fresh 时不重复 build。`graft-sync` 只在 Topic 优先导致全局 Map 被明确标记为 `deferred` 时自动做一次收尾；已实际失败的全局构建只保留 `retry-global-map`，不启动重试循环。
- SelfWorkFlow 不实现第二套图、Watcher、daemon 或查询逻辑；缺少官方入口时标记 `unverified`，仅在明确报告后允许简单文本定位使用 `rg`，不得把它冒充 Graft 证据。Topic Deep 暂时失败时不得静默切换到 `rg`；可以继续非结构性对话，但必须保留 `retry-topic-deep` 和未验证标记。
