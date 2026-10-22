# SelfWorkFlow

## 通过 GitHub 安装入口 Skill

仓库提供统一入口 [`skills/selfworkflow/SKILL.md`](skills/selfworkflow/SKILL.md)。在支持 GitHub Skill 来源的宿主（例如 WheelMaker）中添加 `InCloudsBelly/SelfWorkFlow`，选择并安装 **selfworkflow**；添加来源本身不等于安装。其他 `skills/` 目录是专业方法，不需要为启用主流程全部安装。

WheelMaker 当前只接受仓库地址，不接受带分支的 GitHub tree URL，因此仓库默认分支应为 `main`。Windows 上完整文档路径较长；遇到 `Filename too long` 时，在宿主的这个来源缓存仓库启用 `git -C <来源缓存目录> config core.longpaths true` 后重试更新。若检出已部分失败，应先确认缓存中的改动均来自本次失败检出再恢复；不要重置用户的工作仓库。

入口 Skill 优先读取用户或宿主全局指令配置的公共入口；没有配置时，读取随包的 `skills/selfworkflow/references/public/WORKFLOW.md`，随后绑定其不可变文档版本。安装完成后读取随包规则无需联网，也不依赖维护者本机的 `D:` 盘。明确配置的入口不可用时报告缺口，不静默切换来源。私有 GitHub 仓库的获取权限仍由安装宿主处理，不在 Skill 中保存凭据。

发布 Skill 时，从仓库根使用现有文档发布器生成随包文档，再一并提交 Skill 和完整的 `references/public/`：

```powershell
.venv\Scripts\python.exe -m selfworkflow.cli documents publish --repository . --output skills/selfworkflow/references/public
```

已安装的随包文档通过宿主的 Skill 来源更新操作刷新；单独推送仓库不会自动更新已安装副本。维护者另行发布根 `public/` 时，也必须同时提交入口与其引用的完整 `public/releases/<revision>/`。

若希望默认启用，在宿主支持的全局指令中写入：

```text
默认工程流程使用 selfworkflow Skill；每个用户顶层工程任务实际读取其固定公共入口，子任务和续接继承主任务的 revision 与 documentRoot。
```

已有下文的公共入口全局指令时可以直接沿用，无需重复配置。安装只证明文件已分发；Codex 和 DeepSeek Harness 的发现、调用、文档读取与版本绑定仍需在各自新会话中验证。本 Skill 不安装 MCP 或执行旧安装器；普通文档接入不依赖这些能力。

## 文档直接使用（默认）

普通 Agent 只需读取 [公共工作流入口](public/WORKFLOW.md)，再按该入口绑定的版本加载规则和方法；消费者无需安装 SelfWorkflow、Python/Node 或原生 Skill。工具能力仍按实际需要独立检查，缺少能力不能伪造通过。

新 Agent 按公共入口中的“新 Agent 快速接入”链接完成首次核对；维护源见 [接入指南](workflow/onboarding.md) 和 [可选宿主说明模板](workflow/templates/AGENT_ADAPTER.md)。一个固定入口即可开始，宿主差异只记录实际工具接线。

首次接入时，把固定入口引用放入宿主指令；此后工作流更新不改各宿主配置：

```text
每个用户顶层任务实际读取 D:/SelfWorkFlow/public/WORKFLOW.md。
子任务、独立 Reviewer 和上下文续接继承主任务的 revision 与 documentRoot。
只按需读取当前版本，不使用历史安装的规则/方法副本。
```

维护者修改唯一规则源后运行 `Publish_SelfWorkFlow_Documents.bat`，或使用维护环境：

```powershell
.venv\Scripts\python.exe -m selfworkflow.cli documents publish --repository D:\SelfWorkFlow --output D:\SelfWorkFlow\public
```

发布器整理固定来源的方法、检查引用闭合，先发布完整的不可变文档版本，再切换公共入口。发布失败保持上版；旧任务及其子任务继续使用原版，新顶层任务读取新版。公共版本只包含文档与必要静态资料，不含消费者需执行的程序。

现有受管安装的一次迁移可在 `install plan` 追加 `--document-root <public-root>`；或在兼容安装脚本传 `-DocumentRoot <public-root>`。先审查计划再按原有 planHash 应用：受管 Skill 按所有权和内容 hash 退役，用户修改会使计划暂停，原事务可回滚。当前安装的工具桥接快照可以保留。后续规则更新只运行文档发布，不再执行安装。

`documents check --root <public-root>` 是维护者校验；`documents snippet --root <public-root>` 输出固定引用。两者均不是 Agent 读取文档的前置条件。离线或只能一次性导入内容的宿主仍需重新分发，不承诺自动刷新。

## 可选 Wiki 模块

SelfOpenWiki 的自有 MCP、配置、个人覆写 Skill 与构建逻辑位于
`extensions/knowledge/selfopenwiki/`。OpenWiki 和 Viewer 是根 `.gitmodules`
直接管理的固定版本依赖；`knowledge` 安装 profile 才准备这两个子模块。

```text
Manage_SelfWorkFlow_Wiki.bat inspect
Manage_SelfWorkFlow_Wiki.bat setup --with-mcp
Manage_SelfWorkFlow_Wiki.bat visualize --wiki-root "<absolute-wiki-git-root>"
selfworkflow wiki inspect --repository "<absolute-selfworkflow-source-root>"
```

静态 Agent snapshot 保留规则和受控源码，实际工具在显式源仓库的模块目录构建。
`source-ready` 只说明源码区具备新鲜构建/能力证据，不表示宿主已切换 MCP。
Wiki 的正文、长期 `.claims` 与可分享来源保存在独立 Wiki Git 仓库；阅读及重新
绑定不需要携带旧运行区。目录与导入规范见
[WIKI_LAYOUT.md](extensions/knowledge/selfopenwiki/WIKI_LAYOUT.md)。

SelfWorkFlow is a code-first, vendor-neutral Agent workflow. Its default product is
a compact operational core, not the repository's complete maintenance and release
machinery.

## 可选工具部署与旧安装兼容

After cloning the repository, run this from Explorer or a terminal:

```bat
Install_SelfWorkFlow.bat
Install_SelfWorkFlow.bat -Profile knowledge
Install_SelfWorkFlow.bat -Profile knowledge -DshRoot "%USERPROFILE%\.dsh"
```

`-DshRoot` is optional and explicit. It adds a separate managed block at
`<DshRoot>\AGENTS.md` for DeepSeek Harness; Codex's own managed block remains
managed as before. It manages the instruction root only; DSH profile MCP entries
such as CodeGraph remain explicit profile configuration. Once installed with
`-DshRoot`, repeat it on upgrades: omitting it pauses the plan instead of
silently dropping the DSH binding. Changing the DSH root is also paused. To
unbind or migrate, first roll back any later install transactions in LIFO order,
then run `selfworkflow install rollback-plan` and
`selfworkflow install rollback` on the transaction that introduced the DSH root.
This increment has no automatic root migration.

The installer checks or prepares the repository Python environment, initializes
the pinned Git Submodules, installs the pinned CodeGraph runtime with Node >=20, and packages only the curated Matt Pocock Skills
listed in `dependencies/locks/matt-pocock-skills.lock.yaml`. The upstream
`grilling` and `grill-me` are installed with that curated set. Both are available
only on explicit user request in every mode; Full/Deep do not enable them.
SelfWorkflow does not require, install, or default-route to Superpowers.

The installer verifies the pinned CodeGraph runtime and never scans disks for
another code graph or binds an alternate provider. The project `.codegraph/`
index is initialized only when its database is missing and is synchronized
after edits. An existing index that remains not-fresh is preserved and reported;
automatic rebuilds or cache deletion are not part of the workflow.

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
the source lock. When `-DshRoot` is supplied, DSH receives the same hash-bound
bootstrap plus its `## 宿主适配` section under its own instruction root. A pre-existing user-level Superpowers installation remains
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

The default is an instruction-based `agent-policy`, not a conforming Host.
Full/Deep describe task depth; they do not activate contract APIs. Ordinary
tasks reuse explicit authorization within unchanged scope and fresh evidence
within unchanged inputs. Full/Deep read-only analysis uses one independent reviewer;
Full/Deep changes use one post-change independent reviewer covering both
Standards and Spec. Intermediate plans are self-reviewed; a pre-implementation
independent gate is reserved for material architecture, security, persistence,
irreversible risk or explicit request. TEA and full Grilling are explicit-only.
Contract-only dispatch, runner, receipts and cleanup
attestation apply only to explicit contract-managed work or tasks accepted by a conforming Host under its contract. Host capability alone does not switch the task mode.
Unavailable contract capability stops that mode; it is never silently downgraded.
Instructions do not provide OS-level isolation or replace host permissions.

### 个人入口与来源备份

默认自然语言请求使用 canonical Skill；本机 `patent-disclosure-local` 和
`skill-creator-local` 在各自 `agents/openai.yaml` 设置
`policy.allow_implicit_invocation=false`，保留显式指定本地版本的入口。
改名本身不解决语义重复；调用策略与 Skill 正文分别维护。

迁移 hash-bound runtime 时，应检查 catalog 引用的 Git revision 是否被普通
分支或标签覆盖。不可达来源必须与交付材料一起保存为完整 Git bundle，记录
来源路径、revision/ref、contentHash 与 bundle SHA256，并在独立 bare repository
恢复、比较 OID 和对应文件字节。不要仅备份某一个自定义 ref；当前三个受管
Skill 分别需要 `e2ef4d49d8dc60a6e7fb514ff66c5d0e0ef561c3` 和
`0387e8f0130e8d4a63e49b322c17967b1c64f5f7` 两条来源提交。

打包可在独立 bare repository 中从主仓库只读 fetch 所需 OID，建立临时来源
ref 后生成 bundle；主仓库的 ref、分支和索引保持原状。迁移时先校验 bundle
SHA256 与 `git bundle verify`，再将其中 ref fetch 到目标仓库并核对来源字节。
后续 catalog revision 改变时重新计算需要携带的来源，不复用旧清单作新来源证明。
bundle 仅保存可达 Git 对象，不能代替工作区、索引或安装快照的备份；不要用
reset 或覆盖用户修改完成恢复。当前备份与恢复证据位于
`selfworkflow/20261013-workflow-followup/`，该目录不自动加入 Git。

The runtime manifest is `<snapshot>/artifact-manifest.json`. Read only identity
and relevant hashes instead of loading the complete file list or searching old
installation logs. TEA packages its knowledge references and one canonical
assessment entry per name. Nested TEA entries are explicit-only; the main adapter
selects methods without restarting upstream menus, teams or confirmation loops.

Installation result `cleanupPending` separates verified publication from lock
cleanup. A committed install with an unreleased lock returns `applied` and a
visible warning; this is not a rolled-back or uncommitted installation. Do not
delete an unknown/active process's lock. A later conflicting writer still fails
closed. File verification does not attest cleanup or native skill activation.

Ordinary work loads the installed root `WORKFLOW.md` and only the capability
needed for the current stage:

```text
classify briefly
-> locate the owning layer
-> bounded core Design/Plan in every mode; TEA and full Grilling only on explicit user request
-> pre-implementation independent Review only for material architecture/security/persistence/irreversible risk or explicit request
-> Matt TDD RED/GREEN for behavior changes; diagnosing-bugs may compose with it
-> implement only the approved smallest safe change
-> review the complete task package; Full/Deep use one independent reviewer covering Standards + Spec
-> verify the affected behavior before Complete; explicit contract tasks additionally require Host-bound receipts and package-bound verification
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
passes the ordered manifest and verified Skill bytes to one independent
reviewer covering Standards and Spec;
the Host code route uses an explicit `independent-code-review` payload and receipt
contract, while the Grill design route remains `independent-design-review`;
required Skill drift or an unavailable independent context is `unverified` and
cannot be presented as a passed Review. The profile cannot override protected
workflow rules. The schema and read-only validator are in
`schemas/project-review-profile.schema.json` and `selfworkflow project-review
validate --project-root <project-root>`.

Reviewers inherit the current parent model and reasoning settings. There is no
Review-specific model configuration or `review-model` CLI; legacy local files
are left untouched and are not read. Explicit model overrides are rejected.
Context independence is preserved without importing the author's history.
Legacy receipt fields remain null for format compatibility, not model proof.
Reuse unchanged evidence and the existing reviewer for affected rechecks;
avoid redundant calls, but never stop unfinished work because of a token or
call-count budget. Same-model dispatch does not guarantee a cache hit.

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

## Default CodeGraph code provider

默认 `selfworkflow.cmd` 使用安装快照中的 Host 代码和冻结依赖，不继承 `PYTHONPATH`。`--host-info` 返回已校验的 artifact 和 CLI 路径；开发源码改变后须重新 build/install。Python 解释器保留共享安装，但版本、平台和文件 hash 必须匹配，变化后重新构建安装。Host launcher 纳入安装计划的可选 `hostLauncher`，与快照一起验证并可回滚；旧 API/计划仍兼容。

CodeGraph is the default local code-reading Provider and is pinned to
`@colbymchenry/codegraph` `v1.6.2` by `dependencies/locks/codegraph.lock.yaml`.
The Windows installer downloads only the lock's tagged release asset and verifies
the package metadata, archive, package identity and final entry hash before use.
An explicit `-CodeGraphPath` is recorded as a local override and is not treated
as a reproducible managed runtime.
The official `codegraph serve --mcp` entry remains responsible for its watcher,
daemon, locking and graph implementation; SelfWorkFlow only owns project
boundary checks and lifecycle routing.

Every code task uses the current project root. If `.codegraph/` is missing,
SelfWorkFlow runs a full `init`; stale indexes are synchronized and rebuilt with
`index --force` only when the status requires it. After an Agent writes, deletes,
renames or rolls back code, one `sync` covers the merged changed paths. No Deep,
Topic or conversation graph is required.

```powershell
& "$env:LOCALAPPDATA\SelfWorkFlow\bin\selfworkflow.cmd" provider preflight --project-root D:\project
& "$env:LOCALAPPDATA\SelfWorkFlow\bin\selfworkflow.cmd" provider query --project-root D:\project --query "Where is the request flow?"
& "$env:LOCALAPPDATA\SelfWorkFlow\bin\selfworkflow.cmd" provider sync --project-root D:\project --changed-path Source\main.cpp
```

The project `.codegraph/` directory is a local, reproducible cache and is not
automatically added, committed or pushed. An explicitly requested cleanup may
remove a legacy `<repo>\graft\` cache; it is not used as CodeGraph input.

## Code reading

CodeGraph is the only code-graph Provider. The official MCP supplies structural
queries; the workflow verifies its project binding and freshness before use.
If CodeGraph is unavailable, the workflow reports `unverified`; `rg` remains
available for exact text but is not structural evidence. A missing project map
is initialized automatically, and a stale map is synchronized and rebuilt when
required. No Deep, Topic or conversation binding is involved.
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
  CodeGraph source binding, non-executing source inspection, write-ahead
  CAS-protected installer, automatic project-index lifecycle and content-addressed
  maintenance planning are implemented and automated-tested. The checked-in V3
  request intentionally remains `paused`
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
- Codex CLI/Desktop, Claude Code, Cursor, OpenCode, and DeepSeek Harness (DSH)
  remain `experimental-unverified`; Copilot is `instructions-only` and unknown
  Agents use the generic bootstrap and the composed `unknown` adapter described
  in [Agent integration boundaries](adapters/README.md). The portable text lives once in
  `adapters/shared/policy.md`; each `adapters/<id>/` entry holds only that host's
  delta plus its `adapter.yaml` declaration. A new policy adapter is data, not
  code; automatic installation and MCP configuration remain separate integrations.
  Hosts without genuine differences can reuse the unknown bootstrap. See
  [Agent integration boundaries](adapters/README.md). Codex and DSH both receive
  the composed shared policy and their own notes from the installer. DSH
  is `agent-policy` only: it has a managed `AGENTS.md` root and async `subagent`
  Review mapping, not a conforming Host contract or a managed MCP profile writer.
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

## Skill 与工作流维护

`anthropics/skills` 通过 `dependencies/upstream/anthropic-skills` submodule 固定版本接入。
normal 依赖初始化只按父仓库 gitlink 同步；runtime 打包同时验证
`dependencies/locks/anthropic-skills.lock.yaml`、Git tree、dirty 和所选文件 hash。

当用户明确要求新增、融合、改造个人 Skill/工作流或优化触发时，加载
`workflow-skill-maintenance`。例如“把新的科学绘图 Skill 接入个人工作流”。
普通开发、写文档、绘图或使用现有 Skill 不加载此维护入口。

运行时只发布一个本地维护入口；上游 skill-creator 的完整方法引用和许可证位于
`references/anthropic-skills/skill-creator`，不进入日常 Skill 发现树。
安装后的入口按当前对话 bootstrap 的 snapshot 绝对根定位引用。
上游 Claude CLI/API 和评测脚本按宿主能力与本次授权选择，不自动运行。

本能力支持普通 agent-policy 的维护任务；不新增 V2/V3 契约阶段或调度器。
源仓库变更经验证后，使用现有安装流程更新个人 snapshot 才会进入新会话。
不要通过整库安装或覆盖其他 skill-creator 入口重复接入。

## 文档、界面与 Obsidian 能力

三个社区来源作为固定 submodule 加入 normal 依赖集，并以 commit、Git tree、
干净状态和所选文件 hash 验证。个人发现目录只增加以下五个窄入口：

| 入口 | 自动触发 | 邻近任务不触发 |
| --- | --- | --- |
| `ui-ux-pro-max` | 实际 UI 的视觉、布局、交互和可访问性设计 | UI 线程崩溃、GPU 性能、文档排版、静态科学图 |
| `content-research-writer` | 文章、教程、专题报告的研究与实质写作 | 短问答、摘要、翻译、工作报告、内部计划/Review、仅导出格式 |
| `obsidian-markdown` | 明确 Obsidian 笔记的专属 Markdown 语法 | 普通 Markdown、README、SKILL.md、通用 frontmatter |
| `obsidian-bases` | Obsidian Bases/.base 与笔记筛选视图 | Excel/CSV、SQL、Redmine、通用知识库 |
| `json-canvas` | JSON Canvas/.canvas/Obsidian 画布文件 | 泛称流程图、Mermaid、HTML canvas、PNG/SVG |

来源分别为 `dependencies/upstream/ui-ux-pro-max`、`composio-skills`、
`obsidian-skills`，锁位于 `dependencies/locks/<source-id>.lock.yaml`。
完整的所选方法与支持文件位于运行时 `references/community-skills/<source-id>/`，
不进入 Skill 发现树。入口按当前 bootstrap 的 snapshot 定位并校验引用。
UI 搜索使用同目录数据与 Python 标准库；只在需要时执行，不默认持久化设计系统。
Composio 仅接入 `content-research-writer`，不会安装整库连接器。
Obsidian 不自动扫描或写入未授权 vault，也不代替知识后端确认流程。

UI 与 Obsidian 保留 MIT LICENSE；Composio 所选 writer 无单独 LICENSE，
保留 README 的 Apache-2.0 声明，并在锁中标记为 `declared`。
触发描述与正负案例审查不等于真实模型触发率或 Token 节省测量。
使用现有受管安装流程更新个人 snapshot 后，新会话即可发现这些入口。

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
