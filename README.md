# SelfWorkFlow

SelfWorkFlow is a Windows-only foundation for reproducible, cross-vendor agent
workflows. Task 1 provides the Python package, unified test entry points, and a
confirmation-gated Codex CLI bootstrap.

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

The verification wrapper currently implements the unit suite:

```powershell
.\scripts\verify.ps1 -Suite unit
```

Suites not implemented by Task 1 return structured `not-implemented` results
and a nonzero exit code. Native verification returns
`requires-user-action` with its own nonzero exit code. Consequently, `all`
cannot report success while required suites remain unavailable.

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
non-reparse, owned by the current SID or SYSTEM, and free of dangerous access
for other principals. The plan binds absolute `node.exe` and `npm-cli.js`,
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

### Security boundary

Held directory handles provide a concrete guarantee for already opened
ancestors: while those handles remain open, another process cannot rename or
delete those directories, and identity/reparse checks detect a changed path
mapping. Confirmed-plan, Node, npm entry, and available inventory handles remain
open through the child process.

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
  `Ran 62 tests in 266.955s`.

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
