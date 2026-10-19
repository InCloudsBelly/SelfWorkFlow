# 契约 Host 的 Review 与验证

仅显式 contract-managed task 或 conforming Host 加载。普通任务不加载本文件；进入契约模式后必须完整执行，能力缺失暂停该模式并标为 `unverified`，不得转普通模式冒充通过。

## Independent Review


Pre-implementation Review receives the final design, test design, plan, rules, and package hash. Post-landing Review uses one readable package containing the approved request, acceptance criteria, final documents, applicable rules, and actual task delta including committed, staged, unstaged, untracked, deleted, binary-hash, and Git file-mode entries. Worktree and index bytes plus modes are bound separately so staged-only and mode-only changes cannot evade Review.

Bind the package and every receipt to the same `workflowMode`. Light uses one structured `self_attested` review. Full and Deep use one independent `host_attested` review with axis `combined`, covering Standards and Spec against the same package. Reject missing, stale or cross-mode evidence; never require two reviewers. Inherit the parent model/settings without a Review-specific override. Map `critical` to Critical, `high`/`medium` to Important, and `low`/`info` to Minor. Critical and Important must be resolved; each Minor needs a disposition.

Review receipts are workflow evidence, not identity, model, or cryptographic proof. Full/Deep require one genuinely independent Host context and its observed execution ID; missing capability is `unverified`, never manufactured. Ordinary intermediate plans are self-reviewed; a pre-implementation independent gate is reserved for material architecture, security, persistence, irreversible risk or explicit request.

## Fresh verification and completion

Before Review, capture the approved paths plus the complete dirty/untracked workspace fingerprint. Build a deterministic semantic package containing actual spec text, task delta, and at least one user-confirmed verification plan with an explicit process-exit result contract. Changes outside approved paths fail closed. Timestamps and absolute repository paths do not enter the semantic package hash.

Run verification only through the package-bound local runner. It accepts structured `argv`, repository-relative `cwd`, timeout, and result contract; it does not use a shell or stdin, does not inherit arbitrary environment variables, and applies a hard streaming output limit. Timeout or output overflow terminates the process tree and fails closed if termination cannot be confirmed. Process cleanup first reaps the group leader and then confirms the remaining container is empty. It is not an OS sandbox, so destructive commands still require the normal explicit user authorization.

Each `runner_attested` receipt records the current package hash, plan hash, argv, cwd, start/end time, exit code, failure count, output hashes, and structured consumer-observable result. Completion rejects caller-supplied verification receipts, executes every bound plan itself, and rebuilds the current package from the original baseline, specification, and plans before and after execution; it never trusts a caller-supplied current hash. It fails closed when Review is missing, non-independent, stale, or has open Critical/Important; when Minor lacks disposition; when verification is failed or `unverified`; or when final or out-of-scope content changed after Review. Never infer completion from a process-success summary alone.
