# SelfWorkFlow core workflow

This document describes the checked-in, vendor-neutral core that is currently
implemented and tested. The linked YAML files are the declarative sources; the
Python module supplies deterministic protected-rule merging, JSON evidence
parsing, canonical content hashing, and completion decisions.

## Lifecycle

The phase order is `discovered` → `capability-checked` → `classified` →
`designed` → `planned` → `implemented` → `reviewed` → `verified` →
`completed`. Execution status and verification status remain separate. A task
may be `active`, `paused`, `blocked`, `failed`, or `completed`; verification is
`not-applicable`, `not-run`, `partial`, `passed`, or `failed`.

The exact phase and status vocabulary is in
[the lifecycle source](workflow/lifecycle.yaml). Classification thresholds and
upgrade-only overrides are in [the policy source](workflow/policies.yaml).

## Phase capability contract

Before classification or state-changing work, identify the capabilities the
current phase needs and report each as `supported`, `unsupported`, or
`unverified`. Only `supported` satisfies a required capability. An unsupported,
unverified, or missing report pauses the task with the missing capability,
purpose, reason, recommendation, permitted one-time alternative, and
non-waivable boundaries.

A one-time manual alternative requires explicit user authorization. It does not
change the capability report and never permits automatic downgrade. The
standard names and pause contract are defined by
[the lifecycle source](workflow/lifecycle.yaml) and
[the policy source](workflow/policies.yaml).

## Rule precedence

Protected rules have priority over ordinary skill rules, project rules, and the
personal overlay, in that order. Lower-priority layers may add rules, but cannot
replace any protected rule. Their merge result is deterministic and deeply
immutable.

Repository-owner changes to protected rules require all four gates together:
explicit destructive-change confirmation, a major version bump, independent
Review evidence, and behavioral-test evidence. The exact invariants and gate
shape are in [the protected-rule source](workflow/protected-rules.yaml), its
[closed schema](schemas/protected-rules.schema.json), and
[the tested implementation](src/selfworkflow/evidence.py).

`enforced` means the checked-in code or schema performs the stated check.
agent-policy rules are behavior-tested policies, not technical enforcement.
The protected set forbids fabricated capability, Review, or test claims;
silent degradation; exposure of credentials or sensitive information;
unauthorized side effects or irreversible operations; damage to existing user
changes; and completion without fresh verification evidence.

## Completion evidence

A modifying task records exactly `classification`, `capabilities`,
`selectedSkills`, `acceptanceCriteria`, `changes`, `review`, `verification`,
`skipped`, and `residualRisks`. Structured change, Review, and verification
records cannot be replaced by empty collections or prose claims. Every
acceptance criterion references recorded verification IDs. Every skipped or
not-applicable item has a non-empty reason.

Completion requires `passed` verification bound to the canonical hash of the
current result and observed within its declared validity window. `failed`,
`not-run`, `partial`, stale, future-dated, clock-rollback, and hash-mismatched
evidence cannot complete. `not-applicable` is eligible only for a pure
`read-only` task with no change items.

The stable field list and status policy remain in
[the evidence source](workflow/evidence.yaml). The concrete immutable JSON
fixture contract and completion checks are exercised by
[the evidence tests](tests/unit/test_evidence.py).

## On-demand loading

Load only the source needed for the current phase: lifecycle and policy for
capability checking or classification, protected rules for merging or governed
changes, and evidence rules for Review or completion. Load
[the core implementation](src/selfworkflow/evidence.py) only when executing or
auditing those deterministic checks. This keeps unrelated phase material out of
the active context while preserving direct links to every implemented contract.
