# SelfOpenWiki

本目录是 SelfWorkflow 的可选 Wiki 实现。两个上游 submodule 由 SelfWorkflow
根 `.gitmodules` 持有，自有 MCP、配置与个人覆写规则保持原相对布局。
统一入口为源仓库根 `Manage_SelfWorkFlow_Wiki.bat`；可迁移知识目录遵循
[WIKI_LAYOUT.md](WIKI_LAYOUT.md)。以下独立工具说明供模块构建与维护参考，
不替换 SelfWorkflow 的阶段、授权、Review 或验证流程。

SelfOpenWiki is a Windows-first, locally installable knowledge system built on
the official OpenWiki source. The knowledge-production path remains the
unmodified, pinned Git submodule at `upstream/openwiki`; the local visualizer
is the separately pinned `zxh_wiki_viewer` fork at
`visualizer/zxh_wiki_viewer`. SelfOpenWiki-owned integration, MCP, Agent Skill,
configuration, and build logic live outside both submodules.

## Quick links

- [Design](docs/specs/2026-08-14-selfopenwiki-v1-design.md)
- [Test design](docs/testing/2026-08-14-selfopenwiki-v1-test-design.md)
- [Implementation plan](docs/plans/2026-08-14-selfopenwiki-v1.md)
- [OpenWiki v2 integration design](docs/specs/2026-09-10-selfopenwiki-v2-openwiki-integration-design.md)
- [OpenWiki v2 test design](docs/testing/2026-09-10-selfopenwiki-v2-test-design.md)
- [OpenWiki v2 implementation plan](docs/plans/2026-09-10-selfopenwiki-v2-implementation-plan.md)
- [Official OpenWiki submodule](upstream/openwiki)
- [Personal visualizer submodule](visualizer/zxh_wiki_viewer)

## Setup, install, and storage boundaries

`Setup.bat` builds the pinned official OpenWiki production path and the
`zxh_wiki_viewer` visualizer without selecting or changing personal knowledge
storage. `Setup.bat --with-mcp` additionally builds the local MCP and Win32
helper. `Install.bat` is the explicit Agent-facing binding operation: it
refuses to continue until the Agent has obtained the user's Wiki-root and the
required safety confirmations.

从 SelfWorkflow 源仓库使用此模块。独立 SelfOpenWiki 仓库仅保留导入来源记录，
不是安装或运行依赖。在 SelfWorkflow 源根初始化两项固定依赖：

```powershell
git submodule update --init --recursive -- extensions/knowledge/selfopenwiki/upstream/openwiki extensions/knowledge/selfopenwiki/visualizer/zxh_wiki_viewer
.\Manage_SelfWorkFlow_Wiki.bat setup --with-mcp
```

个人工作流只发现根 `kg-selfopenwiki` 后端入口，并按本轮操作读取一个引用。
模块内部 `self-openwiki` Skill 是返回的 Writer/协议包的一部分；普通读取不重复加载它。

MCP 0.1.2 的默认个人发布保留正式目录与 Git 元数据，按变更文件提交并通过本机 v5 日志恢复，
目录监听和只读预览可以保持打开。新版 MCP 在同一锁内读取，待恢复的发布不报告 ready；
所有参与一致性读写的 MCP 连接都需升级。直接文件 Viewer 可能看到提交过程，
外部工具须避免在发布期间同时写入正式文件。仍需原有用户确认、独立 Review 与 CAS，
更新结束后不自动打开正式文件面板或切换工作目录。

Before invoking `Install.bat`, the Agent must verify the following authorization;
reuse authorization already given for this scope and ask only for missing items:

1. the absolute Wiki-root directory to use;
2. that the user understands SelfOpenWiki will read and write Markdown there
   and has handled backups/data safety; and
3. if the directory is a Git repository, that the user has the relevant
   technical authorization to write that knowledge working tree. This does not
   authorize commits or pushes.

The Agent then invokes the fail-closed command below. A missing path or
authorization pauses setup/storage writes only; there is no default Wiki
directory and no automatic directory creation.

For a normal local directory:

```powershell
.\Install.bat --wiki-root '<wiki-root>' --confirm-data-safety
```

For a Git-backed personal Wiki, only after the user confirms the repository
authorization:

```powershell
.\Install.bat --wiki-root '<wiki-root>' --confirm-data-safety --confirm-git-authorization
```

Install runs the existing MCP setup, then binds the selected directory. It
does not migrate knowledge, edit the Wiki `.git`, commit, or push. Migration,
commit, and push remain separate explicitly authorized operations. The
selected directory is the Wiki root itself; its runtime state is kept beside
it at `<wiki-root>.selfopenwiki`.

Personal knowledge is external to this public repository. Its formal Markdown
tree is `<wiki-root>` (a Git repository root for the v2 lifecycle), while SelfOpenWiki
runtime state is the sibling `<wiki-root>.selfopenwiki`. Normal knowledge
operations do not commit or push the Wiki repository; migration publication is
an explicit, separately authorized operation.

## Personal Wiki v2 lifecycle

The adapted personal flow exposes the six official OpenWiki lifecycle names:
`openwiki_begin`, `openwiki_submit_plan`, `openwiki_next_page`,
`openwiki_inspect_page_claims`, `openwiki_submit_page`, and `openwiki_finish`.
They are adapted to the SelfOpenWiki protocol
`selfopenwiki:personal-openwiki-v1`: the caller supplies the absolute external
`wikiRoot`, PageJobs write only to a C7 candidate, Claims are submitted as
sparse decisions, and only C7 review plus CAS publication changes the formal
Wiki. The user's Wiki Git repository is never committed, pushed, fetched, or
rewritten by this flow.

For new pages, include any hand-maintained navigation page needed to connect
them from `quickstart.md`; a reachable topic index is sufficient. A plan with no
writable navigation entry is rejected before candidate creation and can be
corrected in the same run. Accepted queues remain immutable, and final link,
Claims, review, and CAS checks still apply.

The official Submodule is pinned to OpenWiki `0.7.1` at commit
`d1c7fc75a6a906da258cd94dbcb1602f98516480`. The active materialization
manifest is v2 with `patches: []`; personal behavior is maintained in the
SelfOpenWiki adapter and Skill rather than patched into `upstream/openwiki`.

Upstream updates are explicit and commit-bound. Generate a review plan first;
after the new contract and personal Skill adaptation are approved, apply the
same commit with the transactional helper:

```powershell
node scripts/update-upstream.mjs '<40-character-commit>'
node scripts/update-upstream.mjs --apply '<40-character-commit>'
# or: Update-Upstream.bat --apply '<40-character-commit>'
```

`--apply` updates the Submodule checkout, zero-patch manifest, checked-in
personal bindings, compatibility hashes, generated official checkout, and
only the `upstream/openwiki` gitlink. Verification failure restores those
captured artifacts; it never touches the external personal Wiki repository.
The personal Skill remains an explicit semantic-review boundary for each
upstream iteration.

To bind this checkout to an existing personal Wiki, run:

```powershell
node scripts/configure-storage.mjs --wiki-root '<wiki-root>'
```

Replace the path with the directory you own. The command writes only the local
configuration under `%LOCALAPPDATA%\SelfOpenWiki` and never changes the Wiki
repository's `.git` metadata.

## Build the local MCP and Agent integration

After the official submodule has been materialized into `.work\openwiki`, the
setup flow builds the independent SelfOpenWiki package and the visualizer
submodule from the repository root:

```powershell
node scripts/materialize-openwiki.mjs
corepack pnpm@10.33.2 --dir self-openwiki/mcp-server install --frozen-lockfile --ignore-scripts
corepack pnpm@10.33.2 --dir self-openwiki/mcp-server run build
corepack pnpm@10.33.2 --dir self-openwiki/mcp-server run build:win32-helper
corepack pnpm@10.33.2 --dir visualizer/zxh_wiki_viewer install --frozen-lockfile
corepack pnpm@10.33.2 --dir visualizer/zxh_wiki_viewer run build
```

The MCP entry is `self-openwiki\mcp-server\dist\index.js`. It reads the
selected Wiki root from the local storage config; it does not embed a Wiki
path and it does not modify the upstream submodule. Capability verification is
explicit and fail-closed:

```powershell
$env:CI = 'true'
node self-openwiki/scripts/verify-capabilities.mts
```

The verifier refreshes the derived compatibility binding, reuses the existing
build output directories, and runs the builds, full test suite, Skill checks,
and built MCP smoke before activating new capability evidence. The binding
checks the SelfOpenWiki module's current source bytes. Unrelated SelfWorkflow
changes, Git staging, and parent commits do not invalidate an unchanged module.
For base or specialized Skill edits, review the changed package and update its
checked-in trusted package hash first; verification does not auto-trust edits.
An already connected server loads newly verified Skill rules on its next call.
Executable or runtime-configuration changes still require an MCP reconnect;
`openwiki_status` reports that boundary. When a recovery message says
`Reconnect this MCP server`, reconnect and check status instead of retrying
the same connection. A missing or stale verification result
blocks further Wiki operations until the module verifier succeeds.

An external Agent must call `openwiki_status` first, confirm schema 2 external
mode and both external capability IDs, then use the writer → `prepare_review` →
independent Reviewer → publish flow. The MCP owns snapshots, receipts,
validation, CAS, recovery, and publication; it never creates the writer,
Reviewer, model, or SubAgent. Legacy query/update/model tools remain explicit
`legacy_provider` operations. Normal knowledge writes do not commit or push the
selected Wiki repository; ask the user before making a single dedicated commit,
and request push authorization separately.

## View the selected personal Wiki

OpenWiki remains the production and knowledge-lifecycle implementation. The
visualization entry point is the pinned `zxh_wiki_viewer` submodule, which reads
the same external Wiki root without copying or modifying it:

```powershell
.\Visualize.bat
```

The default starts the Next.js development server at
`http://127.0.0.1:3000/wiki/local`. After `Setup.bat` has built the viewer,
the production server can be started with:

```powershell
.\Visualize.bat --production
```

The launcher reads the Wiki root from SelfOpenWiki's local storage
configuration and injects it as `SELFOPENWIKI_WIKI_ROOT`; the path is never
committed to this repository. 缺少实时 Viewer contract 时停止并报告 unverified；
不把旧官方 CLI 作为自动 fallback。
