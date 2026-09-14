# Deep 模式

适用：高复杂度、高风险、边界不清或用户要求深度收敛的任务。

路由顺序明确为：Design/Plan 或行为实现/调试阶段自动加载 `design-grill-me`，直接执行 Matt `grilling` 正文并采用 Deep 的更完整 frontier，且该路径只执行一次；显式 `grill-me` 仍仅作为用户入口，纯分析不自动加载。行为变更时再加载 `implement-tdd`、`tea-test-design`（T3）；实施前加载 `plan-integrated-review`；落地代码加载 `review-code-review` 和 `tea-test-review`。文档等非行为任务不加载代码 TEA。不再另行加载 Full 的 grilling 模块。TEA 使用 T3：补充边界、失败恢复、并发/安全/性能等与任务真实风险相关的测试，不为线性任务无条件扩张变异测试。

实施前必须完成完整设计、TEA、实施计划和独立文档包 Review；用户明确确认后才 TDD 和编辑。落地后保留 Standards/Spec 双独立 Review、`tea-test-review`、新鲜验证和完成门禁。Reviewer 只读取主 Agent 预先绑定的 Review package/evidence，严禁调用 Graft、provider、验证、写入或创建下级 Agent；Review override 仅限该 Reviewer，不得传播给其他 SubAgent；缺少 evidence 时返回 `unverified`。额外 `tea-atdd`、`tea-trace`、`tea-nfr` 仍需显式选择。缺少独立能力标为 `unverified`，不得静默降级。

代码任务先加载 `graft-read`；专题 Deep 加载 `graft-deep`，写入后加载 `graft-update`。Deep 范围必须是当前专题的显式文件清单，不能扩大到全仓库。
