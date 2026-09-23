# SelfWorkFlow

SelfWorkFlow is a code-first, vendor-neutral Agent workflow. Its default product is
a compact operational core, not the repository's complete maintenance and release
machinery.

## Windows one-click installation

After cloning the repository, run this from Explorer or a terminal:

```bat
Install_SelfWorkFlow.bat
Install_SelfWorkFlow.bat -Profile knowledge
```

The installer checks or prepares the repository Python environment, initializes
the pinned Git Submodules, builds the pinned Graft CLI with Node >=20, and packages only the curated Matt Pocock Skills
listed in `dependencies/locks/matt-pocock-skills.lock.yaml`. The upstream
`grilling` and `grill-me` are installed with that curated set. Full automatically
routes to `grilling`; Deep routes to `grill-me`, whose upstream workflow runs the
deeper `grilling` frontier. Light remains explicit-only.
SelfWorkflow does not require, install, or default-route to Superpowers.

The installer verifies and builds only the pinned Graft submodule. It never scans
disks for another code graph or binds an alternate provider. Project graph
initialization is lazy and task-scoped; an explicit update is required before
rebuilding a stale graph.

The Matt Skills source is the repository's fixed
`dependencies/upstream/matt-pocock-skills` Gitlink. Upgrades are explicit source
changes and require refreshed lock hashes and tests; installation never follows
the upstream branch automatically. Before publishing workflow files, the installer shows the generated plan
and requires the exact confirmation `APPLY`. It uses a write-ahead transactional
installer, verifies the manifest, and rolls back the current publication if a later
verification step fails. Detailed diagnostics and machine-readable artifacts are written under
`%LOCALAPPDATA%\SelfWorkFlow\logs\install-<timestamp>`. Logs do not include an
environment dump or credential values.

Codex receives a hash-bound copy of only the selected Matt Skill directories plus
the source lock. A pre-existing user-level Superpowers installation remains
untouched and unmanaged; it is used only when the user explicitly asks for it.
Doctor and install plans hash only SelfWorkFlow's exact managed targets, so
unrelated Codex sessions, databases, executables, logs, caches, large files and
plugin junctions are not read or claimed as installer state. Unmanaged target
directories remain hard conflicts. A failure to delete an already verified Provider rollback receipt
is reported as pending cleanup and does not tear down a committed installation.
Restart Codex after a successful install. The restart and native Skill
activation remain `unverified` until exercised in the real host.

For unattended sandboxing or diagnostics, inspect all parameters first:

```powershell
.\scripts\install-selfworkflow.ps1 -Help
```

## Default workflow

Ordinary work loads the installed root `WORKFLOW.md` and only the capability
needed for the current stage:

```text
classify briefly
-> locate the owning layer
-> Light: bounded core Design; Full: Matt grilling; Deep: Matt grill-me with a deeper frontier
-> SelfWorkflow Plan; Full/Deep behavior changes require TEA test design, and modifying Full/Deep tasks require pre-implementation Review
-> Matt TDD RED/GREEN for behavior changes; diagnosing-bugs may compose with it
-> implement only the approved smallest safe change
-> review the complete task package; Full/Deep use independent Standards + Spec axes
-> execute package-bound verification and rebuild the package before Complete
```

The conceptual sequence is `Discover -> Capability Check -> Classify -> Design ->
Plan -> Implement/Debug -> Review -> Verify -> optional Knowledge -> Complete`.

Ponytail replaces the former Caveman code-minimization layer. It is loaded only
for routed coding/engineering work: `ponytail` is the default code lens,
`ponytail-review` supplements over-engineering review, `ponytail-audit` is
explicit-only, and `ponytail-help` is a one-shot help card. The selected Skills
come from the pinned `dependencies/upstream/ponytail` submodule; upstream hooks,
daemons, plugin files, environment variables, and global config are not copied
or activated. The route accepts task-scoped `lite`, `full`, `ultra`, or `off`,
with `full` as the code-task default. Non-code work does not load Ponytail.

For ordinary work, thin Agent adapters follow `WORKFLOW.md` directly and do not
manufacture a PlanGraph or RunLedger. `selfworkflow resolve` is an opt-in
contract-management interface for an explicit V3 request or a conforming Host
that can provide fresh capability evidence; when used, the Host refuses paused
plans, loads only current-stage modules, and records runtime facts in a
plan-bound RunLedger. Automatic or explicit Grill remains subject to the
applicable independent design/integrated Review. The Host verifies typed Grill completion, clean-summary
provenance, the repository review-policy hash, and plan/attempt/summary-bound fallback
authorization before that gate can pass. Knowledge persistence is optional and confirmation
gated. The explicit `knowledge` profile provides the generic knowledge contract
and optional backend adapters; ordinary
code tasks and the default `core` profile do not load it.

Every landed change, including a document-only delivery, receives post-landing
Review and verification. Intermediate design and plan documents are reviewed
by their Gates and then continue into implementation. Strictly local,
easy-to-rollback minor decisions may adopt an independent SubAgent recommendation
through a validated `decision-record`; all critical decisions still return to
the user.

Projects may opt into additional Review expertise with a checked-in
`.selfworkflow/review.yaml`. It is an explicit, hash-bound manifest of
project-relative Skill files. A missing profile is harmless and is not replaced
by directory scanning. A Host is given the project root and conversation ID;
on the first matching Full/Deep code Review it creates the bound session and
passes the same ordered manifest and verified Skill bytes to both independent
Standards and Spec reviewers;
the Host code route uses an explicit `independent-code-review` payload and receipt
contract, while the Grill design route remains `independent-design-review`;
required Skill drift or an unavailable independent context is `unverified` and
cannot be presented as a passed Review. The profile cannot override protected
workflow rules. The schema and read-only validator are in
`schemas/project-review-profile.schema.json` and `selfworkflow project-review
validate --project-root <project-root>`.

Review models are configured per Agent in the machine-local
`%LOCALAPPDATA%\SelfWorkFlow\config\review-models.local.yaml` file. Missing
Agent entries pause Review for user configuration; no model alias or reasoning
level is inferred. Use `selfworkflow review-model status --agent <id>` to
inspect a selection and `selfworkflow review-model set --agent <id> --model
<model> --reasoning-effort <effort> --confirm` to save a confirmed default.
One-time overrides remain in the current Review dispatch only; they are never a
generic SubAgent default and are not propagated to other SubAgents. The selected value is
payload-bound, and the Host must return the same value in its dispatch
observation; a mismatch fails closed. Model execution is still host-attested
and must not be claimed from configuration alone. The file is machine-local
and must not be committed.

Runtime profiles are closed and deterministic:

- `core` (default): compact workflow, code-quality sources, stage routing, and thin
  Agent adapters;
- `knowledge`: `core` plus the generic Knowledge contract and optional backend
  adapters. The SelfOpenWiki adapter/Skill is one explicit option and requires
  an external Wiki root; the generic workflow does not depend on it;
- `maintainer`: the complete governance, installation, release, and extension
  snapshot.

The `core` and `maintainer` artifacts include the explicit V3 contracts,
bounded TEA candidates, C++ routing, `cpp-core` and Provider descriptors. The
repository-scoped Provider management entry is deliberately not packaged into
the static Agent snapshot. These files are loaded only by matching V3 requests; machine
configuration, logs, indexes and caches are never packaged.

## Default Graft code provider

Graft is the default local code-reading Provider and is pinned at
`dependencies/upstream/graft` with `dependencies/locks/graft.lock.yaml`. The
installer verifies the gitlink, source tree, package/lockfile/license hashes,
then runs `npm ci --ignore-scripts`, a controlled native-package rebuild,
`npm run build`, and a CLI runtime smoke test. The installed Agent query path is
the official Graft MCP; SelfWorkFlow does not reimplement Graft's graph or query
protocol.
The project graph is initialized lazily when a global map is explicitly
confirmed for creation or update; Deep Topic binding does not initialize it. The
installer publishes the official MCP launcher at
`%LOCALAPPDATA%\SelfWorkFlow\bin\graft-mcp.cmd`, which starts
`graft mcp <current-working-directory>` so each project keeps its own `graft/`.
The SelfWorkFlow Host CLI at
`%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd` is retained for lifecycle
checks, explicit maintenance, and recovery. After an Agent writes code,
SelfWorkFlow triggers the official Graft structural update; ordinary reads do
not run Deep, while a code write in a conversation bound to a Topic continues
automatically in the same Worker call into that Topic's scoped Deep. It does not
run a second graph implementation, watcher, or daemon. A Deep build uses the current Agent model through
a one-shot loopback Codex bridge. Before any graph decision,
`graft-preflight` first verifies
the real Provider runtime (`--version` and the required commands); an
existing `graft/` directory alone is not evidence that Graft is usable. See
`docs/providers/graft.md`.

Official `graft init` can register Graft's native MCP and hooks. SelfWorkFlow
uses the official MCP as the primary query path and keeps only a thin lifecycle
gate around it; the launcher is bound to the current working directory rather
than a fixed project path.

```powershell
node dependencies/upstream/graft/dist/cli.js build D:\project --no-gitignore --no-ignore
node dependencies/upstream/graft/dist/cli.js map D:\project --json --no-refresh

%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd provider graft-preflight --project-root D:\project
%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd provider graft-sync --project-root D:\project --conversation-id <current-conversation-id> --changed-path Source\main.cpp
%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd provider graft-ensure --project-root D:\project --conversation-id <current-conversation-id>
%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd provider graft-deep --project-root D:\project --conversation-id <current-conversation-id>
```

The active Host automatically injects the current conversation model and
reasoning effort for this internal command; users do not choose them. If the
Host cannot provide both values, the command fails closed. Topic and official
Graft manifests record only the last run; they are never defaults.
These values are historical; they are not defaults.

When automatic Topic refresh cannot complete, the Worker returns a visible
`partial`/`unverified` result with `retry-topic-deep`. The conversation may
continue, but the workflow must not silently replace Graft with `rg` or report
the Topic as fresh.

## Code reading

Graft is the only code-graph Provider. The official MCP supplies structural
queries and freshness; the workflow verifies its project binding before use.
If Graft is missing, stale, unavailable, or does not cover a target, the
workflow marks that limitation and falls back to `rg` for exact text and
uncovered files. `rg` is not structural evidence and does not replace a
required fresh Graft result. See
`docs/providers/graft.md`.

For a code task, an existing fresh global non-Deep Code Map is used automatically;
no explicit opt-in or Topic binding is required. `graft-ensure` checks it before
reading. A stale map requires user confirmation before update; a missing map is
not initialized automatically. After an Agent code write, including rollback,
delete, or rename, `graft-sync` updates the affected global map paths. Deep Topic
freshness/builds are never checked automatically; they require an explicit user
request and an existing binding.
A missing or failed capability is reported explicitly; it is not silently
replaced with `rg` as structural evidence.

## Current capability status

- Deterministic workflow, Pipeline, Catalog v2, PlanGraph/RunLedger validation,
  Git index policy, routing, stateless task resolution,
  Skill absorption, adapters,
  optional generic Knowledge slots, runtime build, and
  sandbox transaction install/verify/rollback are implemented and automated-tested.
- V3 schemas, versioned Catalog/Pipeline loaders, immutable PlanGraph/RunLedger
  validation, bounded selector kernel, TEA candidate routing, C++ content-addressed
  routing, the Matt Skills foundation, the fail-closed post-Grill contract gate,
  Graft source binding, non-executing source inspection, write-ahead
  CAS-protected installer and content-addressed maintenance planning are implemented
  and automated-tested. The checked-in V3 request intentionally remains `paused`
  until a conforming Host supplies fresh supported evidence.
- OpenSpec routing, a generic specialist Review selector/aggregate execution path,
  and Heavy/Forensic adapters and dependencies remain outside this release.
  Review dispatch now has a fail-closed ephemeral
  SubAgent contract: the Host must provide the selected model, a hash-bound
  complete code/plan package, project-primary/generic-supplementary Skill
  precedence, structured
  result, Markdown summary, and cleanup evidence. Fake-port tests do not prove
  native support; each vendor Host must still provide fresh capability and
  model-execution evidence before being marked supported.
- Codex CLI/Desktop, Claude Code, Cursor, and OpenCode remain
  `experimental-unverified`; Copilot is `instructions-only` and unknown Agents use
  `adapters/unknown/BOOTSTRAP.md`.
- The generic knowledge lifecycle and optional SelfOpenWiki adapter are packaged.
  Backend capability evidence and current-host activation remain unverified until
  exercised against the selected backend.
- Installer manifests currently record `securityStatus: unverified`; do not use the
  sandbox result as proof of production ACL hardening.
- Native login, model/OAuth calls and formal global installation remain unverified
  until their versioned evidence exists.

The detailed design-to-implementation audit is recorded in
`docs/reviews/2026-08-09-v3-design-implementation-conformance.md`.

## Build and sandbox installation

```powershell
.venv\Scripts\python.exe -m selfworkflow.cli build --repository . --version 0.1.0.dev0 --profile core --output build\runtime
.venv\Scripts\python.exe -m selfworkflow.cli install plan --artifact build\runtime --agents-root <sandbox-agents> --codex-root <sandbox-codex> --state-root <sandbox-state> --version 0.1.0.dev0 --output build\install-plan.json
```

Use `--profile knowledge` or `--profile maintainer` only when the requested task
actually needs those boundaries.

Knowledge backends are selected explicitly and own their installation and MCP
binding contracts. SelfOpenWiki, for example, validates an external Wiki root
before its own Install flow; SelfWorkFlow does not guess a backend command,
write a Wiki, or modify a Wiki repository.

Resolve a complete static workflow plan without starting a long-lived orchestrator:

```powershell
Copy-Item build\runtime\workflow\resolve-request.example.json build\request.json
# Update the copied request with observed C/R and fresh capability evidence.
.venv\Scripts\python.exe -m selfworkflow.cli resolve --catalog build\runtime\catalog.json --request build\request.json
```

The result is a hash-bound PlanGraph containing static stage applicability,
selected modules, Gates, and failure owners. Runtime results are recorded
separately. Validate a RunLedger with the exact PlanGraph and original capability
snapshot using `selfworkflow ledger validate --ledger <ledger.json> --plan
<plan.json> --capability-snapshot <snapshot.json>`. Capability evidence is not
authentication or native-host proof. `paused` must not be silently promoted.

Review the complete plan and its `planHash`, then pass that exact hash to
`install apply`. Use the returned manifest for `install verify`; use the returned
transaction path for `install rollback-plan`, review its hash, then run `install
rollback`. Plans bind the exact snapshot files, mapped Skill files, current pointer,
Codex `AGENTS.md`, and StateRoot current manifest. They fail on managed-target or
artifact drift, damaged managed blocks, reparse targets, nested install roots,
unmanaged Skill collisions, or unmanaged version snapshots; unrelated runtime files
do not invalidate a confirmed plan.

## Development environment

Run these commands from the repository root in Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements-dev.lock.txt -e .
```

The lock file pins both direct development dependencies and their transitive
dependencies. The editable package uses the `src` layout.

## Tests and verification

Run the complete unit suite:

```powershell
.\scripts\test.ps1
```

The test script resolves the repository from its own location, temporarily
uses that directory for discovery, and restores both its location stack and
`PYTHONPATH`. It therefore works when invoked from another current directory.

Run one exact dotted unittest:

```powershell
.\scripts\test.ps1 -Test tests.test_smoke
```

The verification wrapper implements scoped automated suites:

```powershell
.\scripts\verify.ps1 -Suite unit
.\scripts\verify.ps1 -Suite conformance
.\scripts\verify.ps1 -Suite installer
.\scripts\verify.ps1 -Suite behavioral
.\scripts\verify.ps1 -Suite automated
```

Native verification returns `requires-user-action` with its own nonzero exit code.
Consequently, `all` reports an incomplete release while native evidence remains
unavailable, even when every automated suite passes.

## Codex CLI bootstrap

`scripts\bootstrap-codex-cli.ps1` is Windows-only. `Discover` validates a
portable Node/npm toolchain, performs one isolated metadata query, and emits a
complete `planSchemaVersion: 2` JSON plan. Save and review that exact plan
before Apply:

```powershell
$planJson = .\scripts\bootstrap-codex-cli.ps1 `
  -Mode Discover `
  -ToolchainRoot <approved-toolchain-root>
[IO.File]::WriteAllText(
  <absolute-confirmed-plan-path>,
  $planJson,
  [Text.UTF8Encoding]::new($false)
)
$plan = $planJson | ConvertFrom-Json

.\scripts\bootstrap-codex-cli.ps1 `
  -Mode Apply `
  -ConfirmedPlanPath <absolute-confirmed-plan-path> `
  -ConfirmPlanHash $plan.planHash
```

Apply requires both confirmation parameters. It locks and reads the plan,
validates its exact shape, recomputes its canonical hash, compares the embedded
and parameter hashes, and verifies every planned toolchain identity before it
compiles a Win32 helper, creates a directory, changes an ACL, or starts an
external process. Old hash-only Apply and plan v1 fail closed. Apply does not
repeat the metadata query.

The install root remains
`%LOCALAPPDATA%\SelfWorkFlow\bootstrap\codex-cli`. `ToolchainRoot` must descend
from the pre-existing
`%LOCALAPPDATA%\SelfWorkFlow\bootstrap\toolchains` anchor. Discover never
creates or changes that anchor. The chain from `%LOCALAPPDATA%` through the
toolchain, and every deterministic inventory entry, must be canonical,
non-reparse, owned by the current SID or SYSTEM, protected from ACL inheritance,
and free of dangerous access for other principals. The plan binds absolute
`node.exe` and `npm-cli.js`,
their hashes, the complete tree inventory/hash, fixed arguments, trusted cwd,
exact environment whitelist, explicit registry/user/global/cache settings,
expected DACL, and all side-effect/uninstall boundaries.

npm is started through `ProcessStartInfo` using the absolute Node executable
and npm JS entrypoint. Shell execution is disabled; the inherited environment
is cleared before the exact whitelist is added. `NODE_OPTIONS`, `NODE_PATH`,
extra CA, proxy/TLS, token, inherited npm config, PATH lookup, user npmrc, and
project npmrc cannot alter the planned invocation. External `icacls` is not
used: .NET writes the DACL and an independent filesystem read verifies the
exact protected current-user/SYSTEM rules.

The manifest has two validation layers. JSON Schema handles exact static shape
and formats. `scripts\lib\bootstrap-manifest.ps1` independently checks exact
top/package properties, `schemaVersion: 2`, canonical root, current SID/SYSTEM
DACL, confirmed plan hash, package-tree hash, package metadata, and actual
SDDL. It records `expectedCliVersion` and
`cliVersionVerification: "not-run"`; the bootstrap never executes the newly
installed Codex Agent. Real process startup, login, and model calls belong to
native acceptance.

Python `jsonschema` is used by tests to verify the checked-in schema; it is not
embedded in the PowerShell bootstrap. Production uses the schema-aligned exact
semantic validator before writing and again after reading the atomically moved
file. Publication cleanup is covered by **module-level deterministic fault
injection + real filesystem atomic publish**: an isolated PowerShell test
process replaces only the in-process semantic function, lets the pre-write call
pass, observes the real moved file during the post-move call, then throws and
verifies removal of the formal and temporary files. This is not claimed as a
concurrent-attack test.

Toolchain and installed-package tree hashes use one canonical algorithm: sort
the complete `path/type/sha256` inventory, serialize it as canonical JSON, and
hash that JSON with SHA-256. Reparse points and paths escaping the canonical
root are rejected before an inventory is accepted.

Installed-package verification takes independent tree snapshots before reading
package metadata and after validating package/lock identity. A mismatch fails
closed; the latter hash is bound into the manifest and recomputed by semantic
validation before and after atomic publication. Ordinary package-tree files do
not retain handles between snapshots, so this does not eliminate mutation by
the current SID, SYSTEM, or OS-privileged actors after a final check.

### Security boundary

Held directory handles provide a concrete guarantee for already opened
ancestors: while those handles remain open, another process cannot rename or
delete those directories, and identity/reparse checks detect a changed path
mapping. Directory-chain, confirmed-plan, Node, and npm entry handles remain
open through the child process. Ordinary inventory files are locked only while
their hashes are read; final rehash plus owner and protected-DACL checks bound
their verification, but no full-tree handle set remains open.

This is not an absolute same-SID adversary guarantee. Windows directory
creation and subsequent handle acquisition are not atomic for previously
missing install components. Current-SID, SYSTEM, or OS-privileged processes can
also race any toolchain or installed file that could not remain individually
locked after the final inventory check. The plan reports these limits as
`unverified`; stronger isolation requires another principal or sandbox. Real
npm/network/Codex behavior also remains unverified in Task 1.

Tests run the system's real `node.exe` with
`tests\fixtures\bootstrap\fake-npm-cli.js` inside a protected temporary
toolchain. They use no network and do not run real npm or Codex.

## Reconstructed baseline test evidence

This is a **reconstructed baseline, not a replacement for original session
logs**. The baseline was unpacked from
`f5b6fd41717879da4e2e86f35f94ff389079fa9d` into a new system temporary
directory. Only `tests\__init__.py`, `tests\test_smoke.py`,
`tests\test_bootstrap_cli.py`, and the then-current (now-retired) command
fixture as recorded by source commit
`11f6c42e9b59664965d867f515e023c4a671e050` were then copied into it; no
production implementation from that commit was copied. That test snapshot has
23 bootstrap tests and 15 smoke tests (38 total).

The locked dependency directory was exposed to the system Python through
`PYTHONPATH`, which does not process the editable-package `.pth` file.

The reconstructed baseline command, run from the unpacked base directory, was:

```powershell
$env:PYTHONPATH = '<WORKTREE>\.venv\Lib\site-packages'
C:\Python314\python.exe -m unittest discover -s tests -t . -v
```

- UTC: `2026-08-07T06:43:45.8412378Z`
- Exit code: `1` (Red; `Ran 38 tests in 2.655s`)
- Redacted output SHA-256:
  `367d19e3390747cb118882d571191fa4ed8231a45e202e769cbd079c4107c6cf`

The corresponding 38-test source-snapshot Green command, run from the
repository root, was:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

- UTC: `2026-08-07T06:44:04.1869116Z`
- Exit code: `0` (Green; `Ran 38 tests in 23.482s`)
- Redacted output SHA-256:
  `3c5a7bba6fcce0b2d76958824985e15a6dfa4c9fad959fa54d3f943d665272cf`

For both hashes, captured stdout was concatenated with stderr, CRLF was
normalized to LF, and the evidence temporary root, worktree root, and user
profile were replaced with placeholders before UTF-8 SHA-256 hashing. Raw
outputs were not added to Git. Both 38-test records are evidence for the tests
from `11f6c42e9b59664965d867f515e023c4a671e050`; neither describes the current
test count.

## Review-hardening evidence for 646fb6f

The source tree committed as
`646fb6f6fa4df37a90d26be40920d8c4d12e6be7` contained 57 tests. The following
full Green runs were actually executed in this worktree on 2026-08-07 while
preparing that commit:

- `.\scripts\test.ps1`: exit `0`; `Ran 57 tests in 67.845s`.
- `.\scripts\verify.ps1 -Suite unit`: exit `0`; `Ran 57 tests in 71.101s`.

No output hash was captured for those two runs, so none is claimed here. The
following are also actual Red/Green observations from preparing that source
commit, not reconstructed baseline output; raw command output was not added to
Git.

- Installed package/lock parsing: the source-commit test (since migrated into
  `BootstrapConfirmedPlanTests.test_apply_rejects_invalid_install_artifacts_without_publication`)
  first failed in all five then-existing subcases because raw JSON/StrictMode
  exceptions escaped (exit 1 or the wrong stage code), then passed after fixed
  stage errors were added. The current table also checks that no formal or
  temporary manifest survives any invalid-artifact case.
- Static schema restrictions:
  `.venv\Scripts\python.exe -m unittest tests.test_bootstrap_cli.BootstrapCodexCliTests.test_manifest_schema_rejects_unsafe_static_values -v`
  first failed for all three unsafe values (`C:\..\Windows`, Everyone
  FullControl, and extra CLI text), then passed after the schema was tightened.
- Dynamic manifest semantics: four source-commit tests each failed before its
  root, DACL, version, or hash rule and passed after the minimal rule. Those
  cases are now consolidated in
  `BootstrapConfirmedPlanTests.test_manifest_semantics_rejects_shape_and_binding_drift`.
  The retired source-commit write-path test first wrote a manifest despite a
  failing validator; its current deterministic replacement is
  `BootstrapCodexCliTests.test_manifest_atomic_publish_validates_before_temp_or_move`.
- Arbitrary working directory:
  `.venv\Scripts\python.exe -m unittest tests.test_smoke.TestScriptTests.test_default_discovery_uses_repository_from_arbitrary_cwd -v`
  first failed because the child inherited the outside directory, then passed
  after repository-scoped location handling was added.
- Reparse first-side-effect check: the retired source-snapshot test first found
  `bootstrap\codex-cli` created through the injected junction, then passed with
  an empty junction target after full-chain verification moved before
  `CreateDirectory`. Current lock-or-fail-closed coverage is
  `BootstrapConfirmedPlanTests.test_apply_ancestor_junction_race_is_locked_or_fails_closed_before_install`.

## Review-fix evidence after 646fb6f

The following Red/Green commands were actually run in the post-`646fb6f`
worktree represented by this README on 2026-08-07. No output hashes were
captured, so none are claimed; raw output was not added to Git.

- ACL error redaction: the retired source-snapshot command-injection test first
  failed because stderr included a sensitive command path (`Ran 1 test in
  1.147s`), then passed with fixed error text and code 48 (`Ran 1 test in
  1.378s`). External ACL commands were subsequently removed; the current
  contract is
  `BootstrapConfirmedPlanTests.test_icacls_command_parameter_is_removed_without_side_effects`.
- Discover/Apply canonical SemVer: the retired paired test first failed because
  Discover accepted `1.2.3-01` and Apply returned a plan-drift code (`Ran 1 test
  in 1.712s`), then passed with invalid metadata rejected (`Ran 1 test in
  1.689s`). Current coverage is split between
  `BootstrapConfirmedPlanTests.test_discover_rejects_numeric_prerelease_leading_zero`
  and the semantic validator test below.
- Manifest schema canonical SemVer:
  `.\scripts\test.ps1 -Test tests.test_bootstrap_cli.BootstrapCodexCliTests.test_manifest_schema_rejects_unsafe_static_values`
  first failed for both package and CLI `1.2.3-01` values
  (`Ran 1 test in 0.062s`), then passed while retaining the legal
  `1.2.3-alpha.1+build.01` case (`Ran 1 test in 0.059s`).
- Manifest semantic canonical SemVer:
  `.\scripts\test.ps1 -Test tests.test_bootstrap_cli.BootstrapConfirmedPlanTests.test_manifest_semantics_rejects_internally_consistent_illegal_semver`
  first accepted an internally consistent plan/manifest using `1.2.3-01`
  (`Ran 1 test in 1.852s`), then rejected it with semantic code 58
  (`Ran 1 test in 1.780s`).
- Current post-migration full Green: `.\scripts\test.ps1` exited `0` with
  `Ran 66 tests in 298.119s`.

## Manifest v2 atomic-publication evidence

These are current-worktree observations, not reconstructed logs. The module
fault test first failed because `Publish-SelfWorkflowManifestAtomic` did not
exist (`validationCalls` was `0`), then passed after the existing temp-write,
flush, Move, post-read validation, and cleanup path was extracted into that
function:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_bootstrap_cli.BootstrapCodexCliTests.test_manifest_atomic_publish_cleans_published_file_after_postcheck_failure -v
```

The Green run exited `0` and ran one test in `0.356s`. The three migrated final
Apply assertions (schema/semantic manifest, install-only/no view, no Codex, and
exact ACL) exited `0` with three tests in `10.805s`. The main success,
pre-write existing-manifest rejection, and atomic-rename failure integrations
exited `0` with three tests in `7.455s`. No raw outputs or temporary evidence
files were added to Git. After the three stale exit-61 assertions were migrated,
the 35-test `BootstrapConfirmedPlanTests` group exited `0` with all tests Green
in `104.091s`.

The final Move-failure oracle is deterministic module-level fault injection
against the real filesystem publication function, not a concurrent attack
claim and not a production test seam. Its first validator call creates a
directory conflict at the formal manifest path; the real temp-write and
`[IO.File]::Move` then fail. The test verifies one validator call, preservation
of the conflict object, absence of a formal manifest file, and temp cleanup:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_bootstrap_cli.BootstrapCodexCliTests.test_manifest_atomic_publish_cleans_temp_after_move_conflict -v
```

That run exited `0` and ran one test in `0.341s`. The pre-write first-validator
fault and post-Move second-validator fault remain separate dynamic tests.

One historical full-suite migration-inventory run of `.\scripts\test.ps1` then exited `1`:
`Ran 99 tests in 124.943s`, with 40 reported failures and 16 reported errors
(subtests make those incident counts larger than the number of affected test
methods). All 35 v2 confirmed-plan tests and all 16 smoke tests were Green. The
42 non-Green methods were then-unmigrated v1 tests: static source classification found
38 using the removed `-NpmCommand`/fake-cmd interface and four using the
removed `-IcaclsCommand` injection interface. This run is a migration inventory,
not a product-regression claim; those old tests were intentionally not bulk
rewritten in this task step.

## Project-local work-document lifecycle

For `Full`/`Deep` tasks, or tasks that produce at least two formal design/test/
plan/review documents, SelfWorkFlow can record the document lifecycle below the
project's local `./selfworkflow/` directory. A single-document `Light` task does
not create it. The directory is protected by an exact common-Git
`info/exclude` entry and is never added, committed, pushed, or written to the
project `.gitignore`.

Use the thin CLI operations `selfworkflow artifact transition` and
`selfworkflow artifact reconcile`. They bind each update to the content
generation, state revision, Manifest hash, and operation nonce. The normal path
is capture/revise → Review → post-landing Review → Verify → local-final →
optional user-confirmed knowledge publication → complete. Critical/Important
findings block Verify; stale Review evidence cannot satisfy a new generation.
`reconcile --dry-run` is zero-write and returns a plan hash; apply requires that
same hash and never silently falls back. The optional knowledge package contains
only final documents, bounded source metadata, hashes, and residual risks.
