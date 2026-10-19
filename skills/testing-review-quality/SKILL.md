---
name: testing-review-quality
description: 用于行为变更 TDD 和测试证据核验；普通 Review 直接读 review.md，纯分析或机械文档不因阶段名称加载。
---

# 测试、Review 与验证

SelfWorkflow 管理阶段、模式和授权；本 Skill 只提供测试方法与证据要求。

## 行为变更

使用 Matt tdd：RED 须因缺失行为而非环境/语法/fixture 失败；最小 GREEN 后复跑同一命令和最窄回归，覆盖直接/失败路径、状态不变量。功能、修复、行为重构、迁移均适用；机械修改或规格修订可免 TDD，仍需解析及实际消费者验证。

禁编译/测试时记录编写状态、`execution=not-run`、`verification=unverified`、原因和人工步骤，不虚构 RED/GREEN。豁免仅绑定当前任务/范围。

## Review

到阶段只读当前 runtime 的 `workflow/modules/review.md`，此处不重复调度、隔离或复审规则。

## Verify / Complete

测试证据绑定命令、退出状态、消费者输出及验收条件；输入/规则/环境未变则复用，漂移只重验影响项。通用副作用与验收安全由 `workflow-quality` 承接。

仅显式契约或 Host 已按契约承接时加载 [契约 Host 规则](references/contract-host.md)，保留防伪与完成门禁；能力不足如实阻塞该模式。
