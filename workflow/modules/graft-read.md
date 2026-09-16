# Graft 读取模块

- SelfWorkFlow 只做项目边界、能力门禁和任务路由；官方 Graft MCP/CLI 负责图、查询和 freshness，SelfWorkflow 不复制 Graft 的实现、Watcher 或 daemon。
- 官方 MCP 是 Agent 查询入口；不得运行裸 CLI 查询，也不得用 CLI 结果冒充正式 MCP 证据。唯一例外是 SelfWorkFlow 的 Topic 适配器：它调用同一份已绑定的官方 Graft CLI，并显式传入 `--context-dir`，用于读取对应 Topic 图。
- 普通代码任务优先按需使用官方 Graft MCP 的全局非 Deep Code Map（`graft_repo_map`、`graft_file_api`、`graft_find_code`、`graft_trace_calls`、`graft_find_all`）；全局 `graft/manifest.json` 不是 Topic 流程的前置条件或门禁。查询不得隐式 refresh，也不把 `rg` 作为默认阅读入口。
- 新对话在首次使用代码/Graft 前，先用当前稳定 `conversation-id` 调用 `provider graft-topics`。若存在可选 Topic，列出 `topicId` 与 freshness 让用户选择；用户选择后调用 `provider graft-topic-select --topic-id <id>` 自动绑定。用户明确不需要时调用 `provider graft-topic-select --disable`，本对话持久标记 `no-deep-topic`，后续不再调用 Graft。没有可选 Topic 时只报告“无现有专题”，是否创建新专题或跳过由用户决定。
- Topic 查询不得检查或读取项目根 `graft/`；必须传入当前稳定 `conversation-id`，从项目 `./selfworkflow/graft-deep/.conversation-bindings/` 恢复唯一绑定的 `<topic-id>`，再通过 `provider status/query --conversation-id` 使用该 context。显式 `--context-dir` 仅可作为同一绑定的核对值。绑定缺失、冲突、过期、Provider 不可用或边界无效时失败关闭，不回退到根图；结果必须回显 `conversationId → topicId`。
- Topic status 若返回 `topicFreshness=stale` 或 `topicStaleFiles` 非空，写后 Worker 优先在同一次调用中使用同一 `conversation-id`、当前 Host 模型和 reasoning effort 自动执行 Topic Deep，并将全局 Map 延后；省略 `--scope-file` 复用已绑定 Topic 的历史 scope，只更新该 scope，不扩大范围。刷新完成并重新验证 fresh 前，不得把旧图称为当前证据；自动刷新失败必须显式报告，不得静默回退 `rg`。
- 已绑定 Topic 时，只校验并使用该 Topic 的 context/manifest；不得为 Topic 读取、检查或构建项目根 `graft/manifest.json`。全局 Code Map 缺失或过期只单独标记 `globalMap=unverified`，不阻塞 Topic；仅简单文本定位可在明确报告后临时使用 `rg`，需要新鲜 Topic 结构证据的任务失败关闭。
- Graft 输出只是结构证据，仍需用最窄源码读取确认关键事实；不得把手工读取任一 `graft/` 文件冒充正式 Graft 查询。
