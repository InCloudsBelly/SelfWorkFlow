# SelfWorkFlow v1 原生宿主与 C7OpenWiki 验收细化

本文件是 `2026-08-07-selfworkflow-v1.md` 的可执行子计划，只覆盖不能由静态或模拟测试替代的真实验收。任何凭据只由宿主自身读取，不进入 Git、命令输出或测试证据。

## A. Codex CLI

### A1. 固定当前失败边界

依次运行并记录退出码、标准错误 hash 和解析路径，不记录 token：

```powershell
Get-Command codex -All | Select-Object CommandType,Name,Source,Version
where.exe codex
codex --version
codex login status
```

若 WindowsApps 入口仍为 `Access is denied`，检查文件 ACL、App Execution Alias、包版本和 `codex doctor` 是否可进入。先区分“入口不可执行”“CLI 未安装”“认证失败”“模型不可用”和“SelfWorkFlow 适配失败”。

### A2. 使用可追溯官方 CLI

若 A1 已找到 `--version`、`login status` 均成功的现有官方 CLI，记录路径、版本和文件 hash 后直接使用，不安装。若缺失或 WindowsApps 入口不可执行，在 Task 10 尚不存在时允许使用 Task 1 已经 fake-npm TDD 验证的独立 bootstrap。先准备位于 `%LOCALAPPDATA%\SelfWorkFlow\bootstrap\toolchains` 预存受保护 anchor 下的 portable Node/npm toolchain，再执行 Discover。Discover 完整验证 toolchain 后只执行一次 metadata view，不创建或修改 Codex install target：

```powershell
$planJson = powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap-codex-cli.ps1 -Mode Discover -BootstrapRoot "$env:LOCALAPPDATA\SelfWorkFlow\bootstrap\codex-cli" -ToolchainRoot <approved-toolchain-root>
[IO.File]::WriteAllText(<confirmed-plan-path>, $planJson, [Text.UTF8Encoding]::new($false))
```

Discovery 输出 `planSchemaVersion: 2` 完整计划，包含 node/npm entry 与完整 toolchain inventory/hash、精确 version/integrity、固定 argv/env/cwd、规范化目标、private DACL、预计副作用、卸载边界和 plan hash。用户审阅保存的完整计划并明确确认其 hash 后才执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap-codex-cli.ps1 -Mode Apply -ConfirmedPlanPath <absolute-confirmed-plan-path> -ConfirmPlanHash <actual-discovery-hash>
```

Apply 在任何外部进程和写入前锁定计划，精确校验 shape、三方 hash、静态执行语义及全部 toolchain identity；它不重复 metadata view。随后创建空目录，用 .NET 应用并独立回读 current-user SID + SYSTEM 的 protected DACL，再以绝对 node/npm entry、固定 cwd 和精确环境白名单执行 install。成功后写 `bootstrap-tool-manifest.json`（符合 `schemas/bootstrap-tool-manifest.schema.json`），绑定路径、version、integrity、package tree hash、SDDL、`expectedCliVersion` 和 `cliVersionVerification: "not-run"`。Task 1 bootstrap 不执行 Codex；本节 A3 的真实启动才产生 CLI 行为证据。Task 10 只接管合法 manifest；字段、hash、路径或 SDDL 漂移即拒绝，不重复安装。登录或账号变化仍需另行授权；不得复制、打印或提交 `auth.json`。

### A3. 临时安装态测试

创建临时 Git 仓库，将待发布 `AGENTS.md` 薄入口和 `.agents/skills/<stable-id>` 快照装入其中，以项目级发现验证同一内容；认证继续由现有 Codex Home 管理，命令使用 `--ignore-user-config`，官方行为是忽略配置但保留认证。

只读场景使用独立 `codex exec --ephemeral --json --sandbox read-only --ask-for-approval never --ignore-user-config --cd <fixture-repo> --output-schema <scenario-schema> -`；写任务改用 `--sandbox workspace-write`。完整 prompt 来自以下版本化文件：

- `tests/acceptance/codex-cli/c0-readonly.md`
- `tests/acceptance/codex-cli/c1-change-paused.md`
- `tests/acceptance/codex-cli/c2r2-design.md`
- `tests/acceptance/codex-cli/grill-explicit.md`
- `tests/acceptance/codex-cli/missing-superpowers.md`
- `tests/acceptance/codex-cli/skill-minimality.md`
- `tests/acceptance/codex-cli/write-tdd.md`
- `tests/acceptance/codex-cli/review-write-result.md`

Schema 要求输出 `classification`、`capabilities`、`instructionSources`、`selectedSkills`、`stagesObserved`、`paused`、`verification` 和 `residualRisks`。每个被选 Skill 含一个仅正文可见的测试 nonce；未选 Skill 含不同 nonce。通过条件是选中 nonce 可见、未选 nonce 不可见、无未授权写入，且 JSONL 中没有与声明矛盾的命令或文件变化。

写任务仓库预置一个最小 Python 缺陷和证明原始症状的失败测试。第一会话必须保留真实 Red 输出，再只修改允许文件，使直接/失败路径 Green 并生成 diff/evidence；第二个全新、read-only 会话只接收验收条件、完整 diff 和测试证据，执行独立 Review。由于 `--ephemeral` 不可恢复，Review 通过后由确定性 harness 直接重跑最终测试、检查 diff/允许路径/状态不变量并生成 verification evidence；不得声称恢复第一会话，也不能只相信 Agent 自报阶段。

### A4. 正式全局发现

只有正式安装计划经用户确认并 apply 后，运行两个新 `--ephemeral` 会话：一个查询 active instruction sources，一个执行 C2/R2 场景。没有全局 override 时必须看到 `~/.codex/AGENTS.md`；存在非空 `AGENTS.override.md` 时必须证明 Doctor 已暂停、用户选择了 override 合并策略，并只看到该 override 中的托管块；两种情况都必须看到 `$HOME/.agents/skills` 的版本化 Skill。临时项目级结果不能替代此检查。

## B. Codex Desktop

正式安装后生成带随机 nonce 的 `tests/acceptance/codex-desktop/prompt.md` 和期望 Schema。由于桌面新任务必须由用户创建或由用户明确授权创建，执行到此处暂停一次：

1. 用户在 `D:\SelfWorkFlow` 新建本地任务，或明确授权 Agent 创建该任务；
2. 新任务不得继承当前实现对话，只接收版本化 prompt；
3. 分别运行只读、C2/R2、显式 Grill-me 与 Skill 最小加载场景；
4. 在隔离合成仓库执行与 CLI 相同的真实写任务：Red、限定路径修改、Green；再由另一个不继承上下文的新 Desktop 任务做只读独立 Review，最后回到实现任务运行最终验证；
5. 记录 App 版本、task ID、输入/输出 hash、仓库前后 tree、真实 diff、测试输出、选中 Skill、阶段、Review 隔离和验证结论；
6. 用 nonce 证明读取的是正式安装态 Skill 正文，不以当前会话记忆代替。

Codex CLI 和 Desktop 必须各自通过，才把 Codex 状态改为 `supported`。

## C. C7OpenWiki MCP

### C1. 锁定来源与保护正式 Wiki

执行前记录但不输出敏感文件内容：

- `D:\openwikiC7` HEAD、branch、tracked dirty 清单；
- 未跟踪 `c7-openwiki` 的确定性文件 manifest/tree hash，排除 `node_modules`、build、runtime、凭据和临时文件；
- `D:\openwikiC7\c7-openwiki\runtime\wiki\**\*.md` 的正式 Wiki tree hash；
- `runtime/config.json`、`credentials.json` 仅记录存在性和不可逆摘要，不复制到 SelfWorkFlow。

任何 provenance hash 变化都使旧验收失效。

### C2. 验证能力证据

先记录 C7 工作树快照，再运行：

```powershell
pnpm verify:capabilities
```

工作目录固定为 `D:\openwikiC7\c7-openwiki`。命令必须通过并生成与当前代码、契约、依赖、Skill、测试和 build hash 匹配的 `runtime/verified-capabilities.json`。运行后再次读取 Git 状态；出现新的 tracked 变化即暂停并报告，不回滚用户文件。

### C3. 独立 runtime 与 stdio Harness

在 C7 允许的默认 runtime 根内部创建 `runtime/selfworkflow-acceptance-<run-id>`，复制当前 capability evidence，不复制正式 Wiki、配置或凭据。由 harness 设置环境并 spawn server，禁止先在当前终端直接运行会占用 stdio 的 server：

```powershell
node scripts/c7-openwiki-acceptance.mjs --server D:\openwikiC7\c7-openwiki\mcp-server\dist\index.js --runtime <isolated-runtime> --scenario tests\acceptance\c7-openwiki\native.json --artifacts <artifact-dir>
```

`scripts/c7-openwiki-acceptance.mjs` 自行设置 `C7_OPENWIKI_RUNTIME_DIR`，管理 stdin/stdout/stderr、超时、退出和清理，并发送标准 MCP `initialize`、`notifications/initialized`、`tools/list` 和 `tools/call`。Harness 把 JSONL 原始结果写入被忽略的 artifacts，版本化证据只保存脱敏摘要和 hash。

七个工具逐一使用 `tool-contract.json` 中的合法最小输入和非法边界输入。`openwiki_setup` 在独立 runtime 中完成用户选择的模型与 reasoning effort 的真实验证；OAuth 需要用户交互时暂停，不复制正式 token。只有 status 返回 initialized、authorized 且 verifiedModels 精确匹配，才继续。

`openwiki_prepare_sources` 真实负例至少包含已知敏感文件名、PEM 私钥片段、二进制文件，以及 prepare 后再改变内容/hash；全部必须拒绝或使旧确认失效，且不得把原文写入版本化证据。

### C4. Query、Propose 与 Update

- `knowledge.read`：调用 `openwiki_query`，验证正式 Wiki tree hash 不变；允许独立 runtime 内 OAuth 刷新、事务和临时状态变化。
- `knowledge.propose`：调用 query 形成预期 base revision 和候选 diff；“无副作用”严格解释为“不发布 Wiki 内容”，不承诺 OAuth/临时事务零变化。
- `knowledge.update`：仅对独立 runtime 中的合成测试 Wiki 执行。先 `openwiki_prepare_sources` 绑定 manifest；文件变化使确认失效；只有用户明确确认该测试写入后才传 literal `confirmedByUser: true`；验证 CAS、合法终态、强制复审和失败隔离。

测试前后重新计算正式 Wiki tree hash，必须完全相同。最后清理独立 runtime；清理失败记录为 attention，不递归删除未解析或越界路径。

## D. 证据判定

- 静态 Schema、fixture、fake server 或 mock provider 只能得到 `static-conformance-passed`；
- 真实进程启动但未完成登录/模型调用为 `experimental-unverified`；
- 只有输入、版本、环境、输出 hash、退出码和副作用边界均验证后才是 `native-behavior-tested`；
- 任何步骤失败先新增最小 Red/Green 修复任务，修复后从受影响的最早验收点重跑。

## E. 首次安装、升级与回滚

在同一个显式 sandbox/state root 中执行，`<hash>` 必须是 plan 文件的实际 SHA-256，不能用布尔确认替代：

```powershell
.venv\Scripts\python.exe -m selfworkflow.cli build --version 0.1.0.dev0 --output build\runtime-dev0
.venv\Scripts\python.exe -m selfworkflow.cli install plan --artifact build\runtime-dev0 --agents-root <sandbox-agents> --codex-root <sandbox-codex> --state-root <sandbox-state> --output build\install-dev0.json
.venv\Scripts\python.exe -m selfworkflow.cli install apply --plan build\install-dev0.json --confirm-plan-hash <dev0-hash>
.venv\Scripts\python.exe -m selfworkflow.cli install verify --manifest <dev0-manifest>
.venv\Scripts\python.exe -m selfworkflow.cli build --version 0.1.0 --output build\runtime-0.1.0
.venv\Scripts\python.exe -m selfworkflow.cli install plan --artifact build\runtime-0.1.0 --agents-root <sandbox-agents> --codex-root <sandbox-codex> --state-root <sandbox-state> --output build\install-0.1.0.json
.venv\Scripts\python.exe -m selfworkflow.cli install apply --plan build\install-0.1.0.json --confirm-plan-hash <candidate-hash>
.venv\Scripts\python.exe -m selfworkflow.cli install rollback-plan --transaction <candidate-upgrade-transaction-id> --output build\rollback-to-dev0.json
.venv\Scripts\python.exe -m selfworkflow.cli install rollback --plan build\rollback-to-dev0.json --confirm-plan-hash <actual-rollback-plan-hash>
.venv\Scripts\python.exe -m selfworkflow.cli install apply --plan build\install-0.1.0.json --confirm-plan-hash <candidate-hash>
```

在 baseline、candidate、rollback 和 candidate-restored 四个点分别保存托管文件 hash、非托管 tree hash、manifest 和 SDDL。预期版本序列为 `0.1.0.dev0 -> 0.1.0 -> 0.1.0.dev0 -> 0.1.0`，非托管 hash 全程不变。
