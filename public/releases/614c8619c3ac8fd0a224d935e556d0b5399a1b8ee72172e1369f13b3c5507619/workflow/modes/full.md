# Full 模式

适用：中高复杂度/风险。普通 agent-policy 的工作顺序如下，不启动 contract Host。

1. 设计/测试设计/计划合成紧凑方案，主 Agent 自审；只问真正未决的范围、风险和授权。
2. 按启动入口确定实施边界并复用授权。行为变更用 `testing-review-quality` / `implement-tdd`；不自动 Grilling 或 TEA。
3. Review 阶段读 `workflow/modules/review.md`，由其决定前置审查、独立上下文和复审；此处不重复调度规则。
4. 主 Agent 核对新鲜验证与实际消费者结果；未执行项如实标记，证据未变则复用。

纯分析仅阅读、Review 和证据核对；机械文档同步只做窄校验。专业能力按启动入口加载。
