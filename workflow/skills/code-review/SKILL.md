---
name: code-review
description: 审查用户指定的 PR、分支、提交或未提交代码，综合检查 Standards/Spec、行为风险和测试证据。普通实现、测试执行或机械文档同步不触发；工作流内审查由 review 模块调度。
---

# 代码审查

这是 SelfWorkflow 的本地单审入口，替代上游双审编排；不加载上游 code-review 正文。

主 Agent 复用当前 snapshot 的 [workflow/modules/review.md](../../../workflow/modules/review.md)：Light 自审，Full/Deep 一个独立 Reviewer 综合 Standards/Spec；不传模型/推理覆盖，不复制主历史。若已被委派为 Reviewer，只完成已分配审查，不再派发或重启流程。

固定用户指定的比较基线和实际增量；未指定时先看当前未提交改动，无改动且基线不明才询问。主 Agent 提供请求/规格、适用标准、增量及验证证据；已有完整材料复用，不要求另建 issue/spec。

沿受影响路径检查正确性、安全、兼容性、测试与越界，不只读 diff。按 Review 模块的覆盖与完成条件检查整个约定范围，发现问题后继续剩余项。Standards 引用真实项目规则，Spec 对照真实需求；缺失材料标 unverified，不编造标准。发现需有可达输入/反例、具体位置、影响和最小建议；两个轴在同次审查内标识，不拆成两份重复报告。

只报告审查结论，不擅自修复或运行测试；Reviewer 不调用 provider。输出按严重性合并发现、覆盖情况、验收结论与必要缺口；有待审项时明确未完成。修复后复用原 Reviewer，按覆盖记录补齐未审范围及失效的影响项。
