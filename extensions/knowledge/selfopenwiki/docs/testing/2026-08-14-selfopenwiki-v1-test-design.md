---
workflowStatus: completed
totalSteps: 5
stepsCompleted:
  - step-01-detect-mode
  - step-02-load-context
  - step-03-risk-and-testability
  - step-04-coverage-plan
  - step-05-generate-output
lastStep: step-05-generate-output
nextStep: ""
lastSaved: 2026-08-14
workflowType: testarch-test-design
mode: system-level
---

# SelfOpenWiki v0.1 Test Design

User-confirmed amendment: the selected personal directory is the explicit
`wikiRoot` itself. `runtimeRoot` is derived as the same-parent sibling
`<wiki-root>.selfopenwiki`; the older `<storage-root>\wiki` nesting is
superseded for all storage-layout acceptance criteria below.

Purpose: define risk-based acceptance evidence for the architecture, build,
installation, external-agent MCP, private Wiki root, and one-time knowledge
migration before implementation begins.

This test design supersedes the earlier contract package, including
`cb19090e…ce4958a`. All earlier Batch 1
RED/GREEN counts, including the reported 22/22 result, generated build results,
materialization markers, and Review conclusions are historical diagnostics
only. New P0 RED evidence is pending and must be produced from this package
after whole-package Review and explicit user confirmation.

## Inputs and mode

System-level mode is used because this change creates a repository, installation
boundary, persistent storage layout, recovery model, and deployment/migration
workflow. Inputs are the approved user requirements, the design companion,
current reviewed predecessor source/tests, frozen official OpenWiki commit
`355f4f68e71bd024631cdcff7aa871c3e72435da`, and the observed source/destination
repositories.

The locked TEA reference set includes risk governance, probability/impact, NFR
criteria, ADR readiness, test levels, priorities, and test quality. Its source
identity is not part of the public contract package.

## Executive summary

The critical risks are private-data loss, Git metadata damage, path escape,
non-reproducible upstream patching, and invalid recovery across separated roots.
All functional tests are expected to remain below the PR execution threshold;
the full upstream/MCP build and real stdio verifier may run as the release gate.

All P0 and P1 release scenarios must pass 100% with zero skip and no open
Critical or Important Review finding. Every high risk requires implemented and
tested mitigation before migration or installation side effects.

## Dependencies and blockers

- Official OpenWiki commit
  `355f4f68e71bd024631cdcff7aa871c3e72435da` must fetch and verify exactly;
  any upstream change invalidates this contract before patch generation.
- The envelope-bound legacy source tree and every expected Wiki file must remain
  present and unchanged until migration acceptance.
- The public and private remotes must still match the reviewed empty/unborn
  state before their first pushes.
- Node 22 or newer, Git, Corepack, repository-pinned pnpm, and a stable .NET 9
  SDK selected by the committed `global.json` policy must be available. Exact
  SDK/runtime-pack/toolchain versions and the helper's actual handshake runtime
  are capability-evidence inputs. Helper publication is self-contained and may
  not depend on a framework-dependent host runtime.
- The tracked bootstrap executable/manifests do not exist yet. Batch 1 must
  generate them from the reviewed source/toolchain locks, prove an independent
  network-free rebuild byte-identical, and pass complete-diff Review before they
  can be authenticity evidence. This contract revision generates no binary.
- Setup/real race tests require an exclusive quiescent Windows test sandbox. The
  pre-handshake TCB limitation must be reported rather than converted into a
  zero-side-effect claim.
- Real Windows reparse/junction tests are required; unsupported test hosts may
  not convert those P0 scenarios to PASS.
- Native host rediscovery after Codex restart can only be claimed after a new
  host session. In-process stdio verification is necessary but not equivalent.

## Risk assessment

Probability and impact use TEA's 1–3 scale; score is probability × impact.

| ID    | Category | Risk                                                                                   |   P |   I | Score | Required mitigation                                                                                           |
| ----- | -------- | -------------------------------------------------------------------------------------- | --: | --: | ----: | ------------------------------------------------------------------------------------------------------------- |
| R-001 | DATA     | Migration or publish loses/replaces private Wiki bytes                                 |   3 |   3 |     9 | Immutable source manifest, candidate copy, atomic adoption, post-adoption replay, old source retained         |
| R-002 | DATA     | Treating Git root as formal tree moves/destroys `.git`                                 |   3 |   3 |     9 | Explicit Wiki root with derived same-parent runtime sibling; `.git` remains outside snapshots              |
| R-003 | SEC      | Symlink/junction or ancestor race escapes repository/storage boundaries                |   2 |   3 |     6 | Canonical non-link roots, handle identities, pre/post ancestor checks, no-follow helper evidence              |
| R-004 | TECH     | Floating or dirty upstream/patch state produces unverifiable build                     |   2 |   3 |     6 | Exact gitlink, URL/commit/clean checks, canonical patch manifest, generated checkout only                     |
| R-005 | DATA     | Separated Wiki/runtime roots break atomic publication or recovery                      |   2 |   3 |     6 | Direct same-parent Wiki/runtime siblings; same-volume checks; crash-phase regression                          |
| R-006 | SEC      | Stale capability evidence activates different source/build/Skill bytes                 |   2 |   3 |     6 | Existing full fingerprints plus submodule/patch/config/install-script bindings; smoke-before-activation       |
| R-007 | OPS      | Installer overwrites unrelated Skill/MCP/config data or cannot roll back               |   2 |   3 |     6 | Exact ownership, CAS/backup transaction, conflict refusal, post-write verification, rollback tests            |
| R-008 | DATA     | Git migration commit/push contains unexpected or stale bytes                           |   2 |   3 |     6 | Empty index, exact mapped path set, staged-blob scan/manifest, commit-tree verification, remote CAS preflight |
| R-009 | OPS      | Old system is removed before new install/data proves usable                            |   2 |   3 |     6 | Explicit retirement checkpoint; backup and no-delete assertions throughout release                            |
| R-010 | TECH     | Product rename leaves predecessor paths, parent assumptions, or broken tool contracts  |   2 |   2 |     4 | Static inventory tests, exact nine-tool regression, host-neutral paths, full predecessor/external tests       |
| R-011 | OPS      | Host assumes MCP creates subAgents or reuses writer as Reviewer                        |   2 |   2 |     4 | Skill evals, distinct execution-ID tests, real external writer/Reviewer stdio smoke                           |
| R-012 | PERF     | Large or hostile trees/output exhaust memory or make setup unbounded                   |   1 |   3 |     3 | Preserve tree/file/output bounds, streaming/handle reads, fixed process timeouts, long test separated         |
| R-013 | SEC      | Run-policy authorize/use races read or write outside a bound root or mount             |   3 |   3 |     9 | Held no-reparse root/mount handles, handle-relative helper I/O, real Windows replacement races                |
| R-014 | SEC      | Patch replacement or hostile Git config executes different bytes or an outside program |   2 |   3 |     6 | Handle-bound immutable patch capture, stdin apply, allowlisted Git environment/config, outside sentinels      |
| R-015 | REL      | Unbuilt/drifted candidate or unowned recovery state replaces the last-good build       |   2 |   3 |     6 | Build-before-adopt, strict dist/helper inventory, per-attempt ownership, exact response-loss replay           |
| R-016 | SEC      | Helper artifact/path is replaced between build, launch, handshake, or backend use      |   3 |   3 |     9 | External immutable attempt artifact, strict manifest, prelaunch/post-handshake handle attestation             |
| R-017 | SEC      | Materializer path mutation or hardlink/alias escapes the held owner/root namespace     |   3 |   3 |     9 | Helper-only handle-relative mutation, no-delete-share handles, strict component grammar/link-count checks     |
| R-018 | SEC      | Hostile submodule config/attributes or inherited executable path runs an outside tool  |   3 |   3 |     9 | Handle-bound config/attribute allowlists, Win32-derived executables, fixed config/environment, sentinels      |
| R-019 | REL      | Framework/runtime-pack or artifact inventory drift reuses an incompatible helper       |   2 |   3 |     6 | Self-contained publish, exhaustive manifest, actual runtime handshake, missing/extra/drift rejection          |
| R-020 | SEC      | Unreviewed or drifted tracked bootstrap executes before native trust is established    |   3 |   3 |     9 | Reviewed release tree, source/toolchain locks, byte-identical rebuild, explicit pre-handshake TCB             |
| R-021 | SEC      | Child/descendant survives helper/parent crash or timeout and performs late writes      |   3 |   3 |     9 | Suspended launch, no-breakaway Job kill-on-close, parent watchdog, zero-process/I/O drain before transition   |
| R-022 | PERF     | Client-loop glob or backtracking regex exhausts request/time/tree/output bounds        |   3 |   3 |     9 | Single helper operation, linear glob subset, nonbacktracking regex, fixed deadlines/cancellation/bounds       |

## Testability assessment

### Actionable architecture requirements

1. Root selection and derivation must be exposed as pure validation/derivation
   functions before filesystem mutation.
2. Setup, install, materialization, migration, and Git publication need injected
   command/filesystem ports or test-owned wrappers. Production must not gain
   public test flags.
3. Publisher fault seams already used for crash recovery remain private and are
   extended only for the new storage-layout boundaries.
4. Install and migration return bounded, schema-checked receipts that expose
   hashes and paths but never Wiki contents or secrets.
5. The real built-stdio smoke must run with a temporary Wiki root; the user's
   private Wiki is read-only during installation verification.
6. Win32 secure-filesystem tests use a test-owned deterministic process wrapper
   around the real helper plus real files/directories/junctions. Production has
   no fault-injection command, environment flag, public skip, or model-visible
   absolute-path seam.
7. Materializer fixtures may inject one private `verifyCandidate` port through
   the exported module interface. The production CLI always performs the real
   helper build, frozen install, typecheck, build, and focused security tests.

### Existing strengths

- Strict Zod contracts and exact nine-tool server matrix.
- Handle-bound Markdown snapshot reads and reparse rejection.
- Operation/Wiki lock ordering, durable transaction state, journals, markers,
  tombstones, and recovery-of-recovery coverage.
- Hash-bound capability activation after real stdio smoke.
- Provider-free external-agent path with strict writer/Reviewer receipts.

## Acceptance criteria

### Repository and upstream

- AC-01: Fresh clone with submodules and the same exact evidence-bound toolchain
  produces the same gitlink, patches, generated OpenWiki build, MCP/helper build,
  and capability fingerprints. A different supported toolchain invalidates
  evidence and requires a fresh build rather than cross-toolchain byte equality.
- AC-02: Setup never changes `git status` inside `upstream/openwiki`.
- AC-03: Wrong URL/commit, dirty submodule, reordered/changed patch, failed
  applicability, partial generated tree, or stale evidence fails closed.
- AC-03a: Setup's only parent `.git` changes are the exact allowlisted pinned
  submodule config/gitdir/gitfile objects; failure restores previous parent Git
  metadata, and the selected Wiki root's `.git` remains byte-identical.
- AC-03b: Patch validation opens each bounded patch once, binds pre-open path,
  handle-before/after, post-read path, and ancestor identities, and passes the
  captured immutable bytes to both Git applicability and apply through standard
  input. Replacement, growth, truncation, link, or ancestor drift fails before
  candidate mutation.
- AC-03c: The public bootstrap root contains only tracked
  `SelfOpenWiki.Win32Helper.exe` and strict `bootstrap-manifest.json`; tracked
  bootstrap-source/toolchain locks exhaustively bind all source/client/build and
  .NET/Roslyn/reference/runtime-pack inputs. During unborn development, the exact
  contract package plus independent complete-diff Review authenticates these
  bytes without requiring clean HEAD/index. Before release acceptance, two
  network-free pinned-toolchain builds are byte-identical and independently
  reviewed. Published Setup accepts only the exact release tree, clean bootstrap
  files, current-user ACL/non-reparse roots, and expected image/protocol hashes.
  The attested tracked helper creates an external attempt whose final executable
  is byte-identical to that reviewed binary; strict manifest/attempt/runtime/
  inventory evidence and real patched-client tests precede adoption. No artifact
  cache becomes Install state or exposes a concrete LocalAppData path publicly.
- AC-03d: Every materializer Git process uses helper-derived verified Git and
  Windows executable paths, a fixed minimal environment, bounded timeout/output,
  and literal hardened config. The helper holds and strictly parses the actual
  submodule gitdir/config; only exact frozen values for repositoryformatversion,
  filemode, bare, logallrefupdates, worktree, symlinks, ignorecase, origin, and
  main branch tracking are accepted. Batch 0 Setup alone may normalize that
  allowlist; materializer only validates it. The frozen Git tree object and
  filesystem path `.gitattributes` remain absent throughout each operation;
  nothing opens/hashes a nonexistent file. Any extra/include/url-rewrite/
  fsmonitor/hook/credential/filter/submodule-update/upload/archive/follow-tag
  state, attribute appearance, or inherited executable selection cannot execute
  an outside program or change an outside sentinel.
- AC-03e: Candidate, backup, journal, and lock state is bound to a random
  attempt/nonce plus PID and operating-system process-start identity. Strict
  canonical bounded handle reads bind path/ancestor and pre/post-handle
  identities, reject extra/duplicate keys, require canonical re-encoding, and
  reject replacement; unowned deterministic paths fail closed; exact
  response-loss phases replay; PID reuse is recoverable.
- AC-03f: Bootstrap creates only the external helper artifact. After attestation,
  the helper opens the repository root, creates/adopts `.work` handle-relative,
  and holds it. Every create/write/rename/remove/adopt mutation of a candidate,
  backup, journal, lock, or adopted checkout uses that owner session; Node path
  APIs are read-only. Handles deny delete sharing through Git/build.
  A final check-to-mutation ancestor/junction replacement cannot read or change
  an outside sentinel, and unowned artifact or `.work` conflicts are not removed.
- AC-03g: After native handshake, the helper alone launches Git/dotnet/Corepack/
  pnpm/Node/tests suspended into a no-breakaway `KILL_ON_JOB_CLOSE` Job with
  fixed process/memory/output/deadline bounds. It watches the parent process
  handle/start identity. Parent/helper crash or timeout kills/cancels descendants
  and drains active process/I/O to zero before inventory/adopt/cleanup/retry; no
  direct Node spawn or late write crosses the terminal transition.
- AC-04: `Update-Upstream.bat` changes only the reviewed gitlink/patch/evidence
  set and never follows latest automatically.

### Wiki-root installation

- AC-05: Interactive first install prompts for a Wiki root; unattended install
  requires an absolute `--wiki-root`.
- AC-06: The persisted config contains one canonical `wikiRoot` and derives
  exactly `<wikiRoot>.selfopenwiki` as `runtimeRoot`.
- AC-07: Ordinary local roots and Git worktrees are accepted. Links, reparse
  paths, path replacement, nesting, collisions, cross-volume recovery, and
  hostile inherited environment fail before mutation.
- AC-07a: An absent Wiki root is created only as one exclusive final leaf
  below an existing canonical non-link parent. Failure removes it only if it is
  still the same owned empty directory; a missing parent chain is rejected.
- AC-07b: Repository/submodule/generated/patch, selected Wiki root/runtime
  sibling, legacy source, tracked bootstrap, external helper artifact/attempt, LocalAppData
  config/envelope/journal, installed Skill, Codex config, and backup roots obey
  the documented bidirectional non-overlap/containment matrix and ACL/identity
  handoffs. Equal, unexpected ancestor/descendant, case-alias, and replacement-
  race violations fail before mutation.
- AC-07c: Version 0.1 Git repositories use one embedded non-link `.git`
  directory. Linked worktrees, gitfiles, `commondir`, alternates, hostile
  hooks/filters/signing/editor/pager/prompt configuration, and inherited Git
  path/object environment fail before publication mutation.
- AC-08: Setup/Install leave the selected Wiki root's `.git` and ignore files
  unchanged and outside all snapshots, transactions, journals, and publication
  renames. The explicit migration commit alone may add the reviewed tracked
  `.gitignore`.
- AC-09: Reinstall is idempotent; conflicting MCP/Skill/config ownership fails
  closed; any partial install restores exact previous bytes.

### MCP behavior

- AC-10: Exact nine tool names and public schemas remain compatible.
- AC-11: Status reports the selected Wiki root and truthful readiness without
  exposing credentials or requiring OAuth in external mode.
- AC-12: Legacy provider mode remains explicit; external mode never invokes
  provider/model/finalizer paths.
- AC-13: Writer and Reviewer execution IDs must differ; all receipt and package
  hashes bind the same transaction/generation/revisions.
- AC-14: Every existing publish/recovery crash phase works with the selected
  Wiki root and its sibling `.selfopenwiki` runtime root and never touches `.git`.
- AC-15: Startup recovery completes before begin/finalize can expose a writable
  path or mutate formal knowledge.
- AC-15a: With run policy active on Windows, read, write, edit, list, glob, grep,
  upload, download, mkdir, remove, and rename operate only through the private
  helper session bound to held no-reparse root/mount handles and permissions.
  Model input cannot select an absolute host/helper/root/mount path. NFC relative
  components reject empty/dot, separator, colon, NUL/control, wildcard,
  trailing-dot/space, ADS, NT/device/short aliases, and DOS reserved names.
  Existing/new files require link count exactly one before any read or write.
- AC-15b: Host-only `SELFOPENWIKI_SECURE_FS_HELPER` points to the verified
  executable in any owner-verified immutable artifact attempt and
  `SELFOPENWIKI_SECURE_FS_ATTESTATION` points to its strict manifest. The parent
  binds manifest SHA-256/`attemptId`, verifies executable/manifest handles before
  launch and after handshake, and matches process-image volume/file ID/SHA,
  protocol, runtime, toolchain, manifest hash, and attempt. File, root, mount, or
  ancestor junction replacement in each
  authorize-to-open/create/write/enumerate window fails closed and leaves every
  outside sentinel byte-identical. Helper absence/path/hash/version drift,
  inherited/conflicting environment, session root replacement, crash, timeout,
  protocol drift, or bounds overflow likewise exposes no bytes and produces no
  external mutation.
- AC-15c: With run policy absent, the official upstream filesystem behavior is
  byte- and semantic-compatible and does not require the helper. No public MCP
  or persistent Wiki schema changes.
- AC-15d: Bootstrap trusts only the OS loader, clean reviewed release/bootstrap/
  source bytes, and verified Windows/.NET toolchain. Quiescent exclusive Setup is
  mandatory. Before the first handshake, arbitrary same-user code/replacement is
  outside the guarantee and tests assert drift detection, not impossible zero-
  side-effect prevention.
  After handshake, real replacement/reparse/hardlink/ADS/device/trailing-alias
  and available 8.3-alias cases remain P0 and leave outside bytes unread/
  unchanged.
- AC-15e: Glob/grep each use one helper request. Glob accepts only `*`, `?`,
  whole-component `**`, and character classes through an iterative linear
  matcher; braces/extglob/malformed patterns fail. Grep accepts at most 1,024
  UTF-8 pattern bytes, rejects backreference/lookaround, and uses .NET
  nonbacktracking/culture-invariant regex with 250 ms timeout. One monotonic
  30-second deadline/cancellation covers internal batching; depth 64, 100,000
  entries, 50 MiB examined, 10,000 results, and 16 MiB encoded/model output are
  hard bounds.

### Migration and Git release

- AC-16: The observed source exactly matches the private Review envelope's
  relative paths, bytes, hashes, no-link/case-collision constraints, and
  canonical manifest without exposing those values in public history.
- AC-17: Migration copies into a private candidate, verifies every byte/hash,
  durably records `candidate_verified`, atomically adopts the selected Wiki root,
  and retains the old source.
- AC-18: Source or destination drift, non-empty target, partial candidate,
  crash-before/after-adopt, link swap, extra file, hash mismatch, or invalid
  receipt cannot report unverified success. A matching durable intent,
  directory identities, and formal manifest after adoption must replay exact
  terminal success; any mismatch fails closed and preserves evidence.
- AC-19: The authorized Wiki commit stages only `.gitignore` and the exact
  envelope-bound Markdown paths relative to the selected Wiki root, matches
  staged blob hashes to the receipt, contains no runtime state, and is pushed
  only if the private remote is still the expected empty branch.
- AC-20: SelfOpenWiki release is one locally created initial MIT commit plus
  annotated `v0.1.0`, exact submodule gitlink, no generated/runtime/private Wiki
  content, successful fresh-clone Setup/sandbox-Install verification of that
  exact commit, and only then one atomic normal push of `main` and the tag to the
  expected empty remote.
- AC-21: The old repository/MCP/Skill are not deleted or overwritten before a
  separate final retirement confirmation.
- AC-22: Public staged blobs and the candidate commit contain no private
  envelope, path, remote, manifest fingerprint, or forbidden literal.
- AC-23: The envelope exists only below the fixed LocalAppData owner root with
  current-user ACL and non-link identity. Public/private Git worktrees, selected
  storage, legacy source, generated checkout, and installed Skill contain no
  envelope/backup. The real transactional Install runs from the stable exact
  candidate commit after private migration publication, preserves personal Wiki
  and `.git` bytes, supports exact retry/rollback, and completes before public
  branch/tag publication.
- AC-24: The public README passes a release-blocking contract for Setup, Install,
  external storage, exact MCP/Skill configuration, host-owned writer/Reviewer
  subAgents, explicit legacy mode, recovery, and no automatic Git publication;
  it contains no private envelope binding.
- AC-25: Private/public publication journals occupy only their fixed
  storage-runtime/LocalAppData roots, bind exact Git roots/objects/refs/receipts,
  and converge after retry or response loss without force/reset/ref deletion.
- AC-26: Real migration initializes/adopts runtime through the shared layout
  owner before Install; later real Install adopts the same identities and does
  not rewrite Wiki or `.git` bytes.

## Coverage plan

P0/P1/P2/P3 express risk priority, not execution timing.

| Test ID    | Requirement                                                           | Level               | Priority | Risks                         | Evidence                                                      |
| ---------- | --------------------------------------------------------------------- | ------------------- | -------- | ----------------------------- | ------------------------------------------------------------- |
| SW-INT-001 | Exact Wiki-root derivation and strict config schema                   | Unit                | P0       | R-002,R-005                   | Pure path/schema tests                                        |
| SW-INT-002 | Selected Git Wiki root preserves `.git`; metadata is never formal content | Integration         | P0       | R-002                         | Real temporary Git repo and identity manifest                 |
| SW-INT-003 | Runtime/Wiki sibling identity and same-volume enforcement             | Integration         | P0       | R-003,R-005                   | Real Windows filesystem tests                                 |
| SW-INT-004 | Root/ancestor/file replacement, junction, symlink rejection           | Integration         | P0       | R-003                         | Real reparse objects and deterministic hooks                  |
| SW-INT-005 | Submodule remains clean through successful/failed setup               | Integration         | P0       | R-004                         | Fixture remotes plus real git status                          |
| SW-INT-006 | Patch manifest/apply/generated checkout atomicity                     | Integration         | P0       | R-004,R-006                   | Fixture patch stacks and interrupted adoption                 |
| SW-INT-007 | Capability evidence activates only after built stdio smoke            | Integration         | P0       | R-006                         | Existing evidence attack matrix plus new fingerprints         |
| SW-E2E-001 | Fresh clone → Setup → Install with local non-Git store                | E2E                 | P0       | R-004,R-007                   | Windows sandbox install                                       |
| SW-E2E-002 | Setup → Install with Git store, real external writer/Reviewer publish | E2E                 | P0       | R-002,R-005,R-011             | Built MCP stdio, formal revision change, `.git` stable        |
| SW-INT-008 | All publish/recovery crash phases under new layout                    | Integration         | P0       | R-001,R-005                   | Existing fault matrix rerun and new layout fixture            |
| SW-INT-009 | Envelope-bound candidate migration/WAL/adoption/replay                | Integration         | P0       | R-001,R-003                   | Synthetic manifest plus private E2E envelope                  |
| SW-INT-010 | Migration drift/partial/link/case/extra-file failures                 | Integration         | P0       | R-001,R-003                   | Deterministic filesystem fault cases                          |
| SW-INT-011 | Staged-blob manifest and exact Wiki commit path set                   | Integration         | P0       | R-008                         | Local bare remote and alternate index fixtures                |
| SW-E2E-003 | Authorized real migration verification before private push            | E2E/manual gate     | P0       | R-001,R-008                   | Pre/post manifests, commit tree, remote branch                |
| SW-INT-012 | Installer conflict, rollback, response loss, idempotent retry         | Integration         | P1       | R-007                         | Sandboxed Codex/Skill/config roots                            |
| SW-API-001 | Nine tools and schema-2 compatibility                                 | API/contract        | P1       | R-010                         | Existing contract/server/runtime suites                       |
| SW-API-002 | External failure/resume/repair/clarification/abort/publish            | API/integration     | P1       | R-010,R-011                   | Existing Task 2–7 suites                                      |
| SW-INT-013 | Product/path inventory contains no installed predecessor names        | Static/integration  | P1       | R-010                         | Allowlisted historical provenance only                        |
| SW-INT-014 | Setup output, child process, tree, and config bounds                  | Integration         | P1       | R-012                         | Existing bounded probes plus hostile fixtures                 |
| SW-INT-015 | Envelope owner-root/ACL/link/identity/write-or-verify boundaries      | Integration         | P0       | R-003,R-008                   | Real LocalAppData sandbox and Git-tree absence checks         |
| SW-E2E-004 | Stable candidate real Install after private push, before public push  | E2E/manual gate     | P0       | R-001,R-007                   | Artifact/config hashes, status, retry/rollback evidence       |
| SW-E2E-005 | Public commit/tag privacy, fresh clone, atomic publication            | E2E/release         | P0       | R-004,R-006,R-008             | Local/bare remotes, raw objects, response-loss reconcile      |
| SW-INT-016 | Bidirectional root non-overlap and handoff identity                   | Integration         | P0       | R-002,R-003,R-005             | Pairwise matrix, case aliases, replacement hooks              |
| SW-INT-017 | Exact toolchain evidence invalidation and rebuild                     | Integration         | P0       | R-004,R-006                   | Node/.NET/Corepack/pnpm/OS/arch drift                         |
| SW-INT-018 | Embedded Git metadata ownership, hostile config, publication journals | Integration         | P0       | R-003,R-008,R-021             | Real repos/helper Jobs, phase/response-loss/descendant faults |
| SW-E2E-006 | Migration runtime initialization followed by Install adoption         | E2E                 | P0       | R-001,R-005,R-007             | Exact identities, ACL, Wiki/.git before/after manifests       |
| SW-DOC-001 | README explains build/install/data/Git/subAgent boundaries            | Static              | P1       | R-007,R-011                   | Release-blocking documentation contract                       |
| SW-INT-019 | Immutable patch handles/ancestor identities and stdin Git apply       | Integration         | P0       | R-003,R-004,R-014             | Real replacement/growth/truncate/link fixtures                |
| SW-INT-020 | External helper build/attestation plus build/test-before-adopt        | Integration         | P0       | R-004,R-006,R-015,R-016,R-019 | Real self-contained build, handshake, failure/drift/crash     |
| SW-INT-021 | Win32 secure-filesystem protocol and authorize/use race closure       | Integration         | P0       | R-003,R-013,R-017             | Real helper, reparse/hardlink/alias races, outside sentinels  |
| SW-INT-022 | Materializer Git executable/config/attribute sandbox                  | Integration         | P0       | R-004,R-014,R-018             | Actual gitfile/config/attributes and hostile sentinels        |
| SW-INT-023 | Per-attempt recovery ownership, response loss, and PID reuse          | Integration         | P0       | R-003,R-015                   | Strict records, unowned conflicts, real process lifecycle     |
| SW-INT-024 | Tracked bootstrap handoff to external immutable helper artifact       | Integration         | P0       | R-016,R-019,R-020             | Release tree/ACL/handshake/manifest/runtime drift             |
| SW-INT-025 | Helper-only `.work` mutation and final check-to-use replacement       | Integration         | P0       | R-003,R-017                   | Real held handles, junction race, outside sentinel            |
| SW-INT-026 | NFC path grammar, DOS/ADS/8.3 aliases, and hardlink rejection         | Integration         | P0       | R-013,R-017                   | Real NTFS hardlink/ADS/device/alias matrix                    |
| SW-INT-027 | Candidate helper and patched client combined pre-adoption test        | Integration         | P0       | R-013,R-016,R-019             | Real built helper/client handshake and backend operations     |
| SW-INT-028 | Bootstrap source/toolchain locks and byte-identical rebuild ceremony  | Integration/release | P0       | R-006,R-019,R-020             | Two network-free builds plus independent complete-diff Review |
| SW-INT-029 | Suspended process-tree Job lifecycle and zero-descendant drain        | Integration         | P0       | R-012,R-021                   | Background child, helper/parent crash, timeout, late write    |
| SW-INT-030 | Single-operation bounded glob and nonbacktracking grep                | Integration         | P0       | R-012,R-022                   | Hostile regex, max tree/results/output, cancellation          |
| SW-INT-031 | Bootstrap/artifact/storage/config/install root matrix and handoff     | Integration         | P0       | R-003,R-016,R-017             | Pairwise aliases/ACL/identity/replacement matrix              |
| SW-INT-032 | Exact real submodule config and continuous `.gitattributes` absence   | Integration         | P0       | R-004,R-014,R-018             | Actual gitdir config/tree/path plus hostile extras            |

No behavior is duplicated at multiple levels: pure validation remains unit-level,
filesystem ownership/recovery is integration-level, and only clone/install/stdio
and authorized migration publication are E2E gates.

## Failure-path matrix

At minimum, tests cover:

- missing tools, dependency/build failure, oversized or malicious child output;
- submodule URL/commit/dirty state and patch byte/order/apply drift;
- parent `.git` exact submodule allowlist/rollback and selected-storage `.git`
  zero-mutation identity;
- generated checkout creation, build, adoption, and response-loss phases;
- patch file/final-component/ancestor replacement, growth, truncation, link
  substitution, immutable stdin applicability/apply, and root identity drift;
- missing/unreviewed/dirty tracked bootstrap, bootstrap/source/toolchain manifest
  duplicate/extra/noncanonical/drift, wrong release tree, permissive ACL/reparse,
  PDB/host-path/private-byte leakage, network restore, and non-byte-identical
  independent rebuild;
- pre-handshake executable/path/ancestor replacement detection under quiescent
  Setup without claiming zero side effects; post-handshake external attempt ACL/
  reparse conflict, manifest response loss, executable/manifest replacement,
  missing/extra payload, runtime/roll-forward drift, and wrong image ID/hash;
- frozen install, typecheck/build/security-test or real helper/client-combination
  failure, `dist` drift, and crash before every adoption/backup-cleanup phase;
- actual frozen legitimate submodule config plus missing/wrong/extra/duplicate/
  include config, `url.insteadOf`, `core.worktree` drift, submodule update, remote
  upload/receive-pack, credential helper, fsmonitor, trace destination, template,
  hook/filter, frozen-tree or filesystem `.gitattributes` appearance, external transport,
  signing, follow-tags, pager/editor/prompt state, and inherited fake Git/
  System32 paths, with every outside sentinel byte-identical;
- unowned candidate/backup/journal/lock conflicts, extra/duplicate/replaced
  journal records, PID reuse, owner nonce mismatch, and exact response-loss
  replay;
- real Windows file/root/mount/ancestor junction replacement in the
  authorize-to-open/create/write/enumerate windows, held-session root
  replacement, helper missing/stale/wrong-version/crash/timeout, request-ID or
  response-order mismatch, unknown/extra/duplicate protocol fields, and every
  byte/count/depth/path/component limit plus one;
- final check-to-mutation `.work` ancestor/junction replacement for every
  candidate/backup/journal/lock/adopt operation, with Node mutation forbidden;
- pairwise bootstrap/external-attempt/repository/config/envelope/journal/storage/
  legacy/install root equality, containment, case alias, ACL/identity drift, and
  handoff replacement;
- NFC/non-NFC components, empty/dot/separator/colon/NUL/control/wildcard,
  trailing dot/space, ADS, NT/device namespace, DOS reserved name with case and
  extension, real hardlink, and available 8.3 alias, with outside bytes neither
  exposed nor changed;
- process spawns a background/grandchild writer then helper crash, parent crash,
  timeout, cancellation, Job-limit breach, late write, and retry; transition is
  blocked until process/I/O count reaches zero and the outside sentinel is stable;
- glob braces/extglob/malformed class/invalid UTF-8 and max-depth/tree/bytes/
  results/output/cancellation; grep `(a+)+$`, backreference/lookaround, 1,025-byte
  pattern, 250 ms regex timeout, whole-operation 30-second timeout, and retry;
- install config write, Skill backup, MCP config CAS, smoke, activation, rollback;
- Wiki root absent/present, Git/non-Git, non-directory, link/reparse,
  replacement, case alias, nesting, non-writable, active-transaction switch;
- migration-owned runtime create/adopt/ACL/identity, owned-empty rollback, and
  later Install adoption without Wiki or Git drift;
- migration candidate creation, each file copy, manifest write, adoption,
  intent-before-adopt, rename-after-intent, terminal receipt, intent cleanup,
  response loss, retry, and conflict;
- publish displacement/install/marker/terminal/cleanup and recovery-of-recovery;
- Git index contamination, staged/worktree drift, sensitive blob, unexpected
  remote branch, rejected push, and response loss after push.
- private/public Git owner plan or journal drift, remote CAS conflict, rejected
  and response-lost commands, exact retry, and no force/reset/ref deletion;
- private/public publication Git is launched only by an attested helper Job;
  helper/parent crash, timeout, background descendant, and late write drain to
  zero before journal reconciliation or retry;
- envelope wrong-root/nesting, permissive ACL, link/reparse/replacement,
  duplicate/conflicting bytes, backup response loss, and appearance in either
  Git worktree;
- stable candidate real-Install failure/rollback/retry while personal Wiki and
  `.git` identity manifests remain unchanged.
- public candidate parentless commit, MIT/gitlink/tree, fixed commit/tag
  messages, raw-object privacy scan, exact fresh clone, atomic branch+tag
  success, unsupported/rejected push with no ref update, response loss with
  exact both-or-neither reconciliation, and remote OID postflight.

## State invariants

1. At most one formal selected Wiki root and one active transaction exist.
2. `.git` is never beneath a path passed to snapshot, copy, rename, or recursive
   cleanup.
3. A migration success implies source and target canonical manifests match and a
   durable receipt binds both roots and the adopted tree.
4. A publish success implies marker, state/tombstone, formal revision, and
   capability/receipt bindings agree.
5. Setup evidence implies the exact release tree, reviewed bootstrap/source/
   toolchain locks, submodule, patch stack, process limits, tests, Skill, helper,
   and built MCP completed real stdio verification.
6. No installer or migration failure deletes an unowned path.
7. The legacy system remains a rollback source until the retirement gate.
8. A formal migration tree without a terminal receipt is accepted only when an
   exact durable `candidate_verified` intent binds it.
9. Publication success/retry is explainable by one exclusive journal in the
   fixed non-Git-staged owner root and exact local/remote object IDs.
10. A generated checkout can be last-good only when its marker revalidates the
    reviewed tracked bootstrap/source/toolchain roots, byte-identical external
    helper manifest/attempt/handshake runtime, and complete regular/non-link
    build artifact inventories after the real helper/client combination and all
    candidate tests.
11. A run-policy success is explainable by one still-open helper session whose
    root and mount handle identities match startup; lexical checks or PID
    equality alone never establish authority or ownership.
12. No materializer cleanup removes or adopts a deterministic path without an
    exact per-attempt owner record and current filesystem identity.
13. Published Setup's pre-handshake phase is limited to read-only checks and the
    OS bootstrap launch under the explicit TCB; no test claims an unprovable
    zero-side-effect last-check guarantee. After handshake, every external
    artifact/`.work` mutation is explainable by one held helper owner session.
14. Every accepted helper file has link count one and every accepted virtual
    component is NFC-canonical and outside all forbidden Windows alias classes.
15. Every Git command is explainable by one verified executable/toolchain,
    exact real local config allowlist, continuous `.gitattributes` absence, and
    fixed config/environment; no inherited executable/config selector contributes.
16. A command terminal state implies its Job has zero active descendants and
    outstanding I/O; no inventory/adopt/cleanup/retry overlaps a late writer.
17. One glob/grep request maps to one bounded helper operation and one monotonic
    deadline, never a client loop or backtracking regex.
18. Tracked bootstrap and external helper roots obey only the documented
    containment and remain disjoint from config/envelope/journal/storage/legacy/
    install roots across every ACL/identity handoff.

## NFR coverage

| Category        | Requirement                                                                     | Planned validation                                                                          | Evidence                                                                   |
| --------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Security        | Reviewed bootstrap TCB; no post-handshake path/config/process escape or secrets | Reproducibility/Review, real races/aliases, hostile Git/process sentinels, staged-blob scan | Binary/manifests Review plus focused verifier report                       |
| Reliability     | Crash/timeout kills descendants; no acknowledged data loss; retry converges     | Job lifecycle/late-write plus migration/publish/install response-loss matrix                | Zero-process/I/O drain, durable receipts/journals/manifests                |
| Performance     | Bounded helper I/O/glob/grep/process trees; minimum local throughput            | Protocol/tree/regex/Job boundary+1; 8 MiB read/replace warm-up plus three samples           | Fixed deadlines/output/process limits and ≥5 MiB/s each measured direction |
| Maintainability | One root owner per concern; exact public contract; no duplicated upstream fork  | Static boundaries, full tests, patch inventory                                              | Diff Review and capability fingerprints                                    |
| Portability     | Windows 10/11 x64 only in v0.1                                                  | Real PowerShell/cmd/reparse/helper tests                                                    | Windows CI/local report                                                    |
| Privacy         | Tracked bootstrap/locks contain no private or concrete host data                | Binary strings/PDB plus exact public Git path/tree and private remote-tree inspection       | Complete-diff and commit-tree scans                                        |

The private protocol release bounds are 16 MiB/frame, 10 MiB/file payload,
4,096 UTF-8 bytes/path, 255 UTF-8 bytes/component, 64 components, 100,000
enumerated entries, 10,000 discovery results, 50 MiB/discovery request, 4,096
requests/session, 30 seconds/request, and 30 minutes idle/session. Boundary and
`+1` tests are P0. On a local temporary NTFS volume, after one warm-up, each of
three measured 8 MiB sequential helper reads and atomic replacements must meet
at least 5 MiB/s in each direction without weakening any identity check. This
is a release floor, not a general performance claim; broader benchmarking is P3.

Each spawn Job is capped at 128 active processes, 8 GiB committed job memory,
and 4 MiB combined output per command. Git deadlines are 30 seconds,
build/install/typecheck/focused-test deadlines are 30 minutes, and the named
full regression deadline is 60 minutes. Terminal evidence requires zero active
processes and I/O. Glob/grep use one helper call and one 30-second monotonic
deadline. Glob's fixed linear subset is `*`, `?`, whole-component `**`, and
character classes. Grep is nonbacktracking/culture-invariant, limits patterns to
1,024 UTF-8 bytes and regex work to 250 ms, and rejects backreference/lookaround.
Both share depth 64, 100,000 entries, 50 MiB examined bytes, 10,000 results, and
16 MiB response/model-output limits.

## Execution strategy

- Pull request/local gate: all functional/unit/integration tests when under 15
  minutes, typecheck, builds, formatting, diff checks, static ownership checks.
- Release gate: full upstream and MCP test suites, real helper, Skill evals,
  capability verifier, built stdio install smoke, and isolated migration/push
  rehearsals against local bare remotes.
- Manual gated side effects: the actual private Wiki migration/push and public
  SelfOpenWiki push/tag occur only after independent Review. The real selected
  store Install occurs after private push and exact candidate fresh-clone gates,
  but before the public atomic push.

## Quality gates

- P0 and P1 release tests: 100% pass and zero skip; required Windows filesystem
  cases cannot be converted to PASS on unsupported hosts.
- Batch 1A/1B P0 suites run on real Windows with the real built helper and zero
  skip. A mock-only, unsupported-host, or simulated-link result is not evidence.
- The helper gate uses the external owner-verified self-contained artifact,
  exhaustive manifest, real handshake identity/runtime, and real patched client;
  a framework-dependent build, repository `bin` path, or mock handshake fails.
- The tracked bootstrap gate requires its exact public path set, closed
  manifests, no PDB/private/host paths, two byte-identical network-free builds,
  independent complete-diff Review, and explicit acceptance of the documented
  pre-handshake TCB. No binary is accepted from this document-only revision.
- Every configured release command must exit zero. Any observational P2/P3
  result is nonblocking only when explicitly excluded from release commands and
  cannot cover an acceptance, security, compatibility, or rollback requirement.
- Critical/Important Review findings: zero.
- High-risk mitigations: implemented and tested.
- Public schema/tool compatibility: exact.
- Capability evidence: current and smoke-bound.
- Migration manifest: exact match to the private Review envelope.
- Final SelfOpenWiki and Wiki commit path sets: exact; worktrees clean except
  explicitly ignored local runtime.
- `unverified`: native rediscovery after restarting the user's Codex host and
  permanent deletion of the old repository until separately confirmed.

## Estimated test effort

- P0: approximately 35–60 hours.
- P1: approximately 18–35 hours.
- P2/P3: approximately 4–12 hours.
- Total implementation-test effort: approximately 60–110 hours, reduced by
  migrating the existing 600+ test suite and hardened recovery fixtures.

These are planning ranges, not delivery-time promises.
