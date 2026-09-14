# Full 模式

适用：中高复杂度或中高风险任务；用户可主动选择。

顺序固定：

1. Design/Plan 或行为实现/调试阶段自动加载 `design-grilling`（Matt `grilling`），当前 frontier 只执行一次；纯分析不自动加载。
2. 行为变更加载 `implement-tdd`、`tea-test-design`（T2）；设计测试直接路径、失败路径、状态不变量、侵入性和最窄回归。文档等非行为任务不加载代码 TEA。
3. 正式文档完成后先执行独立 `plan-integrated-review`；Critical/Important 清零、Minor 有处置后才请求用户明确实施确认。
4. 确认后执行真实 TDD Red/Green 和计划内实施。
5. 落地后用 `review-code-review` 做 Standards/Spec 两个独立临时 SubAgent Review，并加载 `tea-test-review` 检查测试质量；Reviewer 只消费主 Agent 提供的 hash-bound package，不调用 Graft 或其他任务工具；Review override 仅限该 Reviewer；再执行新鲜验证。

代码任务按需加载 `graft-read`；有专题 Deep 时加载 `graft-deep`，写入后加载 `graft-update`。专题 Deep 只接收显式文件范围，不对整个仓库无条件执行。

`tea-atdd`、`tea-trace`、`tea-nfr` 仅显式选择。项目 Review Skill 若匹配且 hash 通过，优先于通用 Review Skill；不能覆盖硬规则。任何 scope、owner、侵入预算或文档包变更都使确认和旧 Review 失效。
