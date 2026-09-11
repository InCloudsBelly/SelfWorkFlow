# Deep 模式

适用：高复杂度、高风险、边界不清或用户要求深度收敛的任务。

路由顺序明确为：Design/Plan 或行为实现/调试阶段自动加载 `design-grill-me`（Matt `grill-me`），其上游流程负责更完整的 `grilling` frontier，且该路径只执行一次；纯分析不自动加载。行为变更时再加载 `implement-tdd`、`tea-test-design`（T3）；实施前加载 `plan-integrated-review`；落地代码加载 `review-code-review` 和 `tea-test-review`。文档等非行为任务不加载代码 TEA。不再另行加载 Full 的 grilling 模块。TEA 使用 T3：补充边界、失败恢复、并发/安全/性能等与任务真实风险相关的测试，不为线性任务无条件扩张变异测试。

实施前必须完成完整设计、TEA、实施计划和独立文档包 Review；用户明确确认后才 TDD 和编辑。落地后保留 Standards/Spec 双独立 Review、`tea-test-review`、新鲜验证和完成门禁。额外 `tea-atdd`、`tea-trace`、`tea-nfr` 仍需显式选择。缺少独立能力标为 `unverified`，不得静默降级。
