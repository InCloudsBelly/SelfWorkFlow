# SelfOpenWiki v2 测试设计与风险评估

Status: implementation landed; post-landing Review and verification pending.

Date: 2026-09-10

## 1. Scope

This is a system-level test design for the OpenWiki Submodule upgrade,
personal six-stage lifecycle adapter, existing nine-tool C7 compatibility,
versioned Skill adaptation, explicit external Wiki root, and update iteration
workflow.

Priority labels P0/P1/P2/P3 describe risk and user impact, not execution timing.

## 2. Risk assessment

| ID | Category | Risk | P | I | Score | Mitigation | Owner |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| R-001 | BUS/TECH | Six-stage semantics are mapped incorrectly and personal deposition loses pages or lifecycle state. | 2 | 3 | 6 | Contract tests for every stage, durable resume tests, trace matrix, independent Review. | Lifecycle adapter |
| R-002 | DATA | Candidate or `finish` writes directly to the formal Wiki before review/CAS. | 2 | 3 | 6 | Black-box publication-boundary tests, crash injection, unchanged formal-tree assertions. | C7 transaction |
| R-003 | DATA/SEC | `wikiRoot`, runtime sibling, and user `.git` metadata overlap or are replaced. | 2 | 3 | 6 | Canonical path tests, link/junction rejection, sentinel and Git identity checks. | Storage owner |
| R-004 | TECH | Upstream update leaves adapter or Skill bound to an incompatible protocol. | 3 | 3 | 9 | Explicit commit lock, protocol snapshot, capability matrix, fail-closed drift tests. | Update coordinator |
| R-005 | TECH | Legacy nine-tool callers regress while the new six-stage surface is added. | 2 | 3 | 6 | Existing C7 suite plus mixed-surface isolation and tool discovery tests. | MCP surface |
| R-006 | DATA | Claims/frontmatter migration changes accurate personal content without approval. | 2 | 3 | 6 | Read-only drift detection, candidate-only migration, explicit confirmation, byte/metadata diff. | Skill adapter |
| R-007 | OPS | Invalid status/capability evidence permits a run to continue. | 2 | 3 | 6 | Structured-result validation, fail-closed startup, stale-hash and missing-evidence tests. | Capability gate |
| R-008 | OPS | Interrupted Writer/Reviewer/CAS run cannot resume or leaves residue. | 2 | 3 | 6 | Failure injection at every stage, startup rehydration, recovery scrub and idempotency tests. | Transaction owner |
| R-009 | PERF | Page-by-page personal Wiki runs grow state or latency without a bounded policy. | 2 | 2 | 4 | Measure representative page queues and record thresholds as UNKNOWN until baseline exists. | Lifecycle adapter |
| R-010 | MAINT | Personal behavior leaks into upstream patching, making future Submodule updates expensive. | 3 | 2 | 6 | Source-clean assertion, patch diff budget, adapter ownership tests, update simulation. | Repository owner |

P=probability, I=impact. Scores ≥6 are high-priority mitigations.

## 3. Acceptance-to-test trace

| AC | Scenario IDs | Level | Priority |
| --- | --- | --- | --- |
| AC-01 | S-050–S-056 | integration / system | P0 |
| AC-02 | S-010–S-019, S-027–S-029 | API / system | P0 |
| AC-03 | S-020–S-026 | API / regression | P0 |
| AC-04 | S-030–S-039 | system / failure-path | P0 |
| AC-05 | S-040–S-047 | unit / integration | P0 |
| AC-06 | S-017–S-019, S-030–S-039, S-048–S-059 | API / system | P0 |
| AC-07 | S-060–S-062, S-067–S-068 | unit / integration | P0 |
| AC-08 | S-066–S-078 | system / update simulation | P0 |
| AC-09 | S-063–S-065, S-079–S-089 | build / migration / stdio / installer | P0 |
| AC-10 | S-089–S-093 | review/evidence gate | P0 |

Each scenario range has one named fixture owner and one planned command family;
the final implementation must replace these planned paths with actual test
files and record the exact invocations in fresh receipts.

| Scenarios | Fixture / seam | Planned command family |
| --- | --- | --- |
| S-010–S-019, S-027–S-029, S-038b | `personal-lifecycle.v2` with in-memory RunStore, fake clock, candidate binding and Claim fixtures | `corepack pnpm@10.33.2 --dir self-openwiki/mcp-server exec vitest run test/personal-lifecycle.v2.ts` |
| S-020–S-026, S-037–S-039, S-076 | `mcp-surface.v2` in-process MCP request/response harness | `corepack pnpm@10.33.2 --dir self-openwiki/mcp-server exec vitest run test/mcp-surface.v2.ts` |
| S-030–S-036, S-048–S-049, S-084 | `transaction-recovery.v2` with crash points, lock owner and C7 journal fixtures | `corepack pnpm@10.33.2 --dir self-openwiki/mcp-server exec vitest run test/transaction-recovery.v2.ts` |
| S-040–S-047, S-087–S-088 | temporary independent Git Wiki with metadata/sentinel snapshots | `corepack pnpm@10.33.2 --dir self-openwiki/mcp-server exec vitest run test/wiki-root-boundary.v2.ts` |
| S-050–S-059, S-066–S-078 | exact-commit Submodule fixture, zero-patch manifest, isolated parent copy | `node --test test/update-upstream.v2.test.mjs` |
| S-060–S-065 | Skill package fixture and canonical hash vectors | `corepack pnpm@10.33.2 --dir self-openwiki/mcp-server exec vitest run test/skills.v2.ts` |
| S-079–S-086, S-089 | fresh install, built distribution and real stdio process | `corepack pnpm@10.33.2 --dir self-openwiki/mcp-server test` |
| S-090–S-093 | immutable document package and evidence-gate fixtures | SelfWorkflow Review/Verify commands with bound receipts |

## 4. Direct and failure-path coverage

### P0 lifecycle

- S-010: `begin` accepts an existing canonical external Wiki root and returns
  a new durable personal run.
- S-011: `begin` resumes the same run after process restart.
- S-012: `begin` returns noop when the bound Wiki/source/Skill revisions have
  no required changes.
- S-013: `begin` rejects a changed Wiki revision, source manifest, or Skill
  hash and requires a new plan.
- S-014: `submit_plan` stores meaningful personal taxonomy and rejects paths
  outside the root or generated index authoring; a plan with no page and no
  deletion is rejected, while no-work updates return `begin`'s noop.
- S-015: `next_page` returns one deterministic assigned page job plus a
  persisted candidate write package whose root is a runtime descendant and
  whose page path is the only permitted changed path; queue order survives
  retry.
- S-015a: a candidate root outside `<wikiRoot>.selfopenwiki`, or with a link or
  junction ancestor, is rejected before a write package is exposed; a valid
  upstream transaction is sent through the C7 abort seam when possible.
- S-016: `inspect_page_claims` reads the authoritative `.claims/` sidecar
  bound to the current page revision and is required only for intentional
  revision or retraction of otherwise-current Claims.
- S-017: `submit_page` accepts one assigned page with OKF metadata and sparse
  Claim decisions, and rejects non-assigned pages.
- S-018: invalid page, evidence, Claim, or schema input leaves the durable run
  resumable and formal Wiki unchanged.
- S-018a: a stale or malformed personal Claim sidecar fails closed; client
  Claim input cannot replace the authoritative sidecar snapshot.
- S-019: queue exhaustion returns nonterminal `queue_complete`, and `finish`
  returns complete only after all page jobs and C7 publication gates are closed.
- S-019a: `finish` derives Claim sidecars from the reviewed candidate bytes, so
  modified existing pages and newly created pages receive matching
  `pageVersion` hashes after C7 publication.

### P0 legacy and boundary regression

- S-020: all 15 intended tools are discovered with stable names and separate
  descriptions/schemas.
- S-021: old `openwiki_status` returns a valid structured result or a valid
  structured fail-closed error; no raw invalid structured result is emitted.
- S-022: old external-agent begin/finalize flow still enforces writer/reviewer
  identity, receipt binding, and no direct formal writes.
- S-023: legacy provider tools require their explicit discriminator and cannot
  become the default external flow.
- S-024: six-stage and nine-tool runs cannot cross `wikiRoot` or active-run
  identities.
- S-025: a failed six-stage run can be resumed without duplicating pages,
  Claims, or publication.
- S-026: tool error codes remain strict, bounded, and recoverable; business and
  transport failures use `isError: true` without `structuredContent`, while
  resumable statuses use validated success content.
- S-027: submitting the same page payload twice returns the same accepted
  result without duplicating Claims or advancing the queue twice.
- S-028: submitting a different payload for an already accepted job is
  `invalid_state`; it cannot overwrite the candidate or Claim record.
- S-029: a `changes_requested` repair creates a new generation with new
  candidate and receipt bindings; generation 4 or any silent repair after the
  two-successor limit is rejected as `needs_clarification`.

### P0 publication and recovery

- S-030: `submit_page` changes only the isolated candidate.
- S-031: Writer failure preserves candidate and returns a resumable failure.
- S-032: Reviewer failure preserves candidate and prevents publication.
- S-033: blocking Claim issue prevents `finish` and formal Wiki change.
- S-034: CAS conflict prevents publication, reports the current revision, and
  requires refresh/reconfirmation.
- S-035: crash before candidate adoption leaves formal Wiki and user `.git`
  unchanged.
- S-036: crash during adoption recovers or rolls back atomically and scrubs
  temporary residue; the candidate-marker/RunStore matrix handles absent,
  candidate-written with or without acceptance, accepted, and mismatched
  records, including `accepted + absent` entering `restore_required`, exactly
  as specified.
- S-037: the adapted `finish` returns `review_required` while the C7
  transaction is candidate-writable or review-ready, and remains resumable.
- S-038: a published C7 transaction is acknowledged by `finish` exactly once;
  duplicate finish calls do not create a second publication or generation.
- S-038a: terminal RunStore state is written before the active pointer is
  removed, and a restart replays the same terminal result without duplicating
  publication.
- S-038b: a restart after C7 publishes Markdown but before the personal
  finalization marker advances from `prepared` to `published` promotes the
  hash-matched marker, applies Claims exactly once, and lets the RunStore bind
  to the recovered terminal revision.
- S-039: reviewer and writer execution IDs are distinct, every receipt binds
  the same run/generation/candidate/Claim hashes, all four verdicts map to the
  declared finish states, and a replayed old generation is rejected.

### P0 storage, source, and security

- S-040: relative, non-canonical, missing, symlinked, junctioned, and aliased
  Wiki roots are rejected.
- S-041: `runtimeRoot` is exactly `<wikiRoot>.selfopenwiki`, is a sibling, and
  cannot be inside the Wiki tree.
- S-042: user `.git` identity and configuration are preserved across all normal
  runs, migration candidates, and failures.
- S-043: source manifests require explicit confirmation and become invalid on
  file hash or path changes.
- S-044: sensitive or unsupported source files cannot bypass preparation.
- S-045: no credentials, provider tokens, or private model reasoning appear in
  Wiki pages, claims, receipts, or diagnostics.
- S-046: path traversal, ADS, reserved device names, case collisions, and
  control characters are rejected.
- S-047: a user Wiki outside the SelfOpenWiki repository is never silently
  replaced by a repository-local default.

### P0 binding and drift

- S-048: `PersonalRunStore` contains only one canonical run record and stores
  C7 transaction/receipt references rather than duplicate candidate or review
  state.
- S-049: two MCP processes competing for one `wikiRoot` are serialized by the
  operation/wiki lock; a PID mismatch alone cannot take over a live lock.

### P0 upstream iteration and build

- S-050: exact upstream commit equals the parent gitlink and remote reference
  when an explicit upgrade is requested; a dirty parent gitlink is preserved
  and never overwritten during candidate preparation.
- S-051: the official Submodule worktree is clean before and after materialize
  and build.
- S-052: adapter/Skill/capability evidence hashes, including tool annotation
  and description hashes, are invalidated when any bound input changes.
- S-053: unsupported upstream protocol or missing official build fails closed
  before personal Wiki access.
- S-054: an update candidate can build the official Submodule unchanged and
  the SelfOpenWiki adapter against it.
- S-055: stale patch manifests cannot be applied to a new upstream commit.
- S-056: the active v2 manifest rejects any non-empty patch list; the old patch
  is treated as historical input only.
- S-057: an upgrade simulation updates Submodule, Skill, adapter, tests, and docs
  without modifying personal Wiki data.
- S-058: materialization failure leaves parent gitlink and personal Wiki
  unchanged.
- S-059: current official Claims/PageJob/finish capabilities are represented
  in the capability matrix, provenance is finalized by the runtime, and the
  mapping is tested at the adapter seam.

### P0 update and release gate

- S-066: a user-provided upstream tag is resolved to one exact commit before
  the gitlink or manifest changes; only the exact commit is persisted.
- S-067: the compatibility manifest binds all six input/output schema hashes,
  adapter source hashes, Skill package hash, upstream commit, and capability
  IDs using the specified canonical UTF-8 and length-prefixed bytes; fixture
  vectors cover empty, modified, deleted/conflicted, and dirty-gitlink source
  manifests. The parent source helper uses one complete three-layer vector and
  excludes only its two generated binding outputs to avoid a self-hash cycle.
- S-068: changing any bound adapter, schema, Skill, or upstream byte invalidates
  only the six-stage capability set and leaves legacy state explicit.
- S-069: a generated candidate can be rebuilt from the clean Submodule and
  parent sources without mutating the user Wiki or upstream worktree.
- S-070: update failure before candidate adoption leaves the parent gitlink,
  manifest, generated tree, and personal Wiki unchanged.
- S-071: update failure after a disposable candidate is created removes or
  quarantines only that candidate and preserves the prior usable artifact.
- S-072: current official tool names, protocol version, annotations, and
  intentional personal schema deviations match the compatibility matrix.
- S-073: official Claims/PageJob/finish behavior is represented by the adapter
  without importing upstream private persistence ownership.
- S-074: active-run source, Skill, adapter, or upstream drift invalidates the
  plan, preserves the candidate, and requires a new `begin`.
- S-075: a changed compatibility manifest cannot be adopted with old capability
  receipts.
- S-076: all 15 tools have deterministic discovery order and no schema/name
  collision between adapted six-stage and legacy nine-tool paths.
- S-077: build and capability evidence bind the same parent commit, Submodule
  commit, adapter hash, Skill hash, generated marker, lockfile, and explicit
  WikiRootResolver/C7 marker owner source files, including the C7 transaction,
  publisher, and recovery implementations.
- S-078: rollback of an update restores prior generated artifacts and binding
  metadata without deleting or rewriting a live personal Wiki run; ambiguous
  recovery keeps the journal and lock for explicit manual recovery and never
  checks out the active Submodule as a repair shortcut.

### Skill contract and migration safety

- S-060: Skill manifest validates id, version, upstream commit, protocol
  version, package hash, and ordered composition.
- S-061: Skill drift is reported as unverified and blocks writing.
- S-062: personal Skill describes the six-stage flow and C7 publish boundary
  without claiming official schema identity.
- S-063: detected legacy format drift creates a migration candidate only.
- S-064: explicit migration confirmation publishes through the normal review
  and CAS path.
- S-065: migration failure leaves original bytes and `.git` metadata intact.

### P0 build, host, and evidence execution

- S-079: clean install/build succeeds from a fresh parent checkout with the
  exact Submodule gitlink and zero-patch manifest.
- S-080: launch `node self-openwiki/mcp-server/dist/index.js` through the MCP
  SDK stdio client, validate framing, discover all 15 tools in the canonical
  order, and execute adapted six-stage calls with structured outputs.
- S-081: explicit external Git `wikiRoot` smoke completes a candidate/review/
  publish/finish cycle without commit or push.
- S-082: installer writes only approved local config/Skill/MCP targets and
  preserves existing user-owned targets on failure.
- S-083: capability verification fails closed on missing, stale, or invalid
  structured status and emits no false verified record.
- S-084: process restart after each lifecycle stage resumes the same run and
  does not duplicate PageJobs or Claims.
- S-085: all failure-path diagnostics are bounded and scrub credential-like
  content.
- S-086: generated indexes, provenance, run metadata, and receipts are owned by
  the runtime and are not authored as assigned page content.
- S-087: manual Git inspection confirms no commit, ref, index, config, hook,
  remote, or reflog change in the personal Wiki during the MCP cycle.
- S-088: current user uncommitted Wiki changes survive both successful candidate
  publication and every failed/recovered run.
- S-089: fresh verification receipts bind the exact invocation, cwd, controlled
  environment, input digest, exit code, failure count, and acceptance IDs;
  independent Standards and Spec Review receipts each bind the immutable
  three-document package hash, level >= L2, input/output hashes, and distinct
  execution ids.

### P0 Review/evidence completion

- S-090: pre-implementation Review receives the exact three-document package
  and returns the same package hash.
- S-091: open Critical/Important Review findings prevent implementation or
  completion.
- S-092: every Minor Review finding has an explicit disposition.
- S-093: post-landing Review and verification are invalidated by package or
  working-tree drift and must be freshly rerun.

The Review fixture is a strict receipt, not a prose assertion:

```text
ReviewReceiptFixture = {
  type: "selfworkflow-review-receipt-v1", version: 1,
  axis: "standards" | "spec",
  provider: bounded-id, receiptId: bounded-id,
  reviewerIdentity: bounded-id, reviewerContextId: bounded-id,
  executionId: bounded-id,
  reviewModel: bounded-id, reasoningEffort: "low" | "medium" | "high" | "xhigh" | "max" | "ultra",
  reviewExecutionMode: "ephemeral-subagent",
  lifecycle: "created-executed-cleaned",
  packageHash: Hash, inputHash: Hash, outputHash: Hash, summaryHash: Hash,
  decision: "approve" | "request_changes",
  level: "L2" | "L3",
  issues: [{ severity: "critical" | "important" | "minor" | "info",
             code, message, disposition? }](0..256),
  producedAt: UTC RFC 3339
}
```

S-089 asserts every field above, recomputes `outputHash` from the actual
receipt, and requires two receipts with the same `packageHash` but distinct
`axis`, `receiptId`, `reviewerIdentity`, `reviewerContextId`, and `executionId`.
Both must be `approve`, level `L2` or `L3`, and have a cleaned ephemeral
lifecycle; no private reviewer reasoning is accepted. S-090 recomputes the
three-document package hash before comparing both receipt inputs. S-091 maps
`critical`/`important` to a blocking gate, S-092 requires a non-empty
`disposition` for every `minor`/`info` issue, and S-093 changes one package,
manifest, or worktree byte to prove both receipts become stale and cannot
satisfy completion.

## 5. Test seams

Preferred seams, in order:

1. Pure contract adapters for upstream request/result mapping.
2. Injected clock, filesystem, path resolver, Git command runner, and receipt
   store already used by the C7 runtime.
3. Temporary isolated Wiki repositories with sentinel files and real `.git`
   metadata.
4. MCP in-process request handlers for strict tool and structured-output tests.
5. Real stdio MCP smoke using the built distribution.
6. A disposable exact-commit upgrade fixture for materialization and update
   simulation.

No test-only production macro or public enum change is planned. Test coverage
must not drive a broader runtime abstraction than the above seams require.

## 6. NFR planning

| Area | Planned evidence | Threshold |
| --- | --- | --- |
| Security/path safety | canonical-path, link, ADS, secret, Git-config and credential tests | Exact rejection of unsafe inputs; no credential leakage |
| Reliability/recovery | crash/failure injection at every transaction phase and restart/resume | No formal Wiki mutation on failed or incomplete runs; resumable state is deterministic; closure requires no lock, journal, marker, or active transaction |
| Maintainability | adapter ownership, patch-size/path audit, Skill hash and update simulation | No Submodule source edit; all extension behavior has a parent owner |
| Performance | 10, 100, and 500 page queues with representative Claim/source manifests; `corepack pnpm@10.33.2 --dir self-openwiki/mcp-server exec vitest run test/performance.v2.ts --reporter=json` | UNKNOWN until baseline is collected; record measurements, never guess a threshold |
| Compatibility | six-stage contract, nine-tool regression, old content read, explicit migration | P0 contract and regression scenarios pass |

## 7. Execution strategy

- PR: all unit, contract, adapter, C7 regression, path-safety, Skill, and
  materialization tests that fit within the repository's normal test budget.
- Nightly/weekly: real stdio, installer, crash/recovery stress, large Wiki,
  and performance measurements.
- Manual release gate: independent Standards/Spec Review, fresh capability
  evidence, user-facing personal Wiki smoke, and explicit external Git review.

P0 requires 100% pass. P1 requires at least 95% pass with no unresolved high
risk. Any failed security, data-integrity, recovery, or drift scenario blocks
release regardless of aggregate percentage.

## 8. Evidence gaps

- The generated compatibility manifest and adapter hashes must be refreshed
  after the final source/document edits; until that receipt exists, startup
  compatibility remains unverified.
- Native Win32 helper build/stdio evidence is environment-dependent and is
  currently unverified when the installed .NET SDK lacks its required runtime
  pack.
- The personal adapter now includes `.claims` sidecars in its personal root
  revision and persists reconciled Claims after C7 publication through a
  hash-checked durable finalization journal with idempotent startup recovery;
  recovery also closes the C7-published/prepared-marker crash window before
  RunStore binding. The final full MCP suite now passes 43/43 files and
  669/669 tests. Native
  helper/stdio and post-landing receipts remain environment/release checks.
- Performance thresholds are not yet established and remain UNKNOWN.

These are implementation and verification gates, not assumptions of success.
