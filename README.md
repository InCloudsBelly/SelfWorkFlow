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

## Reconstructed baseline test evidence

This is a **reconstructed baseline, not a replacement for original session
logs**. The baseline was unpacked from
`f5b6fd41717879da4e2e86f35f94ff389079fa9d` into a new system temporary
directory. Only the current `tests\__init__.py`, `tests\test_smoke.py`,
`tests\test_bootstrap_cli.py`, and `tests\fixtures\bootstrap\fake-npm.cmd`
were then copied into it; no current production implementation was copied.
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

The current-tree Green command, run from the repository root, was:

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
outputs were not added to Git.
