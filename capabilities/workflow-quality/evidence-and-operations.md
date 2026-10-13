# Evidence and operations

普通 agent-policy：以当前请求、实际任务增量、独立 Review 结果和新鲜验证作为完成证据。按 `workflow/modules/review.md` 调度，Critical/Important 处理完毕、Minor 有处置。相同输入的有效证据复用，变化才使相关证据失效；不要求 PlanGraph、RunLedger、专用 runner 或宿主 attestation。缺少必要证据标 `unverified`，不得声称该验收通过。既有明确授权在相同范围内复用。

仅显式 contract-managed task / conforming Host：Review package 包含实际规格、worktree/index 字节与 Git mode、任务 delta、批准的验证计划。Full/Deep 写入任务由 Standards/Spec 消费同一 package hash。Complete 拒绝调用方自填 Verify receipt，使用 bounded runner 执行绑定计划，记录命令、时间、退出码、失败数、输出 hash 与结构化结果；清理进程组后提供 cleanup 证据。能力不可用则阻塞契约门禁，不静默降级。

副作用批次须有范围、授权、执行结果、复读与恢复办法。故障注入只在临时环境验证事务/回滚实现变更，不要求每次文档编辑或实际发布都人为触发故障。安装完整性与清理状态分别报告；提交后清理失败不得伪称内容回滚，也不能隐藏待清理事项。提示词约束不构成 OS sandbox 或工具权限隔离。
