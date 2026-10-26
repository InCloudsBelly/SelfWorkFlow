---
name: testing-review-quality
description: 行为变更 TDD、测试设计或执行证据核验；普通 Review、纯分析和机械文档不触发。
---

# 测试与验证

阶段/授权归 SelfWorkflow，代码边界归 code-quality，[独立审查](../../workflow/modules/review.md)只归 Review 模块。

行为变更采用 RED→最小 GREEN→同命令复跑与最窄回归：RED 必须因缺失行为失败，不是环境/语法/fixture 失败。通过现有公共接口/真实消费者测试正常、失败、边界及状态不变量；预期独立于实现，不 Mock 私有协作，不横向预写整套假想测试。测试接缝写入实施契约；同范围已有授权复用，实质接口/范围选择才澄清。
复杂接缝、Mock 或用例设计需要示例时，再按需读[TDD 方法](../matt-pocock/tdd/SKILL.md)；不为每次普通测试预载上游。

机械修改/规格修订可免 TDD，仍做解析及消费者验证。禁编译/测试时分别记编写状态、`execution=not-run`、`verification=unverified`、原因与人工步骤，不虚构 RED/GREEN，豁免只绑定本次范围。
验证绑定命令、退出状态、消费者输出与验收；输入/规则/环境未变复用，变化只重验影响项。通用副作用归 workflow-quality。仅显式契约或 Host 已按契约承接时读[契约规则](references/contract-host.md)，缺能力不降级冒充通过。
