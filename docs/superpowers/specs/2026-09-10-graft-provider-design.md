# SelfWorkFlow Graft Provider 设计

**日期：** 2026-09-10
**状态：** 设计已获用户确认；Submodule、来源锁、Adapter、工作流路由、项目预检、事件合并和结构 Worker 已实现。专题 Deep 正在按本次修订接入；各厂商原生 Host Hook 仍是独立边界。
**范围：** 个人工作流中的代码结构索引、关系查询和 Agent 修改后的自动结构更新

## 1. 背景与目标

Graft 提供本地代码图、结构关系查询、仓库地图、符号调用链和可选的深度语义摘要。它的结构索引不要求 API Key，图可以重新生成；深度语义分析才需要配置模型 Provider。Graft 的公开入口、初始化选项和 MCP 工具见 [Graft README](https://github.com/trailhq/Graft/blob/main/README.md)、[CLI 实现](https://github.com/trailhq/Graft/blob/main/src/cli.ts) 和 [MCP 工具实现](https://github.com/trailhq/Graft/blob/main/src/mcp/tools.ts)。

本设计将 Graft 接入 SelfWorkFlow 的正式 Provider 体系，并完全替代默认 CodeGraph 路径，目标是：

- 把 Graft 的来源、版本和构建身份纳入个人工作流的 Submodule 治理。
- 让正式 Provider 可参与能力检查、Provider 绑定、代码阅读、Review 和证据链。
- Agent 修改代码后自动触发一次合并后的结构更新；纯查询不触发更新。
- 把图和指纹放在当前项目目录内的稳定忽略目录中，不写入 C 盘缓存，不改变索引状态，不执行暂存操作。
- 保留结构查询失败时的可用降级路径；显式要求 Graft 证据的任务则严格失败关闭。
- 保留 Graft 的 MCP 体验，但把 MCP 定义为交互便利层；正式工作流证据通过受控 CLI 入口取得。
- 支持一个对话一个专题的持续 Deep 上下文：全局 structural Map 与专题 Deep 分开，专题只对明确文件范围执行。

本实现批次已修改 Submodule、来源锁、Adapter、安装器构建门禁、工作流代码模块、项目生命周期 Worker 和相关测试；不修改公共生命周期/证据 Schema、业务 API/ABI、Wiki 数据或用户现有 CodeGraph 配置。Worker 接收统一 `agent_write` 事件并先检查绑定 Topic；Topic 过期时优先由同一次 Host 调用继续受范围约束的 Topic Deep，全局结构 Map 延后且不阻塞主任务；Topic fresh 时才执行独立的全局结构 build。

## 2. 范围与非目标

### 范围

1. Graft 的 Submodule 来源、Gitlink 身份、锁定信息和构建安装流程。
2. 正式 `graft` Provider 的能力、绑定、查询和刷新语义。
3. 项目目录内图缓存的路径解析、Ignore 边界和无暂存规则。
4. Agent 编辑完成后的受控、合并、可恢复结构更新 Worker。
5. CodeGraph 的默认路由移除、旧配置保留为遗留状态以及迁移文档。
6. Codex 及其他已配置 Agent Host 的统一 Hook 接口；初始原生验证以 Codex 为主。
7. C++、TypeScript、Python 合成项目的原生验收；不宣称直接覆盖 Unreal 工程语义。
8. 专题 Deep 的范围、增量复用、状态和与通用知识模块的解耦边界。

### 非目标

- 本轮不实现 Graft 自带 Hook、文件系统 Watcher、全局 daemon 或厂商专属原生 Hook；Topic Deep 只通过 SelfWorkFlow 的绑定链路触发。
- 不自动扫描所有项目，不在安装时为未知项目建立图。
- 不把 Graft Deep 语义分析放入全局结构 Worker；已绑定 Topic 的代码写入在 Worker 成功后自动继续原范围 Deep。
- 不启用 Graft 自带的竞争性 Hook；SelfWorkFlow 只维护一个修改事件入口。
- 不把查询操作伪装成新鲜图证据，也不允许查询隐式构建。
- 不把 Deep 生成的 Wiki 草稿直接当作已确认知识或自动发布到知识后端。
- 不自动删除用户机器上的 CodeGraph 配置、缓存或其他遗留文件。
- 不把模型 Key、访问令牌或个人 Provider 配置写入仓库文档、Submodule 或提交。

## 3. 已确认决策

| 主题 | 已确认方案 | 约束 |
| --- | --- | --- |
| Provider 级别 | 正式 Graft Provider | 具备 Catalog、能力声明、绑定、受控命令和证据路径；MCP 只是便利入口 |
| 默认代码图 | Graft 完全替代 CodeGraph | CodeGraph 不作为默认降级 Provider；查询失败时只降级到 `rg` 等无图读取 |
| 来源与身份 | `dependencies/upstream/graft` Git Submodule | 配套 `dependencies/locks/graft.lock.yaml`；记录 URL、Gitlink commit、树摘要、脏文件清单、许可证和 Adapter 绑定哈希 |
| 安装 | 安装流程从锁定 Submodule 构建并安装 Graft 运行时 | 使用项目管理的 Node/npm 构建；不依赖全局 PATH、临时 `npx` 或未锁定网络包 |
| 图位置 | 当前项目目录内 | 优先使用已登记且稳定、已忽略的项目内目录；否则使用 `<repo>/graft` |
| 忽略规则 | 仅在必要时为选定项目目录补充锚定的 `/graft/` Ignore 规则 | 不扫描任意被忽略目录，不猜测业务缓存目录，不执行暂存操作 |
| 自动更新 | Agent 修改代码完成后按当前 `conversation-id` 触发全局 Map，并在绑定 Topic 过期时自动继续该 Topic Deep | 每项目一个锁；可合并重复事件；全局 structural Map 与 Topic Deep 严格分离 |
| 查询 | 查询使用当前图且不刷新 | 使用 Graft 的 `--no-refresh` 或 `GRAFT_NO_REFRESH=1`；查询不得写图、侧车或指纹 |
| Deep | 已绑定 Topic 的代码写入自动触发原范围 Deep；无绑定时仍需显式选择 | 复用当前 conversation 的 Host 模型、Topic 和 scope；不得对根 `graft/` 执行 Deep |
| 专题 Deep | 明确 topic 与文件范围后持续维护一个专题上下文 | 以源文件 hash 增量更新；不按 Git hash 建目录；结果可被知识模块引用但不触发知识发布 |
| 失败 | 普通任务不阻塞，显式图证据任务失败关闭 | 标记 stale/unverified，普通代码阅读降级到 `rg`；不得伪造 Graft 结果 |
| Host | SelfWorkFlow 提供统一受控 Host Hook | 不启用 Graft 自带竞争性 Hook；先验证 Codex，再覆盖其他配置的 Agent Host |
| 首次建图 | 当前项目首次代码任务或首次 Agent 修改时惰性初始化 | 安装阶段不扫描项目；首次更新失败仍保留降级语义 |

## 4. 总体架构

```text
锁定的 Graft Submodule
        │
        ├── 受控 npm ci/build ──> SelfWorkFlow 管理的本机运行时
        │                              │
        │                              ├── CLI formal Provider
        │                              └── MCP interactive convenience
        │
当前项目目录 ──> Project Binding ──> <repo>/graft 或已验证的 ignored cache
        │                              │
        ├── Agent 编辑完成 ──> Coalescing Update Worker ──> Topic freshness
        │                                      ├── stale ──> 原范围 Deep
        │                                      └── fresh ──> 全局结构 build
        └── 代码查询 ────────────────> no-refresh CLI ─────> 只读查询结果
```

### 4.1 来源、身份与安装

Submodule 的规范路径为 `dependencies/upstream/graft`，远端 URL 使用用户指定的 Graft 仓库。锁文件位于 `dependencies/locks/graft.lock.yaml`，由实现阶段根据现有 Submodule 锁治理补齐。锁文件至少应绑定：

- 规范远端 URL 和固定 Gitlink commit。
- 该 commit 的树摘要、预期版本/包身份和构建入口。
- 构建所需 Node/npm 范围及 lockfile 身份。
- 许可证及来源审计信息。
- Graft Adapter 对命令模板、输出解析和运行时版本的绑定哈希。

安装器只从已检出的锁定 Submodule 构建。构建产物可以位于 SelfWorkFlow 管理的本机运行时目录，例如 `%LOCALAPPDATA%\SelfWorkFlow\runtime\graft\<identity>`；这只保存可复用的运行时，不保存项目图。正式 Provider 必须调用该受控运行时，不通过全局 PATH、未锁定下载或临时 `npx` 解析 Graft。

安装时只验证来源、构建和运行时可执行性，不为所有已知项目建图。项目首次进入代码任务或首次发生 Agent 修改时，才惰性创建/刷新该项目的图。

### 4.2 项目图缓存边界

图路径解析按以下顺序执行：

1. 读取当前 SelfWorkFlow 项目绑定；只有当绑定路径规范化后仍位于项目根目录内、不是 Reparse Point、未越过路径边界且通过 Ignore 验证时才接受。
2. 如果没有有效绑定，使用 `<repo>/graft`。
3. 若 `<repo>/graft` 尚未被忽略，只为该项目补充锚定的 `/graft/` 规则；这是明确受控的项目元数据变更，不包含暂存或提交。
4. 不在项目内任意搜索“看起来像缓存”的目录，也不把机器级缓存目录、C 盘目录或其他项目的图当作当前图。
5. 绑定被删除、移出项目根目录、成为 Reparse Point、取消 Ignore 或无法验证时，产生 `graft-cache-boundary-invalid`，暂停自动更新；普通查询降级到 `rg`，需要图证据的任务失败关闭。

图、指纹、侧车和 Graft 的项目上下文文件都必须受同一缓存边界和 Ignore 校验约束。实现阶段应优先复用当前项目已稳定注册且已被忽略的目录；“已忽略”不能单独证明它是可安全复用的业务缓存。

### 4.3 Provider 与能力

Provider ID 为 `graft`。正式能力至少包括：

| 能力 | 含义 | 默认证据语义 |
| --- | --- | --- |
| `code.context` | 项目地图、结构节点、文件 API、精确查找 | 本地结构图，带 Provider 身份和图新鲜度 |
| `code.relationships` | callers、调用链、符号关系和跨文件导航 | 本地结构图，带查询命令、输入摘要和图版本 |
| `code.semantic` | 可选 Deep 语义摘要 | 未绑定 Topic 时仍需显式选择；已绑定 Topic 的写后原 scope Deep 由 Worker 自动维护 |

`code.semantic` 不得因为安装了 Graft 或存在 API Key 就对未绑定 Topic 自动进入默认计划。已绑定 Topic 的写后刷新是该对话既有选择的维护动作；若当前实现或宿主无法提供可验证的 Deep 收据，必须报告为 `unverified`，不能报告为 supported。

正式 Adapter 负责固定命令模板、仓库根目录、受控环境、超时、输出上限、敏感信息脱敏、退出码和新鲜度解析。MCP 可以用于交互探索，但正式 Review/Verify 证据必须经过 SelfWorkFlow 的受控 CLI 入口和收据封装。

专题 Deep 不新增知识发布入口。知识模块可选择读取专题结果作为来源参考，但 Graft 不触发、依赖或写入 Wiki；`knowledge.update` 仍由知识后端自己的确认和 compare-and-swap 负责。

### 4.4 查询与更新分离

| 操作 | 是否允许写图 | 是否自动触发更新 | 说明 |
| --- | --- | --- | --- |
| Agent 修改代码完成 | 是 | 是 | 进入合并 Worker，执行结构更新 |
| Provider 查询 | 否 | 否 | 强制 `--no-refresh`/`GRAFT_NO_REFRESH=1` |
| 首次项目惰性初始化 | 是 | 仅由首个代码任务或首次修改触发 | 不在安装阶段执行 |
| 显式 `build` | 是 | 由用户/计划显式请求 | 可记录为独立维护操作 |
| `build --deep` | 是 | 否 | 未绑定 Topic 时手动、批准、远程能力和敏感数据边界单独确认；绑定 Topic 的写后原 scope 由 Worker 自动执行 |
| MCP 连接 | 否 | 否 | 启动环境固定为 no-refresh；不让 MCP 隐式更新 |
| 专题 Deep | 写入项目内专题上下文 | 首次绑定需明确选择；后续代码写入由 Worker 自动维护 | 范围受限、按源 hash 增量，不直接写知识库 |

Worker 采用每项目单锁、事件去重和短时间合并窗口。Worker 的状态至少区分 queued、running、succeeded、stale、failed、boundary-invalid；失败不回滚到旧图之外的假成功状态。旧图可作为 stale reference，但不能满足需要新鲜 Graft 证据的验收条件。

### 4.5 失败与降级

普通代码阅读任务的降级顺序为：

1. 新鲜的正式 Graft 结构查询。
2. 已存在但 stale 的 Graft 图，仅作为明确标注的只读参考。
3. `rg`、文件读取和其他无图路径。

如果任务的验收标准明确要求 Graft 的结构证据，则第 1 步不可用时直接报告 `unverified`/失败关闭，不把第 2、3 步伪装成 Graft 证据。安装、构建、权限、边界和输出解析错误都要保留可诊断原因；不因普通查询失败而触发隐式安装、网络下载或 Deep 请求。

## 5. Graft 命令与工作流映射

下表是实现阶段的命令契约。命令名称来自 Graft 当前 CLI/MCP 设计；具体参数和输出 Schema 仍需在锁定版本上做原生验证。

| Graft 表面 | SelfWorkFlow 用途 | 更新/证据要求 |
| --- | --- | --- |
| `graft build <repo>` | 项目首次结构初始化、编辑后的结构更新 | 受控 Worker 调用；绑定项目路径和 Graft 身份 |
| `graft map <repo>` | 代码上下文和仓库地图 | Provider 查询；强制 no-refresh |
| `graft ask <question> <repo>` | 结构上下文辅助问答 | 结构查询默认 no-refresh；不自动进入 Deep |
| `graft callers <symbol> <repo>` | 调用者、调用链和关系导航 | Provider 查询；强制 no-refresh |
| `graft grep <pattern> <repo>` | 图辅助的精确查找 | Provider 查询；强制 no-refresh |
| `graft check <repo>` | 新鲜度和健康状态检查 | 只读检查；不得因检查动作刷新图 |
| `graft mcp` | 交互式 MCP Server | 通过 SelfWorkFlow 注入 no-refresh 环境；不是正式收据的唯一来源 |
| `graft build --deep` | 手动深度语义分析 | 单独批准、远程模型、敏感数据、成本和收据边界 |

实现时必须以锁定 Submodule 的 `--help`、JSON 输出和失败路径修正命令模板；不以当前网络 README 的瞬时输出作为永久 Schema 证据。

## 6. CodeGraph 迁移

默认路由、Provider 选择、安装 UX、支持矩阵和相关说明迁移到 Graft 后，CodeGraph 不再作为正式 fallback。迁移应分为独立、可审计步骤：

1. 增加 Graft 的正式 Provider、绑定和能力矩阵。
2. 将默认代码读取路由切换到 `graft`，查询固定 no-refresh。
3. 删除 CodeGraph 的默认安装和维护入口，不删除用户文件。
4. 将已有 CodeGraph 机器配置标记为 `legacy/orphaned`，保留读取和提示能力，禁止自动迁移或自动删除。
5. 通过全量 diff Review 和迁移验收后，才清理不再使用的 CodeGraph Provider 源码/文档。

CodeGraph 的清理属于未来实现阶段的迁移变更，本轮不修改现有 CodeGraph 文件，也不改变当前用户配置。

## 7. Host Hook 与生命周期

SelfWorkFlow 提供统一的“Agent 修改完成”事件接口。Host 只提交受控的项目身份、修改路径摘要和任务身份；Worker 自己重新校验项目根目录、路径边界、扩展名和 Graft 图绑定，不信任 Host 传入的缓存路径。

事件处理规则：

- 代码编辑动作完成后提交事件；连续编辑在合并窗口内合并。
- 纯读取、搜索、Provider 查询、Review 查询和 MCP 查询不提交更新事件。
- Worker 独立维护全局 structural Map，并返回绑定 Topic 的唯一 `nextAction`；Topic stale 时优先在同一 conversation 内继续原范围 Topic Deep，全局 Map 可延后重试且不阻塞主任务。个人 Wiki 的 Deep 仍由 `knowledge.propose` 独立触发。
- 更新失败不阻塞普通任务，但必须形成 stale/unverified 状态和可读诊断。
- 明确要求新鲜图证据的任务必须等待成功收据，否则失败关闭。
- 不启用 Graft 自有 Hook，避免双重更新、双重锁和难以归因的生命周期竞争。

初始验收覆盖 Codex Native Hook；接口设计保持对其他已配置 Agent Host 的可扩展性。文件系统 Watcher、编辑器 Watcher 和全局后台守护进程不在第一版范围内。

### 7.1 专题 Deep 与知识模块

一个对话只绑定一个 `topic-id`。全局 `graft/` 保存非 Deep structural Map，专题上下文保存于项目 `./selfworkflow/graft-deep/<topic-id>/graft`。SelfWorkFlow 将明确的项目内文件清单作为官方 Graft 的重复 `--only-dir`，并以源文件 hash 识别增量变化；不按 Git hash 建目录，不创建临时 Git 仓库，不扫描全仓库。

知识模块完全独立：它可以把专题结果作为可选来源，但不触发 Deep、不依赖 Graft，也不把 Deep 结果直接发布到 Wiki。若官方 Graft 不支持安全的精确范围参数，必须报告 `unverified`，不得扩大范围。

## 8. 安全、隐私与可维护性

- 结构构建和结构查询默认本地执行，不依赖模型 Key 或网络。
- Deep 只能在显式批准后读取限定源文件，必须记录 Provider、模型、Base URL、输入摘要和输出摘要；凭据只来自受控机器环境。
- Adapter 固定允许的环境变量和路径，禁止把 API Key 拼入命令行或收据明文。
- 所有输出有字符/字节上限；错误输出、环境和模型配置需要脱敏。
- Wiki Deep 只读取已批准提案范围，结果先进入提案材料；不得绕过知识后端的人工确认和发布 CAS。
- 图缓存只在项目目录内，绑定不可越过项目根目录；Reparse Point、路径别名和 Ignore 取消均失败关闭。
- 构建身份、运行时身份和图身份分开记录；运行时缓存位置不能推导项目图位置。
- 影响范围限定在 Provider、安装/构建、Host Hook、Worker 和测试适配层；不为测试便利修改公共业务 API、持久化格式或共享热路径。

## 9. 侵入性预算与不可越界项

### 允许范围

- 新增 Graft Provider 和其本地配置/绑定描述。
- 在现有 Submodule/Provider/Installer 扩展点注册 Graft。
- 增加受控 Host Hook 到 Worker 的窄接口。
- 增加 Provider 专属单元、安装器测试和合成项目验收测试。
- 删除 CodeGraph 的默认路由和安装 UX，但保留遗留配置的非破坏性识别。
- 必要时只为 Graft 图补充项目根目录 `/graft/` Ignore 规则。

### 不允许自动扩大

- 修改 SelfWorkFlow 受保护生命周期、证据模型或通用任务分类。
- 改变既有非 Graft 调用者的行为以统一命名。
- 新增全局编译宏、公共 API/ABI、持久化 Schema 或 Build Variant。
- 用测试专用生产分支改变正式 Provider 行为。
- 引入全局 Watcher、Graft 竞争 Hook、未锁定 npm 下载或隐式网络服务。
- 扫描/改写用户项目中的任意 Ignore 目录，或将图写到机器级目录。
- 自动删除 CodeGraph 配置、缓存、Submodule 或用户已有修改。

若实现需要越过上述边界，必须停止实施，修订设计、测试范围和侵入性预算，并重新取得用户确认。

## 10. 验收标准

- **AC-1 来源身份：** 安装器能从固定 Submodule commit 构建 Graft，并输出与锁文件一致的来源和构建身份。
- **AC-2 正式 Provider：** `graft` 可被能力检查、Provider 绑定和正式代码上下文路径识别；MCP 不替代正式 Adapter。
- **AC-3 项目图位置：** 图只位于当前项目根目录内的已验证 ignored 目录；没有有效目录时使用 `<repo>/graft`。
- **AC-4 Ignore/暂存边界：** 必要的 Ignore 变更是锚定、最小且可审计的；流程没有暂存或提交动作。
- **AC-5 查询无写入：** `map`、`ask`、`callers`、`grep`、`check` 和 MCP 查询不会触发 refresh/build 或写图。
- **AC-6 修改自动更新：** Agent 修改代码后会提交合并事件，Worker 最终只执行一次结构更新；纯查询不会提交事件。
- **AC-7 失败降级：** 普通任务在 Graft 不可用时降级到 `rg` 并保留 stale/unverified 原因；要求新鲜 Graft 证据的任务失败关闭。
- **AC-8 CodeGraph 迁移：** 默认路径不再依赖 CodeGraph，已有 CodeGraph 配置被保留并标记遗留，不被自动删除。
- **AC-9 Deep 边界：** 写后 Worker 绝不对全局图调用 Deep；绑定 Topic stale 时，主 Agent 必须使用同一 `conversation-id`、当前 Host 模型和原 scope 继续 Topic Deep，并复核 freshness。
- **AC-10 原生验证：** C++、TypeScript、Python 合成项目和 Codex Hook 均有真实失败/成功验收；Unreal 相关能力只按已验证范围声明。
- **AC-11 专题 Deep：** 明确 topic 与非空文件范围后，官方 Deep 只处理该范围并写入项目内专题上下文；全局 Map 不被覆盖，源文件 hash 漂移时状态转为 stale/failed；知识模块只可选择引用，不能触发或承载 Deep。

## 11. 仍需在实现阶段验证的事项

以下内容在当前文档阶段保持 `unverified`，不可提前当作实现事实：

- 锁定 Graft commit 对应的准确包版本、Node/npm 范围、构建脚本和输出目录。
- 该版本 CLI/MCP 的 JSON 输出字段、退出码、并发行为和 `--no-refresh` 覆盖范围。
- Submodule 中是否需要补充构建适配层，及其许可证/第三方依赖清单。
- SelfWorkFlow 当前各 Agent Host 可提供的“修改完成”Hook 能力和事件语义。
- Windows 下 Reparse Point、Ignore、锁文件和路径大小写的原生验收。
- Graft 对 Unreal/C++ 宏、生成代码、引擎模块和 clangd 的实际覆盖度。
- 构建产物 provenance、缓存复用和安装器离线失败路径。
- `knowledge.propose` 当前具体后端、提案文件格式、范围过滤和 Deep 结果接入点。
- 首次外部模型确认是否可按项目/后端配置复用，以及不同敏感数据策略的有效期。
- 独立 Review SubAgent 是否在实施会话中可用；不可用时不得伪造独立 Review 证据。

本设计的实现边界、任务拆分和未来验证命令见 [实施计划](../plans/2026-09-10-graft-provider.md)；面向使用者的操作契约见 [Graft Provider 使用文档](../../providers/graft.md)。
