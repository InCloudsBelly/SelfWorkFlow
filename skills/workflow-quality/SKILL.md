---
name: workflow-quality
description: Use when a task changes files, performs side effects, requires review or verification evidence, or risks affecting existing user work.
---

# Workflow Quality

- Map every acceptance criterion to fresh evidence. Mark non-applicable checks with a reason and unavailable checks as `unverified`.
- Review the full diff for logic closure, failure paths, safety, intrusion, compatibility, and unrelated changes.
- Treat credentials, irreversible actions, user changes, and completion evidence as protected invariants.
- Never replace an unavailable capability with a weaker mechanism without explicit authorization and a recorded limitation.
- Before completion, verify the direct behavior and the smallest affected regression surface. Documentation changes validate format, links, references, and rendered/generated output when applicable.
- Side effects use `plan -> review -> confirm -> apply -> reread`; failed or partial apply retains recoverable evidence and does not report success.
