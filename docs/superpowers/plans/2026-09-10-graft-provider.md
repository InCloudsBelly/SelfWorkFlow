# SelfWorkFlow Graft Provider Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Graft 作为 SelfWorkFlow 的正式代码图 Provider，纳入锁定 Submodule、受控安装、项目内图缓存、no-refresh 查询和 Host-neutral 写入 Worker，并替代默认 CodeGraph 路由；Deep 语义图和厂商专属原生 Hook 另行实施。

**Architecture:** Graft 源码固定在 `dependencies/upstream/graft`，由锁文件绑定身份；Installer 校验并构建 Submodule 入口，图缓存仍由 Graft 写入项目目录。正式 Adapter 通过受控 CLI 提供证据，查询固定 no-refresh；显式 Graft 证据任务失败关闭。Host 在 Agent 写入完成后发送 `agent_write`，SelfWorkFlow 合并路径并运行结构 Worker；不启用后台刷新、文件 Watcher 或 Deep。

**Tech Stack:** Python 3.11, unittest, PyYAML/jsonschema, Node >=20, npm lockfile, PowerShell, Graft tree-sitter/CLI/MCP。

---

> 实施状态：Submodule、锁文件、来源校验、只读 Adapter、项目预检、`agent_write` 事件合并 Worker、Provider Manager、默认路由、Installer 构建门禁及对应测试已落地。Deep 构建、知识扩展和厂商专属原生 Hook 仍是后续边界，不能据此宣称已支持。

## 1. 固定范围

### 允许修改的组件

- Graft Submodule、Submodule 锁和现有 Submodule profile 扩展点。
- SelfWorkFlow v3 Provider、Provider binding、support matrix、Catalog 和 Provider 配置 Schema（仅在必要时）。
- SelfWorkFlow Installer、Provider 管理 CLI 和受控 Host Hook/Worker 扩展点。
- 已配置知识生命周期中的 `knowledge.propose` 扩展点，用于在用户启动个人 Wiki 沉淀后自动生成一次受限 Deep 增强材料。
- Graft 专属单元测试、Installer 测试、合成项目验收测试和新增文档。
- CodeGraph 默认路由、安装 UX 和说明的迁移清理；保留用户已有 CodeGraph 配置为 `legacy/orphaned`，不自动删除。

### 不可修改/不可自动扩大

- 当前文档阶段不修改任何实现文件。
- 实施阶段不修改受保护生命周期、证据模型、通用分类、公共 API/ABI、持久化 Schema、全局宏或共享热路径。
- 不启用 Graft 自带竞争性 Hook、文件系统 Watcher、全局守护进程或未锁定网络安装。
- 不扫描所有项目，不把图放入 C 盘或机器级缓存，不扫描任意 Ignore 目录。
- 不让查询触发刷新，不让自动 Worker 调用 Deep。
- 不让 Deep Wiki 增强绕过 `knowledge.propose`、人工确认或 `knowledge.update` 的 CAS；不自动发布生成内容。
- 不执行暂存、提交或自动删除用户文件。

## 2. 文件映射

下表是计划中的候选文件边界。实际实现前必须以当前工作树和锁定 Graft 版本重新确认；本轮未修改这些路径。

| 未来文件 | 作用 |
| --- | --- |
| `.gitmodules` | 注册 `dependencies/upstream/graft` Submodule |
| `dependencies/locks/graft.lock.yaml` | 固定 URL、Gitlink、树摘要、包/构建身份、许可证和 Adapter 哈希 |
| `src/selfworkflow/v3/submodule_profiles.py` | 复用并扩展 Submodule 来源和身份校验 |
| `src/selfworkflow/v3/providers/graft.py` | 新增正式 Graft Adapter、命令模板、输出边界和收据字段 |
| `src/selfworkflow/v3/provider_manager.py` | 注册 `graft` Provider、能力检查和生命周期路由 |
| `src/selfworkflow/v3/provider_config.py` | 读取 Graft 本地绑定、运行时和 Deep 受控配置 |
| `src/selfworkflow/v3/provider_binding.py` | 实现项目根目录、图路径和身份绑定校验 |
| `src/selfworkflow/v3/support_matrix.py` | 声明 Graft/C++/TypeScript/Python/Host 的已验证支持范围 |
| `providers/v3/catalog.yaml` | 将 Graft 注册为正式 Provider 并移除 CodeGraph 默认路由 |
| `providers/v3/graft.yaml` 或等价 Provider 描述 | 声明 Graft capabilities、命令和 failure semantics |
| `schemas/v3/*` | 只有 Provider 身份/配置确实需要新字段时才扩展；不得为测试便利改公共证据 Schema |
| `scripts/install-selfworkflow.ps1` | 从锁定 Submodule 执行 npm ci/build 并安装受控运行时；处理 Graft 安装而非全局 PATH |
| `scripts/manage-selfworkflow-providers.ps1` | Graft Provider 安装、状态、绑定和遗留 CodeGraph 提示 |
| `scripts/lib/*` | 仅在现有 Installer 辅助层无法覆盖时新增最窄辅助函数 |
| `src/selfworkflow/cli.py` | 暴露正式 Provider 状态、绑定和维护入口；查询入口必须 no-refresh |
| `src/selfworkflow/v3/host_hooks.py` 或现有等价扩展点 | 接收 Agent 修改完成事件，不实现文件 Watcher |
| `src/selfworkflow/v3/graft_update_worker.py` 或现有等价扩展点 | 每项目锁、合并窗口、状态和结构更新执行 |
| 现有 `knowledge.propose` 扩展点（实现时按当前知识后端解析实际路径） | 用户启动 Wiki 沉淀后触发一次 Deep 增强，并把结果作为提案材料 |
| `tests/unit/v3/test_graft_adapter.py` | Adapter 命令、退出码、输出上限、脱敏和 no-refresh 单元测试 |
| `tests/unit/v3/test_provider_manager.py` | Provider 注册、能力状态、绑定和失败降级测试 |
| `tests/unit/v3/test_graft_binding.py` | 项目内路径、Ignore、Reparse Point 和边界失败测试 |
| `tests/unit/v3/test_graft_update_worker.py` | 事件合并、锁、查询不触发、失败状态和重试测试 |
| `tests/installer/test_submodule_profiles.py` | Graft Submodule/lock/provenance 校验 |
| `tests/installer/test_one_click.py` | 构建、安装、离线/损坏依赖和运行时身份测试 |
| `tests/acceptance/test_v3_provider_workflow.py` 或新 Graft acceptance | 正式 Provider 工作流、证据和 CodeGraph 迁移测试 |
| `tests/fixtures/graft-repos/*` | C++、TypeScript、Python 最小合成项目；只存测试输入，不存真实图缓存 |
| `docs/providers/graft.md` | 面向使用者的安装、查询、更新和故障处理说明 |
| `docs/superpowers/specs/2026-09-10-graft-provider-design.md` | 已确认设计基线；变更需重新 Review/确认 |

CodeGraph 旧文件的删除/修改只能作为后续独立迁移任务的一部分，不得在实现 Graft 基础能力时顺手扩大范围。

## 3. 实施任务

### Task 1 — 锁定 Graft 来源与 Submodule 身份

- [ ] 为 `dependencies/upstream/graft` 增加 Submodule 注册和锁文件测试。
- [ ] RED：使用缺失 Gitlink、错误 URL、脏树、树摘要不匹配的 fixture，确认安装前拒绝。
- [ ] 实现 Submodule profile/lock 校验，记录 Gitlink commit、树摘要、包版本、许可证和 Adapter 输入哈希。
- [ ] GREEN：复用当前测试入口运行来源、身份和失败路径测试。
- [ ] 仅在用户明确授权后执行实际 Submodule 写入；不执行暂存或提交。

未来验证入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests/installer/test_submodule_profiles.py
```

### Task 2 — 从锁定 Submodule 构建并安装受控运行时

- [ ] RED：锁文件/lockfile/Node 版本不满足时，Installer 必须失败关闭且不使用全局 Graft。
- [ ] 实现 `npm ci`、构建、产物身份记录和 SelfWorkFlow 管理的本机运行时目录。
- [ ] 限定 Node >=20 和项目锁定 lockfile；禁止临时 `npx`、全局 PATH 和未锁定网络包作为正式入口。
- [ ] GREEN：验证可执行性、版本、路径、来源和离线失败语义。
- [ ] 明确运行时目录与项目图目录分离；图不得写入运行时目录或 C 盘。

未来验证入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests/installer/test_one_click.py
```

### Task 3 — 实现正式 Graft Adapter

- [ ] RED：断言命令模板缺少仓库根目录、缺少 no-refresh、越权环境、超长输出和未脱敏 Key 时拒绝。
- [ ] 新增 `src/selfworkflow/v3/providers/graft.py`，固定 `map`、`ask`、`callers`、`grep`、`check` 等结构查询模板。
- [ ] Adapter 为每次调用绑定 Provider ID、运行时身份、项目图身份、输入摘要、受控环境和退出码。
- [ ] 查询强制 `--no-refresh` 或 `GRAFT_NO_REFRESH=1`；不接受调用方取消该约束。
- [ ] GREEN：使用进程级 fake Graft 和最小 JSON fixture 验证成功、失败、超时、截断、脱敏和 stale 状态。

未来验证入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests/unit/v3/test_graft_adapter.py
```

### Task 4 — 实现项目内图路径与 Ignore 边界

- [ ] RED：验证项目外路径、Reparse Point、未忽略路径、已取消 Ignore 和任意猜测目录都被拒绝。
- [ ] 实现绑定优先、`<repo>/graft` 兜底、锚定 `/graft/` Ignore 规则和 `graft-cache-boundary-invalid`。
- [ ] 复用已登记且稳定的 ignored 目录时，重新验证路径、归属和用途；不扫描任意 ignored 目录。
- [ ] GREEN：在 Windows 合成项目中验证大小写、相对路径、删除、重建和并发边界。
- [ ] 测试断言没有任何暂存或提交操作；文档和测试不得调用暂存命令。

未来验证入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests/unit/v3/test_graft_binding.py
```

### Task 5 — 增加修改后合并 Worker

- [x] RED：连续修改事件只产生一次最终结构更新；查询、Review 查询和普通读取不产生更新事件。
- [x] 接入 Host-neutral 的“Agent 修改完成”事件入口，不实现文件系统/编辑器 Watcher。
- [x] 实现每项目单锁、持久化队列、事件合并、诊断和失败可重试语义；不引入后台 daemon 或取消正在运行的进程。
- [x] Worker 只调用结构 build，不调用 Deep；边界无效时暂停并降级。
- [x] GREEN：验证成功、失败、重复事件、并发锁和 stale 图行为。

未来验证入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests/unit/v3/test_graft_update_worker.py
```

### Task 6 — 注册正式 Provider 与支持矩阵

- [x] RED：来源身份、Provider 绑定或 Provider ID 错误时，能力检查不得通过。
- [x] 注册 `graft` Provider；结构能力与可选语义能力保持分离。
- [x] 让正式 CLI 查询成为证据路径；MCP 作为带 no-refresh 环境的交互入口。
- [x] Provider Manager 支持 Graft 状态、查询、预检、事件和 Worker 路由。
- [x] GREEN：Provider Manager、来源绑定、no-refresh 和失败诊断测试通过。

未来验证入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests/unit/v3/test_provider_manager.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests/acceptance/test_v3_provider_workflow.py
```

### Task 7 — 迁移 CodeGraph 默认路由

- [x] RED：默认代码图路由不应再把 CodeGraph 当作默认 Provider；既有 CodeGraph 配置必须保留。
- [x] 将默认 Provider、安装 UX、维护入口和说明切换到 Graft。
- [x] 保留旧配置读取/提示，不自动删除机器文件、缓存或用户变更。
- [x] 未删除 CodeGraph 源码；它仍只能走显式 legacy/用户本地路径。
- [x] GREEN：Provider/Installer/acceptance 迁移测试通过。

这一步已按用户确认实施；后续再改变默认 Provider 仍须重新设计、Review 和确认。

### Task 8 — MCP 配置与 Deep 受控路径

- [ ] RED：MCP server 在未设置 Key 时仍可提供结构能力；MCP 查询不得 refresh；Deep 未批准时必须拒绝。
- [ ] 由 SelfWorkFlow 生成/维护 MCP 配置，注入受控运行时和 `GRAFT_NO_REFRESH=1`。
- [ ] 不启用 Graft 自带竞争 Hook；不把凭据写入仓库、命令行、配置快照或收据明文。
- [ ] 把普通 `build --deep` 保持为显式维护操作，记录模型、Base URL、输入摘要、敏感数据确认和结果状态。
- [ ] 为个人 Wiki 的 `knowledge.propose` 增加一次性 Deep 增强入口：用户启动知识沉淀后自动执行一次，但只读取提案范围。
- [ ] Deep 结果只写入知识提案材料；`knowledge.update` 仍要求用户确认和后端 compare-and-swap。
- [ ] GREEN：验证 no-key structural、Deep missing-capability、redaction 和用户拒绝路径。

### Task 9 — Wiki Deep 知识增强

- [ ] RED：没有用户启动的 `knowledge.propose` 时不触发 Deep；同一提案版本重复进入时不重复调用。
- [ ] 实现提案范围、内容哈希、Graft/模型身份和一次性 Deep 结果的绑定。
- [ ] 默认只处理提案涉及的文件和结构关系；范围参数不可用时报告 `unverified`，不得静默扩大到全仓库。
- [ ] 将 Deep 输出作为 Wiki 草稿增强材料，保留职责、约束、依赖、关键逻辑和不确定项；不直接发布。
- [ ] GREEN：验证成功、无 Key、用户拒绝、敏感范围拒绝、远程失败、输出不可信和后端 CAS 失败路径。

### Task 10 — 原生验收

- [x] 为 Worker/绑定准备最小项目 fixture，并覆盖项目内路径、Ignore、失败重试和并发锁。
- [ ] 通过真实构建、查询、修改、Worker 更新和再次查询验证结构变化；安装后执行一次实际项目验收。
- [x] 验证查询不主动 build；更新只写项目图和 SelfWorkFlow 状态，不执行暂存或提交。
- [ ] 在具体 Agent 的原生 Hook 上验证编辑事件；当前仅声明 Host-neutral CLI 入口已支持。
- [x] 验证 Graft 失败时普通任务使用 `rg`，显式新鲜图证据任务失败关闭。

### Task 11 — Review、验证与交付

- [ ] 完成完整 diff Review，确认只修改批准组件、没有隐式 CodeGraph/生命周期扩大。
- [ ] 运行单元、Installer、acceptance、可用 Host 和文档链接/格式检查。
- [ ] 对每个 Minor Review finding 记录 disposition；Critical/Important 必须关闭。
- [ ] 生成新鲜验证收据，包含命令、工作目录、退出码、失败数、时间范围和消费者结果。
- [ ] 完成后只交付工作树状态；提交/合并/清理需要用户另行明确授权。

## 4. 验证矩阵

| 验收对象 | 直接验证 | 失败路径 | 证据 |
| --- | --- | --- | --- |
| Submodule/锁 | commit、树摘要、lockfile、许可证和 Adapter 哈希一致 | URL/commit/树/lockfile 漂移 | Installer receipt |
| 安装运行时 | Node/npm、构建产物、版本和来源 | 无 Node、依赖损坏、网络不可用、运行时越权 | Installer tests |
| 图路径 | 项目内、ignored、非 Reparse、稳定绑定 | 项目外、取消 Ignore、Reparse、删除 | Binding tests |
| 查询 | `--no-refresh`、无图写入、输出可解析 | Graft 缺失、超时、坏 JSON、stale | Adapter receipt |
| 修改更新 | 事件合并、锁、最终 build | 重复事件、崩溃、并发、构建失败 | Worker tests |
| Provider | Catalog、capability、binding、evidence | 身份漂移、能力 unverified | Provider tests |
| CodeGraph 迁移 | 默认选择 Graft，旧配置遗留 | 旧配置误删、仍被默认路由 | Acceptance tests |
| Host | Codex 修改后更新，查询不更新 | Hook 不可用、事件缺失 | Native receipt |
| Deep | 手动批准、受控远程调用、脱敏 | 未批准、无 Key、能力 drift | Manual/acceptance evidence |
| Wiki Deep | `knowledge.propose` 后一次/提案版本，范围受限且只进入提案 | 无确认、超范围、重复调用、后端 CAS 失败 | Knowledge proposal receipt |

建议的当前仓库统一测试入口是：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test <test-path-or-selector>
```

不要以系统 Python 直接运行测试替代仓库入口；具体 selector 由实现时现有 `scripts/test.ps1` 的参数契约确认。

## 5. 回滚与恢复

- Graft Provider 未通过验证时，恢复到无图的 `rg` 代码阅读路径；不恢复 CodeGraph 为默认 Provider。
- Worker 失败时保留旧图并标记 stale，暂停自动更新，允许用户显式重试。
- 项目缓存边界无效时停止写图；修复 Ignore/绑定后再初始化，不把图迁移到机器目录。
- 安装失败时保留旧的 SelfWorkFlow 运行时，不删除用户配置；撤销 Graft Provider binding 即可停用。
- CodeGraph 配置只标记为遗留，不自动删除；需要用户后续明确授权才可清理。
- 任何超出本计划 owner/component/侵入性预算的变更都回到设计和确认阶段。

## 6. 完成门槛

未来实现只有在以下条件同时满足后才能声称完成：

1. 代码实施契约已审阅且获得明确实施确认。
2. TDD RED/GREEN 证据真实对应预期行为和最窄回归路径。
3. 完整 diff 的 Standards/Spec Review 通过，Critical/Important 为零，Minor 均有 disposition。
4. Installer、Provider、Worker、Host 和三类合成项目验证均有新鲜收据。
5. 查询无写入、修改自动更新、项目内图边界、无暂存/提交、CodeGraph 遗留保护均有直接证据。
6. 代码编辑 Worker 和查询不会触发 Deep；个人 Wiki 只在用户已启动的 `knowledge.propose` 中自动执行一次，且受外部数据确认、范围限制、提案审核和可审计收据约束。

当前安装前仍须完成 Task 10 的真实项目验收和 Task 11 的完整 diff Review；未完成项必须保持 `unverified`，不能宣称全部边界已验收。
