# Graft 写后更新模块

## 固定调用顺序

已有可用 Map 且未明确禁用时，无论是否绑定 Topic，Agent 修改阶段结束后自动调用一次 `graft-sync`。覆盖编辑、撤回/回滚、删除、重命名（新旧路径）及 Agent 代码恢复；记录实际操作路径，不只看最终 Git diff（撤回后可为空）。只维护全局非 Deep Code Map，不触发或检查 Deep。

外部编辑/分支切换或来源不明的 stale：`graft-ensure` 只读检查，询问后才加 `--allow-update`；用户主动要求刷新视为本次确认。缺失图不自动初始化。不是后台监听：下次读取前发现外部漂移；构建期间再次变化不得称为 fresh。

- 收集本次实际变更路径，调用固定入口：`%LOCALAPPDATA%/SelfWorkFlow/bin/selfworkflow.cmd provider graft-sync --project-root <project-root> --conversation-id <current-conversation-id> --changed-path <path>`。缺少身份或路径必须在入队前失败关闭；查询、Review 和纯读取不更新。不得临时拼接 `graft-event`/`graft-worker`，也不得把只读 MCP 当作 Worker。
- Worker 返回的 `globalMap.deep` 必须为 `false`；正常 Worker 不返回 `run-graft-deep`，也不检查 Topic。全局 Map 更新失败保留队列并返回 `partial`/`retry-global-map`，不伪造 fresh、不静默回退 `rg`。
- Deep Topic 与全局 Map 独立维护。只有用户明确要求 Deep 时才由主 Agent 调用 `graft-deep`；Reviewer 不调用 Graft/provider。Deep 失败不得改变全局 Map 状态。
- `graft-ensure` 与 `graft-sync` 只在成功前重新检查全局 Map freshness；fresh 时不重复 build，不创建后台重试循环。
- SelfWorkFlow 不实现第二套图、Watcher、daemon 或查询逻辑；缺少官方写入入口时标记 `unverified`，不得改用官方只读 MCP、根图 freshness 或裸 CLI 冒充更新成功。仅在明确报告后允许简单文本定位使用 `rg`；Topic Deep 或全局 Map 任一层暂时失败时不得静默切换到 `rg`，必须保留对应的 `retry-topic-deep` 或 `retry-global-map`。
