# 可选工作流增强

仅用户明确选择时启用以下模块；不得根据任务大小、文件名或项目默认值自动启用。

下表的只读、不落盘和前置条件只约束对应增强模块的调用，不限制其他 owner 已获授权的普通任务；缺失增强能力不阻塞无关模块。

| 模块 | 阶段 / slot | 执行入口 | 边界 |
| --- | --- | --- | --- |
| `tea-framework` | Plan / `plan.assessment` | [skills/tea-quality/SKILL.md](../../skills/tea-quality/SKILL.md) → framework | 只读评估已有框架、测试约定、命令与缺口；不生成脚手架。 |
| `tea-ci` | Verify、Release 检查 / `verify.ci` | [skills/tea-quality/SKILL.md](../../skills/tea-quality/SKILL.md) → ci | 只读检查流水线、质量门禁、制品和运行证据；不编辑 CI，不启动远端任务。 |
| `ponytail-debt` | Review / `review.debt` | `skills/ponytail-debt/SKILL.md` | 当前任务范围的一次性债务报告；不启用会话模式，不修改代码，不自动落盘。 |
| `implement-spec` | Implement 前置 / `implement.spec` | [skills/implement-spec/SKILL.md](../../skills/implement-spec/SKILL.md) | 大型多任务需求的可选实施契约与协调指引；必须已有 spec、任务 DAG、Plan Review 和明确实施确认。 |

普通对话直接按上述入口读取技能；只有 contract-managed Host 才生成 PlanGraph 和 RunLedger。
V3 的 `implement-spec` 还要求 `durableSpec=true`、`requirementsMaturity=approved`、`writeTask=true` 和 `operationType=implement`。
V2 Host 没有前两个分类字段，须在执行入口核验同样的事实，缺少任意前置条件均停止，不得仅凭路由成功开始实施。

`framework` 与已有 `test-design` 分别运行；`ci` 不替代测试执行、trace 或 NFR。
Release 检查绑定 `verified` 阶段，将发布检查范围写入 `verificationPlan`；不引入新的发布副作用。
TEA 的 `validated` receipt 仅证明报告结构、输入及运行时身份绑定通过，**不表示 CI 成功或质量门禁通过**。
没有真实运行证据时保留 `unverified`；不把静态配置检查当作测试执行。

`implement-spec` 选择时使用专用 slot，不重复加载默认 `implement-matt` 协调入口，仍保留 SelfWorkflow 的 Review、确认、TDD、独立审查和验证。
任务切片和并行只是可选组织方式；本适配器不提供新的调度器，也不授权 reset、push、PR、关闭任务或删除工作树。

报告默认返回对话。用户明确要求保存时才写入批准路径，先确认没有覆盖已有文件或输入文件；符号链接和目录联接不得用于逃出范围。
这些技能约束不是操作系统沙箱，Host 必须限制实际执行动作并复查变更。

本轮不接入 `teach-me-testing`、Ponytail `gain` 或 TEA `automate`；这些能力不进入普通代码任务路径。
