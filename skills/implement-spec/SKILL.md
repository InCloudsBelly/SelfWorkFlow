---
name: implement-spec
description: 显式要求按 spec 与至少两个依赖 tickets 整体实施时使用；普通实现、单票、规划或代码审查不触发。
metadata:
  activation: explicit
---

# Implement Spec 本地适配

Host 执行的指令 wrapper，不是 scheduler。沿现有 SelfWorkflow 阶段与授权；本规则替代上游默认 reset、额外 merger、PR、关单和清理步骤。仅编排细节确有缺口时参考同版上游：文档模式 `methods/matt-pocock/implement-spec/METHOD.md`；runtime 模式 `skills/matt-pocock/implement-spec/` 下的 `SKILL.md`。来源由 Matt 锁与 hash 绑定，不加载默认 implement 或重开完整 TDD 方法。

## 契约

以下为 Host/Reviewer 的声明，不是自动执行配置；结构化证据校验仅契约 Host 使用。

```yaml
kind: instruction-wrapper
activation: explicit
minimumTickets: 2
upstreamReference: skills/matt-pocock/implement-spec/SKILL.md
requires:
  - spec
  - ticket-dag
  - plan-review
  - implementation-confirmation
  - independent-agents
  - independent-review
  - git-permissions
missingEvidence: unverified
outputs:
  - integration-head
  - ticket-results
  - tdd-evidence
  - review-evidence
  - verification-evidence
  - retained-worktrees
  - pending-actions
  - limitations
completionRequires:
  - all-tickets-integrated
  - independent-review-passed
  - verification-passed
  - no-open-blocking-findings
neverAutomatic:
  - reset
  - push
  - pull-request
  - ticket-close
  - worktree-cleanup
```

## 输入与授权

- spec 指针/版本/hash、验收、范围及非目标；至少两票唯一 ID、各自验收与允许路径、依赖和结果位置。先核整张 DAG：依赖已知、无自依赖/环；本地 tickets 可用，tracker 可选。
- 复用绑定当前 spec/DAG/范围的计划审查与实施授权。普通计划合并自审，高风险才按 review 模块前置独立审查；用户整体实施请求可提供实施授权，不为 Agent 自拟计划或等价细节重复确认。实质范围/风险变化才重新核对。
- 核实际独立实现/审查能力、仓库绝对路径、HEAD/dirty、integration base 与 Git 授权；不把当前对话角色名当独立 Agent。必要且可逆的本地分支/worktree/commit/merge 沿任务及仓库既有授权，不默认 reset、push、PR、关单或清理。

缺输入、来源完整性、独立能力或必要授权时记 unverified，只停依赖的编排；继续独立且已授权工作，不用串行自审冒充已执行本编排。

## 执行

1. 保留现有 checkout/dirty，选择或创建基于批准 commit 的 integration branch；同名或 base 冲突时保留现场，不 reset 校正。
2. 仅前置已合入且验证通过的票进入 frontier；共享文件串行，互不冲突的 ready 票才可并行。每票用独立 branch/worktree 和新上下文，只传绑定、spec/ticket 指针、integration HEAD、允许路径、验收与证据；不 fork 完整作者历史。
3. 沿既有测试方法取得 RED→最小 GREEN、失败路径与最窄回归，报告实际命令/退出状态/diff 或 commit。禁运行或证据缺失记 not-run/unverified，不报完成。仅测试方法无法覆盖时补读同版 Matt TDD。
4. 主协调者串行集成，不逐票另建 merger。HEAD 前进后先合入最新 integration tip、处理范围内冲突并重验影响项；不 reset/覆盖 dirty。验证失败保留工作树与失败 frontier，阻断依赖票；无影响的有效测试复用。
5. 全票集成后沿 review 模块由一个独立 Reviewer 核对最终 HEAD；关闭相关 Critical/Important，Minor 有处置。必要修复与复核复用原 Reviewer，只失效变化及首次漏检所影响的覆盖，不每票重做整套 Review。
6. 最终 HEAD 的整体验收与最窄回归有效后交付 integration-head、ticket-results、TDD/Review/验证证据、retained-worktrees、pending-actions、limitations。代码集成完成与 PR/关单/清理分别记录；失败或缺门禁不报整份 spec 完成。

创建 PR 已获授权时才按需使用 pr；不因本编排自动发布、标 ready、关闭 tracker 或发送消息。保留工作树；仅明确清理授权下核绝对路径、所有权、dirty/未合入提交并复读结果，不删除其他任务产物。恢复时核对 HEAD/dirty/票状态，复用仍有效的证据。

声明/打包测试不证明模型遵循、独立执行或调度性能；缺实测标 unverified。
