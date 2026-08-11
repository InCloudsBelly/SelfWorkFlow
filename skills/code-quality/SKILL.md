---
name: code-quality
description: Use when reading or explaining behavior code, diagnosing behavior, fixing bugs, refactoring, or changing configuration consumers, persistence, or cross-layer behavior.
---

# Code Quality

Use this Skill for understanding or changing behavior code, bug fixes, refactors, configuration consumers, and cross-layer behavior. It is standalone and does not depend on any maintainer-local Skill.

## Read-only reasoning core

For read-only analysis, trace the smallest complete slice from inputs and owners through transforms to observable outputs. Identify invariants, failure ownership, and evidence gaps, then stop with an evidence-backed explanation. Read-only analysis does not activate change rules, TDD, builds, debugger actions, or a full workflow.

## Change rules

Apply this loop only when diagnosing a failure that needs verification or when changing files:

1. Freeze the failure envelope: expected, actual, exact inputs, first observation point, modes, retry/resume state, and current dirty changes.
2. Build the smallest complete slice: `producer -> persisted state -> transform -> consumer/detection point`.
3. Find `last-good` and `first-bad` using persisted evidence, not only logs, exit codes, dirty flags, or same-process transient state.
4. Separate root-cause owner from detection point. Repair the earliest layer that owns the data and invariant. A downstream consumer may reject invalid input or improve diagnostics; it must not reconstruct data it does not own.
5. Inventory durable data, caches, checkpoints, recovery records, temporary outputs, and partial writes. Compute invalidation and rebuild scope before changing behavior.
6. Prefer the narrowest compatible owner-layer change. Application policy must not leak into stable lower-layer public APIs without demonstrated shared need and compatibility review. Apply the intrusion budget below before accepting a design.
7. Protect the user's existing changes. Inspect the full diff, isolate the task diff, and stop on unsafe overlap.
8. Prove Red/Green for the direct path, failure path, state invariants, affected shared paths, and the narrowest regression set. A no-op, process success, or in-memory state is not consumer-observable success; reread the actual output.
9. Report evidence and gaps. Never claim an unrun build, test, review, persistence check, or runtime behavior.

For batch or side-effecting configuration changes, enforce `plan -> review -> confirm -> apply -> reread`, plus rollback evidence. Do not silently downgrade when a required capability is unavailable.

## Implementation contract

Before the first test or production-code edit, present an implementation contract and obtain explicit implementation confirmation. Until then, restrict work to read-only analysis and design, test-design, or plan documents; do not write tests, shaders, build scripts, behavior configuration, or production code.

The contract records the expected owner-layer changes and main files/symbols, at least one alternative, impact radius, test seam, unverified evidence, and the trade-offs for safety, performance, compatibility, maintenance, and rollback. Light uses a compact inline contract. Full/Deep records the code boundary in the design, direct/failure paths and performance evidence in test design, and exact files, no-go boundaries, TDD, rollback, and verification in the implementation plan; independent whole-package Review precedes user confirmation.

If implementation crosses the approved owner/module boundary, adds public API/ABI/schema, persistent formats, a global build macro or variant, or materially increases any approved risk or cost, the contract becomes invalid. Stop editing, revise and re-review the documents, then obtain a new explicit implementation confirmation. Equivalent private details inside the approved budget do not require another prompt; report them in final Review.

## Intrusion budget

Judge intrusion by impact radius, not changed-line count. Public headers, APIs or public enum values, ABI/schema/persistent formats, a global build macro or build variant, cross-module infrastructure, shared hot paths, and test-originated production changes are high-intrusion signals.

Choose the narrowest owner-layer solution that satisfies acceptance. When a high-intrusion signal appears, record the affected files/layers, public contracts, build variants, maintenance and rollback cost, and at least one narrower alternative. If a narrower solution works, reject the heavier design. If none works, crossing the boundary requires explicit user approval as a critical decision. Final Review compares the approved budget with the actual intrusion delta and stops if the diff exceeds it.

Test coverage must not drive production architecture. Prefer a test-owned translation unit or module, an existing extension point, a narrow injected seam, capture tooling, or black-box verification. A local test macro inside a test-owned boundary is valid; do not impose a blanket ban. By default, do not add a test-only public enum slot, change its `Num` or registration matrix, alter object layout, or spread test branches through shared production paths. If required evidence cannot be obtained within the approved budget, mark it `unverified` and state the risk and manual verification method instead of widening production code.

Example: a test cannot reuse a translation-unit-private processor. Adding a test-only public enum slot under a global build macro is rejected when a test-owned adapter, existing hook, or black-box capture can verify the same behavior.
