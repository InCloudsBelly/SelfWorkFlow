# 代码模块

命中代码、配置消费者、持久化、跨层行为、Bug、重构或 C/C++/UE 任务时加载。

- 先追踪最小完整链路：输入 → owner → 状态/缓存/临时产物 → 输出；区分 root cause owner 与 detection point，优先在最早拥有不变量的层修复。
- 以影响半径判断侵入性，不以行数判断。公共 API/ABI/Schema、持久化、全局宏/Build variant、共享热路径和非必要调用者是高风险信号；先比较更窄方案。
- 仅对 C/C++/UE 任务默认加载 `cpp-core`，再按类型、并发、ABI、性能、安全、构建或 UE 信号读取专项引用；其他代码任务不加载。测试不得反向推动生产架构。
- 代码任务默认先检查官方 Graft MCP 能力与当前项目根目录，再调用 `graft_check_freshness`。工具可用且图新鲜时优先直接使用官方 MCP；按任务选择 `graft_find_code`、`graft_file_api`、`graft_trace_calls`、`graft_find_all`、`graft_repo_map`。SelfWorkflow 不复制 Graft 的图、查询或文档逻辑，只做项目边界、freshness 和失败门禁。缺少 MCP、图过期或目标未覆盖时返回 `unverified`，普通任务可回退 `rg`；需要新鲜图证据的任务失败关闭。
- 安装器将官方 `graft mcp <当前工作目录>` 注册到 Codex，并把图保留在当前项目的 `graft/`。不得运行裸 CLI 查询、手工解析 `graft/` 或把固定项目路径写进全局配置；官方 MCP 是 Agent 查询入口。SelfWorkflow Host CLI `%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd` 仅用于预检、维护和故障恢复。
- 修改代码后由 SelfWorkflow 自动发送一次 `agent_write` 事件并触发官方 Graft 的结构更新；MCP 本身没有写入工具，更新通过锁定版本的官方 `graft build` 完成。事件和 Worker 都先通过项目边界与 Provider runtime 门禁，失败保留旧图和可重试队列；不启用额外 Watcher、daemon 或第二套图逻辑。查询、读取、Review 和测试读取不发送事件。
- 用户或任务明确要求 Graft Deep 时，仅主 Agent 可把本次对话实际使用的 `model` 与 `reasoning-effort` 显式传给 `provider graft-deep`；必须在创建任何 Review SubAgent 前完成并绑定 evidence。Reviewer 不得调用 Graft 查询、Deep、event、worker 或 provider 维护；缺少或不匹配的模型信息、Codex 失败、Deep 输出不完整或 freshness 校验失败均为 `unverified`，不得猜测模型或降级成结构构建。
- 行为变更必须记录 TDD RED/GREEN、失败路径、状态不变量和最窄回归；不扩大稳定调用者或无关模块。
