---
name: implement-spec
description: 仅在用户显式要求 implement-spec 大型多任务实施编排，且 spec、至少两个 tickets 的依赖图、计划 Review 和实施确认齐备时使用。普通 implement、单 ticket、仅规划或仅审查不触发。
metadata:
  activation: explicit
---

# Implement Spec 本地适配

这是由 Host Agent 执行的指令 wrapper，不是自动编排引擎，也不提供 scheduler。
先检查下述门禁，再读取当前 runtime 根目录下的
`methods/matt-pocock/implement-spec/METHOD.md` 作为上游 reference。
其源码由 `dependencies/locks/matt-pocock-skills.lock.yaml` 的 selected skill 与 hash 绑定；不得修改上游。
上游提供 tickets 依赖图、integration branch、worktrees、TDD、merge、review 的方法；
本契约替代其 reset、默认 PR、ticket 关闭及清理指令。上游引用不授予 Git 或外部副作用权限。

## Adapter 契约

以下 YAML 是供 Host 与 reviewer 阅读的约束，不是可执行调度配置。

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

## 输入与触发判定

- `spec`：可读取的规格路径或引用及其版本/hash、验收条件、修改范围和非目标。
- `ticket-dag`：至少两个唯一 ticket ID，各自的验收条件、允许修改路径、依赖 ID 和结果位置。
  依赖必须指向已知 ticket，无自依赖和环；允许显式空依赖集合。校验整张图后才能计算 frontier。
  issue tracker 可选，本地 tickets 可用；外部 tracker 不可读且无完整本地材料时，标记 `unverified`。
- `plan-review` 与 `implementation-confirmation`：已通过的计划 Review 及用户实施确认，绑定当前 spec、tickets、范围与计划版本。
  先 Review，再实施确认，最后才能启动实现。既有有效授权可以复用；文件、依赖、范围或计划改变使证据失效时重新 Review/确认。
- `independent-agents` 与 `independent-review`：Host 实际可创建独立实现上下文、等待并取得执行结果，以及创建与实现者不同的 reviewer。
  检查实际工具和回执能力，不凭角色名称推断能力。当前对话自称多个角色不构成独立 agent。
- `git-permissions`：仓库绝对路径、当前 HEAD、dirty 清单、integration base 的确定 commit、目标分支/工作树位置，
  以及现有 Git 策略和本次授权中允许的创建分支、worktree、commit、merge 等操作。
  不能从“实现 spec”推导出全部 Git 权限；缺少某项权限只准备该操作的具体计划并请求所需确认。

用户显式请求且全部门禁满足，才进入本适配。普通“实现这个功能”、自动识别大型任务、单 ticket、仅写 spec 或 review 均不触发；
保持原工作流，不伪称已执行本编排。显式请求但缺失上下文、reference/hash 验证、授权或独立能力时，
返回 `unverified`、缺失项和下一步；不创建工作树、不派发实现、不用串行自审冒充独立编排。

## 执行规则

1. 记录基线和已有 dirty；在授权范围内创建或选择 integration branch，确认它对应批准的 base commit。
   保留用户现有 checkout 与修改。分支名冲突、来源不明或 base 不符时先报告；不得 reset 已有分支或工作树。
   可以在既有授权范围内另建从正确 commit 开始的工作树，否则停在该操作的确认边界。
2. 根据依赖结果计算 frontier：只有所有前置 ticket 已合入 integration branch 且对应验证通过的 ticket 才 ready。
   只并行派发无未满足依赖且写入边界互不冲突的任务；共享文件任务串行安排。并发数量受真实 Host 能力限制。
   向实现者传递 spec/ticket 指针、允许路径、base commit 和验收条件；不得扩大写入范围。
3. 每个实现者使用独立 branch/worktree，记录路径与起始 commit，并核实来自指定 integration HEAD。
   加载 runtime 的 Matt `tdd`，先取得目标行为的 RED，再最小 GREEN，并执行 ticket 的失败路径和相关回归验证。
   报告命令、退出码、结果及 diff/commit；缺少真实执行证据即 `unverified`，测试失败不能报完成。
4. integration branch 的写入与 merge 由单一协调者串行执行（可以是授权的 merger agent）。
   integration HEAD 已前进时，在既有授权内将其合入 ticket branch 并重新验证；存在冲突就保留现场，
   不用 reset、强制覆盖或丢弃 dirty 来继续。解决冲突若超出批准范围，返回计划确认。
   确认票据范围与证据后才 merge；每次合入后复跑受影响验证，失败则阻断依赖此 ticket 的 frontier，记录部分完成状态。
5. 全部 ticket 合入后，对最终 integration HEAD/diff 执行独立 Review，遵循当前模式和项目 Review 规则；
   Full/Deep 由一个独立 Reviewer 综合核对 Standards/Spec，不创建双 Reviewer。修复 Critical/Important，记录 Minor 处置；变化只失效受影响结论，必要复核复用同一 Reviewer，并持续推进到验收。
   没有独立 Review 能力或回执则为 `unverified`，不能用自身检查声明通过。
6. 在同一最终 HEAD 上取得整体验收、失败路径和最窄回归证据，再报告结果。
   完成指代码集成和验收完成，不代表 tracker 已关闭、PR 已发布或工作树已清理。

## Git 与外部副作用替代

遵循现有仓库 Git 权限和 `plan → review → confirm → apply → reread` 边界；已有授权只覆盖其明确对象和动作。
本 skill 不增加 Git 权限，不绕过 Host 审批，不因上游步骤或 tracker 惯例自动执行下列动作：

- `reset`：禁止作为 base 校正、冲突恢复或任务重试的默认操作；保留原状态并提供可审查的恢复方案。
- `push` / `pull-request`：默认仅交付 integration branch 与 diff。push、创建 draft PR、标记 ready 各自检查授权，
  不默认添加会关闭 spec/tickets 的 PR 文本。
- `ticket-close`：默认输出 ticket ID 与实现/验证状态映射；外部关闭、改状态或发送消息需明确授权。
- `worktree-cleanup`：默认保留并列出工作树。清理前确认具体绝对路径、所有权、dirty 和未合入提交，
  在授权范围内执行并复读结果；不得清理用户或其他任务的工作树，不使用强制删除掩盖失败。

失败保留分支、worktree、已取得的证据和未完成 frontier，报告冲突/失败命令及可恢复位置。
恢复前重读 HEAD、dirty、ticket 状态与授权，失效的 Review/验证不得复用。

## 输出与交付

输出 `integration-head`（分支与最终 commit）、`ticket-results`（每票依赖、状态、commit 和验收结果）、
`tdd-evidence`、`review-evidence`、`verification-evidence`（均关联实际代码版本、执行者/命令与结果）、
`retained-worktrees`（路径及 dirty/合入状态）、`pending-actions`（待授权或失败的 Git/外部动作）、`limitations`。
区分 passed、failed 和 `unverified`；存在缺失门禁、失败验证或阻塞发现时，不报告完整 spec 已实现。

本地契约 conformance 测试只能证明 wrapper 与锁文件约束存在，不能证明模型遵循、真实独立执行或自动调度。
catalog 的 explicit 路由和 runtime reference copy 由集成方提供并另行测试；未取得其证据时记为 `unverified`。
