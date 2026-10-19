# SelfOpenWiki v2 实施计划

Status: implementation landed; post-landing Review and verification pending.

Date: 2026-09-10

## 1. Frozen objective

Upgrade SelfOpenWiki from the old patched OpenWiki/C7 integration to a
versioned adapter architecture that:

- consumes a pinned current OpenWiki Submodule without editing its bytes;
- exposes the adapted official six lifecycle tools across personal Wiki
  creation and update;
- preserves the existing nine C7 tools and publication guarantees;
- adapts the personal Skill and its documentation for every upstream upgrade;
- uses an explicitly configured Wiki root that may be a separate Git repo;
- leaves personal Wiki commit/push to an explicit outer Git workflow.

## 2. Expected implementation contract

### Modification intent

Replace the current direct dependency on the old patched CLI/provider chain with
a SelfOpenWiki-owned personal lifecycle adapter and a versioned Skill contract.
Add adapted six-stage MCP handlers, retain the nine-tool compatibility layer,
and make the upstream update path regenerate all bindings as one reviewable
unit.

### Owner layers and expected files

Expected paths are bounded to these owners; exact private filenames may be
refined after RED tests:

- `self-openwiki/mcp-server/src/contracts.ts`: adapted six-stage schemas and
  shared identity/error types.
- `self-openwiki/mcp-server/src/server.ts`: six-stage registration alongside
  the existing nine-tool surface.
- `self-openwiki/mcp-server/src/runtime.ts`: dispatch seams and capability
  gates; existing C7 paths remain compatibility implementations.
- New private modules under `self-openwiki/mcp-server/src/` for personal
  lifecycle, upstream adapter, Skill manifest, Wiki-root ownership, and the
  C7-owned candidate marker: `official-lifecycle-adapter.ts`,
  `personal-candidate-marker.ts`, `personal-claims.ts`,
  `personal-wiki-snapshot.ts`, `personal-run-store.ts`,
  `personal-skill-adapter.ts`, `personal-wiki-lifecycle.ts`, and
  `personal-wiki-root.ts`.
- `self-openwiki/mcp-server/test/`: contract, lifecycle, boundary, recovery,
  mixed-surface, and stdio tests.
- `self-openwiki/openwiki-skills/` and
  `self-openwiki/agent-skills/self-openwiki/`: personal Skill and references.
- `self-openwiki/config/`: capability matrix, trusted Skill binding, and
  version compatibility data.
- `self-openwiki/config/personal-openwiki-compatibility.json`: exact upstream,
  adapted protocol, six input/output schema hashes, adapter source hashes,
  Skill package hash, and capability IDs.
- `scripts/materialize-openwiki.mjs`, `scripts/update-upstream.mjs`, and
  related tests: explicit upstream upgrade and clean-build ownership.
- `scripts/parent-source-manifest.mjs`: complete, hash-bound parent `HEAD`,
  index, and worktree source observation used by compatibility checks; its two
  generated binding outputs are excluded to avoid a self-hash cycle.
- `patches/openwiki/`: historical v1 input only; the active v2 manifest must
  contain zero patches.
- `README.md` and new v2 migration/update docs: user-facing setup and
  operational contract.

No file inside `upstream/openwiki` is an allowed implementation target.

### Alternatives considered

1. Continue the broad internal upstream patch: rejected because it already
   fails against v0.5.1 and makes each Submodule update a patch migration.
2. Reimplement the official six tools independently: rejected because it
   duplicates upstream lifecycle logic and risks protocol drift.
3. Use a SelfOpenWiki adapter plus versioned Skill and keep the Submodule
   clean: selected because ownership and upgrade seams are explicit.

### Intrusion budget

Allowed impact is parent MCP/server/config/Skill/scripts/tests/docs plus the
derived runtime sibling. No upstream source edit, public ABI change outside
the MCP package, personal persistent-format rewrite, automatic Git push, or
provider-default expansion is allowed.

Crossing any of those boundaries invalidates this plan and requires a new
design, Review, and user confirmation.

### Persistence ownership

`PersonalRunStore` is the sole owner of the adapted six-stage durable run,
PageJob queue, personal Claim decisions, source/Skill/upstream bindings, owner
lease, and the C7 transaction reference. It does not copy candidate bytes or
review state. `C7Transaction` remains the sole owner of candidate bytes,
Writer/Reviewer receipts, review package, recovery journal, and CAS
publication. `WikiPublisher` remains the sole formal Wiki tree owner.

The narrow bridge is `validateAssignedPage(runId, jobId, transactionId,
bindingHash, claimDecision)`: it verifies the active job and C7 candidate
binding, reads the host-written assigned Markdown inside the candidate root,
and atomically advances the RunStore record. `finish` returns `review_required`
or `publish_pending` until the C7 transaction is terminally published; only
then can it return `complete`.

Personal Claim snapshots are read from the external Wiki's validated `.claims/`
sidecars and bound to the page content revision. Client inputs submit sparse
decisions against that snapshot; they do not become an authoritative Claim
source. A plan with no page and no deletion is rejected; an update with no
work returns `begin`'s idempotent `noop` result.

The existing `withC7Locks` operation/wiki locks provide the cross-process
owner-lease seam. A durable owner token and process-start metadata are stored
for diagnostics, but a PID mismatch alone never authorizes takeover.

### Compatibility and rollback

- Existing nine-tool schemas and C7 transaction state remain readable.
- The new six-stage surface is additive and explicitly labeled adapted.
- A failed build or capability check leaves the prior generated/runtime
  candidate and personal Wiki unchanged.
- A failed Wiki update leaves formal content and user `.git` unchanged.
- A rejected migration leaves the old Wiki tree available.
- A live or interrupted personal run is never deleted during product rollback;
  it remains resumable or enters the existing `restore_required`/abort path.
- A created candidate is deleted or quarantined only by its C7 recovery owner;
  the adapter never recursively removes a user Wiki root.
- A published Wiki is not automatically rewritten to roll back a software
  update; the user-owned Git repository provides the explicit content revert.
- Rollback is the prior parent commit plus prior exact Submodule gitlink and
  Skill hash; no destructive reset is part of the plan.

### Test seams

Use existing injected runtime dependencies and add only narrow seams for:

- upstream protocol mapping;
- durable run store and page queue;
- canonical Wiki-root resolver;
- candidate/publish transaction;
- Skill hash/manifest loader;
- Git/materialization command runner;
- clock, crash, and receipt injection.

## 3. Implementation stages

### Stage A — Baseline and contract freeze

1. Capture current parent/Submodule gitlink, current v0.1 docs, nine-tool
   schemas, capability matrix, and failed materializer evidence.
2. Record the existing parent `M upstream/openwiki` as a user-owned working
   tree change. Do not reset, checkout, stage over, or overwrite it. Use an
   isolated validation copy whenever a clean parent tree is required.
3. Define the adapted six-stage schemas and state/error mapping in the design
   document before production edits.
4. Freeze the version binding tuple:
   `upstreamCommit + adapterVersion + personalSkillHash + protocolVersion`.

Exit: design package and acceptance/test matrix are Review-ready.

### Stage B — Adapter and lifecycle core

1. Write RED contract tests for each adapted six-stage tool and the shared
   `wikiRoot`/run identity invariants.
2. Implement the smallest `PersonalRunStore` and `OfficialLifecycleAdapter`
   modules that can begin, plan, schedule, inspect Claims, validate a
   host-written candidate page, and finish only through the C7 publication
   seam.
3. Map upstream Claims/PageJob concepts to the personal run without duplicating
   C7 candidate/review persistence ownership.
4. Have `C7Transaction` create
   `<runtimeRoot>/transactions/<transactionId>/generations/<generation>/candidate`
   before `next_page`; return that candidate root, the assigned relative page
   path, and exact read/list/write permissions as a persisted write package.
5. Make `submit_page` validate the host-written assigned candidate page, not
   write formal content. Make `finish` accept only strict untrusted candidate
   or review receipts, delegate validation to C7, and return resumable
   `review_required`/`publish_pending` states until final publication.
6. Add failure, resume, conflict, duplicate-submit, generation-replay, repair
   limit, receipt-binding, and queue-order tests.
7. Require candidate roots to remain under the selected runtime sibling and
   reject link/junction ancestors before exposing a write package.

### Stage C — MCP integration and legacy compatibility

1. Add six-stage tool schemas and handlers without changing old tool schemas.
2. Route overlapping operations to shared root, Skill, source, Claim, and
   transaction owners.
3. Fix the six-stage and legacy envelope path so every success has validated
   `structuredContent`, while every business/protocol failure has `isError: true`
   with a validated JSON error envelope and no `structuredContent`.
4. Add the bounded error-code/recovery mapping from the design and ensure
   invalid output is converted to a validated fail-closed envelope.
5. Run mixed-surface isolation and existing C7 regression tests.

### Stage D — Skill adaptation and personal Wiki documentation

1. Update the personal Skill to describe the adapted six-stage flow, C7
   publication boundary, Claim decisions, migration behavior, and explicit
   `wikiRoot`.
2. Add exact upstream compatibility, protocol version, package hash, and
   capability requirements.
3. Keep the official upstream Skill as an upstream input/reference; do not
   edit it or imply that it defines personal policy.
4. Add migration and operations references without rewriting historical v1
   documents.

### Stage E — Submodule update and materialization

1. Define `selfopenwiki:openwiki-patch-manifest:v2` with an exact upstream URL,
   exact 40-hex commit, and `patches: []`; reject the v1 domain and never load
   its old broad patch.
2. Resolve `--tag <name>` using the exact remote tag and peeled tag object
   before any gitlink or manifest mutation; persist only the resolved commit.
3. Prepare the parent gitlink and update the expected commit in the zero-patch
   upgrade candidate from the old frozen value to the reviewed v0.5.1 commit;
   do not mutate the current parent index while building or testing. The
   current `M upstream/openwiki` is preserved as the user's exact worktree
   selection.
4. After the candidate passes Review and the user explicitly authorizes
   adoption, stage only that exact Submodule gitlink with ordinary Git
   operations; never reset, checkout, or overwrite unrelated parent changes.
5. Make materialization build the official Submodule unchanged, skip
   `git apply` completely for v2, and prove the generated tree is reproducible.
6. Remove the broad personal behavior from the old patch path. If the upstream
   built protocol/export cannot support a required capability, stop with
   `upstream_incompatible`; do not reintroduce an internal patch fallback.
7. Update `personal-openwiki-compatibility.json`, capability matrix, Skill
   hashes, package/version locks, and update
   simulation tests.
8. Recompute the exact parent source-manifest vectors, adapter/C7 owner source
   set, Skill, generated-marker, and lockfile hashes before writing the
   compatibility manifest.
9. Verify parent/Submodule cleanliness and no personal Wiki access during
   materialization.

The update candidate is transactional at the parent-artifact level: capture
the current gitlink, active manifest, generated marker, adapter/Skill hashes,
and package lock; build and validate a disposable candidate; adopt the
candidate only after all checks pass; on failure restore only the candidate
artifact set from the captured bytes. The coordinator never uses `git reset`
or `git checkout` to repair the current worktree. If recovery cannot restore a
captured artifact without ambiguity, it leaves the journal and lock in place
for explicit manual recovery rather than guessing. A live personal RunStore or
C7 transaction is preserved and handed to its own restore/abort path rather
than being deleted by the product rollback.

### Stage F — Migration, installer, and host verification

1. Preserve explicit `--wiki-root` and sibling runtime derivation; for the
   v2 six-stage flow require the path to be the exact top level of an existing
   independent Git repository and do not auto-initialize one.
2. Add adapted six-stage personal Wiki smoke against a temporary external Git
   working tree.
3. Test detected drift as candidate-only migration; require explicit user
   confirmation before publication.
4. Run real stdio MCP, installer, recovery, and capability verification.

## 4. TDD contract

Behavior changes require real RED and GREEN evidence.

RED must be a focused command that fails because the adapted behavior is
missing, not because materialization or TypeScript compilation is broken. The
first RED slice should cover `openwiki_begin` for an explicit external
`wikiRoot`, followed by the six-stage lifecycle and publication boundary.

GREEN reruns the same command after the smallest implementation and then runs
the narrowest affected regression. Later stages repeat this pair for Skill
drift, upstream update simulation, recovery, and the nine-tool compatibility
surface.

Expected command families, to be resolved against actual package scripts before
execution:

```text
corepack pnpm@10.33.2 --dir self-openwiki/mcp-server vitest run <focused-test>
corepack pnpm@10.33.2 --dir self-openwiki/mcp-server typecheck
corepack pnpm@10.33.2 --dir self-openwiki/mcp-server test
node scripts/materialize-openwiki.mjs
node scripts/update-upstream.mjs --help
corepack pnpm@10.33.2 test
```

The materializer is currently expected to fail before the update migration is
implemented because its frozen commit is stale; that failure is baseline
evidence, not RED for a lifecycle feature.

## 5. Review and verification gates

### Pre-implementation

- Deep design Review receives this design, test design, plan, acceptance
  criteria, rules, and complete document hash.
- Standards and Spec results are independent and hash-bound.
- Critical/Important findings are resolved; every Minor has a disposition.
- The user confirms the final implementation contract.

### Post-landing

- Complete diff Review covers parent code, scripts, Skills, configs, tests,
  docs, gitlink, generated artifacts, and file modes.
- Fresh capability verification proves the exact upstream/adapter/Skill tuple.
- Fresh tests cover P0 direct and failure paths plus P1 compatibility.
- Real stdio and external Wiki-root smoke tests pass.
- No stale, unbound, partial, or fabricated evidence is accepted.

## 6. Out of scope

- Editing or forking upstream OpenWiki source as a product feature.
- Automatic tracking of upstream `main`.
- Automatic personal Wiki commit/push.
- Deleting or rewriting historical v1 design documents.
- Automatic migration of personal Wiki content.
- Adding unrelated providers, model selection, or cloud storage.
- Building a generic multi-user Wiki service.

## 7. Plan gate

This plan is complete as a design artifact but is not implementation
authorization. After independent Review, the implementation contract must be
presented again with the final file set, intrusion delta, RED command, GREEN
command, rollback, and verification commands. Only explicit user confirmation
of that contract permits editing tests or production code.
