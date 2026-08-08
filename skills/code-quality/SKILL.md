---
name: code-quality
description: Use when diagnosing or implementing behavior code, bug fixes, refactors, configuration consumers, persistence changes, or cross-layer changes.
---

# Code Quality

Use this Skill for behavior code, bug fixes, refactors, configuration consumers, and cross-layer changes. It is standalone and does not depend on any maintainer-local Skill.

## Required loop

1. Freeze the failure envelope: expected, actual, exact inputs, first observation point, modes, retry/resume state, and current dirty changes.
2. Build the smallest complete slice: `producer -> persisted state -> transform -> consumer/detection point`.
3. Find `last-good` and `first-bad` using persisted evidence, not only logs, exit codes, dirty flags, or same-process transient state.
4. Separate root-cause owner from detection point. Repair the earliest layer that owns the data and invariant. A downstream consumer may reject invalid input or improve diagnostics; it must not reconstruct data it does not own.
5. Inventory durable data, caches, checkpoints, recovery records, temporary outputs, and partial writes. Compute invalidation and rebuild scope before changing behavior.
6. Prefer the narrowest compatible owner-layer change. Application policy must not leak into stable lower-layer public APIs without demonstrated shared need and compatibility review.
7. Protect the user's existing changes. Inspect the full diff, isolate the task diff, and stop on unsafe overlap.
8. Prove Red/Green for the direct path, failure path, state invariants, affected shared paths, and the narrowest regression set. A no-op, process success, or in-memory state is not consumer-observable success; reread the actual output.
9. Report evidence and gaps. Never claim an unrun build, test, review, persistence check, or runtime behavior.

For batch or side-effecting configuration changes, enforce `plan -> review -> confirm -> apply -> reread`, plus rollback evidence. Do not silently downgrade when a required capability is unavailable.
