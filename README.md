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

The allowed root is `%LOCALAPPDATA%\SelfWorkFlow\bootstrap\codex-cli`. Apply
rejects path escapes, reparse-point ancestors, and unsafe existing targets. It
then applies a protected DACL containing only the current user and SYSTEM,
installs the exact planned package version, verifies package integrity and CLI
version, and writes `bootstrap-tool-manifest.json`.

Tests use `tests\fixtures\bootstrap\fake-npm.cmd`; they do not install the real
Codex CLI.
