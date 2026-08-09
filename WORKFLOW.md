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

## Modular execution protocol

The checked-in Pipeline is the fixed lightweight spine; Catalog v2 is the only
runtime module registry. A Host performs this sequence:

```text
Discover -> Capability Check -> Classify -> Design -> Plan
-> Implement/Debug -> Review -> Verify -> optional Knowledge -> Complete
```

The Host calls `selfworkflow resolve` with a normalized request and fresh,
identity-bound capability evidence. An `active` result contains an immutable
PlanGraph; `paused` must never be promoted or silently degraded. Only modules in
the current PlanGraph stage are loaded. Runtime attempts, Gate results, skips,
and failures belong in a RunLedger bound to the exact `planHash`, `requestHash`,
and capability snapshot. Changed or expired evidence requires a new plan and
supersedes the old ledger.

All modifying tasks use Brainstorming; Light keeps it bounded and uses an inline
Plan, while Full and Deep also use Writing Plans. Deep recommends Grill-me but never enables
it automatically; when the user selects it, Grill-me is followed by an
independent-context Brainstorming cross-review. Every modifying task still
requires complete-diff Review and the narrowest sufficient direct, failure-path,
and related-regression verification. Users are prompted only for material scope
or product choices, sensitive data, irreversible/external effects, protected
defaults, and formal knowledge publication.

Knowledge exposes only optional `knowledge.read`, `knowledge.propose`, and
`knowledge.update` slots. This version does not implement or enable C7OpenWiki;
its concrete MCP behavior is a later, separately tested extension.

## Review and decision closure

Every landed change requires post-landing Review before completion. A Review
fix remains in the active Review stage and creates a new RunLedger v2 attempt;
results from older attempts stay auditable but cannot satisfy the latest
attempt. The final Review receipt binds the final document or complete diff
hash. Only changed Request, capability, or other static PlanGraph inputs cause
re-planning.

Design and plan documents are intermediate artifacts. `design.gate` reviews a
final design/specification hash and `plan.gate` reviews a final implementation
plan hash before implementation continues. A document that is itself the final
deliverable still lands through `document`, post-landing Review, and Verify.
Writing a plan never completes an implementation request.

Ask the user for every critical decision: scope or acceptance changes,
public/API/Schema/compatibility or persistent-data changes, security or
sensitive data, external or irreversible effects, protected defaults,
user-owned changes, or material uncertainty. A minor decision is eligible for
automatic recommendation only when it stays within the approved scope, affects
one local component, has easy rollback, preserves compatibility and security,
has no external side effects, and has low uncertainty. If an independent
SubAgent is available, it may compare two to four valid alternatives. Adopt its
recommendation and save a validated `decision-record`; automatic adoption
requires `selectedId == recommendationId`. A structured self-review records
independence as `unverified`. Any failed criterion or desired deviation becomes
a critical decision and returns to the user. Store conclusions and evidence,
never private model reasoning. Usage is `agent-policy`; only the record contract
is mechanically validated.

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
personal overlay, in that order. Lower-priority layers have only the typed
`add-requirement` and `advisory` operations under ordinary-layer contract
version 1. Each operation contains a closed `kind`/`target`/`mode`/`value`
constraint from a finite vocabulary; arbitrary prose has no rule authority.
Duplicate ordinary IDs are rejected across layers. New operations or values
require a contract, schema, version, and test change. Ordinary layers cannot
replace a protected rule or alter the fixed protected evaluators. Their merge
result is deterministic and deeply immutable.

Repository-owner changes to protected rules require all four gates together:
an explicit confirmation attestation, an actual SemVer major increase, an
independent Review attestation, and a passed behavioral-test execution receipt.
All three receipts bind the canonical proposal hash over the base and proposed
rule hashes, both policy versions, an operation nonce, proposal time, validity
window, and expected behavioral-test invocation hash. Before collection, the
behavioral invocation input binds a pre-test subject containing those operation
fields without the invocation, avoiding a hash cycle. The proposal must precede
all three receipts; receipts cannot
be future-dated or outlive the proposal window. Owner Review accepts L2 or L3
through the same review-level comparator used by completion. Every referenced
artifact is resolved from a collector-sealed store and its canonical hash is recomputed. The exact
invariants and gate shape are in
[the protected-rule source](workflow/protected-rules.yaml), its
[closed schema](schemas/protected-rules.schema.json), and
[the tested implementation](src/selfworkflow/evidence.py).

`enforced` means the checked-in code or schema performs the stated check.
agent-policy depends on agent adherence and has unit-tested structure; it is
not technical or behavioral enforcement.
The protected set forbids fabricated capability, Review, or test claims;
silent degradation; exposure of credentials or sensitive information;
unauthorized side effects or irreversible operations; damage to existing user
changes; and completion without fresh verification evidence.

## Completion evidence

A trusted, deeply immutable completion policy is passed separately from the
evidence. It fixes task kind, C/R classification, the ordered required
capability list, required criterion and verification IDs, and implementation
identity. It also fixes a per-task operation nonce, artifact freshness window,
and the canonical expected invocation hash for each required verification.
Evidence cannot declare its own governing policy. C1/R1 requires at
least L0 Review; any C/R level 2 or 3 requires at least L2, with reviewer and
context independent from implementation. Only level 2 may fall back to L1,
and only when the trusted policy carries a typed authorization recording that
independent Review capability is unsupported or unverified, the user was
prompted, and the user explicitly authorized the fallback. Level 3 cannot use
this path. L1 fallback is same-host, new-context Review: the actor may be the
implementer, but the Review context must differ from the implementation
context. Evidence cannot self-report or silently trigger the exception.

A modifying task records exactly `classification`, `capabilities`,
`selectedSkills`, `acceptanceCriteria`, `changes`, `review`, `verification`,
`skipped`, and `residualRisks`. Structured change, Review, and verification
records cannot be replaced by empty collections or prose claims. Capability,
Review, and verification references resolve only through a collector-sealed,
deeply immutable artifact store. Review attestations record provider, receipt,
input and output hashes, decision, level, and identities; the collector derives
the input hash from the completion subject and the output hash from the actual
provided receipt content. Verification execution receipts additionally bind a
frozen invocation containing executable/module identity, argv, repository cwd,
controlled environment keys and digest, and input digest. The canonical
envelope is retained with its hash for audit; its cwd is `.` or a canonical
Windows-safe repository-relative directory. The input digest binds the current
task nonce, manifests, derived changes, complete acceptance graph, and result
content before the policy adds the expected invocation hash. Receipts record finite
check type, exit code, timestamps, and criterion links. The trusted policy—not
the evidence—fixes the expected invocation hash. Every acceptance criterion and
verification artifact links in both directions. Every skipped or
not-applicable item has a non-empty reason; required policy items cannot be
skipped.

Base and final file manifests are hashed and compared to derive the exact
added, modified, and deleted paths; declared changes must match that derivation
in both directions. The completion subject hash binds the trusted policy hash,
both manifest hashes, derived changes, the complete criterion/verification
graph (including descriptions, applicability, reasons, and links), and the
result-content hash. Review and verification receipts must bind that subject.
Completion requires `passed` verification observed within its declared
validity window. `failed`,
`not-run`, `partial`, stale, future-dated, clock-rollback, and hash-mismatched
evidence cannot complete. `not-applicable` is eligible only for a pure
`read-only` task with no change items.

Inputs use character/count checks before sequence materialization or UTF-8
encoding where the shape permits, followed by exact UTF-8 accounting. Evidence
JSON is limited to 1 MiB by characters and UTF-8 bytes; ordinary direct text is
limited to 64 KiB and identifiers to 1 KiB; canonical values are limited to
50,000 nodes, 1 MiB per string, and 8 MiB total. Artifact stores are capped at
2,048 records and receipt output at 8 MiB. Evidence collections are capped at
64 capabilities, 256 skills, 512
criteria/verifications/skips, 256 residual risks, and 10,000 changes. Manifests
are capped at 20,000 paths, 8 MiB per file, and 64 MiB total. Repository paths
are canonical Windows-safe relative paths with a 1,024-character path and
255-character segment limit; aliases by NFC/casefold, reserved device names,
ADS, traversal, absolute paths, controls, invalid characters, and trailing dots
or spaces are rejected.

These checks provide deterministic structural, hash, time, manifest, and
policy validation. `ArtifactCollector` is an explicit trusted collection
boundary that preserves audit fields; it is not a defense against malicious
code in the same process and does not independently prove that an external
provider executed a command. Provider trust and receipt acquisition are
deployment responsibilities. Nonces bind receipts to the current trusted
policy/proposal, while durable cross-process replay registries remain a future
transaction-layer responsibility. The collector rejects duplicate
`(provider, receiptId)` pairs within one store, including across artifact kinds.
Separately, `agent-policy` rules depend on agent
adherence and have unit-tested structure, not technical or behavioral
enforcement.

The stable field list and status policy remain in
[the evidence source](workflow/evidence.yaml). The concrete immutable JSON
fixture contract and completion checks are exercised by
[the evidence tests](tests/unit/test_evidence.py). Shared bounded-value,
canonicalization, and manifest checks are in
[the value helper](src/selfworkflow/_evidence_values.py); the typed invocation,
collector, receipt, and trusted-store boundary is in
[the artifact helper](src/selfworkflow/_evidence_artifacts.py).

## On-demand loading

Load only the source needed for the current phase: lifecycle and policy for
capability checking or classification, protected rules for merging or governed
changes, and evidence rules for Review or completion. Load
[the core implementation](src/selfworkflow/evidence.py) only when executing or
auditing those deterministic checks. This keeps unrelated phase material out of
the active context while preserving direct links to every implemented contract.

## Superpowers source support

Modifying tasks require a user-selected, inspected Superpowers source. Missing
or declined sources pause writes; read-only analysis may continue only with an
explicit limitation. Catalog v2 loads only Skills mapped to the current Pipeline slot.
Grill-me is explicit-only; a high complexity/risk classification recommends it
but never activates it. A completed Grill-me design requires a separate-context
Brainstorming cross-review before implementation. Source selection, dirty-state
authorization, stage mappings, and runtime loading are deterministic contracts
in `dependencies/superpowers.lock.yaml` and `overlays/superpowers/`.

## Adapters, knowledge, and release governance

Vendor adapters are thin capability declarations and bootstrap entries; they
cannot override protected invariants. Runtime builds contain checked-in sources
and generated Catalog data, never maintainer-local source paths. Knowledge is an
optional `read -> propose -> update` extension: propose never publishes, update
requires explicit confirmation and verified compare-and-swap semantics, and
private model reasoning is not durable knowledge. A backend contract gap remains
`unverified` rather than being inferred.

Release eligibility requires a clean source commit, fresh passed unit,
conformance, installer, and behavioral receipts, independent L2-or-higher Review,
and native evidence for both Codex CLI and Desktop. Static conformance cannot be
promoted to native support. Skipped checks and residual risks remain visible in
the release manifest.
