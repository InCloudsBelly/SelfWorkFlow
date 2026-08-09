# CodeGraph Provider

SelfWorkFlow treats CodeGraph as an optional, user-owned local Provider. The
built-in `cpp-core` remains usable without it. Configuration is explicit and
machine-local; the repository never scans for CodeGraph and never commits a
local path.

A different existing `codegraph` binding is preserved by default. Replace it
only after reviewing the conflict, using `configure --replace-existing` or the
installer's `-ReplaceCodeGraphOverride` switch.

## Configure

Run `Install_SelfWorkFlow.bat` and choose the local CodeGraph override, or use:

```bat
Manage_SelfWorkFlow_Providers.bat configure --codegraph-path <local-codegraph-root>
```

The selected directory must be the exact root of a Git checkout and must contain
the fixed entry `dist\bin\codegraph.js`. Configuration records the commit, Git
tree and relevant working-state-derived source hash, an `unverified` version
placeholder, dirty state, command hash
and binding hash in
`%LOCALAPPDATA%\SelfWorkFlow\config\providers.local.yaml`. This is the same V3
machine configuration consumed by Provider selection; it is not a parallel
management-only registry. Existing unrelated Provider entries are preserved.

Dirty means the selected source is not reproducible from its commit alone. It
is reported, not silently normalized. SelfWorkFlow may inspect a user-owned
checkout, but this release never executes, upgrades, or removes it.

## Operations and safety

`list` and source inspection do not execute Provider code. Git inspection runs
with system/global configuration disabled, fsmonitor disabled, optional locks
disabled, and external diff/textconv disabled. `doctor` and `status` are reserved
CLI names but fail closed with `provider-operation-unverified`; this release has
no production Provider process dispatch. That boundary remains closed until an
immutable LaunchSpec binds the canonical entry, runtime identity, source hash,
and atomic launch operation.

`query` is intentionally plan-only in this version. The inspected CodeGraph CLI
does not expose a `--no-sync` option for query/explore, so the plan is marked
`potential-local-write`; SelfWorkFlow does not initialize an index implicitly.

`initialize`, `sync` and `rebuild` are maintenance operations. First create a
plan:

```bat
Manage_SelfWorkFlow_Providers.bat maintain --action sync --project-root D:\project --plan-only
```

The plan binds the Provider command, ownership, project root hash, action and
side-effect class. Execution is deliberately disabled in this release. Any call
without `--plan-only`, including one carrying `--confirm-plan-hash`, fails closed
with `provider-maintenance-apply-unverified`. The production Host does not yet
bind the V3 authorization, persistent lease/replay, mutation-evidence, and
rollback ports; a CLI confirmation hash alone is not identity authentication or
sufficient mutation authorization.

## Current verification boundary

Automated tests use an injected Fake command port and prove command rendering,
redaction, no implicit initialization, atomic configuration, rollback,
idempotence, source-drift rejection before dispatch, deterministic planning, and
fail-closed maintenance execution. A prior local observation does not prove the
current checkout, `doctor`, `status`, query freshness, auto-sync behavior,
mutation containment, or rollback. Those operations remain `unverified` until a dedicated native test
uses an exact source identity and disposable synthetic C++ repository.
