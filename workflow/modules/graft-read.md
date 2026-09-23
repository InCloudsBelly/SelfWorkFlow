# Graft 读取模块

官方 MCP 是 Agent 查询入口；SelfWorkflow 只做边界、freshness 和写后路由。

## 唯一路由

已有可用且 fresh 的全局非 Deep Code Map 自动使用，无须启用记录或 Topic 绑定。明确 `--disable`（旧 `no-deep-topic` 禁用记录）仍尊重；缺失不自动初始化，继续原有 Light/Full/Deep 流程。

- 每个代码读取阶段调用固定 Host 入口 `provider graft-ensure --project-root <绝对路径> --conversation-id <当前ID>`；默认只检查全局结构图。fresh 直接查询；stale/外部编辑/分支切换导致漂移时询问更新，同意后加 `--allow-update` 并验证 fresh。拒绝时说明限制，用 `rg` 文本定位，不把旧图当新证据。
- 官方 Graft MCP 是 Agent 查询入口；不得运行裸 CLI 查询。SelfWorkflow 不复制 Graft 的图、Watcher 或 daemon。普通查询只用全局非 Deep Map，不传 Topic context，不读任何 Deep manifest。查询期间再次漂移也先询问，不永久缓存 fresh。
- 普通路径不读取根图、不构建全局 Map 的 Deep 版本。
- 修改后一次 `graft-sync`，详见 `graft-update.md`；fresh 不重复 build，失败保留真实状态。
- 只有用户明确要求 Deep 时加载 `graft-deep.md`：用 `provider graft-topics` 恢复/列出 Topic，必要时 `provider graft-topic-select --topic-id <id>`。Topic 查询不得检查或读取项目根 `graft/`；使用绑定的 `conversation-id` 与 `--context-dir`，回显 `conversationId → topicId`。`topicStaleFiles` 仅按原 scope 处理，不扩大范围。
- 图只是索引证据，关键结论仍核对最窄源码；未覆盖目标/能力不可用时说明限制，允许 `rg` 补充。Reviewer 不调用 Graft/provider。
