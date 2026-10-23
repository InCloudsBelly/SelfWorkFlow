# SelfOpenWiki v2：OpenWiki 官方生命周期与个人 Wiki 适配设计

Status: implementation landed; post-landing Review and verification pending.

Date: 2026-09-10

## 1. Objective

SelfOpenWiki v2 keeps the official `langchain-ai/openwiki` repository as a
reviewed Git Submodule and absorbs its current repository-generation abilities
into the existing personal Wiki workflow. The official six lifecycle concepts
are available throughout personal Wiki deposition, but the personal surface is
an adaptation rather than a claim of byte-for-byte protocol compatibility.

The existing C7 transaction guarantees remain the publication authority:
isolated writer, independent reviewer, candidate validation, compare-and-swap
publication, recovery, and explicit user-controlled Git operations.

## 2. Confirmed decisions

1. The adapted six-stage surface and the existing nine SelfOpenWiki tools
   coexist. Existing callers remain valid.
2. The six-stage surface is usable for personal Wiki initialization, update,
   repair, and deposition, not only for repository code documentation.
3. The host writer writes the assigned page inside the C7 candidate root;
   `submit_page` validates that candidate page and records its Claim decision.
   It never directly publishes to the formal Wiki. Publication occurs only
   after the C7 Writer / Reviewer / CAS flow reaches its publish boundary.
4. Upstream OpenWiki remains a clean, pinned Submodule. No SelfOpenWiki bytes
   are written into `upstream/openwiki`.
5. SelfOpenWiki runtime code owns the adapter. The personal Skill package owns
   workflow policy, page/Claim mapping, extension declarations, and exact
   hashes. A Skill is not treated as executable MCP patch code.
6. The selected personal Wiki directory is an explicit absolute `wikiRoot` and
   must be the top level of an independent user-owned Git working tree for the
   v2 six-stage flow. Runtime state is placed in its deterministic sibling
   `<wikiRoot>.selfopenwiki`. The old non-Git path remains a legacy-nine-tool
   compatibility mode only.
7. SelfOpenWiki may write the Wiki working tree after the normal confirmation
   gates, but it does not automatically commit or push the personal Wiki.
8. Upstream upgrades use an explicit reviewed tag or 40-character commit. A
   drifted Submodule, adapter, Skill, or capability evidence set fails closed.
9. Historical v1 documents remain historical. v2 design, migration, and
   update-policy documents are additive.

10. The parent source binding is a complete three-layer source observation
    (`HEAD`, index, and worktree). The two generated binding files are excluded
    from that observation because including either would create a self-hash
    cycle; their own hashes remain bound by the compatibility manifest.

## 3. Evidence and current incompatibilities

- `upstream/openwiki` is currently `v0.5.1` at commit
  `d1c7fc75a6a906da258cd94dbcb1602f98516480`.
- The current patch manifest and materializer still bind
  `355f4f68e71bd024631cdcff7aa871c3e72435da`.
- The old patch fails `git apply --check` against the current upstream in
  Agent, config, and OpenWiki-home files.
- Upstream v0.5.1 provides the six official lifecycle tools and the
  Claims/PageJob/finish repository lifecycle. Its official host Skill is
  repository-oriented, while the CLI still has a separate personal mode.
- The existing SelfOpenWiki server exposes nine C7 tools and its runtime still
  assumes the old patched CLI/provider execution chain.
- The current `openwiki_status` MCP call fails closed because its structured
  result is invalid. This is not usable capability evidence.

These facts make the change an adapter and lifecycle migration, not a simple
Submodule pointer update.

## 4. Module and ownership model

The design uses deep modules with narrow interfaces and explicit seams.

| Module | Responsibility | Stable seam | Must not own |
| --- | --- | --- | --- |
| `UpstreamOpenWikiSource` | Pinned source, official build, six-tool reference contract | Gitlink, package metadata, official integration artifacts | Personal policy or Wiki data |
| `OfficialLifecycleAdapter` | Translate the upstream six lifecycle vocabulary and stable results into the SelfOpenWiki domain | Begin/plan/next/inspect/submit/finish request and result mapping | Personal persistence or C7 publication |
| `PersonalRunStore` | Sole durable owner of personal run state, PageJobs, authoritative personal Claim snapshots/decisions, source/Skill bindings, and lifecycle state | `wikiRoot`, `runtimeRoot`, run id, owner lease, queue hash, C7 transaction binding | Candidate bytes or Git publication |
| `C7Transaction` | Sole owner of candidate workspace, Writer/Reviewer receipts, validation, CAS publication, and recovery journal | Existing external-agent transaction and recovery contracts | Six-stage queue ownership or upstream protocol decisions |
| `PersonalSkillAdapter` | Load and verify the personal Skill, map policy and extensions | Skill id/version/hash/parent upstream commit | Arbitrary executable patches |
| `WikiRootResolver` | Canonicalize and verify the explicit independent Git Wiki root and its read-only Git boundary | Absolute root, Git-top-level identity, before/after metadata snapshot | Personal run state or publication |
| `McpSurface` | Expose adapted six tools and legacy nine tools | Strict Zod schemas, tool names, structured errors | Tool-specific persistence |
| `UpstreamUpdateCoordinator` | Upgrade Submodule, adapter, Skill, locks, tests and docs as one bounded change | Explicit commit/tag input and capability matrix | Floating branch tracking or personal Wiki mutation |

The preferred seam is the SelfOpenWiki adapter/runtime. The official
Submodule is consumed as a dependency and reference implementation. If an
upstream internal symbol is not a stable public export, the adapter uses the
official built MCP process/protocol boundary instead of adding an internal
patch. `PersonalRunStore` is the only owner of the personal six-stage durable
run. It stores references to the C7 transaction and receipt hashes, never a
second copy of candidate or review state.

## 5. Public MCP surfaces

### 5.1 Adapted six-stage surface

The following names are exposed for personal Wiki runs:

1. `openwiki_begin`
2. `openwiki_submit_plan`
3. `openwiki_next_page`
4. `openwiki_inspect_page_claims`
5. `openwiki_submit_page`
6. `openwiki_finish`

The names and lifecycle order follow upstream so clients can reuse the mental
model and most orchestration logic. Input and output schemas are allowed to
contain SelfOpenWiki fields such as `wikiRoot`, `runtimeRoot` references,
source-manifest identity, C7 transaction identity, and personal workflow
state. The adapter documents every intentional difference; it does not claim
official schema conformance where the shape differs.

The adapted semantics are:

| Stage | Personal Wiki meaning |
| --- | --- |
| `begin` | Validate the explicit Wiki root, source bindings, Skill set, current Wiki revision, and resume/no-op state. Create or resume a durable personal run. |
| `submit_plan` | Save a taxonomy and page-job plan for the personal Wiki. The plan may contain personal knowledge areas, source snapshots, and C7 review scope. |
| `next_page` | Return exactly one assigned page job in deterministic order, including current issue Claims and binding hashes. |
| `inspect_page_claims` | Return the current complete Claim set only when an otherwise-current Claim is intentionally revised or retracted. |
| `submit_page` | Validate the host-written assigned Markdown, OKF-compatible metadata, evidence and sparse Claim decisions; record acceptance only in the isolated candidate binding and RunStore. |
| `finish` | Require queue completion, C7 Writer/Reviewer/CAS publication completion, personal `.claims` sidecar synchronization, cleanup/recovery closure, and a final run receipt before returning `complete`. |

### 5.2 Existing nine-tool surface

The current nine tools remain available as a compatibility layer:

`openwiki_status`, `openwiki_setup`, `openwiki_prepare_sources`,
`openwiki_list_skills`, `openwiki_query`, `openwiki_update`,
`openwiki_begin_external_update`, `openwiki_finalize_external_update`, and
`openwiki_set_default_model`.

The compatibility layer delegates to the same root, Skill, source, Claim,
transaction, and recovery owners wherever semantics overlap. It must not
create a second Wiki store or a second publication authority. Legacy provider
and OAuth behavior remains explicit and is never silently used for the
provider-free external flow.

### 5.2.1 Canonical discovery order

`tools/list` returns exactly these 15 names in this order. The status tool is
first so a host can fail closed before starting either workflow; the adapted
six-stage sequence itself remains contiguous and ordered.

1. `openwiki_status`
2. `openwiki_begin`
3. `openwiki_submit_plan`
4. `openwiki_next_page`
5. `openwiki_inspect_page_claims`
6. `openwiki_submit_page`
7. `openwiki_finish`
8. `openwiki_setup`
9. `openwiki_prepare_sources`
10. `openwiki_list_skills`
11. `openwiki_query`
12. `openwiki_update`
13. `openwiki_begin_external_update`
14. `openwiki_finalize_external_update`
15. `openwiki_set_default_model`

Names are unique. Each tool has an independent input schema hash, output
schema hash, description, and annotation record. A collision or order drift
is a compatibility failure, not a cosmetic change.

### 5.3 Shared invariants

- One active durable run per `wikiRoot` and runtime identity.
- All paths are canonical absolute paths at the boundary and normalized
  repository-relative paths inside a run.
- A source or Wiki revision change invalidates the plan and requires a new
  `begin`.
- Existing issue-free Claims are retained automatically; revisions and
  retractions are sparse and explicit.
- Current personal Claims are authoritative only when read from the bound Wiki
  `.claims/` sidecar for the assigned page. Client input can choose decisions
  against that snapshot but cannot introduce a new authoritative Claim set.
- After C7 reports publication, the personal adapter reconstructs each accepted
  page's complete Claim set from the hash-bound candidate page bytes and
  atomically writes its `.claims` sidecar with a `pageVersion` hash of the
  published Markdown. This covers both modified existing pages and newly
  created pages. A sidecar failure prevents the personal lifecycle from
  reporting terminal completion.
- If the process stops after C7 has published the Markdown but before the
  personal finalization marker advances from `prepared` to `published`, startup
  recovery treats the exact `afterWikiHash` match as the publication proof,
  advances the marker, and resumes the idempotent Claims journal before
  RunStore binding is checked.
- Candidate writes are isolated from formal Wiki publication.
- `finish` cannot report success while a Writer, Reviewer, recovery, or CAS
  phase is unresolved.
- Tool failures return structured, bounded errors and never fabricate hashes,
  receipts, revisions, model evidence, or publication facts.

### 5.4 Adapted six-tool contract

The adapted surface is a distinct `selfopenwiki:personal-openwiki-v1`
protocol. It intentionally reuses the six official names but is not advertised
as the official `openwiki` schema. Every request and response is a strict JSON
object. Every response is either a structured success with `ok: true` or a
structured failure with `ok: false`, `error`, and `recovery`; a failure is
never returned as an unvalidated `structuredContent` value.

| Tool | Required input | Success states / required output | Personal extension |
| --- | --- | --- | --- |
| `openwiki_begin` | `wikiRoot`, `mode: init\|update`, optional `language`, `force`, `sourceManifestId`, `sourceConfirmation`, `skills` | `runId`, `wikiRoot`, `runtimeRoot`, `wikiRevision`, `skillAggregateHash`, `upstreamCommit`, `status: noop\|planning\|resuming` | Requires independent Git top-level; validates root, source, Skill, capability tuple, owner lease and active-run binding. |
| `openwiki_submit_plan` | `runId`, `pages[]` with `path`, `title`, `purpose`, optional `seedPaths`, `relatedPages`, `instructions`, optional `deletePages` | `runId`, `status: plan_accepted`, `queueHash`, `pageCount`, `planHash` | Page plan is persisted only by `PersonalRunStore`; generated indexes are not assigned pages. |
| `openwiki_next_page` | `runId` | `status: page_pending` plus `jobId`, page assignment, Claim issue summary, `candidate` write package, and binding hashes; or nonterminal `status: queue_complete` with `nextAction: finish` | One deterministic PageJob at a time; queue state is leased and replay-safe. |
| `openwiki_inspect_page_claims` | `runId`, `jobId` | `runId`, `jobId`, complete current Claim set, `claimsHash` | Allowed only for intentional revision/retraction of otherwise-current Claims. |
| `openwiki_submit_page` | `runId`, `jobId`, sparse `confirmedClaimIds`, `claims`, `retractedClaimIds` | `runId`, `jobId`, `status: page_accepted`, `remainingPages`, `candidateBindingHash` | Reads and validates the assigned Markdown already written inside the C7 candidate root; it does not accept a formal Wiki path or write the formal Wiki. |
| `openwiki_finish` | `runId`, optional untrusted `candidateReceipt`, optional untrusted `reviewReceipt` | `status: review_required\|publish_pending\|complete`; `complete` requires `published: true`, final revision and final receipt hashes | With no receipt it requests the candidate receipt; with a candidate receipt it freezes the Review package; with a valid review receipt it delegates CAS publication. Supplying both receipts is rejected; there is no atomic two-receipt shortcut. Final hashes are runtime output, never trusted input. |

The adapted error-code set is bounded to:
`invalid_input`, `personal_root_invalid`, `busy`,
`capability_unverified`, `upstream_incompatible`, `source_changed`,
`source_manifest_invalid`, `skill_untrusted`, `invalid_state`,
`validation_failed`, `wiki_conflict`, `restore_required`, and `internal_error`.
`review_required` and `publish_pending` are success statuses, never error
codes. Each error code maps to a finite recovery
action. The complete field-level Zod contract, JSON Schema projection, tool
annotations, and version are owned by `mcp-server/src/contracts.ts` and are
hash-bound in the compatibility manifest.

The error mapping is normative:

| Code | MCP transport | Recovery action | Run/data effect |
| --- | --- | --- | --- |
| `invalid_input`, `personal_root_invalid` | `isError: true`, validated error envelope, no `structuredContent` | `none` / `clarify` | No run mutation |
| `busy` | `isError: true`, validated error envelope | `retry` | No state mutation |
| `capability_unverified`, `upstream_incompatible` | `isError: true`, validated error envelope | `none` | No personal Wiki access or write |
| `source_changed`, `source_manifest_invalid` | `isError: true`, validated error envelope | `clarify` | Existing candidate retained; old plan invalid |
| `skill_untrusted` | `isError: true`, validated error envelope | `none` | Existing candidate retained; Skill-bound writes blocked |
| `invalid_state`, `validation_failed` | `isError: true`, validated error envelope | `none` / `retry` | No formal Wiki mutation; durable run remains inspectable |
| `wiki_conflict` | `isError: true`, validated error envelope | `clarify` | No publication; refresh required |
| `restore_required` | `isError: true`, validated error envelope | `restore` | Candidate/journal retained for C7 recovery |
| `internal_error` | `isError: true`, validated error envelope | `retry` only when explicitly retryable | Fail closed; no fabricated result |

Schema validation happens before dispatch and output validation happens before
the MCP result is returned. A failed output parse is converted to the same
bounded `internal_error` envelope, never to a successful `structuredContent`.

### 5.5 State and persistence ownership

`PersonalRunStore` persists one canonical run record under
`<wikiRoot>.selfopenwiki/runs/<runId>/` containing only run identity, owner
lease, queue/page state, source/Skill/upstream bindings, Claim decision hashes,
and the C7 transaction id/binding hash. It does not persist duplicate candidate
bytes or review receipts beyond references and hashes.

`C7Transaction` remains the owner of its existing candidate, review package,
receipt, recovery journal, and publication state under the runtime root. The
host writer receives the C7 candidate work package and writes the assigned page
inside that candidate root. The adapter supplies a narrow
`validateAssignedPage` seam: it verifies the active job, reads only the
assigned candidate file, validates Markdown/OKF/Claim consistency, and
atomically advances the matching PageJob in `PersonalRunStore`. A page is
accepted only when both records bind the same run, generation, job id,
candidate root hash, page content hash, and Claim decision hash.

`WikiPublisher` remains the sole owner allowed to replace the formal Wiki
tree. `openwiki_finish` first checks that the queue is complete. It then accepts
an untrusted C7 candidate receipt only through the strict existing receipt
contract, freezes/prepares the Review package, and accepts an untrusted Review
receipt only through the strict existing receipt contract. C7 recomputes all
candidate/review hashes and calls `WikiPublisher.publish` only for a valid
review verdict. Until that happens `finish` returns a resumable state and
never claims publication.

The existing `withC7Locks` operation/wiki locks are the cross-process owner
lease. Lock acquisition order is always `operation` then `wiki`; no path may
acquire them in reverse. Each lock is an atomically-created directory with a
cryptographically random owner record. The durable run record stores the owner
token and process metadata for diagnostics. There is no time-based lease
expiry: startup recovery validates the owner record and only removes a lock
whose recorded process is no longer alive; a PID mismatch alone never
authorizes takeover. Recovery closure means no live lock, no active
candidate/review/publish journal, no unreconciled marker, and a terminal
RunStore state.

### 5.6 State machine and binding record

The personal run state machine is:

```text
idle
  -> planning | resuming | noop
planning
  -> plan_accepted | invalid_state | drifted
plan_accepted
  -> page_pending | queue_complete | review_required
page_pending
  -> page_pending | queue_complete | drifted | restore_required
queue_complete
  -> review_required | restore_required
review_required
  -> publish_pending | repair_ready | needs_clarification | restore_required
repair_ready
  -> resuming | needs_clarification
publish_pending
  -> complete | restore_required | wiki_conflict
complete
  -> terminal
drifted / restore_required / needs_clarification
  -> resuming only through an explicit recovery or new confirmed run
```

`generation` starts at 1. A `changes_requested` result can create at most two
successor generations, so valid generations are 1, 2, and 3. An exhausted
generation enters `needs_clarification` and cannot be silently replayed.

Every accepted page and every publication transition carries one canonical
binding record:

```json
{
  "protocol": "selfopenwiki:personal-openwiki-v1",
  "runId": "<uuid>",
  "generation": 1,
  "jobId": "<uuid>",
  "wikiRootHash": "sha256:<64-lower-hex>",
  "wikiRevision": "sha256:<64-lower-hex>",
  "planHash": "sha256:<64-lower-hex>",
  "queueHash": "sha256:<64-lower-hex>",
  "transactionId": "<bounded-id>",
  "candidateBindingHash": "sha256:<64-lower-hex>",
  "candidateRootHash": "sha256:<64-lower-hex>",
  "pagePathHash": "sha256:<64-lower-hex>",
  "claimDecisionHash": "sha256:<64-lower-hex>",
  "writerExecutionId": "<bounded-id>",
  "reviewerExecutionId": "<bounded-id>",
  "reviewPackageHash": "sha256:<64-lower-hex>",
  "reviewReceiptHash": "sha256:<64-lower-hex>",
  "runReceiptHash": "sha256:<64-lower-hex>",
  "beforeWikiHash": "sha256:<64-lower-hex>",
  "afterWikiHash": "sha256:<64-lower-hex>"
}
```

The two host-attested receipt inputs accepted by `finish` are strict and
untrusted until C7 validates them:

```text
CandidateReceipt = {
  type: "external_candidate_receipt", version: 1,
  transactionId, generation, bindingHash, writerExecutionId,
  classification: "minor|provisional|blocking",
  issues: [{ code, message, page?, severity }](0..256),
  questions: string[](0..64), summary: string(1..16384)
}

ReviewReceipt = {
  type: "external_review_receipt", version: 1,
  transactionId, generation, bindingHash, reviewPackageHash,
  candidateRootHash, candidateReceiptHash, reviewerExecutionId,
  verdict: "pass|follow_up|changes_requested|requires_user",
  issues: [{ code, message, page?, severity }](0..256)
}
```

`writerExecutionId` and `reviewerExecutionId` must be non-empty bounded
identities and must differ. C7 binds both to the same transaction, generation,
candidate root, Review package, and RunStore binding. A receipt from an older
generation, a different run, or a different candidate root is rejected. C7
recomputes the candidate and Review receipt hashes; the host supplies evidence,
not authority.

The receipt sequence and verdict mapping are fixed:

| Input to `finish` | Required current state | Result |
| --- | --- | --- |
| neither receipt | queue complete, C7 candidate writable | `review_required`, `nextAction: submit_candidate_receipt` |
| valid `candidateReceipt` only | queue complete, candidate receipt not yet frozen | `review_required`, `nextAction: submit_review_receipt`, frozen Review package |
| valid `reviewReceipt` with `pass` or `follow_up` | Review package frozen and candidate unchanged | C7 calls `WikiPublisher`; `publish_pending` during recovery or `complete` after CAS |
| valid `reviewReceipt` with `changes_requested` | Review package frozen | `repair_ready` with next generation, until generation 3; then `needs_clarification` |
| valid `reviewReceipt` with `requires_user` | Review package frozen | `needs_clarification`; candidate retained and not published |
| both `candidateReceipt` and `reviewReceipt` | any state | `invalid_input`; no receipt is frozen and no C7 action occurs |

The candidate and review receipts are the same C7 receipt contracts used by the
nine-tool external façade. Their hashes, execution identities, and generation
are copied into the RunStore binding only after C7 verifies them. A repeated
`finish` with the same receipt binding returns the previous terminal result;
different receipt bytes for the same phase are `invalid_state`.

Fields that are not known at a transition are omitted only where the state
machine marks them optional; they are never filled with placeholders. The
record is canonical JSON with sorted object keys and arrays in semantic order.
The idempotency key for page staging is
`runId + generation + jobId + candidateRootHash + pageContentHash +
claimDecisionHash`. A duplicate key returns the prior accepted result; a
different payload for the same job is `invalid_state`.

The candidate write package is explicit and local:

```text
candidate = {
  rootPath: <runtimeRoot>/transactions/<transactionId>/generations/<generation>/candidate,
  pagePath: <normalized assigned repository-relative Markdown path>,
  permissions: ["read", "list", "write"]
}
```

`rootPath` is created by `C7Transaction` before `next_page` returns, is a
canonical non-link descendant of `runtimeRoot`, and is never `wikiRoot` or a
descendant of it. The host Writer writes only `rootPath/pagePath`; the adapter
rejects any changed candidate path other than the assigned `pagePath`. The
package is returned in the `page_pending` result, while `submit_page` accepts
no page bytes and reads exactly that path from the persisted C7 work package.
The write package is the controlled bridge needed by the local host and is not
a formal Wiki permission.

`validateAssignedPage` is a two-phase bridge. `C7Transaction` is the sole owner
of the candidate marker; `PersonalRunStore` is the sole owner of the PageJob
acceptance:

```text
CandidatePageMarker = {
  type: "selfopenwiki:candidate-page-marker-v1", version: 1,
  transactionId, runId, generation, jobId,
  candidateRootHash, pagePath, pagePathHash, pageContentHash,
  claimDecisionHash, candidateBindingHash, writerExecutionId,
  state: "candidate_written" | "accepted",
  createdAt, updatedAt
}
```

All marker fields are required, `pagePath` is the normalized assigned Markdown
path, timestamps are UTC RFC 3339 strings, and the object has no unknown keys.
The marker is written to
`<candidateRoot>/.selfopenwiki/page-markers/<jobId>.json`, using a temporary
file, write-through flush, and atomic replace. Under the operation/wiki lock:

1. Validate the RunStore job and C7 candidate binding and read the assigned file
   only under the candidate root.
2. Atomically stage the candidate file, then write a `candidate_written` marker
   containing the complete binding and observed hashes.
3. Atomically append the matching PageJob acceptance to `PersonalRunStore`.
4. Atomically replace the marker state with `accepted`, then return
   `page_accepted`.

Crash recovery uses this fixed table:

| Marker | RunStore acceptance | Recovery |
| --- | --- | --- |
| absent | absent | Retry the job; no acceptance is implied. |
| `candidate_written` and matching hashes | absent | Verify the binding, append exactly one idempotent acceptance, then mark `accepted`. |
| `candidate_written` and matching hashes | present | Verify the same idempotency key, atomically mark `accepted`, and acknowledge the prior acceptance. |
| `accepted` and matching hashes | present | Acknowledge the prior acceptance. |
| `accepted` and matching hashes | absent | Enter `restore_required`; re-verify the candidate and never publish from the marker alone. |
| any marker with mismatched hashes | either | Enter `restore_required`; never publish. |
| absent | present | Enter `restore_required`; never publish. |

The marker is deleted or retained only by the C7 recovery owner after a
terminal transaction decision. A RunStore acceptance without its matching
candidate marker enters `restore_required`; it is never promoted to the formal
Wiki. The only formal-tree interface is the one-way
`C7Transaction.publishReviewedCandidate(...) -> WikiPublisher.publish(...)`
call. `WikiPublisher` performs the final rename/CAS operation and returns the
before/after hashes; `C7Transaction` owns the publication decision and
recovery journal.

### 5.7 Complete adapted schema and MCP envelope

All six tool schemas share these bounds:

- `runId` and `jobId` are UUID strings;
- `wikiRoot` is a canonical absolute non-link directory and must resolve to an
  independent Git top-level;
- hashes are lower-case `sha256:` plus 64 hexadecimal characters;
- page paths are normalized, forward-slash, repository-relative Markdown paths
  with no traversal, aliases, or generated-index assignment;
- `pages` and `deletePages` are bounded arrays of at most 2,048 entries;
- title/purpose/instruction strings are bounded to 512/4,096/8,192 UTF-8
  bytes; `relatedPages` is at most 64 per page;
- Claim statements are at most 4,096 bytes, each has 1–64 evidence resources,
  and a page has at most 256 Claim decisions;
- evidence resources are either `repo://` paths in a confirmed source
  snapshot or `wiki://` paths in the bound Wiki root; bare filesystem paths
  are rejected;
- unknown object keys, proxies, cycles, non-finite numbers, controls, and
  over-limit arrays/strings are rejected before dispatch.

The six request shapes are:

| Tool | Strict request shape |
| --- | --- |
| `openwiki_begin` | `{ wikiRoot, mode, language?, force?, sourceManifestId?, sourceConfirmation?, skills? }` where `mode` is `init\|update`, `skills` is an ordered unique id array, and source fields must appear together. |
| `openwiki_submit_plan` | `{ runId, pages, deletePages? }`; at least one page or deletion is required. An update with no work is represented by the `begin` no-op result; init still requires the quickstart assignment. |
| `openwiki_next_page` | `{ runId }`. The `page_pending` result includes a persisted candidate write package with `rootPath`, assigned `pagePath`, and `permissions: ["read", "list", "write"]`. |
| `openwiki_inspect_page_claims` | `{ runId, jobId }`. |
| `openwiki_submit_page` | `{ runId, jobId, confirmedClaimIds?, claims?, retractedClaimIds? }`; exactly the assigned candidate file is read from the C7 work package. |
| `openwiki_finish` | `{ runId, candidateReceipt?, reviewReceipt? }`; supplied receipts are untrusted input and are accepted only after C7 validation. The semantic form is exactly neither receipt, candidate-only, or review-only; both receipts are rejected with `invalid_input`. |

Before allocating a new C7 candidate, a plan that adds pages must have a writable
page reachable from `quickstart.md` in the planned path set, excluding deletions.
This can be quickstart itself, a reachable topic index, or a new page filling an
existing link. An impossible scope is rejected with `invalid_input` and the
unaccepted queue is rolled back, so the same run can submit a corrected plan.
Existing transactions retain their frozen scope. This feasibility check does not
replace final validation of actual links and navigation, Claims, Review, or CAS.

The success result shapes are discriminated by `status` and always include
`protocol`, `runId` where a run exists, and the binding hashes relevant to the
state. `begin` includes `wikiRoot`, `runtimeRoot`, `wikiRevision`,
`skillAggregateHash`, and `upstreamCommit`; `submit_plan` includes `planHash`,
`queueHash`, `pageCount`; `next_page` includes `jobId` and assignment or
`status: queue_complete` with `nextAction: finish`; `inspect_page_claims` includes `claimsHash` and complete
Claim records; `submit_page` includes `candidateBindingHash` and remaining
queue count; `finish` includes final Wiki revision and C7 receipt hashes only
when `status: complete`.

The success statuses are bounded to `noop`, `planning`, `resuming`,
`plan_accepted`, `page_pending`, `claims_inspected`, `page_accepted`,
`queue_complete`, `review_required`, `publish_pending`, `repair_ready`, `needs_clarification`,
and terminal `complete`. `review_required`
and `publish_pending` are success-shaped resumable states, not terminal
success.

The MCP transport contract is:

- validated success: `isError` omitted, JSON in `content`, and the exact
  validated success object in `structuredContent`;
- validated business/recovery failure: `isError: true`, one bounded JSON error
  envelope in `content`, and no `structuredContent`;
- transport/schema failure: `isError: true`, a bounded `invalid_input` or
  `internal_error` JSON error envelope in `content`, and no
  `structuredContent`.

Every failure envelope is exactly `{ ok: false, error: { code, message,
retryable, details? }, recovery: { action, message? } }`. `review_required` and
`publish_pending` are statuses, never error codes. This applies to both the
adapted six tools and the legacy nine-tool handlers; a legacy compatibility
result may add legacy fields but cannot return an invalid structured object.

The following schema fragments are normative; all objects use
`additionalProperties: false`, and all omitted fields are explicitly optional.

```text
Hash        = string /^sha256:[a-f0-9]{64}$/
RunId       = string UUID
JobId       = string UUID
PagePath    = normalized relative Markdown path, 1..1024 bytes
WikiRoot    = canonical absolute non-link directory whose Git top-level is itself
CandidateWritePackage = { rootPath: canonical absolute non-link directory,
                          pagePath: PagePath,
                          permissions: ["read", "list", "write"] }
Claim       = { id?: string, statement: string(1..4096),
                evidence: [{ resource: string(1..1024) }](1..64) }
PagePlan    = { path: PagePath, title: string(1..512),
                purpose: string(1..4096), seedPaths?: string[](0..128),
                relatedPages?: PagePath[](0..64),
                instructions?: string[](0..64) }
Binding     = { runId: RunId, generation: integer(1..3),
                transactionId: bounded-id, candidateBindingHash: Hash,
                candidateRootHash: Hash, queueHash: Hash, planHash: Hash,
                wikiRevision: Hash }
```

The candidate write package is also a path-boundary assertion: its root must
be a regular directory under the selected `<wikiRoot>.selfopenwiki` runtime
root, with no link or junction ancestor. The adapter canonicalizes and checks
that boundary before exposing the package; a malformed or external candidate
is rejected and, when an upstream transaction identity is still valid, an
abort is attempted through the existing C7 recovery owner.

The required request properties are exactly:

```text
begin       = { wikiRoot, mode, language?, force?, sourceManifestId?,
                sourceConfirmation?, skills? }
submitPlan  = { runId, pages: PagePlan[](0..2048), deletePages?: PagePath[](0..2048) }
nextPage    = { runId }
inspect     = { runId, jobId }
submitPage  = { runId, jobId, confirmedClaimIds?: string[](0..256),
                claims?: Claim[](0..256), retractedClaimIds?: string[](0..256) }
finish      = { runId, candidateReceipt?: CandidateReceipt,
                reviewReceipt?: ReviewReceipt }
```

The required success properties are exactly:

```text
begin planning/resuming = { ok: true, protocol, status, runId, wikiRoot,
                             runtimeRoot, wikiRevision, skillAggregateHash,
                             upstreamCommit, binding }
begin noop              = { ok: true, protocol, status: noop, wikiRoot,
                             runtimeRoot, wikiRevision, skillAggregateHash,
                             upstreamCommit }
submitPlan              = { ok: true, protocol, status: plan_accepted, runId,
                             planHash, queueHash, pageCount, binding }
nextPage pending        = { ok: true, protocol, status: page_pending, runId,
                             jobId, path, title, purpose, seedPaths,
                             relatedPages, issueClaims, candidate, binding }
nextPage queue complete = { ok: true, protocol, status: queue_complete, runId,
                             remainingPages: 0, nextAction: finish, binding }
inspect                 = { ok: true, protocol, status: claims_inspected,
                             runId, jobId, claims, claimsHash, binding }
submitPage              = { ok: true, protocol, status: page_accepted, runId,
                             jobId, remainingPages, candidateBindingHash,
                             pageContentHash, claimDecisionHash, binding }
finish review           = { ok: true, protocol, status: review_required,
                             nextAction: "submit_candidate_receipt"|
                                         "submit_review_receipt",
                             runId, transactionId, generation, binding,
                             reviewPackageHash?, reviewPackage? }
finish publish          = { ok: true, protocol, status: publish_pending,
                             runId, transactionId, generation, binding }
finish repair           = { ok: true, protocol, status: repair_ready,
                             nextAction: "resume", runId, transactionId,
                             generation, binding, issues }
finish clarify          = { ok: true, protocol, status: needs_clarification,
                             nextAction: "clarify|abort", runId,
                             transactionId, generation, binding, issues,
                             questions }
finish complete         = { ok: true, protocol, status: complete, runId,
                             published: true, wikiRevision, beforeWikiHash,
                             afterWikiHash, reviewReceiptHash, runReceiptHash,
                             binding }
```

`queue_complete` and `claims_inspected` are non-terminal statuses. `issueClaims`,
`claims`, and every hash field have the bounds above and are produced by the
runtime. Personal `claims` and `issueClaims` are loaded from and checked
against the Wiki sidecar/page revision; client claims are decisions only, never
authoritative input. A `review_required`
result carries the C7 transaction reference needed by the existing external
review/finalize façade; it does not claim that review has passed.

## 6. Personal Wiki flow

```text
explicit wikiRoot
      |
      v
begin -> source/Skill/revision validation -> plan or noop
      |
      v
submit_plan -> next_page -> research and assigned-candidate-page write
                           |
                           v
                inspect Claims when required
                            |
                            v
                      submit_page
                            |
                            v
               isolated C7 candidate + sparse Claims + RunStore page state
                            |
                            v
                     next_page -> queue_complete
                            |
                            v
        finish(no receipt) -> review_required
                            |
          C7 independent review/finalize receipt accepted
                            |
             finish(reviewReceipt) -> complete
                           |
                           v
          formal Wiki working tree changed; Git still user-owned
```

The six-stage lifecycle is therefore a coordination interface backed by one
personal RunStore. The actual personal Wiki publication remains owned by
`C7Transaction`/`WikiPublisher` so that the new PageJob flow does not weaken
the existing safety boundary. The nine-tool external begin/finalize façade and
the adapted six-tool flow address the same C7 transaction; they cannot create
parallel candidates for one `wikiRoot`.

## 7. Storage and Git boundaries

The selected path is the Wiki root itself and, for the v2 six-stage flow, must
already be an independent Git repository:

```text
<wiki-root>\
├─ .git\                       required user-owned Git metadata for v2
├─ Markdown knowledge tree\
└─ user-owned files allowed by the Wiki contract

<wiki-root>.selfopenwiki\      SelfOpenWiki runtime sibling
```

The installer and MCP accept the canonical absolute `wikiRoot` and verify that
`git -C <wikiRoot> rev-parse --show-toplevel` resolves to that exact path.
They do not infer it from the repository containing SelfOpenWiki, the current
directory, or the OpenWiki Submodule. Runtime state, run metadata, snapshots,
recovery records, and receipts remain outside the formal Wiki tree.

SelfOpenWiki may perform a bounded write to the Wiki working tree only after
the normal user confirmation and transaction gates. The personal Git repo's
commit, push, branch, remote, and identity remain outside the automatic
`finish` operation. The adapter reports the exact changed paths and revision
state so an outer workflow can commit or review them.

During a six-stage MCP run, the personal Git boundary is read-only: validation
may inspect the top-level, status, HEAD, index, refs, config, hooks, remotes,
and reflog, but SelfOpenWiki never calls `add`, `commit`, `reset`, `checkout`,
`merge`, `rebase`, `push`, `fetch`, config mutation, hook installation, or
ref/reflog mutation on the personal Wiki repository. Before and after a run,
the test harness snapshots the worktree, index, HEAD, refs, config, hooks,
remote definitions, reflog, and user-owned uncommitted blobs. A successful
Wiki publication may change only formal Markdown files and runtime-owned
artifacts outside the Git metadata; any other change is a failure.

The same protection applies to the parent repository during an upstream
iteration. The currently observed `M upstream/openwiki` is treated as an
existing user change. The coordinator must not reset, checkout, or overwrite
that gitlink. If a clean parent state is required for a candidate, it creates
an isolated validation copy; mutating the current parent gitlink requires a
separate explicit user action after the candidate passes review.

## 8. Skill and capability adaptation contract

The existing personal Skill is revised in the SelfOpenWiki-owned Skill area;
the official upstream Skill is copied or referenced only as a versioned input,
never edited in place.

The personal Skill manifest must bind:

- Skill id and semantic version;
- exact UTF-8 package hash;
- compatible upstream OpenWiki commit/tag;
- supported adapted six-stage protocol version;
- C7 transaction version;
- allowed page/Claim/frontmatter extensions;
- source and Wiki-root boundaries;
- writer/reviewer/publish rules;
- migration requirements and fail-closed conditions.

The checked-in binding file is
`self-openwiki/config/personal-openwiki-compatibility.json`. Its v2 schema is
canonical JSON with sorted object keys and binds:

```json
{
  "schemaVersion": 2,
  "upstream": {
    "url": "https://github.com/langchain-ai/openwiki.git",
    "commit": "<40-hex-commit>",
    "packageVersion": "<semver>"
  },
  "protocol": {
    "official": "openwiki-repository-v0.5",
    "adapted": "selfopenwiki:personal-openwiki-v1"
  },
  "skill": {
    "id": "self-openwiki",
    "path": "self-openwiki/agent-skills/self-openwiki",
    "packageHash": "sha256:<64-lower-hex>",
    "composition": ["kg-c7-project-wiki", "self-openwiki"]
  },
  "c7": {
    "transactionVersion": "external-update-v1",
    "publisherVersion": "wiki-publisher-v1"
  },
  "build": {
    "parentCommit": "<40-hex-commit>",
    "parentSourceManifestHash": "sha256:<64-lower-hex>",
    "adapterSetHash": "sha256:<64-lower-hex>",
    "generatedMarkerHash": "sha256:<64-lower-hex>",
    "lockfileHash": "sha256:<64-lower-hex>"
  },
  "capabilities": [
    { "id": "openwiki.personal.lifecycle.six-stage", "version": 1, "owner": "PersonalRunStore", "predicate": "six-adapted-handlers", "evidenceKinds": ["contract", "stdio", "lifecycle"] },
    { "id": "openwiki.personal.claims.page-jobs", "version": 1, "owner": "PersonalRunStore", "predicate": "deterministic-claims-pagejobs", "evidenceKinds": ["claim-vectors", "restart", "provenance"] },
    { "id": "openwiki.personal.c7-review-publish", "version": 1, "owner": "C7Transaction", "predicate": "hash-bound-cas-publish", "evidenceKinds": ["receipt", "recovery", "publish"] },
    { "id": "openwiki.personal.wiki-root.external-git", "version": 1, "owner": "WikiRootResolver", "predicate": "independent-git-top-level", "evidenceKinds": ["path", "git-boundary", "smoke"] }
  ],
  "toolBindings": {
    "openwiki_begin": { "inputHash": "sha256:<64-lower-hex>", "outputHash": "sha256:<64-lower-hex>", "annotationHash": "sha256:<64-lower-hex>", "descriptionHash": "sha256:<64-lower-hex>", "implementation": "mcp-server/src/official-lifecycle-adapter.ts#begin" },
    "openwiki_submit_plan": { "inputHash": "sha256:<64-lower-hex>", "outputHash": "sha256:<64-lower-hex>", "annotationHash": "sha256:<64-lower-hex>", "descriptionHash": "sha256:<64-lower-hex>", "implementation": "mcp-server/src/official-lifecycle-adapter.ts#submitPlan" },
    "openwiki_next_page": { "inputHash": "sha256:<64-lower-hex>", "outputHash": "sha256:<64-lower-hex>", "annotationHash": "sha256:<64-lower-hex>", "descriptionHash": "sha256:<64-lower-hex>", "implementation": "mcp-server/src/official-lifecycle-adapter.ts#nextPage" },
    "openwiki_inspect_page_claims": { "inputHash": "sha256:<64-lower-hex>", "outputHash": "sha256:<64-lower-hex>", "annotationHash": "sha256:<64-lower-hex>", "descriptionHash": "sha256:<64-lower-hex>", "implementation": "mcp-server/src/official-lifecycle-adapter.ts#inspectPageClaims" },
    "openwiki_submit_page": { "inputHash": "sha256:<64-lower-hex>", "outputHash": "sha256:<64-lower-hex>", "annotationHash": "sha256:<64-lower-hex>", "descriptionHash": "sha256:<64-lower-hex>", "implementation": "mcp-server/src/official-lifecycle-adapter.ts#submitPage" },
    "openwiki_finish": { "inputHash": "sha256:<64-lower-hex>", "outputHash": "sha256:<64-lower-hex>", "annotationHash": "sha256:<64-lower-hex>", "descriptionHash": "sha256:<64-lower-hex>", "implementation": "mcp-server/src/official-lifecycle-adapter.ts#finish" }
  },
  "discoveryOrder": [
    "openwiki_status", "openwiki_begin", "openwiki_submit_plan",
    "openwiki_next_page", "openwiki_inspect_page_claims",
    "openwiki_submit_page", "openwiki_finish", "openwiki_setup",
    "openwiki_prepare_sources", "openwiki_list_skills", "openwiki_query",
    "openwiki_update", "openwiki_begin_external_update",
    "openwiki_finalize_external_update", "openwiki_set_default_model"
  ]
}
```

The real file includes all six tool bindings and adapter source hashes. Its
canonical document hash is `sha256:` plus SHA-256 over the exact UTF-8
canonical bytes. Skill package hashes use the existing
`kg-c7-skill-package-v1` algorithm from `mcp-server/src/skills.ts`. Capability
verification recomputes the upstream commit, adapter source set, protocol
hashes, Skill package hash, capability ids, and generated build marker. Any
mismatch invalidates the six-stage capability set and blocks all six-stage
write calls; legacy status may still report a separate legacy capability
state.

Each capability record is normalized as
`{ id, version, owner, predicate, evidenceKinds }`. The predicates and their
minimum evidence are fixed:

| Capability id | Predicate | Required evidence |
| --- | --- | --- |
| `openwiki.personal.lifecycle.six-stage` | All six adapted handlers exist, have the bound schemas, and reach the declared state machine | six contract tests, built MCP discovery, lifecycle smoke |
| `openwiki.personal.claims.page-jobs` | PageJob, Claim, queue, and provenance bindings are deterministic and replay-safe | Claim vectors, queue/restart tests, provenance receipt |
| `openwiki.personal.c7-review-publish` | Candidate/review receipts are distinct, hash-bound, and publish only through C7 CAS | receipt tests, review/publish failure tests, C7 recovery evidence |
| `openwiki.personal.wiki-root.external-git` | The explicit Wiki root is an independent Git top-level and Git metadata is preserved | canonical path tests, Git metadata before/after snapshot, external-root smoke |

`parentCommit` records the parent commit used when producing the compatibility
manifest; it is provenance, not an equality gate against the current host HEAD.
`parentSourceManifestHash` now binds the SelfOpenWiki module's allowed worktree
content, independent of the parent HEAD and index. Git staging or a commit with
the same effective module files does not invalidate it; changed module bytes do.
The original three-layer Git manifest remains an audit artifact, not a runtime
capability gate. `generatedMarkerHash` binds the exact materializer
marker, and `lockfileHash` binds the package lock used for the build. A
capability is verified only when every listed predicate and evidence kind is
fresh for the same tuple.

The complete `toolBindings` set is fixed to the following six entries:

| Tool | Binding fields |
| --- | --- |
| `openwiki_begin` | `inputHash`, `outputHash`, `annotationHash`, `descriptionHash`, `implementation` |
| `openwiki_submit_plan` | `inputHash`, `outputHash`, `annotationHash`, `descriptionHash`, `implementation` |
| `openwiki_next_page` | `inputHash`, `outputHash`, `annotationHash`, `descriptionHash`, `implementation` |
| `openwiki_inspect_page_claims` | `inputHash`, `outputHash`, `annotationHash`, `descriptionHash`, `implementation` |
| `openwiki_submit_page` | `inputHash`, `outputHash`, `annotationHash`, `descriptionHash`, `implementation` |
| `openwiki_finish` | `inputHash`, `outputHash`, `annotationHash`, `descriptionHash`, `implementation` |

The v2 adapter source set is an explicit sorted list, not a directory glob:

```text
self-openwiki/mcp-server/src/contracts.ts
self-openwiki/mcp-server/src/external-update-state.ts
self-openwiki/mcp-server/src/external-update-transaction.ts
self-openwiki/mcp-server/src/official-lifecycle-adapter.ts
self-openwiki/mcp-server/src/personal-candidate-marker.ts
self-openwiki/mcp-server/src/personal-claims.ts
self-openwiki/mcp-server/src/personal-run-store.ts
self-openwiki/mcp-server/src/personal-skill-adapter.ts
self-openwiki/mcp-server/src/personal-wiki-lifecycle.ts
self-openwiki/mcp-server/src/personal-wiki-root.ts
self-openwiki/mcp-server/src/publish.ts
self-openwiki/mcp-server/src/recovery.ts
self-openwiki/mcp-server/src/runtime.ts
self-openwiki/mcp-server/src/server.ts
self-openwiki/mcp-server/src/transaction.ts
self-openwiki/mcp-server/src/transaction-recovery.ts
```

The implementation may split a file only by revising this binding list and
re-running Review. The C7 owner files are deliberately included even when a
task changes only the adapter, so `C7Transaction`, `WikiPublisher`, and their
recovery implementation cannot drift under old capability evidence. A file
hash is SHA-256 over its exact bytes. A schema,
annotation, and description hash is SHA-256 over its canonical UTF-8 JSON
value. The adapter-set hash is SHA-256 over
`selfopenwiki-adapter-set-v1\0`, followed by, for each path in that exact
UTF-8-byte lexicographic order, a big-endian `uint32` path-byte length, the
UTF-8 path bytes, the 32 raw bytes of the lowercase SHA-256 file hash, and a
big-endian `uint64` file-byte length. The compatibility-manifest hash is
SHA-256 over `selfopenwiki-personal-compatibility-v2\0` followed by the
canonical UTF-8 JSON of the manifest with only the top-level `manifestHash`
field omitted; every other field, including independently recomputed hash
fields, is an input. Arrays whose order has semantic meaning retain that order;
all object keys are sorted recursively.

The worktree content binding uses the same allowed module paths, omits the two
derived manifests below, and hashes current file bytes, modes, and nested
gitlink source bytes. The domain is `selfopenwiki-module-content-v1\0` followed
by canonical JSON of `{ "version": 1, "scope": "selfopenwiki-module-content", "records": [...] }`.
The records are sorted by UTF-8 path bytes and omit Git layer, index stage, and
worktree dirty flags. This is the runtime value stored in
`parentSourceManifestHash` for schema compatibility.

The retained three-layer Git audit manifest has its own exact canonical record contract. The
allowed path set is the union of `.gitmodules`, `AGENTS.md`, `README.md`,
`docs/`, `patches/openwiki/`, `scripts/`, `self-openwiki/`, and the
`upstream/openwiki` gitlink itself; `.git/`, runtime siblings, and Submodule
contents below the gitlink are excluded. The generated
`self-openwiki/config/bootstrap-source-manifest.json` and
`self-openwiki/config/personal-openwiki-compatibility.json` are excluded from
this source observation to avoid a self-referential hash cycle. For every path
in the union of HEAD, index, and worktree observations, emit records sorted by UTF-8 path bytes,
then layer order `head`, `index`, `worktree`, then index stage `0..3`. `stage`
is always `0` for `head` and `worktree`; a normal index entry uses stage `0`,
while an index conflict emits only its present stages `1`, `2`, and/or `3`
(there is no synthetic stage-0 absent record for a conflict). `worktreeDirty`
is always `false` on `head` and `index` records and on non-gitlink `worktree`
records; only a `worktree` gitlink record may set it to `true` after inspecting
nested Submodule status:

```text
ParentSourceRecord = {
  path: normalized repository-relative path,
  layer: "head" | "index" | "worktree",
  stage: 0 | 1 | 2 | 3,
  kind: "absent" | "blob" | "gitlink",
  mode: "100644" | "100755" | "160000" | null,
  byteLength: uint64,
  byteHash: Hash | null,
  gitlinkCommit: Commit | null,
  worktreeDirty: boolean
}
```

`head` and `index` use Git tree/index bytes and modes; an index conflict emits
all present stages. `worktree` uses the current regular-file bytes and the
Git-normalized mode. For every layer/path that is in the union but missing in
that layer, emit an `absent` record with stage `0`, mode `null`, length `0`,
null hashes, and `worktreeDirty: false`.
Blob records use SHA-256 of their exact bytes. Gitlink records use the exact
40-hex target commit in `gitlinkCommit`, length `0`, mode `160000`, and the
worktree record also carries the nested Submodule dirty bit. Symlinks,
junctions, unsupported modes, duplicate paths, and unlisted paths are a
`source_manifest_invalid` failure, not an alternate encoding. An empty record
set is valid and hashes as the canonical JSON object
`{"version":1,"records":[]}`.

The manifest hash is SHA-256 of
`selfopenwiki-parent-source-manifest-v1\0` followed by the canonical UTF-8 JSON
of `{ "version": 1, "records": [...] }`; every record field above is present,
nulls are retained, object keys are recursively sorted, and the record array
uses the stated semantic order. The normative fixture vectors below use the
exact compact sorted-key JSON shown after each name; the expected digest is
SHA-256 of the domain plus that JSON:

```text
empty
  {"records":[],"version":1}
  7e991f4d5d5045988a783bb6a2b3760bdc7efb7aa2f2a8c847c00597c9354edc

modified-worktree
  {"records":[{"byteHash":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","byteLength":3,"gitlinkCommit":null,"kind":"blob","layer":"worktree","mode":"100644","path":"docs/x.md","stage":0,"worktreeDirty":false}],"version":1}
  b17a28de4e817e24c1b287c6cfed169f32145980c46296dec830f40ea2a0439e

deleted-index-conflict
  {"records":[{"byteHash":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","byteLength":3,"gitlinkCommit":null,"kind":"blob","layer":"head","mode":"100644","path":"docs/x.md","stage":0,"worktreeDirty":false},{"byteHash":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","byteLength":3,"gitlinkCommit":null,"kind":"blob","layer":"index","mode":"100644","path":"docs/x.md","stage":1,"worktreeDirty":false},{"byteHash":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","byteLength":4,"gitlinkCommit":null,"kind":"blob","layer":"index","mode":"100644","path":"docs/x.md","stage":2,"worktreeDirty":false},{"byteHash":"sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","byteLength":5,"gitlinkCommit":null,"kind":"blob","layer":"index","mode":"100644","path":"docs/x.md","stage":3,"worktreeDirty":false},{"byteHash":null,"byteLength":0,"gitlinkCommit":null,"kind":"absent","layer":"worktree","mode":null,"path":"docs/x.md","stage":0,"worktreeDirty":false}],"version":1}
  83ba7acc91cb239f699bdbe1e7097598a3fc40d79856cf7aee20b2b6740fd57e

dirty-gitlink
  {"records":[{"byteHash":null,"byteLength":0,"gitlinkCommit":"1111111111111111111111111111111111111111","kind":"gitlink","layer":"head","mode":"160000","path":"upstream/openwiki","stage":0,"worktreeDirty":false},{"byteHash":null,"byteLength":0,"gitlinkCommit":"1111111111111111111111111111111111111111","kind":"gitlink","layer":"index","mode":"160000","path":"upstream/openwiki","stage":0,"worktreeDirty":false},{"byteHash":null,"byteLength":0,"gitlinkCommit":"2222222222222222222222222222222222222222","kind":"gitlink","layer":"worktree","mode":"160000","path":"upstream/openwiki","stage":0,"worktreeDirty":true}],"version":1}
  8736fa328e5633bec44e1467c9d7b3255431424c55795b43110c1526615d8056
```

The full deleted/conflict and dirty-gitlink records are generated from the
`ParentSourceRecord` schema above, not abbreviated in the implementation; the
fixture test asserts the compact JSON and digest exactly. The
`generatedMarkerHash` is SHA-256 of the exact generated marker bytes and the
`lockfileHash` is SHA-256 of the exact package-lock bytes. These three hashes
are computed before the compatibility-manifest hash, so no hash cycle is
possible.

Drift invalidation is explicit:

| Drift | Active six-stage run | Six-stage capability | Legacy capability |
| --- | --- | --- | --- |
| upstream commit/package or generated build | Mark `drifted`, retain candidate, block writes and resume until explicit recovery/new run | Unverified | Unverified if the legacy implementation binds that upstream build; otherwise unchanged |
| adapter source or six-tool schema/annotation | Mark `drifted`, retain candidate, reject old receipts | Unverified | Unchanged unless a shared file is bound |
| personal Skill package or Skill manifest | Mark `drifted`, retain candidate, reject old Skill-bound receipts | Unverified | Legacy remains explicit only if it does not bind that Skill |
| source manifest or Wiki revision | Mark `drifted`, retain candidate, require new source/user confirmation | Unverified for the run; installation capability remains | Unchanged |
| capability manifest itself | Reject evidence and old receipts; no writes | Unverified | Unverified for capabilities derived from it |

No drift path silently takes over a live run. A candidate is retained until
explicit C7 restore/abort or a user-confirmed migration resolves it.

The Skill must instruct the host to:

1. validate `wikiRoot` and current status;
2. prepare and confirm local source manifests;
3. use the six-stage lifecycle for personal deposition;
4. preserve current issue-free Claims and inspect only intentional changes;
5. write assigned pages only to the isolated candidate;
6. run the existing independent Writer/Reviewer/CAS flow;
7. call `finish` only after publication and recovery are closed;
8. keep commit/push as explicit outer Git actions.

Skill text can change policy and orchestration, but executable behavior changes
belong in the parent MCP adapter. This distinction prevents a prompt-only
change from being mistaken for a tested protocol patch.

## 9. Upgrade iteration contract

An upstream iteration is one bounded change set:

1. Accept an explicit upstream tag or resolve it immediately to a 40-character
   commit; persist only the resolved commit and never silently follow `main`.
2. Verify the URL, commit, clean Submodule worktree, and parent gitlink.
3. Build the official Submodule unchanged and inspect its six-tool protocol,
   Claims, PageJobs, persistence, integration Skill, CLI modes, and tests.
4. Update the SelfOpenWiki adapter contract and compatibility matrix. The
   active v2 materialization manifest has `patches: []`; the official build is
   always produced from clean upstream source.
5. Update the personal Skill rules, package hash, protocol mapping, and
   migration notes.
6. Update schemas, capability evidence, tests, and documentation.
7. Build a disposable generated/runtime candidate without writing the
   Submodule or the selected personal Wiki.
8. Run conformance, C7 regression, installer, recovery, and real stdio smoke
   tests.
9. Stop fail-closed on any source drift, unsupported schema, missing Skill
   hash, failed test, invalid status, or incomplete recovery.

The v2 target explicitly uses zero upstream patches. The old broad patch and
its v1 manifest remain historical migration inputs only; they are not applied
by the v2 materializer. If an upstream capability is not available through a
stable built protocol/export, the adapter reports `upstream_incompatible` and
the update stops. It may not reintroduce an unreviewed internal patch as a
fallback.

The active patch descriptor is
`selfopenwiki:openwiki-patch-manifest:v2`:

```json
{
  "schemaVersion": 2,
  "domain": "selfopenwiki:openwiki-patch-manifest:v2",
  "upstream": {
    "url": "https://github.com/langchain-ai/openwiki.git",
    "commit": "<40-hex-commit>"
  },
  "patches": []
}
```

The v2 validator accepts only an empty `patches` array and the materializer
must not call `git apply` on this path. The existing v1 manifest is rejected by
domain/schema validation rather than loaded as a fallback. An explicit tag is
resolved before any gitlink or manifest write by requiring exactly one commit
from `refs/tags/<tag>` or its peeled `^{}` ref; only that 40-hex commit is
persisted.

## 10. Compatibility and migration

- Existing Wiki content is read without normalization during discovery.
- Existing C7 pages and receipts remain readable during the migration window.
- New pages use the v2 OKF/Claim contract when the page job requires it.
- A detected format, Claim, path, or metadata drift produces a candidate
  migration report; it never rewrites the personal Wiki automatically.
- A user-confirmed migration publishes through the same candidate, review, and
  explicit Git boundary as a normal Wiki update.
- Failed migration leaves the original Wiki tree and its `.git` metadata
  unchanged.

## 11. Intrusion budget and no-go boundaries

### Allowed

- New private adapter modules under `self-openwiki/mcp-server/src`.
- New or revised MCP schemas and server registration in the SelfOpenWiki
  package.
- Versioned personal Skill and references under SelfOpenWiki-owned Skill paths.
- Update/materialization/capability scripts, manifests, tests, and v2 docs.
- New runtime state under the derived `<wikiRoot>.selfopenwiki` sibling.

### Forbidden without a new decision and budget

- Editing tracked files inside `upstream/openwiki`.
- Making the official Submodule follow a floating branch.
- Replacing C7 publication with direct `submit_page` writes.
- Putting runtime state or credentials into the personal Wiki root.
- Automatically committing or pushing the personal Wiki.
- Changing persistent Wiki formats globally without migration evidence.
- Re-enabling the old broad `patches/openwiki` path for personal behavior.
- Expanding the provider/OAuth path into the default provider-free workflow.

The narrow alternative to a broad upstream patch is the parent adapter plus
versioned Skill manifest. That is the selected design because it localizes
SelfOpenWiki behavior, leaves the upstream source upgradeable, and gives tests
a stable seam.

## 12. Acceptance criteria

AC-01. The parent repository pins an explicit upstream commit/tag, the active
v2 materialization manifest has zero patches, and the Submodule remains clean
and byte-identical to that commit after build.

AC-02. The adapted six tools satisfy the field-level
`selfopenwiki:personal-openwiki-v1` contract and can initialize, plan,
schedule, inspect Claims, submit candidate pages, resume, repair, and finish a
personal Wiki run.

AC-03. Existing nine C7 tools remain discoverable and their existing external
transaction contracts continue to pass regression tests.

AC-04. `submit_page` cannot publish directly; the RunStore and C7 transaction
bind the same run/generation/job/candidate/Claim hashes; `finish` cannot
complete before Writer, Reviewer, CAS publication, and recovery closure.

AC-05. An explicit independent external Git Wiki root is canonicalized, kept
separate from SelfOpenWiki and runtime state, and never inferred or silently
replaced.

AC-06. Claims, OKF metadata, source manifests, revisions, provenance, recovery,
and failure states are hash-bound and fail closed on drift.

AC-07. `personal-openwiki-compatibility.json` binds the exact upstream commit,
adapter source set, all six input/output schema hashes, Skill package hash,
capability IDs, and adapted protocol version; Skill or adapter drift
invalidates six-stage capability evidence.

AC-08. A simulated upstream update resolves a tag to an exact commit and
updates the zero-patch Submodule binding, adapter, Skill, capability matrix,
tests, and docs as one reviewable change without editing Submodule contents or
personal Wiki data.

AC-09. Build, MCP protocol, personal lifecycle, migration, installer,
recovery, and real stdio smoke tests pass with fresh evidence.

AC-10. No implementation is accepted with open Critical/Important Review
findings or stale/unbound verification evidence.
