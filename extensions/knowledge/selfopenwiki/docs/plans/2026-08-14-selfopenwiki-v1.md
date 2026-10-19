# SelfOpenWiki v0.1 Implementation Plan

Status: final-contract candidate
Date: 2026-08-14
Design: `docs/specs/2026-08-14-selfopenwiki-v1-design.md`
Test design: `docs/testing/2026-08-14-selfopenwiki-v1-test-design.md`

This revision supersedes every earlier contract package, including
`cb19090e…ce4958a`, and all earlier Batch 1
implementation evidence. Prior test counts, including the reported 22/22
result, generated artifacts, markers, and Review conclusions are not release
evidence. No implementation may resume until this exact three-document package
passes independent whole-package Review and receives explicit user
confirmation.

## Objective

Create and publish the first clean SelfOpenWiki release, based on a pristine
official OpenWiki submodule and an independent migrated MCP/Skill package;
support a first-install selected external personal Wiki store; migrate the
envelope-bound private Wiki at the selected `<wiki-root>`; install and verify the
new local surface; publish both authorized repositories; retain the legacy
system until a final retirement confirmation.

## Frozen decisions

- Parent repository: `<repository-root>`, unborn `main`, existing empty public
  remote.
- Upstream: official `langchain-ai/openwiki` under `upstream/openwiki`, frozen at
  `355f4f68e71bd024631cdcff7aa871c3e72435da`, no in-place edits. Any gitlink
  change invalidates this package and requires new Review/user confirmation.
- Product name: SelfOpenWiki; MCP and Skill name `self-openwiki`; public tool
  names unchanged.
- Platform: Windows x64, Node 22 or newer, pinned pnpm/dependencies, committed
  stable .NET 9 `global.json` roll-forward policy; evidence binds exact Node,
  .NET SDK/runtime packs, actual helper handshake runtime, Corepack, pnpm, OS,
  and architecture values. The helper publish is self-contained `win-x64`.
- Bootstrap TCB: the public release tracks one reviewed self-contained helper
  executable plus strict bootstrap/source/toolchain manifests. This high-
  intrusion binary is necessary to close native bootstrap circularity and still
  requires new user confirmation after whole-package Review. This document-only
  revision does not generate it.
- Storage: one selected canonical Wiki root; the derived
  `<wiki-root>.selfopenwiki\` runtime sibling stays outside the Wiki tree.
- Personal migration bindings live only at
  `%LOCALAPPDATA%\SelfOpenWiki\migration-envelopes\<envelope-id>\envelope.json`
  under migration-owner current-user ACL and non-reparse identity. Public/private
  Git and storage/runtime trees never contain it. Public Git never records paths,
  remote, inventory, manifest, or legacy baseline identity.
- Git: normal MCP writes do not commit/push. This task is authorized to create
  and push one private migration commit and one public initial release commit,
  plus annotated `v0.1.0`.
- License: MIT, matching official OpenWiki.
- Retirement: no old-system deletion in the implementation batches.

## Approved write scope

### SelfOpenWiki repository

- root manifests/docs/launchers/license/ignore files;
- `.gitmodules` and the single `upstream/openwiki` gitlink;
- `patches/openwiki/**` and its manifest;
- `scripts/**` for materialization, setup, install, verification, migration,
  update helper, and tests;
- `self-openwiki/mcp-server/**`, `self-openwiki/win32-helper/**`,
  `self-openwiki/agent-skills/self-openwiki/**`, and
  `self-openwiki/config/**` migrated from the reviewed predecessor baseline;
- the upstream patch's private secure-filesystem client/protocol and its focused
  generated-checkout tests;
- the three contract documents and final evidence updates.

The tracked bootstrap write set is exactly:

- `self-openwiki/win32-helper/bootstrap/win-x64/SelfOpenWiki.Win32Helper.exe`;
- `self-openwiki/win32-helper/bootstrap/win-x64/bootstrap-manifest.json`;
- `self-openwiki/config/bootstrap-source-manifest.json`;
- `self-openwiki/config/toolchain-runtime-lock.json`.

For revised Batch 1, the exact implementation owners are
`self-openwiki/win32-helper/**`, `patches/openwiki/**`,
`scripts/build-win32-helper.mjs`, `scripts/materialize-openwiki.mjs`,
`scripts/update-upstream.mjs`, the root materializer/helper contract tests, and
focused tests materialized by the upstream patch. Helper, private client, patch,
build/materialization owners, tests, and evidence are one atomic rollback unit.
Batch 2 expressly excludes helper migration and owns only the remaining MCP,
Skill, configuration, and package rename.

The helper build owner may create only exclusive current-user ACL/non-reparse
attempts under
`%LOCALAPPDATA%\SelfOpenWiki\helper-artifacts\<attemptId>\`. This private cache
is outside both repositories and personal Wiki storage, is not Install state,
and no concrete local path enters public evidence.

### Bootstrap/artifact root matrix

- The tracked `bootstrapRoot` is the exact public repository child above;
  `helperArtifactRoot` is the exact LocalAppData owner root and contains only
  disjoint direct `<attemptId>` children.
- Repository/bootstrap/artifact attempts are bidirectionally non-overlapping
  with config, migration-envelope, release-journal, Wiki-root/runtime-sibling, legacy,
  installed Skill/Codex config, and backup roots except the documented parent/
  child relations.
- Every handoff binds canonical path, volume/file identity, non-reparse
  ancestors, and required ACL before and after acquisition. Pairwise equality,
  containment, case alias, identity replacement, or wrong ACL fails closed.

### Private Wiki repository

- `.gitignore` containing `.selfopenwiki/`;
- the exact envelope-bound migrated Markdown files at paths relative to the
  selected Wiki root.
- for `publish-wiki.mjs` only, the embedded `.git` index, objects, loose
  `refs/heads/main`, reflog, and reconciliation `FETCH_HEAD` required by its
  reviewed journal; config, hooks, alternates, packed refs, and other metadata
  remain read-only.

### Public repository Git metadata

- for Setup only, exact pinned-submodule config/gitdir/gitfile changes;
- for an existing Batch 0 checkout, Setup alone may create/normalize the exact
  frozen legitimate local submodule keys and records before/after allowlisted
  bytes; materializer only validates the resulting exact config;
- for `release.mjs` only, the embedded `.git` index, objects, loose `main` and
  `v0.1.0` refs/reflogs, and reconciliation `FETCH_HEAD` required by its reviewed
  journal;
- linked worktrees, gitfiles, `commondir`, alternates, hooks, filters, signing,
  editor/pager/prompt programs, force/reset, and unrelated metadata writes are
  prohibited.

### Local installation targets, after repository gates

- `%LOCALAPPDATA%\SelfOpenWiki\config.json` and bounded backups/receipts;
- `%LOCALAPPDATA%\SelfOpenWiki\release-journals\**` owned by `release.mjs`;
- `.agents\skills\self-openwiki` through the installer transaction;
- the `self-openwiki` Codex MCP block and its bounded backup;
- `<wiki-root>.selfopenwiki` runtime only.
- the repository-external LocalAppData private migration envelope and bounded
  backup, owned only by the migration owner; these paths are forbidden beneath
  both repositories, selected Wiki root, legacy/generated/install roots, and every
  staged set. Runtime WAL/receipt remains under
  `<wiki-root>.selfopenwiki\migration` and contains no envelope bytes;

## Prohibited scope

- no tracked edits inside `upstream/openwiki`;
- no runtime Wiki content in the public SelfOpenWiki repository;
- no public MCP schema or tool-name changes;
- no persistent Wiki, transaction, migration, publication, or receipt schema
  changes for the private secure-filesystem protocol;
- no provider/model/subAgent execution inside MCP external mode;
- no automatic knowledge Git commit/push outside the authorized migration;
- no multi-profile, Linux/macOS, hosted database, or team Wiki feature;
- no SelfWorkflow source/install modification during implementation;
- no modification/deletion of the legacy MCP block, Skill, or repository before
  the final retirement checkpoint;
- no force push, history rewrite, or remote creation.
- no unreviewed/bootstrap binary, PDB, concrete host path, private byte, or
  network package restore in the tracked bootstrap/reproducibility ceremony;
- after first native handshake, no direct Node spawn of Git, dotnet, Corepack,
  pnpm, Node, or tests.

Crossing these boundaries invalidates the contract and requires a new Review
and user confirmation.

## Source baseline and provenance

Migrate functionality from the exact clean tracked baseline bound in the local
private Review envelope. Historical planning documents may be retained as
provenance only when they explain a still-active public contract; they do not
define the new product. Generated runtime, credentials, capability evidence,
legacy Wiki data, build output, personal paths/remotes/fingerprints, and old
product install state are never copied into public Git.

The public implementation records only public provenance:

- imported component/path allowlist without the legacy checkout path or baseline
  identity;
- official submodule URL/commit/tree/license hashes;
- ordered patch bytes and path inventory;
- renamed MCP/Skill/helper source inventory;
- reviewed tracked bootstrap executable/manifest, bootstrap source-root, and
  toolchain/runtime-lock hashes plus byte-identical rebuild evidence; binaries
  and manifests contain no concrete host/private data;
- final build, contracts, matrix, Skill, test, verifier, dist, and helper
  fingerprints;
- synthetic migration test manifests and public release commit trees.

The legacy baseline identity, private source/target manifests, private remote,
and private Git commit tree are recorded only in the LocalAppData envelope and
storage runtime intent/receipt. They are forbidden from public docs, plan
evidence, commit/tag messages, and capability evidence.

## TDD sequence

Every behavior batch starts from a focused failing test, records the exact
failure, implements the minimum production change, reruns focused GREEN, then
runs its related regressions. Test-fixture or syntax errors do not count as RED.

### Batch 0 — Repository identity and source freeze

1. Recheck both remotes and current clean/unborn states.
2. Fetch official OpenWiki and verify the frozen commit
   `355f4f68e71bd024631cdcff7aa871c3e72435da`; any mismatch stops for a new
   contract rather than selecting a newer commit.
3. Add failing repository-contract tests for the missing submodule, manifest,
   package names, root layout, protected paths, and release-blocking README
   contract.
4. Add the submodule and root skeleton; make repository-contract tests GREEN.
5. Record source/target inventories without copying private data.

Expected write owners: root manifests, repository contract tests, gitlink.

### Batch 1A — Private Win32 secure-filesystem helper and protocol

1. RED repository/bootstrap contract: exact tracked executable/bootstrap
   manifest and bootstrap-source/toolchain locks are missing; wrong path set,
   schema/domain/order/hash, PDB/host/private strings, or derived-file recursion
   fails. Root-matrix tests cover tracked bootstrap and LocalAppData artifact
   attempts against repository/config/envelope/journal/storage/legacy/install.
2. Implement closed strict `bootstrap-source-manifest.json` and
   `toolchain-runtime-lock.json`. The former exhaustively hashes helper/project,
   private-client patch, build/materialization sources and inputs while excluding
   its own/derived bootstrap bytes; the latter hashes exact dotnet/SDK/Roslyn/
   reference/runtime packs. Both use the frozen domain-separated roots and no
   concrete host path.
3. RED and implement protocol v1/helper source/private client using transient
   development builds only as test fixtures. This pre-acceptance ceremony runs
   under the documented Windows-loader/toolchain/quiescent TCB; it must not claim
   a release-authenticated helper or pre-handshake zero-side-effect race closure.
4. RED bootstrap reproducibility: network restore, source/toolchain drift,
   non-self-contained output, extra payload/PDB, non-byte-identical second build,
   wrong protocol/source root, or dirty tracked bootstrap fails.
5. Generate the tracked candidate during implementation—not this documentation
   revision—at exact
   `self-openwiki/win32-helper/bootstrap/win-x64/SelfOpenWiki.Win32Helper.exe`
   with its only sibling `bootstrap-manifest.json`. Use pinned inputs,
   `-c Release -r win-x64 --self-contained true`, `PublishSingleFile=true`,
   deterministic/CI/PathMap, no debug symbols/PDB, and `--no-restore`. A fresh
   independent rebuild must be byte-identical.
6. Stop for independent complete-diff Review of binary, manifest, source/toolchain
   roots, reproducibility evidence, public privacy scan, and exact write set.
   During unborn development the reviewed contract package/diff authenticates
   bytes without requiring clean HEAD/index; published Setup later requires the
   exact reviewed release commit/tree and clean bootstrap paths.
7. RED tracked-bootstrap launch: wrong release tree/ACL/reparse/path/hash/image/
   protocol/toolchain, prelaunch/post-handshake replacement, stale process,
   crash, or timeout fails. Tests explicitly distinguish observable drift from
   the excluded arbitrary same-user pre-handshake race and run quiescent/exclusive.
8. Implement host launch and handshake. After success, use helper native ops to
   create the external current-user ACL/non-reparse attempt and copy the same
   reviewed single-file binary handle-relative. Write strict
   `artifact-manifest.json` last; final binary/inventory must be byte-identical to
   reviewed bootstrap/source locks. No unreviewed rebuild is adopted.
9. RED process-tree ownership: background/grandchild writer, helper crash, parent
   crash, timeout, cancellation, process/memory/output limit, late write, and
   retry. Implement suspended `CreateProcessW`, no-breakaway
   `KILL_ON_JOB_CLOSE` Job, active-process 128, job-memory 8 GiB, parent
   handle/start watchdog, fixed deadlines/output, cancel/kill, and zero-process/
   I/O drain before transition. After handshake Node directly spawns nothing.
10. RED real Windows file/root/mount/ancestor replacement in every backend window
    plus exact NFC/DOS/ADS/device/short-name/hardlink grammar. Implement held
    no-reparse handles, handle-relative operations, root membership,
    `NumberOfLinks == 1`, permissions, request order, and exact protocol bounds.
11. RED glob/grep as single operations: braces/extglob/malformed/invalid UTF-8,
    `(a+)+$`, backreference/lookaround, 1,025-byte regex, max depth/tree/bytes/
    results/output, cancellation/30-second deadline, and retry. Implement the
    iterative linear glob subset and .NET nonbacktracking/culture-invariant regex
    with 1,024-byte pattern/250 ms timeout and internal bounded batching.
12. GREEN real tracked-bootstrap→external-helper→patched-client combined suite,
    boundary/+1 and throughput gates, zero-skip on Windows. Separately prove no
    run policy preserves official byte/semantics and requires no helper.

Expected write owners: `self-openwiki/win32-helper/**`,
the two exact config locks, `scripts/build-win32-helper.mjs`, external attempt
artifact namespace, only private secure-filesystem/run-policy files and focused
tests inside the ordered upstream patch, and root/generated helper protocol/
reproducibility/process/glob tests. No MCP/public/persistent schema owner is
added.

### Batch 1B — Immutable patch input and verified materialization owner

1. RED patch capture: replace, grow, truncate, or link a patch or its ancestor
   between validation/read/apply phases. Prove the old path-reopen behavior can
   consume bytes different from those validated and that the revised owner
   fails before candidate mutation.
2. Implement bounded handle capture with path/ancestor identity snapshots,
   pre-open path, handle-before/after, post-read path, pre-mutation, and
   post-verification checks. `validateManifest` returns immutable patch bytes
   and identity evidence. Both `git apply --check` and `git apply` consume those
   captured bytes through standard input and never reopen a mutable patch path.
3. RED Git sandbox using the actual frozen submodule gitfile/gitdir/config.
   First prove its legitimate symlinks/ignorecase/main tracking keys pass. Then
   cover missing/wrong/extra/duplicate config, include/includeIf, fsmonitor/hooks/filter/diff/
   textconv/credential, `url.insteadOf`, `core.worktree` drift, submodule update,
   remote helper/uploadpack/receivepack, archive command, push follow-tags,
   appearance of tree/worktree `.gitattributes`, inherited fake
   Git/System32/PATH/COMSPEC/SystemRoot,
   trace/template/exec/prompt/pager/editor/signing, and external transport.
   Every outside executable/sentinel remains untouched.
4. After helper attestation, derive Git executable/System32 only through helper
   Win32 APIs and the verified toolchain manifest. Hold actual gitdir/config
   handles without delete sharing; strict canonical parse permits only exact
   `core.repositoryformatversion=0`, `core.filemode=false`, `core.bare=false`,
   `core.logallrefupdates=true`, `core.symlinks=false`, `core.ignorecase=true`,
   identity-resolving `core.worktree=../../../../upstream/openwiki`, frozen
   origin URL/fetch, and `branch.main.remote=origin`/
   `branch.main.merge=refs/heads/main`. Any other key/value fails. Batch 0 Setup
   is the sole normalization owner; materializer validates only. Prove frozen
   `.gitattributes` tree object and filesystem path remain absent under held
   parent enumeration/change notification; do not open/hash a nonexistent file.
5. Through the helper spawn operation, build a fixed minimal environment with no
   inherited executable/config selector, fixed owner temp, 30-second Git timeout,
   and 4 MiB combined output.
   Disable system/global/environment/non-owner command config. Every command uses
   literal `-c core.fsmonitor=false`, `-c core.hooksPath=NUL`,
   `-c core.attributesFile=NUL`,
   `-c diff.external=`, `-c credential.helper=`,
   `-c protocol.allow=never`, trusted-source-only
   `-c protocol.file.allow=always`, disabled commit/tag signing and noninteractive
   pager. No follow-tags/extra refs or upload/archive/receive external command.
   Git launches suspended into the same no-breakaway kill-on-close Job contract;
   Node never directly spawns it.
6. RED native materializer mutation: replace an ancestor or junction in the
   final check-to-create/write/rename/remove/adopt window for candidate, backup,
   journal, and lock. Prove the old Node path mutation escapes and the new owner
   leaves every outside sentinel untouched. Cover unowned external artifact and
   `.work` conflicts; neither may be deleted.
7. Published Setup's only pre-helper launch is the reviewed tracked bootstrap.
   After its attestation, create the byte-identical external helper artifact,
   open the identity-bound repository root, create/adopt `.work` handle-relative, and
   hold its no-reparse directory handle. Use the helper private owner namespace
   for every candidate/backup/journal/lock create/write/rename/remove/adopt. Node
   path APIs are read-only. Hold root/ancestor/candidate handles without delete
   sharing through Git/build; create children handle-relative and perform strict
   marker-gated artifact cleanup only.
8. RED build-before-adopt: frozen install, typecheck/build/focused security or
   real helper/patched-client combination failure, missing/wrong attestation,
   strict `dist` or helper manifest/file/link/hash/runtime drift, helper/parent
   crash, timeout, background descendant/late write, and retry before every
   adoption/backup-cleanup phase preserve the previous last-good checkout.
9. Complete upstream install/typecheck/build/focused tests only through helper
   process-tree spawn and drain all Jobs before marker/adoption.
   Bind owner-verified helper artifact root, manifest hash/attempt, exhaustive
   inventory, SDK/runtime packs, actual handshake runtime/image identity, and
   strict regular/non-link `dist` inventory. Reuse revalidates all evidence;
   `node_modules` is cache only. CLI has no skip; exported fixtures may inject
   only private `verifyCandidate`.
10. RED ownership/recovery: unowned candidate/backup/journal/lock, duplicate or
    extra JSON keys, unstable/replaced journal, owner/nonce mismatch, every
    response-loss phase, and simulated PID reuse. An unowned deterministic path
    must remain untouched and fail closed.
11. Bind all candidate/backup/journal/lock records to random `attemptId`/nonce,
    PID, operating-system process-start identity, strict canonical bytes, and
    current path/handle identities. Validate exact owner/hash/layout before any
    remove/rename/adopt. Read every record with bounded pre-open path/ancestor,
    open/fstat/read/fstat, and post-read path/ancestor identity checks; reject
    duplicate/extra keys and noncanonical re-encoding. Replay only exact phases;
    PID equality alone is not ownership and PID reuse is recoverable.
12. Rerun immutable patch, actual-config/attribute Git sandbox, process-tree,
    helper-only mutation, build-before-adopt, tracked bootstrap/external
    artifact/attestation, root matrix, component/hardlink grammar, glob/grep,
    helper protocol,
    response-loss, submodule clean, parent `.git` zero-mutation, and generated
    artifact suites. Add/retain the manual explicit-commit upstream update plan;
    it never follows a branch automatically.

Expected write owners: `patches/openwiki/**`, build/materializer/update scripts,
the external helper artifact namespace, root/generated materializer tests, and
the Batch 1A helper/client atomic unit. Node owns no `.work` mutation.

### Batch 2 — Remaining SelfOpenWiki package migration and rename

1. RED: add and run repository/static contract tests against the empty package;
   they must fail on the missing allowlisted inventory and must also prove the
   legacy baseline contains the forbidden active product names and parent-walk
   assumptions the migration is expected to remove.
2. Copy the reviewed MCP/Skill/config code and tests into the new independent
   package using a scripted allowlist constrained by that failing inventory
   test. Do not recopy, replace, or redesign the Batch 1A helper.
3. Rename package, binary, Skill, eval, diagnostics, capability paths, and
   host-neutral docs to SelfOpenWiki; consume the already-reviewed helper
   identity and protocol as a stable private boundary.
4. Change OpenWiki adapter/build paths to the generated patched checkout.
5. GREEN: rerun the inventory test, then complete existing contracts, server,
   runtime, provider, external
   transaction, publish, recovery, snapshot, and Skill suites.

Historical predecessor provenance remains private; active public product and
installation paths may not contain predecessor identities.

The remaining release order is unchanged: storage/configuration ownership,
Setup/capability verification, sandbox installation, migration, private
publication, stable-candidate real Install, public atomic publication, then the
separate retirement checkpoint. Revised Batch 1 does not authorize or reorder
any storage, migration, installation, private-repository, or public-remote side
effect.

### Batch 3 — External storage configuration

Amendment: the selected personal directory is the explicit Wiki root itself;
`runtimeRoot` is derived as the same-parent sibling `<wiki-root>.selfopenwiki`.
Batch 3 uses `--wiki-root` and never inserts an additional `wiki\` child.

1. RED: missing first-run selection, direct Git-root Wiki, link/reparse/path
   replacement, divergent derived roots, cross-volume plan, and active-state
   reconfiguration. Also fail on a missing parent chain and prove exclusive
   final-leaf creation plus identity-bound empty rollback.
2. Implement strict local install config and pure Wiki-root derivation.
3. Implement the complete bidirectional root non-overlap matrix, then split
   bootstrap repository/evidence/openwiki/Wiki-root/runtime-sibling roots.
4. Enforce sibling layout in publisher/recovery/state owners under existing
   locks; preserve legacy test fixtures through explicit new-layout fixtures or
   a narrowly reviewed compatibility adapter.
5. GREEN: Git and non-Git roots, all crash phases, startup recovery, no `.git`
   access/mutation, status truthfulness.

Expected production owners: config/bootstrap/index, publisher/recovery only where
the path relation is owned, and matching focused tests. Persistent public
schemas remain unchanged.

### Batch 4 — Setup and capability verification

1. RED: absent Setup, hostile args, missing dependencies, unbounded child output,
   submodule/patch/build drift, smoke failure, premature evidence activation,
   and missing/inaccurate README Setup/install/storage/MCP/subAgent/Git guidance.
2. Implement `setup.mjs` and `Setup.bat` with fixed commands and bounded output.
3. Adapt the capability matrix/verifier to bind the official gitlink, patch
   manifest, renamed Skill, tests, dist, and helper.
4. Extend real built-stdio smoke to use an isolated Wiki root and the complete
   external writer/Reviewer flow.
5. Implement the public README with synthetic placeholders only and make its
   static contract test GREEN.
6. GREEN: full verifier from an artifact-missing state; no private Wiki access.

### Batch 5 — Transactional installation

1. RED: interactive/noninteractive root selection, invalid root, conflict,
   partial config/Skill/MCP write, smoke failure, response loss, and retry.
2. Implement `install.mjs`/`Install.bat` with plan hash, explicit confirmation,
   write-ahead backup, CAS verification, rollback, and bounded diagnostics.
3. Configure exact `SELF_OPENWIKI_CONFIG` and stable absolute MCP entry.
4. Install the `self-openwiki` Skill and run temporary-store real stdio smoke.
5. Verify sandbox-store status read-only; never access the personal store during
   this implementation batch.
6. GREEN: sandbox install/rollback/idempotency and stable-path smoke. The real
   personal-store installation occurs only after migration and private push.

### Batch 6 — Knowledge migration

1. Recompute the live source manifest before any write; stop on mismatch.
2. RED: missing migration owner and all drift/link/partial/crash/replay/conflict
   scenarios from AC-16 through AC-19.
3. Implement candidate-copy, canonical manifest, durable
   `candidate_verified` intent before rename, atomic adoption, terminal receipt,
   intent cleanup, and exact replay.
4. Through the shared Wiki-root layout validator, require the selected Wiki
   root and its derived same-parent `runtimeRoot`, preserve the selected root's
   `.git` and identity, and identity-bind ACL/owned-empty rollback for later
   Install.
5. Rehearse the real order against temporary Git and non-Git fixtures.
6. Create/verify the local private envelope from the user-confirmed bindings,
   then run the real migration only after focused/full gates and independent
   post-landing Review.
7. Verify source remains unchanged and target is exact.

### Batch 7 — Private Wiki commit and push

1. RED: local-bare-remote tests prove the missing `publish-wiki.mjs` owner cannot
   satisfy strict plan, index/path/blob, remote CAS, journal, rejected push,
   response-loss reconciliation, or exact retry requirements.
2. Implement `publish-wiki.mjs` as the only private Git mutation-plan owner; it
   launches every fixed Git command through the attested helper Job. Make focused
   owner tests GREEN before touching the real private repository.
3. Run a new independent complete-diff Spec and Quality Review bound to the final
   migration and private-publisher bytes; require 0 Critical/Important before
   the first real private-repository mutation.
4. After real migration success, exclusive-create the fixed `.gitignore` bytes
   containing only the reviewed `.selfopenwiki/` rule, or write-or-verify an
   exact existing file; never overwrite conflicting content.
5. Recheck envelope-bound remote URL/emptiness, worktree/index, migration
   receipt, `.gitignore` bytes, and exact path set.
6. Through the owner, stage only `.gitignore` and the exact envelope-bound
   Markdown paths relative to the selected Wiki root, scan staged blobs,
   compare the canonical manifest/path set, and create one dedicated commit.
7. Verify commit tree and source/target manifests again.
8. Push `main` normally through the owner; no force. Reconcile and record the
   exact remote commit identity.

### Batch 8 — Public release and install

1. RED: fixture repositories and local bare remotes prove the missing
   `release.mjs` owner cannot satisfy parentless commit, fixed metadata/privacy,
   fresh-clone gate, annotated tag, atomic two-ref push, rejection, response-loss
   reconciliation, and remote OID requirements.
2. Implement `release.mjs` as the only public Git mutation-plan owner; it
   launches every fixed Git command through the attested helper Job. Make all
   fixture tests GREEN without touching the public remote.
3. Update only plan evidence with final commands/results; do not put a raw patch
   hash inside the patch whose bytes it would change.
4. Freeze the exact public bootstrap path set: the reviewed single-file
   `SelfOpenWiki.Win32Helper.exe`, `bootstrap-manifest.json`,
   `bootstrap-source-manifest.json`, and `toolchain-runtime-lock.json`. Verify
   both network-free rebuilds are byte-identical to the tracked executable and
   that the closed manifests bind the reviewed source, client, build owner,
   protocol, and toolchain bytes. Reject extra bootstrap files, PDB/debug paths,
   concrete host paths, private data, or a dirty bootstrap path.
5. Run final independent Spec and Quality Review over the complete exact diff,
   including the executable/manifests, reproducibility evidence, root matrix,
   pre-handshake TCB, Job lifecycle, and glob/grep security tests. The reviewed
   hashes become release evidence only when Critical/Important are zero.
6. Run all final gates from clean build state and scan public staged blobs and
   binary strings against the private envelope's forbidden literals/
   fingerprints, PDB/source paths, credentials, and unlisted payloads.
7. Through the owner, stage the exact public path set and create one local
   initial commit; do not
   push or tag yet. Use the fixed commit message
   `feat: release SelfOpenWiki v0.1.0`, parse the raw parentless commit object,
   and re-run the privacy scan over its metadata and tree.
8. Verify the candidate commit tree, gitlink, patch manifest, all four bootstrap
   paths, reproducibility/privacy evidence, and clean worktree. Clone that exact
   local HEAD into a fresh isolated directory, initialize submodules, and require
   Setup to accept only that release tree and its clean current-user ACL/
   non-reparse bootstrap root. Run sandbox Install, real stdio/capability
   verification, and complete Spec/Quality Review against committed bytes.
9. From the stable `<repository-root>` at that exact candidate commit, run the
   real transactional `Install.bat --wiki-root <wiki-root>` using the
   envelope-selected root. Verify installed artifact/config hashes, read-only
   personal status, unchanged personal Wiki and `.git` identity manifests,
   exact retry, and failure rollback evidence. The required order is
   `Setup → migration → private push → real Install`.
10. Through the owner, create annotated `v0.1.0` locally with the fixed message
    `SelfOpenWiki v0.1.0`; parse and privacy-scan the raw tag object and verify it
    targets the candidate commit. Atomically push `main` plus the tag to the
    still-empty remote without force. If atomic push is unsupported or any
    remote precondition changed, publish nothing. On response loss, fetch and
    accept only exact both-ref success or neither-ref failure; one-ref publication
    is a blocking restore condition.
11. Verify remote branch/tag object identities and run only bounded read-only
    postflight checks; record final evidence.

### Batch 9 — Retirement checkpoint

Stop and report:

- public SelfOpenWiki remote commit/tag;
- private Wiki remote commit and exact envelope-bound manifest;
- installed MCP/Skill/config evidence;
- successful real status and external flow against a temporary store;
- read-only status against the selected personal store;
- old repository/installation backup inventory.

Ask the user for final destructive authorization. Only a later confirmed action
may remove the legacy Codex MCP block/Skill and delete or archive the legacy
repository. This batch is not pre-authorized by the implementation confirmation.

## Verification commands

Exact scripts may be finalized during implementation, but gates must include:

```powershell
# Production/release entry point. After the tracked-bootstrap handshake, Setup
# sends every Git/dotnet/Corepack/pnpm/Node/test child plan to the helper Job;
# this entry owns contract, typecheck, build, test, and capability gates.
.\Setup.bat

# Revised Batch 1 development-only tracked bootstrap/reproducibility gates.
# The first candidate runs under the explicit pre-handshake toolchain TCB. After
# the reviewed candidate's handshake, the owner sends the independent publish to
# the helper Job. Both use --no-restore and the exact locked publish properties;
# this document revision runs neither command and creates no binary.
node scripts/build-win32-helper.mjs --create-reviewed-candidate <bootstrap-candidate-a> --no-restore
node scripts/build-win32-helper.mjs --verify-reproducible <bootstrap-candidate-a> <bootstrap-candidate-b> --no-restore
# The accepted Setup run records helper-owned Batch 1 P0, materializer, generated
# upstream, full repository, Skill, script syntax, stdio, and capability results.

# Repository hygiene
git diff --check
git status --short
git submodule status -- upstream/openwiki
```

Focused TDD commands and test names must be recorded in the final plan evidence.
Full gates include the migrated MCP suite, official patched OpenWiki suite,
capability verifier, real stdio smoke, install sandbox, migration sandbox, and
Git publication sandbox.

The Batch 1A/1B gate is Windows-only, P0, zero-skip, and uses the reviewed
tracked single-file bootstrap, byte-identical owner-verified external helper
artifact, strict exhaustive manifests, real handshake/runtime/image attestation,
actual patched client, and real junction/reparse/hardlink/ADS/device/alias/
process fixtures. It verifies the exact real local Git config, continuous
`.gitattributes` absence, root matrix, suspended-process Job assignment, crash/
timeout zero-drain, background-descendant late-write rejection, and single-call
glob/grep bounds. A different repository binary, framework-dependent build,
mock handshake, direct post-handshake Node spawn, or unsupported-host result
cannot satisfy it.

## Review gates

Before implementation:

- independent complete-package `design.gate` and `plan.gate` Review;
- zero Critical/Important; Minor fixed or explicitly accepted;
- package hash bound to final design/test/plan bytes;
- explicit user confirmation of that final package.

This revised document package is currently at that pre-implementation gate.
After final document bytes and package hash are produced, a new independent
whole-document Review must evaluate all three documents together. Any document
change invalidates that Review. Only a 0 Critical/Important result, disposition
of every Minor, and new explicit user confirmation permits Batch 1A, followed
by Batch 1B.

After Batch 1A/1B implementation, run a new independent complete-diff Spec and
Quality Review bound to the reviewed tracked executable/manifests, both
byte-identical network-free rebuilds, final helper/client/patch/materializer/
tests, and generated evidence. Critical/Important must be zero before the
bootstrap is an accepted authenticity root or Batch 2 begins.

Before side effects and release:

- post-landing complete-diff Spec and Quality Review;
- zero Critical/Important;
- exact write scope and protected boundaries verified;
- final tests run on final bytes;
- explicit verification that neither old data nor old install was deleted.

## Rollback

- Implementation before real side effects: delete only exact owned temporary
  paths; never reset or clean user-owned repositories broadly.
- Revised Batch 1: helper, client, patch, materializer, focused tests, and
  evidence roll back as one unit. Before release, the tracked bootstrap
  executable plus bootstrap/source/toolchain manifests roll back with that exact
  reviewed unit; after release, any correction is a new complete-diff-reviewed
  commit, never an ad hoc binary replacement or history rewrite. Retain the last
  verified generated checkout and every immutable verified helper artifact.
  Only the attested helper/build owner may remove an unverified external artifact
  or `.work` path after strict marker, identity, ACL, layout, inventory, and
  attempt validation. Unknown or unowned artifact/candidate/backup/journal/lock
  paths are never cleaned. A failure before the first native handshake preserves
  observable state for manual inspection and makes no race-free automatic cleanup
  claim.
- Setup: retain last verified generated checkout/helper/evidence and quarantine
  only deterministic paths whose exact owner records and identities validate
  through the held helper namespace. Helper/parent crash or command timeout must
  terminate the Job and drain active processes and I/O to zero before cleanup,
  inventory, adoption, or retry.
- Install: use recorded backups and CAS to restore exact prior Skill/MCP/config.
- Migration before adoption: delete only the exact owned candidate/empty runtime
  root. After adoption, retain intent/receipt/formal tree and old source.
- Private publication: after push, preserve the private remote commit/ref and
  journal; never delete or rewrite it. Before push, retain local objects for
  exact retry.
- Public candidate/tag: preserve local objects and release journal across
  private-push, Install, or public-push failure.
- Successful real Install is retained on later release failure; a failed Install
  restores its exact backup. The legacy installed surface remains available.
- Atomic public push: neither ref means safe retry; both exact refs means success;
  one/mismatched ref is `restore_required` with no automatic remote mutation.
- Published corrections use a new reviewed commit; no history rewrite.
- Old system: remains the final rollback until a separately confirmed retirement.

## Initial unverified items

- Every revised Batch 1A/1B RED and GREEN, including real helper reparse races,
  immutable patch capture, reviewed tracked bootstrap/source/toolchain locks,
  two byte-identical network-free rebuilds, external self-contained artifact
  handoff/attestation, exact real and hostile Git config plus continuous
  `.gitattributes` absence, hardlink/alias grammar, bootstrap/artifact root
  matrix, helper-only `.work` mutation, real helper/client build-before-adopt,
  Job/parent/crash/timeout/late-write zero-drain, bounded single-operation glob/
  grep, strict inventory/runtime binding, and owner/PID-reuse recovery. No binary
  or rebuild evidence exists in this document-only revision. Earlier Batch 1 and
  `cb19090e…ce4958a` evidence is superseded and cannot close these items.
- Native Codex rediscovery after a host restart.
- Remote pushes until normal Git authentication and remote preconditions are
  rechecked.
- Permanent old-system retirement.

These are gates, not reasons to weaken acceptance criteria.
