---
name: testing-review-quality
description: Use for behavior-change TDD and stage-selected Review, verification, or completion. Load contract receipts and runner rules only for contract-managed tasks.
---

# 测试、Review 与验证

SelfWorkflow 决定阶段、模式和授权；本 Skill 负责测试方法与证据验收，不重新 Discover/Classify，不另起工作流。每次只执行当前阶段。

## 行为变更

功能、修复、行为重构、架构变更、迁移及行为实现/调试使用 Matt `tdd`，诊断不能替代 TDD。同一任务已加载且可用的正文直接复用。

- 记录 RED 命令、预期与实际失败，并确认失败来自缺失行为而非环境、语法或 fixture。
- 仅做满足验收的 GREEN 实施，重跑同一命令，再运行最窄相关回归；覆盖直接路径、失败路径和状态不变量。
- 仅已证明的机械修改或规格文档变更可免 TDD，仍须格式/解析及实际消费者验证；分类冲突失败关闭。
- Full/Deep 行为任务按当前阶段加载 TEA test-design 或 test-review；其他可选 TEA 能力仍按显式选择加载。

用户明确禁止执行编译或测试时，该禁止项优先：仍设计/补充已获授权的测试，做允许的静态检查和 Review，但不得执行被禁止命令，不得虚构 RED/GREEN。分别记录测试编写状态与 `execution=not-run`、`verification=unverified`、原因和人工验证步骤。普通任务可交付已授权修改，明确“执行未验证”；这不满足契约 Host 的 passed/complete 门禁。没有禁止项或明确豁免时，继续正常 TDD。

TEA 引用缺失的豁免与编译/测试禁令分别记录：任务/计划 hash、具体 module、缺失文件/能力、用户原话或消息引用、允许的替代检查、剩余风险及失效条件。只对本任务/本计划生效；恢复能力、范围或关键风险变化后重新评估，不得传递给其他任务。豁免不放宽 Code Tag、独立 Review 或安全规则，不把 unverified 改成 passed。普通任务在已有任务记录中保存即可；契约任务仍需其正式策略与凭据，`allowUnverifiedModuleIds` 单独不构成测试通过证据。

## Review 阶段

先读取 SelfWorkflow 的 `workflow/modules/review.md`（从当前 runtime 根解析），由其唯一管理审查者、材料、模型与复审条件；本 Skill 不再创建另一批 Reviewer。
Light 使用窄结构化自审；Full/Deep 保留 Standards/Spec 两个独立上下文；正式设计、测试设计与实施计划保留独立文档包 Review。
上述双轴针对落地写入；纯分析只做一次独立 Review，发现待修问题是分析结果，不要求当场实施。Review 所需授权复用当前范围内已有明确请求；不另起第二套确认流程。
Critical/Important 必须解决，Minor 记录处置。材料变化后旧结论不得复用；缺少独立能力标为 `unverified`。

## Verify / Complete 阶段

主 Agent 统一执行批准范围内的最窄充分验证，记录命令、退出状态、实际输出和验收映射。核对实际变更与已有用户修改，检查直接路径、失败路径、相关回归及副作用后的复读；不能把进程成功当成消费者行为正确。
复用仍与当前输入一致的证据；相关代码、输入、规则或环境变化使证据失效时重验。未执行、失败或缺失的检查如实标为 `unverified`，不得声称该检查完成或通过；普通交付区分代码完成与验证缺口。Review 和验证责任分离，Reviewer 不重跑测试。

## 契约模式

仅显式 contract-managed task 或 conforming Host，在第一次构造 Review package 或执行门禁前读取 [契约 Host 规则](references/contract-host.md)。其中 package、receipt、runner 和完成门禁全部保留；能力不可用只暂停契约模式，不能伪造回执或静默降级。普通任务不创建 PlanGraph/RunLedger，不加载该引用，也不伪称获得 Host attestation。
