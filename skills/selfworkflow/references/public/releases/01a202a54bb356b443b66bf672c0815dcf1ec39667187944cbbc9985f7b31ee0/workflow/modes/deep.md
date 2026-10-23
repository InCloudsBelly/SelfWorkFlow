# Deep

本模式不要求再读 Full。先给紧凑方案/实施边界，只加与实际风险有关的边界、恢复、并发、安全或性能分析；不自动扩大文档、Agent 或测试架构。

代码实施契约由代码方法管理；行为变更按 [TDD](../../methods/testing-review-quality/METHOD.md)，纯分析/机械文档不触发。交付前一个独立 Reviewer；到阶段读[审查规则](../modules/review.md)，重大架构/安全/持久化/不可逆风险或显式要求才前置。相关 Critical/Important 必须关闭，不因 Token/次数预算中止。
