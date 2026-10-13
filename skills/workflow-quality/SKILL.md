---
name: workflow-quality
description: Use when a task changes files, performs side effects, requires review or verification evidence, or risks affecting existing user work.
---

# Workflow Quality

本 Skill 仅负责跨领域的验收证据、用户已有修改和副作用安全。SelfWorkflow 唯一管理模式、阶段与授权；代码所有权交给 `code-quality`，TDD 与 Review/Verify 细节交给当前阶段选中的 `testing-review-quality`。未命中代码或测试任务不加载它们；已满足的相同门禁复用有效证据，不重新发起 Review、测试或确认。

- Map every acceptance criterion to fresh evidence. Mark non-applicable checks with a reason and unavailable checks as `unverified`.
- Review the full diff for logic closure, failure paths, safety, intrusion, compatibility, and unrelated changes.
- Treat credentials, irreversible actions, user changes, and completion evidence as protected invariants.
- Never replace an unavailable capability with a weaker mechanism without explicit authorization and a recorded limitation.
- Before completion, verify the direct behavior and the smallest affected regression surface. Documentation changes validate format, links, references, and rendered/generated output when applicable.
- Side effects use `plan -> review -> confirm -> apply -> reread`; reuse existing explicit authorization for unchanged scope. Failed or partial apply retains recoverable evidence and does not report success. Separate committed content from pending cleanup; neither is proof of the other.
- Ordinary agent-policy does not require contract runner/receipt/cleanup attestation. Use those only for explicit contract-managed tasks or a conforming Host; unavailable contract capabilities block that mode, not unrelated ordinary tasks. Prompt rules are not an OS sandbox.
- Reuse explicit implementation consent while scope, owner and material risk stay unchanged. Record the request, approved scope, plan identity and prohibited actions in the existing task record. Evidence updates need affected re-review, not duplicate consent. Record each explicit waiver separately with its missing capability, authorization, task/plan binding and residual unverified evidence; never promote it to a passed test or reuse it for another task.
