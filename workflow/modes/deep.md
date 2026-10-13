# Deep 模式

Deep 表示分析深度，不自动启用 contract Host。普通任务与契约任务的 Review 执行证据按 `workflow/modules/review.md` 区分；纯分析只做必要阅读、一次独立 Review 和证据核对。已明确授权且范围不变不重复确认，已经回答的 Grill frontier 不重新访谈；文档可合并成一份完整包。

适用：高复杂度、高风险、边界不清或用户要求深度收敛的任务。

任务文档保持实际范围，不因 Deep 自动扩张为整项目。用户禁止编译/测试时按 `testing-review-quality` 保留 not-run/unverified，普通交付列明验证缺口，不能声称 TDD 或契约验证通过；已有同范围授权复用。

路由顺序明确为：Design/Plan 或行为实现/调试阶段自动加载 `design-grill-me`，直接执行 Matt `grilling` 正文并采用 Deep 的更完整 frontier，且该路径只执行一次；显式 `grill-me` 仍仅作为用户入口，纯分析不自动加载。行为变更时再加载 `implement-tdd`、`tea-test-design`（T3）；实施前加载 `plan-integrated-review`；落地代码加载 `review-code-review` 和 `tea-test-review`。文档等非行为任务不加载代码 TEA。不再另行加载 Full 的 grilling 模块。TEA 使用 T3：补充边界、失败恢复、并发/安全/性能等与任务真实风险相关的测试，不为线性任务无条件扩张变异测试。

行为实现前必须完成完整设计、TEA 测试设计、实施计划和独立文档包 Review；已有明确授权覆盖当前范围时复用，之后才 TDD 和编辑。行为变更落地后保留 Standards/Spec 双独立 Review、`tea-test-review`、新鲜验证和完成门禁。非代码文档按实际任务完成设计/计划、独立文档 Review 和格式、引用、实际消费者验证，不自动加载代码 TEA 或 TDD；其他写入任务仍遵循 Review 模块的 Standards/Spec 双轴门禁。Reviewer 只读取主 Agent 预先绑定的 Review package/evidence，严禁调用 CodeGraph、provider、验证、写入或创建下级 Agent；Review override 仅限该 Reviewer，不得传播给其他 SubAgent；缺少 evidence 时返回 `unverified`。额外 `tea-atdd`、`tea-trace`、`tea-nfr` 仍需显式选择。缺少独立能力标为 `unverified`，不得静默降级。

代码任务先加载 `codegraph-read`；写入后加载 `codegraph-update`。CodeGraph 仍只维护当前项目级全局图，不能引入跨项目或对话级图。
