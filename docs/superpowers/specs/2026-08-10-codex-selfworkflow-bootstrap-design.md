# Codex SelfWorkflow 启动入口设计

## 问题

Codex 启动时保证读取用户级 `AGENTS.md`，但不会保证自动展开其中引用的其他 Markdown。当前安装器只在受管理块中写入 `Read ... WORKFLOW.md`，因此轻量核心是否真正进入任务上下文依赖 Agent 再执行一次文件读取。

## 决策

Codex 适配器把已安装 artifact 的轻量 `WORKFLOW.md` 正文直接内联到用户级 `AGENTS.md` 受管理块。受管理块同时保留 artifact hash、profile 和 snapshot 路径，只有显式契约管理或诊断需要读取 snapshot 中的其他文件。

普通任务直接执行内联策略，不创建 PlanGraph 或 RunLedger。项目级规则可以增加约束，但不能静默关闭全局安全底线。为避免日常噪声，不要求只读短问答额外打印启动横幅；使用工具、修改文件或产生副作用时，首条进度更新应简短报告 `SelfWorkflow active: <profile>`。

## 边界

- 不新增启动脚本、路由器或后台进程。
- 不要求每个任务读取 `current.json`。
- 不修改用户在 managed block 外的内容。
- 不把完整 Catalog、PlanGraph、RunLedger 或知识扩展内联进 `AGENTS.md`。
- 安装或升级仍通过事务安装器更新 managed block；旧任务需重新启动才能获得新指令链。

## 验收

1. 安装后的 managed block 含 artifact `WORKFLOW.md` 的核心规则，而不只是外部引用。
2. managed block 记录 artifact hash、profile 和 snapshot，且普通模式无需读取它们即可工作。
3. 重复安装保持幂等；artifact 工作流变化会刷新 managed block。
4. 用户原有 `AGENTS.md` 内容保持逐字不变。
5. 安装器计划、应用、回滚和运行时快照相关回归通过。
