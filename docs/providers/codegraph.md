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
tree and relevant working-state-derived source hash, CLI version observation,
dirty state, command hash
and binding hash in
`%LOCALAPPDATA%\SelfWorkFlow\config\providers.local.yaml`. This is the same V3
machine configuration consumed by Provider selection; it is not a parallel
management-only registry. Existing unrelated Provider entries are preserved.

Dirty means the selected source is not reproducible from its commit alone. It
is reported, not silently normalized. SelfWorkFlow may inspect or call a
user-owned checkout, but will never upgrade or remove it.

## Operations and safety

`list`, `doctor` and `status` are explicit diagnostics. They use a shell-free,
argument-array process boundary, bounded output and stable redacted errors.
Their adapter support remains `unverified` until native evidence proves the
exact source identity and operation behavior.

`query` is intentionally plan-only in this version. The inspected CodeGraph CLI
does not expose a `--no-sync` option for query/explore, so the plan is marked
`potential-local-write`; SelfWorkFlow does not initialize an index implicitly.

`initialize`, `sync` and `rebuild` are maintenance operations. First create a
plan:

```bat
Manage_SelfWorkFlow_Providers.bat maintain --action sync --project-root D:\project --plan-only
```

Then execute only the exact reviewed hash:

```bat
Manage_SelfWorkFlow_Providers.bat maintain --action sync --project-root D:\project --confirm-plan-hash sha256:<64-hex>
```

The plan binds the Provider command, ownership, project root hash, action and
side-effect class. A mismatched, tampered or in-process replayed plan fails
closed. Machine-process restart invalidates in-memory issuance; the CLI therefore
reissues the same deterministic plan in the confirmed invocation before
execution. This confirmation is a side-effect guard, not identity authentication.

## Current verification boundary

Automated tests use an injected Fake command port and prove command rendering,
redaction, no implicit initialization, atomic configuration, rollback,
idempotence, exact-hash confirmation and replay handling. A local read-only
inspection has observed CodeGraph `1.3.1-ks.7`, `status` on an uninitialized
workspace, no `.codegraph` creation and an unchanged Git worktree, plus the available command surface,
but this does not prove query freshness, auto-sync behavior, mutation containment
or rollback. Those operations remain `unverified` until a dedicated native test
uses an exact source identity and disposable synthetic C++ repository.
