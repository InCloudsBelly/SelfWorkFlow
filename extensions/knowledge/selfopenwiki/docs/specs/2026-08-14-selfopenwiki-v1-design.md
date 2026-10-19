# SelfOpenWiki v0.1 Design

Status: final-contract candidate
Date: 2026-08-14
Owners: repository maintainer and the user who owns each private Wiki store

This revision supersedes every earlier SelfOpenWiki v0.1 contract package. The
immediately prior `cb19090e…ce4958a` package is superseded by this revision.
Earlier Batch 1 results, including the reported 22/22 tests, generated build,
materialization, and Review conclusions, are historical diagnostics only and
are not release evidence. Implementation remains blocked until this complete
three-document package passes a new independent whole-package Review and
receives explicit user confirmation.

### User-confirmed direct Wiki-root amendment

The selected personal directory is the Wiki root itself, not a parent storage
container. The installer persists one canonical absolute `wikiRoot` and derives
the runtime sibling `runtimeRoot` as the same-parent path
`<wiki-root>.selfopenwiki`. This amendment supersedes the earlier
`<storage-root>\wiki` nesting wherever this document mentions personal storage.
The Wiki root may be an ordinary directory or an embedded Git working tree;
`.git` remains user-owned and outside snapshots and runtime transactions.

## Purpose

SelfOpenWiki is a Windows-first, locally installable knowledge system. It keeps
the official `langchain-ai/openwiki` repository as a pinned, unmodified Git
submodule and places the MCP server, Agent Skill, capability verification,
installation, and private knowledge storage outside that submodule.

The first release preserves the existing nine OpenWiki tool contracts. Its
default write workflow is provider-free: the host creates an isolated writer
subAgent and an independent Reviewer subAgent, while the MCP owns snapshots,
receipts, validation, publication, recovery, and replay. The MCP never creates
models or subAgents internally.

## Confirmed requirements

1. `<repository-root>` is a new public parent repository with remote
   `https://github.com/InCloudsBelly/SelfOpenWiki.git`.
2. `upstream/openwiki` is the official OpenWiki Git submodule, pinned to one
   reviewed commit. Setup never tracks a floating branch.
3. The submodule stays byte-clean. SelfOpenWiki-specific OpenWiki changes are a
   small, ordered, hash-bound patch set applied only to an ignored generated
   checkout.
4. The reviewed predecessor MCP behavior is migrated into an independent
   `self-openwiki` package. Predecessor product naming is not part of the new
   public installation.
5. Setup is one-click on Windows. Installation is separate and explicitly
   chooses one active personal Wiki root.
6. A Wiki root may be an ordinary local directory or a Git working tree.
   Git is optional and SelfOpenWiki does not automatically commit or push
   normal knowledge updates.
7. The user's selected Wiki root and legacy Wiki source are supplied through
   a local, ignored, permission-restricted migration envelope. Existing
   knowledge is migrated without content normalization.
8. The authorized one-time migration creates one dedicated commit in the
   selected private Wiki repository and pushes it to the envelope-bound private
   remote after byte-for-byte verification.
9. SelfOpenWiki v0.1 is one clean initial commit on `main`, licensed MIT,
   pushed to the existing empty remote and tagged `v0.1.0` only after all gates
   pass.
10. The legacy repository and installed MCP/Skill remain untouched until the new
    repository, new install, and migrated Wiki are verified. Permanent
    retirement remains a final destructive checkpoint.

## Repository architecture

```text
<repository-root>\
├─ upstream\openwiki\             official pinned submodule; never patched in place
├─ patches\openwiki\              ordered patches plus canonical manifest/hashes
├─ .work\openwiki\                ignored generated patched checkout
├─ self-openwiki\
│  ├─ mcp-server\                 TypeScript MCP, tests, real stdio smoke
│  ├─ win32-helper\               secure-I/O helper source/project
│  │  └─ bootstrap\win-x64\       reviewed tracked bootstrap exe + manifest
│  ├─ agent-skills\self-openwiki\ host orchestration instructions and evals
│  └─ config\                     contracts plus bootstrap source/toolchain locks
├─ scripts\
│  ├─ setup.mjs                   deterministic build and verification owner
│  ├─ build-win32-helper.mjs      external self-contained helper artifact owner
│  ├─ install.mjs                 local config, Skill, and MCP installation owner
│  ├─ materialize-openwiki.mjs    submodule/patch/generated-tree owner
│  ├─ migrate-wiki.mjs            explicit one-time data migration owner
│  ├─ publish-wiki.mjs            private migration Git publication owner
│  └─ release.mjs                 public commit/tag/atomic-push owner
├─ runtime\                        ignored build capability evidence only
├─ Setup.bat
├─ Install.bat
├─ README.md
└─ LICENSE                         MIT
```

The parent repository owns all integration logic. The submodule owns upstream
OpenWiki. The generated checkout is disposable and must be reproducible from
the gitlink and patch manifest.

## Personal Wiki storage contract

The installer accepts the **Wiki root itself**. The selected directory is the
formal Markdown tree and may also be the user's Git working tree.

```text
<wiki-root>\
├─ .git\                            optional, owned by the user
├─ <Markdown files/directories>\     formal managed tree
└─ (no runtime state is stored here)
<wiki-root>.selfopenwiki\           derived local runtime sibling
```

The derivation is identical for every installation:

```text
wikiRoot    = <selected-absolute-wiki-root>
runtimeRoot = <selected-absolute-wiki-root>.selfopenwiki
```

The snapshot format permits only regular Markdown files and directories;
`.git` must never be part of a snapshot. Publication replaces the Wiki content
under `wikiRoot` while preserving `.git`; runtime transactions stay in the
derived sibling and are never moved as part of publication.

The local installation config is a strict schema stored at
`%LOCALAPPDATA%\SelfOpenWiki\config.json`. It persists only the canonical
absolute `wikiRoot`, schema version, and generation. `runtimeRoot` is derived,
not independently configurable, preventing divergent path bindings.
`Install.bat --wiki-root <absolute-path>` is required for unattended use.
Interactive first installation prompts for a path and offers
`%USERPROFILE%\SelfOpenWikiData` as the explicit default.

If the selected Wiki root is absent, its canonical non-reparse parent must
already exist. Install may exclusive-create only the final Wiki-root leaf, record
its identity, and remove it on failure only while it remains the same owned,
empty directory. Missing parent chains are rejected. An existing root is only
adopted after complete path, ownership, layout, writable, volume, and
Git-worktree checks pass.

Version 0.1 supports one active Wiki root per installation. Reconfiguration
is explicit, generation-bound, and refused while an active transaction or
unreconciled recovery journal exists. Multiple profiles are out of scope.

## Path and filesystem invariants

- Repository root, Wiki root, runtime root, generated checkout,
  tracked bootstrap root, external helper artifact/attempt roots, LocalAppData
  config/envelope/journal roots, patch files, and installed targets are absolute
  and canonicalized.
- Existing ancestors and roots must be regular non-link paths. Windows reparse
  points, junctions, symlinks, ancestor replacement, path case collisions, and
  identity drift fail closed before mutation.
- `wikiRoot` and `runtimeRoot` must be distinct canonical paths on the same
  volume; `runtimeRoot` is the deterministic sibling of `wikiRoot`.
- Runtime metadata cannot be inside `wikiRoot`; formal knowledge cannot be
  inside `runtimeRoot`.
- Setup and installation never modify the selected Wiki root's `.git`,
  `.git/info/exclude`, or tracked ignore files. A Git Wiki root that does not
  already ignore `.selfopenwiki/` receives a bounded warning. The separately
  authorized migration publication may stage one reviewed `.gitignore` entry.
- In the public parent checkout, Setup may create only the exact Git-owned
  submodule metadata required by the pinned `upstream/openwiki` gitlink:
  `.git/config` submodule entries, `.git/modules/upstream/openwiki/**`, and the
  submodule worktree gitfile. Pre/post changes are allowlisted and verified;
  failure rolls back only Setup-owned changes. No other parent `.git` mutation
  is accepted.
- Snapshot reads retain the existing handle-bound
  `lstat → open → fstat → read → post-fstat/lstat` and ancestor-identity checks.
- Patch inputs are captured once through bounded handles. Their file and
  ancestor identities are checked before open, against the open handle, after
  read, before Git consumption, and after candidate verification. Git consumes
  only the captured immutable bytes through standard input.
- When run policy is active on Windows, model-visible filesystem operations use
  the private secure-filesystem helper session described below. A successful
  lexical authorization followed by path-based I/O is never sufficient.
- Runtime and migration temporary files use exclusive creation, bounded input,
  canonical bytes, write-or-verify adoption, and deterministic quarantine or
  cleanup after interruption.

### Root non-overlap matrix

Roots are compared by canonical path and filesystem identity in both
equal/ancestor/descendant directions; case aliases and identity replacement are
rejected. The only permitted containment relations are:

- `repositoryRoot` contains the mutually disjoint pinned submodule, patch,
  generated checkout, repository evidence, source, test, docs, tracked
  `bootstrapRoot`, and embedded public `.git` roots;
- `bootstrapRoot` is exactly
  `<repositoryRoot>\self-openwiki\win32-helper\bootstrap\win-x64` and contains
  only reviewed tracked bootstrap files;
- `wikiRoot` is the selected personal directory and may contain an optional
  user-owned `.git`; `runtimeRoot` is its deterministic same-parent sibling
  `<wikiRoot>.selfopenwiki`;
- `%LOCALAPPDATA%\SelfOpenWiki` contains the config file and the mutually
  disjoint migration-envelope, public-release-journal, and
  `helperArtifactRoot` owner roots;
- `helperArtifactRoot` is exactly
  `%LOCALAPPDATA%\SelfOpenWiki\helper-artifacts` and contains mutually disjoint
  direct `<attemptId>` roots only.

Except for the exact containments above, no root may equal, contain, or be
contained by another. In particular `bootstrapRoot` and `helperArtifactRoot`/
attempt roots are bidirectionally disjoint from the Wiki-root/runtime-sibling pair, LocalAppData
config/envelope/journal, legacy source, installed Skill, Codex config, and all
backup roots. Each root binds canonical path, volume/file identity, non-reparse
ancestors, and its required ACL. Handoffs revalidate both source and destination
identities before and after acquisition; tests cover both directions, case
variants, aliases, and ancestor replacement. The only allowed backup containment
is an exact owner-recorded backup child beneath its documented owner root.

Version 0.1 accepts Git storage/publication repositories only when `.git` is an
embedded canonical non-reparse directory. Linked worktrees, gitfiles,
`commondir`, object alternates, and inherited alternate-object environment are
rejected. Each repository's `gitDir`/`gitCommonDir` identity participates in the
matrix and must be contained only by its own worktree root. Publication owners
may write only the allowlisted index, object, loose ref/reflog, and `FETCH_HEAD`
paths required by their canonical plan; repository config and all other Git
metadata are read-only.

## Bootstrap and runtime separation

The current implementation conflates distinct roots. SelfOpenWiki separates
them:

- `repositoryRoot`: immutable SelfOpenWiki checkout, helper source/owner, built
  MCP, and the reviewed tracked bootstrap executable/manifest only;
- `bootstrapRoot`: public release-authenticated bootstrap TCB under the exact
  tracked repository path;
- `helperArtifactRoot`: owner-verified immutable self-contained helper attempts
  under LocalAppData, separate from repository, Install, and personal storage;
- `openWikiRoot`: ignored patched OpenWiki checkout under `.work`;
- `runtimeRoot`: mutable per-Wiki state at the derived sibling
  `<wikiRoot>.selfopenwiki`;
- `wikiRoot`: formal Markdown tree at the selected Wiki root;
- `evidencePath`: repository build evidence under
  `<repositoryRoot>\runtime\verified-capabilities.json`.

The MCP entry reads the install config path from the fixed
`SELF_OPENWIKI_CONFIG` environment variable supplied by the installer. Inherited
values are not trusted by setup or verification: the installer writes the exact
managed MCP block and the server validates the config, repository binding,
evidence fingerprint, and all roots before exposing writable paths.

The publisher no longer requires `wikiRoot` to be nested below `runtimeRoot`.
It requires the stronger Wiki-root/runtime-sibling relation above, revalidates it under
the existing operation/Wiki locks, and keeps recovery trees under
`runtimeRoot\recovery`. Since both managed roots are siblings on the same
volume, formal-tree displacement and installation remain atomic. Cross-volume
or cross-storage recovery plans fail closed.

## Upstream submodule and patch model

`upstream/openwiki` is frozen to official upstream commit
`355f4f68e71bd024631cdcff7aa871c3e72435da`. The gitlink, patch manifest, tests,
and capability evidence all bind this exact object. Any upstream change,
including a newer `main`, invalidates this contract and requires new Review and
user confirmation.

The patch set contains only the hooks required by the migrated MCP, including
the bounded external home, reasoning effort, restricted shell, and run-policy
integration that cannot be supplied through unmodified upstream interfaces.
Each patch has an ordered path, byte length, SHA-256, expected upstream commit,
and affected-path list in one canonical manifest.

Materialization verifies the submodule gitlink, URL, detached commit, clean
status, patch manifest, and patch applicability before creating an exclusive
candidate. Repository, patch, generated-root, and ancestor identities are
captured and rechecked before every mutation boundary and after verification.
Each patch is opened without following the final component, bounded by declared
length, read through that handle, and accepted only when pre-open path,
handle-before, handle-after, post-read path, and ancestor identities agree. The
validated manifest returns immutable patch bytes plus immutable identity
evidence; both `git apply --check` and `git apply` receive those exact bytes on
standard input and never reopen the patch path.

### Reviewed tracked bootstrap and noncircular handoff

The public release tracks exactly
`self-openwiki/win32-helper/bootstrap/win-x64/SelfOpenWiki.Win32Helper.exe` and
`self-openwiki/win32-helper/bootstrap/win-x64/bootstrap-manifest.json`. The
self-contained executable is the only bootstrap payload. The strict canonical
manifest has schema version 1, domain
`selfopenwiki:win32-helper-bootstrap:v1`, the executable path/bytes/SHA-256,
expected private protocol version, and the bound source/toolchain manifest
roots. Its directory inventory is closed and exhaustive; the manifest itself is
authenticated by the reviewed Git tree rather than self-hashed.

Two additional tracked public locks close the derivation chain:

- `self-openwiki/config/bootstrap-source-manifest.json` uses domain
  `selfopenwiki:bootstrap-source-root:v1` and exhaustively lists relative
  path/bytes/SHA-256 for helper source/project, private-client patch bytes,
  build/materialization owners, and their tracked build inputs. It excludes the
  derived bootstrap/artifact manifests and executable, and excludes its own
  bytes from its domain-separated root.
- `self-openwiki/config/toolchain-runtime-lock.json` uses domain
  `selfopenwiki:toolchain-runtime-lock:v1` and binds exact `dotnet.exe`, .NET SDK,
  Roslyn compiler, reference packs, runtime packs, OS, and architecture hashes.

During the unborn development phase, this exact three-document contract package
plus a subsequent independent complete-diff Review authenticates candidate
bootstrap/source/toolchain bytes; HEAD/index cleanliness is not falsely required.
Batch 1 generates the tracked bootstrap candidate from the exact source and
pinned toolchain using `--self-contained true`, `PublishSingleFile=true`,
deterministic/CI/PathMap inputs, no debug symbols/PDB, and `--no-restore`, then
performs a fresh independent build under the same locked conditions. The two
builds must be byte-identical before an independent complete-diff Review may
accept the binary and all three manifests. For published Setup, the final release
commit/tree and that Review are the authenticity root; a fresh clone accepts
only that exact release tree, clean bootstrap files, and current-user ACL/
non-reparse repository/bootstrap roots.

The unavoidable pre-handshake TCB is the Windows loader, reviewed tracked
bootstrap bytes, clean release/source manifests, and verified Windows/.NET
toolchain. Setup runs as a quiescent exclusive operation. Arbitrary concurrent
same-user code execution or replacement before the first native handshake is
outside the guarantee: the contract requires prelaunch and post-handshake
path/hash/image checks to detect observable drift but does not claim the final
bootstrap check-to-load window has zero external side effects. After the first
successful handshake, every mutation and child launch goes through the helper.

`scripts/build-win32-helper.mjs` uses that attested bootstrap helper to create an
exclusive current-user ACL/non-reparse attempt at
`%LOCALAPPDATA%\SelfOpenWiki\helper-artifacts\<attemptId>\`. The helper copies
the reviewed single-file bootstrap payload handle-relative into the attempt;
that same byte-identical executable is the final helper artifact. Release
verification may also ask the bootstrap helper to run the exact self-contained
publish from the source/toolchain locks, with network restore disabled, but its
binary and inventory must remain byte-identical to the reviewed tracked
bootstrap. No unreviewed rebuild is adopted.

The build owner writes strict canonical `artifact-manifest.json` last with
exclusive write-or-verify semantics, verifies exhaustive layout/hash/ACL/
identity evidence through the helper, and makes the same attempt directory
immutable without a second rename. Its private schema version 1/domain
`selfopenwiki:win32-helper-artifact:v1` binds `attemptId`, reviewed bootstrap,
source/toolchain roots, actual runtime, and the exhaustive single executable
payload. The manifest is separately hash-bound by attestation/marker and does
not self-inventory. Missing/extra bytes, link/reparse, ACL, runtime, or identity
drift rejects the artifact. This cache is build evidence, not Install state, and
no concrete user path appears in public history.

After helper attestation, the production materializer completes frozen upstream
dependency installation, typecheck, build, and the complete focused
secure-filesystem, run-policy, external-home, reasoning-effort,
restricted-shell, and materialization tests inside its exclusive generated
candidate. The candidate helper and patched secure-filesystem client run a real
combined protocol/security test before adoption. The production CLI has no
skip-build or skip-test argument. Exported fixture entry points may inject one
private `verifyCandidate` test port, but the CLI always selects the production
verifier.

The materialization marker binds the reviewed bootstrap/source/toolchain roots,
owner-verified helper artifact directory, artifact-manifest hash, `attemptId`,
exhaustive helper inventory, helper handshake identity/runtime evidence, and strict
regular/non-link upstream `dist` per-file inventory. Only a fully verified
candidate may replace the generated checkout or cause the previous backup to be
deleted. Reuse repeats source, manifest, toolchain, runtime, helper handshake,
`dist`, marker, root, and ancestor checks. `node_modules` is only an unbound
dependency cache and cannot substitute for build evidence. Build/test failure,
artifact drift, interruption, or identity drift preserves the last verified
generated checkout and leaves the official submodule clean.

After attestation, the helper uses Win32 APIs plus the verified toolchain
manifest to derive the Git executable and required Windows system directories;
`PATH`, `COMSPEC`, or `SystemRoot` inherited from the caller is never trusted.
Every Git process receives a newly constructed minimal environment and fixed
temporary directory. No other parent variable survives, including every
`GIT_TRACE*`, `GIT_TEMPLATE_DIR`, `GIT_EXEC_PATH`, `GIT_EXTERNAL_DIFF`, askpass,
SSH, proxy, config, object, index, worktree, pager, editor, signing, credential,
and prompt selector. Each process has a 30-second timeout and 4 MiB combined
output limit.

Before any Git command, the helper holds the real submodule gitdir and `config`
without delete sharing and performs a handle-bound, bounded, strict canonical
parse. The only accepted local keys are exact values for
`core.repositoryformatversion=0`, `core.filemode=false`, `core.bare=false`,
`core.logallrefupdates=true`, `core.symlinks=false`, `core.ignorecase=true`,
`core.worktree=../../../../upstream/openwiki` resolving to the identity-bound
source, `remote.origin.url=https://github.com/langchain-ai/openwiki.git`,
`remote.origin.fetch=+refs/heads/*:refs/remotes/origin/*`,
`branch.main.remote=origin`, and `branch.main.merge=refs/heads/main`.
Duplicate or extra keys and every include/includeIf, fsmonitor, hook, filter,
diff/textconv, credential, `url.*`, remote helper, alternate worktree, submodule
update, upload/receive-pack, archive command, or other executable selector fail
closed. System, global, environment, and non-owner command config are disabled.
For an existing Batch 0 checkout, only Setup's already-approved pinned-submodule
Git metadata owner may create or normalize these exact local keys and must record
the before/after allowlisted bytes; the materializer never normalizes config and
accepts only the exact current allowlist.

Every invocation carries the literal protections
`-c core.fsmonitor=false`, `-c core.hooksPath=NUL`,
`-c diff.external=`, `-c core.attributesFile=NUL`,
`-c credential.helper=`, `-c protocol.allow=never`,
`-c protocol.file.allow=always`, `-c core.pager=cat`,
`-c commit.gpgSign=false`, and `-c tag.gpgSign=false`. Only the already
identity-bound local source may use file transport; no command follows tags or
discovers/pushes extra refs, and upload/archive/receive external commands are
forbidden. At the frozen upstream commit, the `.gitattributes` Git tree object
is absent and the worktree path must remain absent. The helper does not open or
hash a nonexistent file: it verifies tree-object absence, holds/enumerates the
identity-bound parent directory, registers change notification through each Git
operation, and cancels on appearance. The patch manifest also forbids adding the
path. Hostile submodule gitfiles/config, `url.insteadOf`, local fsmonitor, trace
variables, templates, credentials, attributes, filters, follow-tags, and
external helpers cannot touch an outside sentinel.

Candidate, backup, journal, and lock ownership is per attempt. A random
`attemptId` and nonce, plus PID and operating-system process-start identity,
bind every strict canonical owner record. Deterministic coordination paths are
never removed, renamed, adopted, or overwritten until their owner marker,
filesystem identity, hash/layout, and journal phase prove they belong to the
current or exactly replayed attempt. Unknown paths, extra/duplicate JSON keys,
unstable handle reads, replacement, or an unowned last-good/candidate conflict
fail closed. Exact response-loss phases replay only from canonical evidence.
Each marker/journal read is bounded and handle-bound: pre-open path and ancestor
identities, open/fstat/read/fstat, post-read path and ancestor identities, and
canonical re-encoding equality must agree. Its parser rejects duplicate and
extra keys before use. PID equality alone never proves a live owner and PID
reuse remains recoverable.

The published pre-handshake phase performs no repository or `.work` mutation;
its only permitted new filesystem state is the external helper artifact attempt
created after the tracked bootstrap attests. The helper then opens the identity-
bound repository root, creates or adopts `.work` handle-relative if needed, and
holds that no-reparse directory handle.
Every materializer mutation of candidate, backup, journal, lock, or adopted
checkout then occurs through the helper's private owner namespace. Node path
APIs remain read-only preflight and never create, write, rename, remove, or adopt
those objects. The helper creates children handle-relative, holds root, ancestor,
and candidate handles without delete sharing through Git and build activity, and
performs all write-or-verify and response-loss transitions. Therefore a final
check-to-mutation ancestor or junction replacement is rejected by the operating
system or helper before an outside sentinel can change. Artifact cleanup is
also helper/owner-only after strict marker validation; unowned conflicts are
never deleted.

Upstream updates are manual: `Update-Upstream.bat <commit>` creates a reviewable
gitlink/patch-refresh change. Setup never executes `submodule update --remote`.

## Private Win32 secure-filesystem protocol

The revised intrusion budget moves `self-openwiki/win32-helper/**` into Batch
1A and adds a private secure-filesystem client/protocol inside the upstream
patch. Batch 2 migrates the MCP, Skill, configuration, and remaining package
surface but does not independently migrate or redesign the helper. Helper,
private client, patch, materializer, their focused tests, and their generated
evidence form one atomic rollback unit.

The helper protocol is private, strictly versioned, canonical, and host-owned.
Only Setup/materialization/installation may set
`SELFOPENWIKI_SECURE_FS_HELPER` to the owner-verified absolute regular/non-link
`SelfOpenWiki.Win32Helper.exe` inside one immutable artifact attempt directory,
and `SELFOPENWIKI_SECURE_FS_ATTESTATION` to that directory's verified
`artifact-manifest.json`. The parent binds both environment values to the
expected manifest SHA-256 and `attemptId`; the client accepts any artifact
absolute path that passes this owner verification and accepts no path from the
model. Model requests contain virtual relative paths and mount IDs only; they
cannot provide an absolute host path, helper path, root path, or mount path.

Before launch and after handshake, the parent reopens the executable and
manifest handle-bound and verifies path, ancestor, handle identities, bytes,
hashes, ACL, and non-reparse state. Protocol handshake returns the helper
process-image volume/file identity and SHA-256, protocol version, actual runtime
version, toolchain identity, artifact-manifest hash, and `attemptId`; the parent
matches them to its pre-opened executable handle and verified manifest.
Replacement or mismatch fails closed before any backend operation.

At startup the helper opens the canonical backend root and every policy mount
with no-reparse semantics, validates every component by handle, binds volume
and file identities, and holds those directory handles for the entire session.
Every request is resolved relative to those held handles and the permission on
the bound mount. The operation set covers existing-file read, atomic
create/replace/write/edit, directory enumeration, directory creation, remove,
rename, the byte I/O required by upload/download, bounded glob/grep, and a
host-only process-tree spawn operation. Patched OpenWiki must not invoke
path-based ripgrep, fast-glob, fallback path reads, or direct Node child-process
APIs while a run policy is active.

The private spawn operation accepts only host-selected symbolic tool IDs and
bounded argument/input plans for verified Git, `dotnet`, Corepack, pnpm, Node,
and named tests; model input cannot select an executable or host path. The helper
calls `CreateProcessW` suspended, assigns the process to a Windows Job Object
with `KILL_ON_JOB_CLOSE`, breakaway prohibited, active-process limit 128, and
8 GiB job-memory limit, then resumes it. Output remains bounded to 4 MiB combined
per command. Git has a 30-second deadline; build/install/typecheck/focused-test
commands have 30-minute deadlines; the explicitly named full regression has a
60-minute deadline.

The helper holds the parent's process handle and start identity as a watchdog.
Parent death cancels work; helper crash closes the Job handle and kills all
descendants. Timeout first signals cancellation, then terminates the Job, waits
until active-process count and outstanding I/O are zero, and only then permits
inventory, adoption, cleanup, or retry. Late descendant writes therefore cannot
cross a completed/failed command boundary. Once the bootstrap handshake succeeds,
Node never directly spawns Git, `dotnet`, Corepack, pnpm, Node, or tests.

Glob and grep are single bounded helper operations, not client loops consuming
up to 4,096 protocol calls. Glob supports only `*`, `?`, whole-component `**`,
and literal/range character classes. A custom iterative matcher runs without
recursion or backtracking in linear input size; braces, extglob, malformed
classes, invalid UTF-8, and unsupported escapes are rejected. Grep accepts at
most 1,024 UTF-8 pattern bytes and uses .NET
`RegexOptions.NonBacktracking | RegexOptions.CultureInvariant` with a fixed
250 ms compile/match timeout; backreferences, lookaround, and unsupported
constructs are rejected. Each operation has one monotonic 30-second deadline
and cancellation token. It batches enumeration/read internally and enforces
depth 64, 100,000 visited entries, 50 MiB examined bytes, 10,000 results, and a
16 MiB encoded response/model-output cap.

Protocol version 1 uses unique request IDs and ordered one-response-per-request
semantics. Every relative component is valid UTF-8 in NFC and within fixed
bounds. The grammar rejects empty, `.`/`..`, `/` or `\`, colon, NUL/control,
wildcard, trailing-dot/space, ADS, NT namespace/device, and short-name aliases,
plus reserved DOS names `CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, and
`LPT1`–`LPT9` regardless of case or extension. Canonical requests and responses
also reject unknown/duplicate/extra fields, unknown operations, invalid UTF-8,
and response/request mismatch. Limits are release contracts: 16 MiB maximum
frame; 10 MiB maximum per-file payload; 4,096 UTF-8 bytes per virtual path; 255
UTF-8 bytes per component; 64 components; 100,000 enumerated entries; 10,000
glob/grep results; 50 MiB aggregate bytes per discovery request; 4,096 requests
per session; 30-second per-request timeout; and 30-minute idle session timeout.
Boundary and `+1` tests are mandatory. After opening an existing regular file,
the helper checks `BY_HANDLE_FILE_INFORMATION.NumberOfLinks == 1`; directories
must remain members of the held root. New/replacement temporary files must have
link count one, and a multi-link existing target is rejected before read or
write.

Missing, stale, wrongly hashed, wrongly located, or wrongly versioned helper
artifacts; an absent or inherited/conflicting helper environment binding; helper
crash or timeout; root/mount/ancestor replacement; reparse discovery; request
or response drift; bound-handle identity drift; and limit overflow fail closed
without exposing bytes or producing an external write. Run policy remains
optional: when it is absent, official upstream legacy filesystem behavior must
remain byte- and semantic-compatible and the helper is not required.

After the tracked bootstrap handshake, every reproducible filesystem
replacement, reparse, hardlink, ADS, device-name, trailing alias, and available
8.3 alias attack remains release-blocking and must fail closed in real Windows
tests without reading or changing outside bytes. The narrower pre-handshake TCB
and excluded arbitrary same-user concurrency are defined in the bootstrap
section and must not be overstated by test conclusions.

This private protocol does not change a public MCP tool or schema and does not
change the persistent Wiki, transaction, receipt, or migration schemas.

## MCP and Agent contract

The public nine tool names and strict schema-2 contracts remain stable, with the
existing capability matrix as the single compatibility baseline:

- `openwiki_status`;
- `openwiki_setup`;
- `openwiki_prepare_sources`;
- `openwiki_list_skills`;
- `openwiki_query`;
- `openwiki_update`;
- `openwiki_begin_external_update`;
- `openwiki_finalize_external_update`;
- `openwiki_set_default_model`.

The installed server and Skill are named `self-openwiki`. Legacy provider mode
remains explicit and optional. External-agent mode requires no OAuth or model
provider inside the MCP.

The host workflow is:

1. Host calls external begin and receives an immutable writer package.
2. Host creates an isolated writer subAgent and records its execution ID.
3. Host writes only the confirmed candidate paths.
4. Host prepares the frozen Review package.
5. Host creates an independent Reviewer subAgent with a different execution ID.
6. Host submits a strict canonical Review receipt.
7. MCP validates bindings and either requests repair/clarification, aborts on
   confirmed user instruction, or publishes atomically.

SelfOpenWiki never claims native subAgent creation. Its Skill explains the host
responsibility and provides complete failure/resume/replay handling.

## Setup and installation

`Setup.bat` performs build-only work:

1. perform read-only preflight, acquire the documented quiescent/exclusive setup
   condition, and validate the reviewed release/bootstrap/source/toolchain
   manifest bytes, repository/bootstrap ACL, and non-reparse roots;
2. launch the tracked bootstrap through the Windows loader and require the native
   image/protocol/toolchain handshake; this is the only pre-helper process launch;
3. through the attested helper process-tree owner, validate Git, Node, Corepack,
   pnpm, and .NET identities; initialize/normalize only the exact pinned
   submodule metadata and accept only the frozen local config allowlist;
4. create and attest the byte-identical self-contained helper in an exclusive
   external artifact attempt without touching `.work` first;
5. through that attested helper, verify and materialize the patched OpenWiki
   checkout, including frozen dependency install, upstream build, and focused
   helper/client security tests before adoption;
6. build the MCP and remaining repository artifacts through helper spawn;
7. through the same helper process-tree owner, run full upstream/MCP tests,
   Skill evals, and real built-stdio capability verification;
8. activate capability evidence only after every Job is drained and the real
   smoke succeeds.

The repository pins pnpm and JavaScript dependencies. A committed `global.json`
restricts helper builds to stable .NET 9 with an explicit roll-forward policy.
Capability evidence records and binds the exact release tree, tracked bootstrap
and bootstrap/source/toolchain manifests, Node, .NET SDK/runtime packs, actual
helper handshake runtime, Corepack, pnpm, OS, architecture, artifact manifest,
process-tree limits, and exhaustive output inventories. Reuse requires every
field to match; missing/extra files or runtime/roll-forward drift rebuilds or
fails. The bootstrap release gate requires byte-identical independent rebuilds
from the exact pinned inputs. Other supported compiler versions are different
inputs and cannot satisfy or replace that gate.

`Install.bat` performs explicit local side effects only after setup evidence is
current:

1. resolve and validate the selected Wiki root;
2. create/secure the selected Wiki root and its derived same-parent runtime sibling, or adopt valid existing roots;
3. atomically write the local install config;
4. install the `self-openwiki` Skill through a backup/rollback transaction;
5. configure the stable `self-openwiki` Codex MCP block using absolute paths;
6. run real initialize/list/status smoke against a temporary test Wiki root;
7. verify read-only status against the selected personal store;
8. roll back all managed targets on failure.

Setup and install do not commit or push Git repositories, migrate data, install
SelfWorkflow, or delete an older installation.

## Knowledge migration

Task-specific migration values never enter the public SelfOpenWiki history.
Before the real migration, the migration owner creates
`%LOCALAPPDATA%\SelfOpenWiki\migration-envelopes\<envelope-id>\envelope.json`.
The envelope and any backup may exist only beneath that repository-external
owner root. They are forbidden beneath the public checkout, selected Wiki root or
private Wiki repository, legacy source, generated checkout, and installed Skill
tree. The owner root and file are canonical, non-reparse, current-user-only ACL
objects created exclusively and protected by handle/path identity,
write-or-verify, bounded input, and atomic backup rules. Its strict schema
binds the canonical legacy Wiki root, selected Wiki/runtime-sibling roots,
private remote, expected branch/empty state, source manifest, per-file path and
hash inventory, legacy rollback identity, and a list of forbidden private
literals/fingerprints for the public release scan. The user's confirmed values
are supplied to the independent Review out of band; the public documents use
only placeholders such as `<legacy-wiki-root>`, `<wiki-root>`, and
`<private-wiki-remote>`.

`<wiki-root>.selfopenwiki\migration` contains only migration candidates,
WAL intents, terminal receipts, and deterministic quarantine/cleanup state. It
never contains the private envelope or its backup.

Migration is a separate explicit command. It:

1. requires an existing envelope-bound Wiki root and calls the shared Wiki-root
   layout validator; it exclusive-creates/adopts the canonical non-reparse
   derived `runtimeRoot` with current-user ACL while preserving the selected
   Wiki root and recording both identities;
2. requires the exact reviewed private envelope and refuses missing, link,
   permissive, noncanonical, replaced, or hash-drifted envelope bytes;
3. requires the target Git worktree/index to be clean and the selected Wiki
   root to satisfy the envelope-bound adoption state;
4. reads source files through the hardened snapshot owner;
5. copies to an exclusive candidate below `.selfopenwiki\migration`;
6. verifies the exact relative paths, byte lengths, per-file hashes, tree hash,
   and canonical manifest;
7. durably writes and verifies a canonical `candidate_verified` intent before
   adoption; it binds source/target identities, candidate ID, expected formal
   absence, and the full manifest without embedding Wiki bytes;
8. atomically adopts the complete candidate content into the selected Wiki root
   while preserving its `.git` directory;
9. on restart, uses the intent plus an exact formal-tree snapshot to distinguish
   completed adoption from conflict, then atomically writes the terminal
   receipt before removing the intent;
10. leaves the old source untouched. Failure removes a newly created runtime
    root only while its recorded identity is unchanged and it is empty; any WAL,
    candidate, receipt, or quarantine makes it durable recovery evidence. The
    later Install only verifies and adopts this initialized layout.

For this authorized migration only, the release phase stages the exact
repository-relative set `.gitignore` plus the envelope-bound Wiki-root relative
Markdown paths, scans staged blob bytes,
compares the staged manifest to the receipt, creates one dedicated migration
commit, verifies its path set/tree, and pushes `main`. Any remote divergence,
unexpected staged path, sensitive-content rule match, or byte drift stops before
commit/push. Ordinary SelfOpenWiki updates never perform these Git operations.
The public SelfOpenWiki staged blobs and candidate commit tree are additionally
scanned against the envelope's forbidden literals/fingerprints; the envelope
itself and all private migration bindings are forbidden public paths.
The tracked bootstrap executable and its three bootstrap/source/toolchain
manifests are an explicit public release path set. Release rejects PDB/debug
paths, concrete host paths, credentials, private-Wiki bytes, unlisted payloads,
or mismatch with the independently reviewed reproducibility hashes.

The initial commit message is the fixed literal
`feat: release SelfOpenWiki v0.1.0`; the annotated tag message is the fixed
literal `SelfOpenWiki v0.1.0`. Before atomic push, the release owner parses and
scans the raw commit and tag objects, verifies target/tree/parent relations,
rejects forbidden private values in metadata, and permits no alternate
user-supplied release message.

## Git publication owners

Only `publish-wiki.mjs` may create/push the authorized private migration commit,
and only `release.mjs` may create the public initial commit, annotated tag, and
atomic public push. Both accept strict canonical plans, invoke fixed `git`
commands only through an attested helper's bounded symbolic spawn plan and Job,
bind repository/remote/branch identities and expected refs, use exclusive write-
ahead journals, and reconcile response loss by fetching exact remote object IDs.
The model and Node owner cannot choose an executable or host path. They never
force, reset, or delete user refs. Conflict or uncertain partial state preserves
the journal and fails closed. Production performs no Git mutation outside these
owners; tests inject only the owner's plan/result seam and use the real helper
plus local bare remotes for success, rejection, response loss, retry, descendant
drain, and both-or-neither ref invariants.

Private publication journals live only at
`<wiki-root>.selfopenwiki\migration\publish\<publication-id>\journal.json`.
Public release journals live only at
`%LOCALAPPDATA%\SelfOpenWiki\release-journals\<repository-id>\<release-id>\journal.json`.
Both roots use canonical non-reparse current-user ACL objects, exclusive
creation, bounded canonical schemas, identity checks, and write-or-verify phase
CAS. Phases bind plan, repository/Git roots, expected refs, created object IDs,
push attempt, fetched reconciliation, and terminal receipt. Journals never enter
a staged tree and are deleted only after terminal evidence is durable.

The owners construct blobs/trees/commits/tags through canonical plumbing from
verified bytes rather than path-based clean/smudge filters. Their fixed process
environment clears inherited Git directory/worktree/index/object-alternate,
editor, pager, signing, and prompt variables; disables hooks and push
verification hooks; and uses no shell. Local config is treated as untrusted
input and cannot select hooks, filters, alternates, signing, or interactive
programs.

## Failure and recovery semantics

- Setup preserves the last verified generated checkout, immutable verified
  helper artifact, reviewed tracked bootstrap/source/toolchain bytes, and
  evidence. A failure before first handshake stops in the documented bootstrap
  TCB state for manual inspection; it does not claim race-free automatic cleanup.
- Materializer interruption preserves every unowned path, the prior last-good
  checkout, and every verified helper artifact. The generated checkout is
  adopted only while bound to an already verified immutable helper attempt.
  Only the helper/owner may clean an unverified artifact or `.work` object after
  exact marker, identity, layout, ACL, and hash validation; an unowned conflict
  is preserved and fails closed. Exact response-loss phases replay through the
  held owner namespace.
- Helper/parent crash or command timeout closes/terminates the Job and waits for
  zero descendants and I/O before any inventory, cleanup, adoption, or retry;
  late writes invalidate the attempt.
- Install preserves or restores the previous config, Skill, and MCP block.
- A partial migration remains quarantined under the exact migration ID and can
  be safely removed or resumed; it never becomes the formal tree.
- A crash after formal adoption but before the terminal receipt replays the
  durable `candidate_verified` intent, verifies the exact formal tree, writes
  the terminal receipt, and then removes the intent without copying again.
- Publisher crash phases retain the existing journal/marker/tombstone recovery
  guarantees under the new sibling-root invariant.
- Reconfiguration, migration, and publication share the established ordered
  operation/Wiki locking boundary. No writable package is exposed while startup
  recovery is unresolved.
- Error messages are bounded and never include Wiki bytes, secrets, environment
  dumps, or arbitrary child output.

## Public documentation contract

The root README is a release-blocking interface. It explains Windows source
prerequisites, `Setup.bat`, `Install.bat`, interactive and unattended external
storage selection, Git and non-Git stores, the exact nine-tool MCP surface,
Skill/MCP host configuration, the host-owned isolated writer and independent
Reviewer subAgent flow, explicit legacy-provider behavior, recovery, and the
rule that ordinary knowledge updates never commit or push. Examples use only
placeholders and synthetic values; private envelope bindings are forbidden.

## Compatibility and non-goals

Preserved:

- public tool names and strict schemas;
- external transaction and recovery formats unless a path-binding version is
  required and explicitly migrated within this release;
- provider-free external-agent behavior;
- explicit legacy provider behavior;
- Windows path security and capability evidence model.
- official legacy OpenWiki filesystem behavior whenever run policy is absent.

Not in v0.1:

- multiple active Wiki profiles in one install;
- Linux/macOS installation;
- hosted or team databases;
- automatic Git commit/push for normal knowledge updates;
- automatic upstream tracking;
- internal MCP model/subAgent creation;
- editing official submodule bytes;
- deleting the legacy repository before final migration/install acceptance.

## Alternatives considered

### Fork OpenWiki directly

Rejected. It mixes upstream history, private integration, and release ownership,
making upgrades and provenance harder to review.

### Vendor a copy of OpenWiki

Rejected. It loses gitlink identity and encourages silent drift.

### Use the entire Git metadata tree as the formal Wiki

Rejected as a whole-root atomic publication target. The selected Wiki root may
be a Git worktree, but `.git` is never part of a snapshot, candidate, rename, or
publication path; only the Markdown worktree paths are adopted and published.
The runtime sibling remains beside the selected Wiki root.

### Point `runtime\wiki` at an external junction

Rejected. Snapshot and publication deliberately reject links/reparse paths; a
junction would reopen path-substitution attacks.

### Store all runtime data in `%LOCALAPPDATA%`

Rejected for v0.1. A Wiki on another volume would break the atomic rename model.
Keeping `.selfopenwiki` beside `wiki` preserves same-volume recovery while the
small install selector config remains in `%LOCALAPPDATA%`.

## Intrusion budget and rollback

Approved high-impact changes are limited to:

- new parent-repository build/install/migration ownership;
- two bounded Git publication owners and their private/runtime and LocalAppData
  journals for the explicitly authorized first releases;
- root separation in MCP bootstrap and publisher path validation;
- product/package/Skill/helper rename from the predecessor to SelfOpenWiki;
- official OpenWiki gitlink plus minimal patch materialization;
- the public tracked self-contained bootstrap executable/manifest,
  `bootstrap-source-manifest.json`, and `toolchain-runtime-lock.json`. This is a
  high-intrusion first-release TCB accepted only because no narrower noncircular
  native bootstrap exists; it contains no private data and requires new user
  confirmation after whole-package Review;
- the remaining `self-openwiki/win32-helper/**`, upstream patch's private
  secure-filesystem client/protocol, `scripts/build-win32-helper.mjs`, external
  immutable helper artifact owner, materializer/process-tree ownership/recovery,
  and their root/generated focused tests as one Batch 1 atomic rollback unit;
- local installation configuration and transactional Codex/Skill setup.

Batch 2 excludes helper migration and owns only the remaining MCP, Skill,
configuration, and package rename. No public MCP schema, persistent Wiki schema,
new provider/model path, hosted service, multi-profile state, or tracked
submodule source edit is approved. If implementation requires one, this
contract and its Review become invalid.

Failure handling is checkpoint-specific:

- before formal migration adoption, remove only exact owned empty candidates;
- after adoption, retain the formal Wiki, source, intent/receipt, and exact
  manifests for replay;
- after private push, retain the immutable private commit and remote ref; this
  task never deletes or rewrites it;
- after local public commit/tag creation, retain their objects and release
  journal for exact retry;
- a failed real Install restores its transaction backup, while a successful
  Install is retained on later public-push failure together with the still-valid
  legacy surface;
- atomic public push resolving to neither ref retains local state for retry;
  resolving to both exact refs is success; any one-ref or mismatched state is
  `restore_required` for manual review and triggers no automatic remote change.

The private commit, Install receipt, public candidate/tag IDs, and remote
reconciliation are cross-bound in the publication journals. The first public
release has no prior commit; any correction is a separately reviewed additive
commit, never a history rewrite. The legacy source and installed surface remain
the operational rollback until the user separately confirms retirement.
