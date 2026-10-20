# Agent 接入边界

普通使用优先读取同一份 `public/WORKFLOW.md`，无需新增 Agent id、声明文件或原生 Skill。本文以下 Adapter/schema/组合规则仅用于安装兼容与显式 Host 集成。公共文档的规则与方法通过同版索引直接读取，厂商差异仅保留固定入口的位置与读取方式。

普通文档接入使用 [新 Agent 快速接入](../workflow/onboarding.md) 和 [可选宿主说明模板](../workflow/templates/AGENT_ADAPTER.md)。由宿主实际支持的持久指令加载说明，不接入下面的旧 YAML/组合机制；文档模式的受管入口不会自动消费旧 `adapter_text`。

通用工作流只在 `WORKFLOW.md` 与 `workflow/modules/` 维护。普通任务按当前宿主的真实能力绑定操作，不按 Agent 名称选择一套流程；工具改名不应要求修改通用模块。没有真实差异的新 Agent 可以直接使用 `unknown` bootstrap，不必新增 Adapter。

## 声明与组合

- `shared/policy.md` 只负责宿主能力绑定与通用规则入口；Review、测试、授权与知识规则仍由原模块管理。
- `<id>/adapter.yaml` 声明集成目标、支持状态与差异文件。`capabilities` 是预期接入能力，不是本次会话的验证证据。目录名必须与 `id` 一致。
- `entryFile` 只保存实际宿主差异。工具名只作为提示；可用性、权限、独立上下文与完成状态以当前会话的工具协议和回执为准。不要复制通用流程或维护 Reviewer 工具白名单。
- `compose_adapter_policy()` 使用同一份 `schemas/adapter.schema.json` 校验声明，再组合共享策略、支持状态说明与差异。非法声明或缺失文件返回空串，由消费者拒绝该接入；不能把空串当作已成功加载。

差异文件不能单独作为完整的全局指令安装。消费者先提供 hash-bound snapshot 与 `WORKFLOW.md` bootstrap，再附上组合结果。当前安装器为 Codex 和显式选择的 DSH 执行这一组合；没有共享布局的历史 artifact 维持原来的通用 bootstrap 安装行为。新共享布局下声明的 Codex/DSH Adapter 无法组合时必须拒绝，不能冒充旧布局跳过校验。

## 接入新的 Agent

1. 先用通用 bootstrap 核对实际能力。没有宿主差异时复用 `unknown`，能力缺失仅标记受影响操作，不能伪造通过或擅自降低核心要求。
2. 确有差异时新增 `<id>/adapter.yaml` 与一个简短的差异文件，用现有 schema 和组合函数验证；不增加 Agent 枚举或专属流程分支。
3. 通过真实宿主验证指令发现路径、Skill 发现、工具权限、独立 Review 和完成信号。静态组合测试通过仍保留 `experimental-unverified` 等支持状态。

新增声明只完成策略接入，不自动提供安装器或 MCP 配置写入能力。新的指令路径、配置写入、迁移或卸载需单独验证其 owner、既有内容保护与回滚；当前 `-DshRoot` 是安装器已有的显式接入，不代表任意 Agent 都能自动安装。
