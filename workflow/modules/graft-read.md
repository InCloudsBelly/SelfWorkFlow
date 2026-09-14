# Graft 读取模块

- SelfWorkFlow 只做项目根目录、MCP capability 和 freshness 门禁；官方 Graft MCP 负责查询，SelfWorkflow 不复制 Graft 的图、查询、Watcher 或 daemon。
- 官方 MCP 是 Agent 查询入口；不得运行裸 CLI 查询，也不得用 CLI 结果冒充正式 MCP 证据。
- 代码任务先检查 `graft_check_freshness`，再按需使用 `graft_repo_map`、`graft_file_api`、`graft_find_code`、`graft_trace_calls`、`graft_find_all`。查询不得隐式 refresh。
- 图必须由官方 MCP 绑定到当前项目的 `graft/`；只接受项目内、可验证且新鲜的图。图缺失、过期、Provider 不可用或边界无效时，普通任务明确标记并回退 `rg`；需要 Graft 证据的任务失败关闭。
- Graft 输出只是结构证据，仍需用最窄源码读取确认关键事实；不得把手工读取 `graft/` 文件冒充正式 Graft 查询。
