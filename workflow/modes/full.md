# Full 模式

适用：中高复杂度/风险；knowledge profile 本身不要求 Full。Full 不等于 contract Host。

1. 设计、测试设计、计划合并为当前改动的紧凑方案，主 Agent 自审；只问影响范围/风险/授权的未决选择，复用已知事实和已有授权。
2. 普通任务不自动 Grilling 或 TEA；用户明确点名才加载指定能力。行为变更仍加载 implement-tdd，覆盖直接路径、失败路径、状态不变量和最窄回归。
3. 首次编辑前确认实施契约。只有重大架构、安全、持久化、不可逆风险或显式要求才前置 plan-integrated-review；普通中间文档不单开 Reviewer。
4. 授权后做真实 RED/GREEN 与计划内实施；范围/owner/侵入预算/关键风险变化才重新确认。
5. 交付前由一个独立 Reviewer 综合 Standards/Spec 与测试证据，按 review.md 隔离；修复复核复用同一 Reviewer，只看受影响项，不能因调用预算中止未完成任务。Review 继承主 Agent 模型/推理配置，无专属覆盖。
6. 主 Agent 核对新鲜验证，相关输入未变则复用；用户禁编译/测试时记录 not-run/unverified，不虚构通过。

纯分析仅必要阅读、一次独立 Review 和证据核对。机械文档同步做窄自审/解析校验，不新增独立门禁。
代码按 codegraph-read / codegraph-update 维护项目唯一 CodeMap。知识可选，不扩大任务。显式契约任务继续遵循其回执与防伪约束。
