# Deep 模式

适用：高复杂度、高风险、边界不清或要求深度分析。

- 用启动入口的紧凑 Design/Plan、实施边界和证据复用规则；本模式不要求再读 Full。
- 只增加与实际风险有关的边界、恢复、并发、安全或性能分析，不自动扩大文档、Agent 或测试架构。
- 行为 TDD 用 `testing-review-quality`；Review 调度、隔离与复审只读 `modules/review.md`。纯分析不套实施流程，机械文档仅窄校验。
- 完整 grilling 和 TEA 仅用户显式点名启用，不因模式、测试等级或项目默认加载。
