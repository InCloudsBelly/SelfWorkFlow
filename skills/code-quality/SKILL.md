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

## Intrusion budget

Judge intrusion by impact radius, not changed-line count. Public headers, APIs or public enum values, ABI/schema/persistent formats, a global build macro or build variant, cross-module infrastructure, shared hot paths, and test-originated production changes are high-intrusion signals.

Choose the narrowest owner-layer solution that satisfies acceptance. When a high-intrusion signal appears, record the affected files/layers, public contracts, build variants, maintenance and rollback cost, and at least one narrower alternative. If a narrower solution works, reject the heavier design. If none works, crossing the boundary requires explicit user approval as a critical decision. Final Review compares the approved budget with the actual intrusion delta and stops if the diff exceeds it.

Test coverage must not drive production architecture. Prefer a test-owned translation unit or module, an existing extension point, a narrow injected seam, capture tooling, or black-box verification. A local test macro inside a test-owned boundary is valid; do not impose a blanket ban. By default, do not add a test-only public enum slot, change its `Num` or registration matrix, alter object layout, or spread test branches through shared production paths. If required evidence cannot be obtained within the approved budget, mark it `unverified` and state the risk and manual verification method instead of widening production code.

Example: a test cannot reuse a translation-unit-private processor. Adding a test-only public enum slot under a global build macro is rejected when a test-owned adapter, existing hook, or black-box capture can verify the same behavior.
