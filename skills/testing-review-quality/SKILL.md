---
name: testing-review-quality
description: Use for behavior-change TDD and stage-selected Review, verification, or completion. Load contract receipts and runner rules only for contract-managed tasks.
---

# 测试、Review 与验证

SelfWorkflow 唯一管理阶段、模式和授权；每次只执行当前阶段，不另起流程或重复确认。

## 行为变更

使用 Matt tdd：先 RED，确认失败源自缺失行为而非环境/语法/fixture；最小 GREEN 后复跑同一命令与最窄回归，覆盖直接/失败路径、状态不变量。功能、修复、行为重构、迁移均适用；已证明机械修改或规格修订可免 TDD，仍需解析及实际消费者验证。
TEA 全部能力只在用户显式点名时加载；Full/Deep 和测试等级不自动触发。

用户禁编译/测试时遵守，记录测试编写状态、execution=not-run、verification=unverified、原因与人工步骤，不虚构 RED/GREEN 或将缺口说成通过。豁免仅绑定当前任务/范围，不能转用于其他任务或削弱安全规则。

## Review

到此阶段只读当前 runtime 的 workflow/modules/review.md，由其唯一调度。Light 自审；Full/Deep 一个独立 Reviewer 综合 Standards/Spec，所有模式无双 Review。普通中间方案自审；重大架构/安全/持久化/不可逆风险或显式请求才前置独立 Review。Reviewer 不重跑测试、不再派发 Agent；修复后只复核受影响项，继续到验收，不因预算耗尽中止。

## Verify / Complete

主 Agent 统一核对命令、退出状态、消费者输出及验收映射，保护已有修改，检查失败路径、最窄回归与副作用复读。输入/规则/环境未变复用证据；相关漂移只重验影响项。未执行/失败/缺失检查如实 unverified；Critical/Important 解决，Minor 记录处置。

仅显式 contract-managed task 或 conforming Host 加载 [契约 Host 规则](references/contract-host.md)，保留 package、receipt、防伪、runner 和完成门禁；普通任务不创建 PlanGraph/RunLedger。契约能力不可用不伪造或降级冒充通过。
