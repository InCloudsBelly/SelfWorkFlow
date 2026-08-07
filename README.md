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

`scripts\bootstrap-codex-cli.ps1` is Windows-only. `Discover` queries package
metadata and emits a read-only plan with a SHA-256 hash. `Apply` regenerates
that plan and requires the user-confirmed hash before it creates or changes the
bootstrap root.

The allowed root is `%LOCALAPPDATA%\SelfWorkFlow\bootstrap\codex-cli`. The plan
binds the canonical npm executable path and SHA-256, an HTTPS registry without
userinfo, fixed metadata/install arguments, isolated npm configuration, the
expected protected DACL, and the side-effect/uninstall boundary. Apply
regenerates these values before accepting `-ConfirmPlanHash`.

Apply rejects path escapes, reparse-point ancestors, and unsafe existing
targets. Existing critical ancestors are opened with Windows directory handles
that request DELETE access and do not share DELETE; their file identities and
reparse attributes are checked again before directory creation and npm install.
Newly created ancestors are added to the same lock set before ACL work. The
bootstrap root receives a protected DACL containing exactly FullControl ACEs
for the current-user SID and SYSTEM.

npm runs with inherited `NPM_CONFIG_*` and token variables cleared, explicit
`NUL` user/global configs, and the planned registry argument. Installed package
and lock JSON are parsed as strict objects with required string fields. Codex
CLI version verification captures stdout and stderr separately and accepts only
one canonical `codex-cli <semver>` stdout line matching package metadata.

The manifest has two validation layers. JSON Schema handles static shape and
format restrictions, including noncanonical `..` roots, strict versions, and
Everyone ACE rejection. Before writing, `scripts\lib\bootstrap-manifest.ps1`
performs dynamic validation against the allowed boundary, current SID/SYSTEM
DACL, regenerated plan hash, package-tree hash, package metadata, CLI version,
and actual SDDL. Any semantic exception fails closed without persisting the
candidate manifest.

### Security boundary

Held directory handles provide a concrete guarantee for already opened
ancestors: while those handles remain open, another process cannot rename or
delete those directories, and identity/reparse checks detect a changed path
mapping. The npm executable is separately held open against write/delete while
its identity is in use.

This is not an absolute same-SID adversary guarantee. Windows directory
creation and subsequent handle acquisition are not atomic here, leaving a
create-and-open window for previously missing components. A process running as
the same SID can also modify package files or ACL state that is not individually
locked after the final verification point. The plan reports both limits as
`unverified`; callers requiring stronger isolation must use a separately
trusted principal or sandbox. Real npm/Codex execution remains unverified in
Task 1 because all automated installer tests use the fake npm fixture.

Tests use `tests\fixtures\bootstrap\fake-npm.cmd`; they do not install the real
Codex CLI.

## Reconstructed baseline test evidence

This is a **reconstructed baseline, not a replacement for original session
logs**. The baseline was unpacked from
`f5b6fd41717879da4e2e86f35f94ff389079fa9d` into a new system temporary
directory. Only `tests\__init__.py`, `tests\test_smoke.py`,
`tests\test_bootstrap_cli.py`, and `tests\fixtures\bootstrap\fake-npm.cmd` as
recorded by source commit
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

- Installed package/lock parsing:
  `.venv\Scripts\python.exe -m unittest tests.test_bootstrap_cli.BootstrapCodexCliTests.test_apply_rejects_invalid_installed_json_with_stable_redacted_error -v`
  first failed in all five subcases because raw JSON/StrictMode exceptions
  escaped (exit 1 or the wrong stage code), then passed after fixed codes 56/57
  and redacted stage errors were added.
- Static schema restrictions:
  `.venv\Scripts\python.exe -m unittest tests.test_bootstrap_cli.BootstrapCodexCliTests.test_manifest_schema_rejects_unsafe_static_values -v`
  first failed for all three unsafe values (`C:\..\Windows`, Everyone
  FullControl, and extra CLI text), then passed after the schema was tightened.
- Dynamic manifest semantics: the four exact tests ending in
  `test_manifest_semantics_rejects_noncanonical_or_outside_root`,
  `test_manifest_semantics_rejects_everyone_dacl`,
  `test_manifest_semantics_rejects_version_drift`, and
  `test_manifest_semantics_rejects_hash_drift` each failed before its semantic
  rule and passed after the minimal rule. The write-path integration test
  `test_apply_validates_manifest_before_write` first wrote a manifest despite a
  failing validator, then passed with exit 58 and no manifest after integration.
- Arbitrary working directory:
  `.venv\Scripts\python.exe -m unittest tests.test_smoke.TestScriptTests.test_default_discovery_uses_repository_from_arbitrary_cwd -v`
  first failed because the child inherited the outside directory, then passed
  after repository-scoped location handling was added.
- Reparse first-side-effect check:
  `.venv\Scripts\python.exe -m unittest tests.test_bootstrap_cli.BootstrapCodexCliTests.test_apply_rechecks_reparse_ancestor_after_metadata_before_install -v`
  first found `bootstrap\codex-cli` created through the injected junction, then
  passed with an empty junction target after full-chain verification moved
  before `CreateDirectory`.

## Review-fix evidence after 646fb6f

The following Red/Green commands were actually run in the post-`646fb6f`
worktree represented by this README on 2026-08-07. No output hashes were
captured, so none are claimed; raw output was not added to Git.

- ACL error redaction:
  `.\scripts\test.ps1 -Test tests.test_bootstrap_cli.BootstrapCodexCliTests.test_apply_redacts_missing_sensitive_icacls_path`
  first failed because stderr included the missing `super-secret` command path
  (`Ran 1 test in 1.147s`), then passed with fixed error text and code 48
  (`Ran 1 test in 1.378s`).
- Discover/Apply canonical SemVer:
  `.\scripts\test.ps1 -Test tests.test_bootstrap_cli.BootstrapCodexCliTests.test_discover_and_apply_reject_numeric_prerelease_leading_zero`
  first failed in both subcases because Discover accepted `1.2.3-01` and Apply
  returned plan-drift code 46 (`Ran 1 test in 1.712s`), then passed with both
  modes rejecting invalid metadata at code 47 (`Ran 1 test in 1.689s`).
- Manifest schema canonical SemVer:
  `.\scripts\test.ps1 -Test tests.test_bootstrap_cli.BootstrapCodexCliTests.test_manifest_schema_rejects_unsafe_static_values`
  first failed for both package and CLI `1.2.3-01` values
  (`Ran 1 test in 0.062s`), then passed while retaining the legal
  `1.2.3-alpha.1+build.01` case (`Ran 1 test in 0.059s`).
- Manifest semantic canonical SemVer:
  `.\scripts\test.ps1 -Test tests.test_bootstrap_cli.BootstrapCodexCliTests.test_manifest_semantics_rejects_numeric_prerelease_leading_zero`
  first accepted an internally consistent plan/manifest using `1.2.3-01`
  (`Ran 1 test in 1.852s`), then rejected it with semantic code 58
  (`Ran 1 test in 1.780s`).
- Current full Green: `.\scripts\test.ps1` exited `0` with
  `Ran 62 tests in 76.377s`.
