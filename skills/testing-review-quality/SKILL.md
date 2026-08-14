---
name: testing-review-quality
description: Use for behavior-changing implementation, Full or Deep review, post-landing review, verification, and completion. Enforces real TDD, identical-package independent Standards/Spec review, and fresh fail-closed completion evidence.
---

# Testing and Review Quality

## Behavior-change TDD

For features, bug fixes, behavioral refactors, architecture changes, migrations, and `implement`/`debug` operations, load Matt `tdd` regardless of its narrower natural-language trigger. Keep diagnosis in its own method slot; it cannot replace TDD.

- Record the RED command, expected failure, observed failure, and why it proves missing behavior rather than an environment, syntax, or fixture error.
- Apply only the minimum GREEN implementation, rerun the same command, then run the narrowest affected regression set.
- Classification conflicts fail closed. Only a proven mechanical or specification-document change may omit TDD; it still needs parser and consumer verification.

## Independent Review

Pre-implementation Review receives the final design, test design, plan, rules, and package hash. Post-landing Review uses one readable package containing the approved request, acceptance criteria, final documents, applicable rules, and actual task delta including committed, staged, unstaged, untracked, deleted, binary-hash, and Git file-mode entries. Worktree and index bytes plus modes are bound separately so staged-only and mode-only changes cannot evade Review.

Run Standards and Spec reviews in two distinct independent contexts against that same package. Both receipts must return its hash and distinct execution IDs. Preserve the two axes. Map `critical` to Critical, `high`/`medium` to Important, and `low`/`info` to Minor. Critical and Important must be resolved; each Minor needs a disposition.

Receipts are `host_attested` workflow evidence. They are not identity, model, or cryptographic proof. If the Host cannot provide two genuinely independent contexts and their observed execution IDs, stop as `unverified`; do not manufacture identifiers.

## Fresh verification and completion

Before Review, capture the approved paths plus the complete dirty/untracked workspace fingerprint. Build a deterministic semantic package containing actual spec text, task delta, and at least one user-confirmed verification plan with an explicit process-exit result contract. Changes outside approved paths fail closed. Timestamps and absolute repository paths do not enter the semantic package hash.

Run verification only through the package-bound local runner. It accepts structured `argv`, repository-relative `cwd`, timeout, and result contract; it does not use a shell or stdin, does not inherit arbitrary environment variables, and applies a hard streaming output limit. Timeout or output overflow terminates the process tree and fails closed if termination cannot be confirmed. Process cleanup first reaps the group leader and then confirms the remaining container is empty. It is not an OS sandbox, so destructive commands still require the normal explicit user authorization.

Each `runner_attested` receipt records the current package hash, plan hash, argv, cwd, start/end time, exit code, failure count, output hashes, and structured consumer-observable result. Completion rejects caller-supplied verification receipts, executes every bound plan itself, and rebuilds the current package from the original baseline, specification, and plans before and after execution; it never trusts a caller-supplied current hash. It fails closed when Review is missing, non-independent, stale, or has open Critical/Important; when Minor lacks disposition; when verification is failed or `unverified`; or when final or out-of-scope content changed after Review. Never infer completion from a process-success summary alone.
