# Graft Provider 使用说明

**状态：** Graft 已作为锁定 Submodule、来源身份校验、受控 Adapter 和项目级更新 Worker 集成；本机已完成锁定版本构建验证。项目图仍按需创建；Deep 语义和各厂商原生 Host Hook 不属于本适配器。
**适用范围：** SelfWorkFlow 个人工作流的代码结构上下文、关系查询和 Agent 修改后的自动结构更新。

## 1. 它解决什么问题

Graft 将项目源代码构造成可查询的本地结构图，可用于仓库地图、文件 API、符号查找、调用者和调用链等代码上下文。结构路径默认不需要模型 Key；可选 Deep 语义摘要才需要单独的模型 Provider 和敏感数据边界。

SelfWorkFlow 接入后，Graft 是唯一代码图 Provider。正式工作流通过受控 CLI Adapter 获取能力检查、代码上下文和关系证据；Graft MCP 仍可用于交互探索，但不会绕过正式的项目边界和验证收据。

知识后端是 SelfWorkFlow 的独立可选模块。Graft 只提供结构图和结构证据，不自动触发 Wiki、Deep 或其他知识库写入；是否沉淀知识由通用 `knowledge` 生命周期和已选后端决定。

Graft 的公开使用入口可参考 [官方 README](https://github.com/trailhq/Graft/blob/main/README.md)。SelfWorkFlow 锁定仓库为 `https://github.com/trailhq/Graft.git`，使用固定版本构建；本机安装器会在发布工作流前执行 `npm ci --ignore-scripts`、受控 native package rebuild、`npm run build` 和 CLI 运行时 smoke test。依赖与构建产物留在 submodule 的本地忽略目录中，不复制到工作流运行时。

## 2. 当前状态

当前已落地：

- `dependencies/upstream/graft` 已注册为 Submodule，锁定 commit、Git tree、包、lockfile 和许可证 hash。
- `src/selfworkflow/v3/providers/graft.py` 提供只读状态、no-refresh 查询、结构 build 和显式维护计划，失败不泄露命令输出。
- 正常 Submodule profile 会同步 Graft；运行时包携带 Graft lock，安装器在构建阶段验证并构建上游入口。
- `src/selfworkflow/v3/graft_lifecycle.py` 提供项目级惰性预检、`agent_write` 事件合并、单锁、可重试队列和一次性结构 Worker；Host 只需调用统一 CLI 入口，不启用文件 Watcher 或全局 daemon。
- Provider Manager 和 CLI 已提供 `graft-preflight`、`graft-event`、`graft-worker`；安装后默认绑定 Graft。
因此，当前可依赖的 SelfWorkFlow Graft 能力包括来源校验、受控结构查询、项目惰性初始化和事件驱动结构更新；Graft 不可用时普通任务回退到 `rg`，需要新鲜图证据的任务失败关闭。Deep 语义以及没有统一 Host 事件接口的原生自动接入必须标为 `unverified`。

## 3. 安装与身份设计

### 来源

正式来源计划为：

```text
Submodule: dependencies/upstream/graft
Lock:     dependencies/locks/graft.lock.yaml
```

安装器从锁定 Submodule 校验并构建 Graft；当前构建产物保留在该 Submodule 的 ignored `dist/` 与 `node_modules/`，不复制到全局 PATH 或未锁定的网络包。正式 Adapter 通过锁定的本地入口使用它；来源、Gitlink commit、树摘要、包/构建身份和 Adapter 哈希进入安装/Provider 收据。

### 图的位置

图、指纹和 Graft 项目上下文必须位于当前项目目录内：

1. 优先使用已登记、用途明确、稳定且已忽略的项目内目录，并重新验证它确实属于当前项目。
2. 没有有效绑定时使用 `<repo>/graft`。
3. 若 `<repo>/graft` 未被忽略，只补充当前项目的锚定 `/graft/` Ignore 规则。
4. 不使用 C 盘机器缓存作为项目图，不扫描任意 Ignore 目录，不执行暂存或提交操作。

绑定路径如果越出项目根目录、成为 Reparse Point、取消 Ignore 或无法复核，会产生 `graft-cache-boundary-invalid`。此时自动更新暂停，普通查询回退到 `rg`；要求新鲜 Graft 图的任务失败关闭。

## 4. 当前工作流边界

### Agent 修改代码后

Agent 完成一次代码写入后，Host/工作流调用以下统一入口：

```powershell
python -m selfworkflow.cli provider graft-event --config-file <machine-config> `
  --project-root D:\project --changed-path Source\a.cpp --changed-path Source\b.h
python -m selfworkflow.cli provider graft-worker --config-file <machine-config> `
  --project-root D:\project
```

首次代码任务使用 `graft-preflight`；若项目图缺失，预检只初始化当前项目并补充 `/graft/` Ignore。事件入口只接受当前项目内路径，并自动合并重复事件。Worker 在一次运行中消费合并后的路径，调用结构 build；构建失败保留旧图和可重试队列。

Host Hook/Worker 的共同约束是：

1. 重新校验项目身份、修改路径和图边界。
2. 合并短时间内的重复事件。
3. 获取每项目锁，执行结构更新。
4. 记录 succeeded、stale、failed 或 boundary-invalid 状态。

普通查询、文件读取、搜索、Review 查询和 MCP 查询都不会触发更新。Worker 只做结构更新，不自动执行 Deep。没有原生 Host Hook 的 Agent 使用上述 CLI 作为等价 Host 事件入口；本项目不提供跨厂商后台守护进程。

### 查询时

已实现的 Adapter 查询会强制 Graft `--no-refresh`，避免查询隐式写图、侧车或指纹。
当前 Adapter 覆盖以下查询能力：

- 项目地图和结构上下文。
- 文件/符号 API。
- callers、调用链和关系导航。
- 精确查找和受限仓库问答。
- 图健康和新鲜度检查，但检查本身不刷新图。

### 个人 Wiki 知识沉淀

知识沉淀不属于 Graft Worker。用户明确启动通用 `knowledge.propose` 后，知识后端可以把 Graft 的结构查询结果作为来源材料；发布仍由知识模块自己的确认和写入规则控制。Graft 不保存 Wiki 路径、凭据、私人回执或模型推理过程，也不因代码编辑自动调用 Deep。

## 5. Graft 直接命令示例

以下命令用于锁定 Submodule 的本地 smoke test；SelfWorkFlow Adapter 会固定相同的查询 no-refresh 约束：

```powershell
node dependencies/upstream/graft/dist/cli.js build <repo> --no-gitignore --no-ignore
node dependencies/upstream/graft/dist/cli.js check <repo> --json
node dependencies/upstream/graft/dist/cli.js map <repo> --json --no-refresh
node dependencies/upstream/graft/dist/cli.js ask "Where is the request flow?" <repo> --source --json --no-refresh
node dependencies/upstream/graft/dist/cli.js callers "Symbol" <repo> --depth all --json --no-refresh
```

实际支持的参数、JSON 字段和退出码必须以锁定 Submodule 的 `--help`、运行输出和失败测试为准。命令示例不能绕过 SelfWorkFlow 的项目绑定、环境控制、输出限制和收据封装。

当前正式 Adapter 已覆盖 Provider 状态、结构查询、显式结构维护和失败诊断；项目生命周期层覆盖预检、事件合并和 Worker，所有查询接口固定 no-refresh。

## 6. MCP 使用边界

Graft MCP 适合在交互过程中探索项目结构。SelfWorkFlow 的正式代码证据仍走绑定后的 CLI Adapter；MCP 查询仍须由宿主提供已校验的项目根目录和运行时边界，并固定 no-refresh。MCP 不替代 `agent_write` 事件入口，也不负责启动 Worker。

MCP 不应：

- 因查询自动 build 或 refresh。
- 代替正式 Provider 的能力检查和 Review/Verify 收据。
- 读取项目外图或机器级缓存。
- 绕过输出上限、路径绑定、凭据脱敏或任务权限。
- 启用 Graft 自带竞争性 Hook。

## 7. Deep 语义分析

结构索引和结构查询是默认本地路径；Graft 的 Deep 摘要不是本适配器的已实现能力。若未来接入 Deep，必须单独设计和验证，并需要：

- 明确的模型、Base URL 和凭据来源。
- 源代码发送范围、敏感数据和外部网络影响确认。
- 输入/输出摘要、成本/超时和失败状态记录。
- 独立的新鲜度和 Review/Verify 语义。

Agent 修改后的 Worker 和普通查询不调用 `build --deep`。当前没有可验证的 Graft Deep 远程能力或收据，因此 `code.semantic` 必须标记为 `unverified`，不能假装已支持。

## 8. 故障处理

| 情况 | 普通任务 | 明确要求新鲜 Graft 证据的任务 |
| --- | --- | --- |
| Graft 未安装/运行时损坏 | 记录 unverified，降级到 `rg` | 失败关闭 |
| 图过期但可读 | 明确标记 stale，只作参考 | 不满足新鲜证据 |
| Worker 构建失败 | 保留旧图并标记 stale/failed，允许后续重试 | 等待成功收据，否则失败 |
| 图路径边界无效 | 暂停自动更新，查询使用 `rg` | 失败关闭 |
| 查询命令失败/输出损坏 | 使用无图读取并保留诊断 | 失败关闭 |
| Deep 能力未配置 | 结构能力继续可用 | Deep 请求为 unverified/拒绝 |
| 知识后端失败 | 保留 Graft 结构查询结果，按知识模块规则处理 | 不得绕过知识模块确认或自动发布 |

不通过重新安装、隐式 refresh、网络下载或自动 Deep 来“修复”一次普通查询失败；知识后端的选择和写入由通用知识模块单独负责。

## 9. 回退策略

Graft 是唯一代码图 Provider。Graft 缺失、过期、不可用或未覆盖目标时，普通任务明确标记限制并回退到 `rg`；`rg` 只提供精确文本和未覆盖文件读取，不冒充结构证据。要求新鲜 Graft 图的任务在无法满足时失败关闭。

## 10. 支持范围与限制

第一版计划用 C++、TypeScript、Python 合成项目和 Codex Native Hook 做原生验收。是否覆盖 Unreal 工程中的生成代码、宏、模块边界、clangd 和引擎特有结构，必须依据实际锁定版本的测试结果声明；文档不会提前宣称完整 Unreal 支持。

设计边界和验收条件见 [Graft Provider 设计](../superpowers/specs/2026-09-10-graft-provider-design.md)，未来实施步骤见 [Graft Provider 实施计划](../superpowers/plans/2026-09-10-graft-provider.md)。
