---
name: code-quality
description: 追踪行为代码的责任层、状态与失效关系，用于解释、诊断或变更行为；纯文档和配置文本维护不触发。
---

# Code Quality

SelfWorkflow 管理阶段、授权与 Review；本 Skill 仅管代码责任层、变更边界和证据，不重新启动流程。

## 只读

沿最小完整切片追踪 producer → persisted state → transform → consumer/detection point，识别不变量、失败责任层与证据缺口。区分 last-good / first-bad；日志、退出码、dirty 或内存状态不等于持久化成功。只读分析不启动 TDD、构建、写入或完整设计。

## 变更

仅诊断需要验证的故障或准备变更时，完整读取 [变更规则](references/change-rules.md)；当前任务同版本正文仍完整时复用。不得为只读任务预载实施规则。最窄 owner-layer 修复优先，不将应用策略泄漏到稳定公共层；保护用户修改，验收看实际消费者结果而非进程成功。

TDD/验证由 testing-review-quality 管理，独立审查由 workflow/modules/review.md 管理。TEA 与完整 grilling 只按显式请求启用。代码首次编辑前需实施契约和已有范围内的明确授权；必要测试不能反向扩张生产架构。
