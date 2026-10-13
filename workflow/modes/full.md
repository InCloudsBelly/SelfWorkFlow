# Full 模式

适用：中高复杂度或中高风险任务；用户可主动选择。

`knowledge` profile 本身不要求 Full。局部修复的设计/测试/计划可合并为当前改动的一份文档，不扩张为整个项目或虚构 epic。已有明确授权覆盖审查后范围时直接复用；用户禁止编译/测试按 `testing-review-quality` 记录 not-run/unverified，不以 TDD 名义执行被禁止命令。契约 Host 的 passed 条件不变。

执行方式先按 `workflow/modules/review.md` 区分普通 agent-policy 与 contract；模式 Full 不等于契约 Host。以下为写入任务顺序；纯分析只执行必要阅读、一次独立 Review 和证据核对。

1. Design/Plan 或行为实现/调试阶段自动加载 `design-grilling`（Matt `grilling`），当前 frontier 只执行一次；只问未决的重要选择，复用已授权范围与已知事实，不重复访谈；纯分析不自动加载。
2. 行为变更加载 `implement-tdd`、`tea-test-design`（T2）；设计测试直接路径、失败路径、状态不变量、侵入性和最窄回归。文档等非行为任务不加载代码 TEA。
3. 正式文档完成后先执行独立 `plan-integrated-review`；Critical/Important 清零、Minor 有处置后核对用户明确实施确认；同一范围已有明确授权则复用，不因阶段切换再问一次。
4. 确认后执行真实 TDD Red/Green 和计划内实施。
5. 落地后用 `review-code-review` 做 Standards/Spec 两个独立临时 SubAgent Review；行为变更才加载 `tea-test-review`，复用同一包检查测试质量。Reviewer 只消费主 Agent 提供的 hash-bound package，不调用 CodeGraph 或其他任务工具；Review override 仅限该 Reviewer；主 Agent 核对新鲜验证证据，未漂移且已通过的同一命令不重跑。

代码任务按需加载 `codegraph-read`；写入后加载 `codegraph-update`。CodeGraph 只维护当前项目级全局图，不接收 conversation、Topic 或 Deep 范围。

`tea-atdd`、`tea-trace`、`tea-nfr` 仅显式选择。项目 Review Skill 若匹配且 hash 通过，优先于通用 Review Skill；不能覆盖硬规则。scope、owner、侵入预算或关键风险变更使确认失效；文档/代码变化使受影响 Review 失效，但同范围澄清、补证据不要求再次实施确认。
