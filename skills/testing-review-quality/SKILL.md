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

Pre-implementation Review receives the final design, test design, plan, rules, and package hash. Post-landing Review uses one readable package containing the approved request, acceptance criteria, final documents, applicable rules, and actual task delta including committed, staged, unstaged, untracked, deleted, and binary-hash entries.

Run Standards and Spec reviews in two distinct independent contexts against that same package. Both receipts must return its hash and distinct execution IDs. Preserve the two axes. Map `critical` to Critical, `high`/`medium` to Important, and `low`/`info` to Minor. Critical and Important must be resolved; each Minor needs a disposition.

Receipts are `host_attested` workflow evidence. They are not identity, model, or cryptographic proof. If the Host cannot provide two genuinely independent contexts and their observed execution IDs, stop as `unverified`; do not manufacture identifiers.

## Fresh verification and completion

Before Review, capture the approved paths plus the complete dirty/untracked workspace fingerprint. Build a deterministic semantic package containing actual spec text, task delta, and user-confirmed verification plans. Changes outside approved paths fail closed. Timestamps and absolute repository paths do not enter the semantic package hash.

Run verification only through the package-bound local runner. It accepts structured `argv`, repository-relative `cwd`, and timeout; it does not use a shell or stdin, does not inherit arbitrary environment variables, and bounds time and output. It is not an OS sandbox, so destructive commands still require the normal explicit user authorization.

Each `runner_attested` receipt records the current package hash, plan hash, argv, cwd, start/end time, exit code, failure count, output hashes, and consumer-observable result. Completion rebuilds the current package from the original baseline, specification, and plans; it never trusts a caller-supplied current hash. It fails closed when Review is missing, non-independent, stale, or has open Critical/Important; when Minor lacks disposition; when verification is missing, failed, stale, or `unverified`; or when final or out-of-scope content changed after Review. Never infer completion from a process-success summary alone.
