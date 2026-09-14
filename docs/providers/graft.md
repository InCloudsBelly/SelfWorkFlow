# Graft Provider 使用说明

**状态：** Graft 已作为锁定 Submodule 和官方 MCP 运行来源接入；SelfWorkFlow 只负责安装、项目边界、能力门禁、任务路由和更新触发。项目图仍由官方 Graft 保存在项目目录内；Deep 语义仍由官方 Graft 管理，SelfWorkFlow 仅提供一次性 Codex loopback transport，不重实现图或摘要逻辑。
**适用范围：** SelfWorkFlow 个人工作流的代码结构上下文、关系查询和 Agent 修改后的自动结构更新。

## 1. 它解决什么问题

Graft 将项目源代码构造成可查询的本地结构图，可用于仓库地图、文件 API、符号查找、调用者和调用链等代码上下文。结构路径默认不需要模型 Key；可选 Deep 语义摘要才需要单独的模型 Provider 和敏感数据边界。

SelfWorkFlow 接入后，Graft 是唯一代码图 Provider，官方 MCP 是 Agent 的主查询入口。SelfWorkFlow 不复制 Graft 的图、查询或文档逻辑，只校验当前项目根目录、工具能力和 freshness；Host CLI 仅用于安装、预检、显式维护和失败恢复。

知识后端是 SelfWorkFlow 的独立可选模块。Graft 只提供结构图和结构证据，不自动触发 Wiki、Deep 或其他知识库写入；是否沉淀知识由通用 `knowledge` 生命周期和已选后端决定。

Graft 的公开使用入口可参考 [官方 README](https://github.com/trailhq/Graft/blob/main/README.md)。SelfWorkFlow 锁定仓库为 `https://github.com/trailhq/Graft.git`，使用固定版本构建；本机安装器会在发布工作流前执行 `npm ci --ignore-scripts`、受控 native package rebuild、`npm run build` 和 CLI 运行时 smoke test。依赖与构建产物留在 submodule 的本地忽略目录中，不复制到工作流运行时。

官方 `graft init` 会按选择注册 MCP，并可为 Codex 写入 `~/.codex/config.toml`；官方 Graft MCP 支持 `graft mcp <dir>` 绑定项目目录。SelfWorkFlow 安装器使用锁定 Submodule 的受管启动薄文件注册同等官方 MCP，不把固定项目路径写入全局配置。这样 MCP 进程按当前工作目录绑定项目，个人图仍留在项目自己的 `graft/`。

## 2. 当前状态

当前已落地：

- `dependencies/upstream/graft` 已注册为 Submodule，锁定 commit、Git tree、包、lockfile 和许可证 hash。
- `src/selfworkflow/v3/providers/graft.py` 仅作为安装/维护/恢复的受控 CLI 适配，不是 Agent 的主查询实现；失败不泄露命令输出。
- 正常 Submodule profile 会同步 Graft；运行时包携带 Graft lock，安装器在构建阶段验证并构建上游入口。
- `src/selfworkflow/v3/graft_lifecycle.py` 提供项目级惰性预检、`agent_write` 事件合并、单锁、可重试队列和一次性结构 Worker；Host 只需调用统一 CLI 入口，不启用文件 Watcher 或全局 daemon。
- Provider Manager 和 CLI 已提供 `graft-preflight`、`graft-event`、`graft-worker`；安装后默认绑定 Graft。`graft-preflight` 先执行 Provider runtime 预检（真实 `--version` 与必需命令清单），再检查项目图；仅图目录存在不能证明 Graft 可用。
因此，当前可依赖的 Graft 能力包括官方 MCP 查询、官方 freshness 检查、项目内图缓存、SelfWorkFlow 触发的官方结构更新，以及显式绑定当前 Agent 模型的官方 Deep 构建；MCP 缺失或失效时预检返回 `unverified`，普通任务回退到 `rg`，需要新鲜图证据的任务失败关闭。SelfWorkFlow 不提供自定义图算法。

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

代码任务默认自动检查官方 MCP 和 freshness 并查询；用户无需再次指定。代码写入完成后由 SelfWorkFlow 触发官方 Graft 结构更新，不等待用户提醒。这里的“自动”是工作流阶段性调用，不是 SelfWorkFlow 自己实现的图服务；安装器提供 `%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd` 作为维护入口和 `%LOCALAPPDATA%\SelfWorkFlow\bin\graft-mcp.cmd` 作为官方 MCP 启动入口。

Host/工作流调用以下统一入口：

```powershell
%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd provider graft-event --config-file <machine-config> `
  --project-root D:\project --changed-path Source\a.cpp --changed-path Source\b.h
%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd provider graft-worker --config-file <machine-config> `
  --project-root D:\project
```

首次代码任务使用 `graft-preflight`；它必须先通过 Provider runtime 预检。仅在 Provider 已验证且项目图缺失时，预检才初始化当前项目并补充 `/graft/` Ignore；Provider 失败时返回 `unverified`，不创建图、不执行 build。事件入口同样先做 Provider 预检，失败时不创建项目缓存；已有队列保留并等待后续重试。事件入口只接受当前项目内路径，并自动合并重复事件。Worker 在一次运行中消费合并后的路径，调用结构 build；构建失败保留旧图和可重试队列。

Host Hook/Worker 的共同约束是：

1. 重新校验项目身份、修改路径和图边界。
2. 合并短时间内的重复事件。
3. 获取每项目锁，执行结构更新。
4. 记录 succeeded、stale、failed 或 boundary-invalid 状态。

普通查询、文件读取、搜索、Review 查询和 MCP 查询都不会触发更新。Worker 只做结构更新，不自动执行 Deep。没有原生 Host Hook 的 Agent 使用上述 CLI 作为等价 Host 事件入口；本项目不提供跨厂商后台守护进程。

### 当前对话模型执行 Deep

Deep 不是普通代码任务的默认步骤。需要时，当前 Agent 将自身本次对话的模型和推理等级作为显式参数传入：

```powershell
%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd provider graft-deep `
  --project-root D:\project `
  --model <current-agent-model> `
  --reasoning-effort <current-effort>
```

SelfWorkFlow 为本次命令生成仅绑定 `127.0.0.1` 的随机内存令牌，启动短生命周期 bridge，并把官方 Graft 的 `GRAFT_BASE_URL` 指向该 bridge。每个 Graft Deep 请求都转成一次只读、临时的 `codex exec`，使用传入的同一模型和推理等级；Codex CLI 复用其已保存的本机登录态，不需要 OpenAI API Key。桥接结束后立即关闭；令牌只在内存中存在，临时 schema/output 只写入系统临时目录并在结束时删除。

Deep 结果只有在官方 build 成功、`graft/check --json` 返回 context/graph 均 fresh 且项目内 `graft/manifest.json` 存在时才报告 succeeded。Codex 缺少登录、模型不支持、超时、坏 JSON、工具调用不完整、构建非零或 freshness 失败均返回失败，不把部分缓存宣称为可用 Deep 图；官方 Graft 自身的语言解析限制仍需按其输出处理。

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

## 5. Agent 的正式调用入口

Agent/Host 不运行裸 CLI 查询。Agent 通过官方 MCP 查询；SelfWorkFlow Host CLI 只执行安装、预检、维护和恢复。固定项目目录不得写死进全局配置，MCP 启动器使用当前工作目录：

```powershell
%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd provider graft-preflight `
  --project-root <repo>
%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd provider query `
  --provider-id graft --project-root <repo> `
  --query "<query>" --query-kind ask
```

预检或查询入口不可达时，返回 `unverified`；普通任务才可明确回退 `rg`，要求 Graft 证据的新鲜任务必须失败关闭。不得因入口不可达而搜索 PATH、安装未锁定的全局 Graft 或手工解析 `graft/`。

## 6. Graft 直接命令示例

以下命令只用于维护者对锁定 Submodule 的本地 smoke test，不是正式工作流证据；SelfWorkFlow Adapter 会固定相同的查询 no-refresh 约束：

```powershell
node dependencies/upstream/graft/dist/cli.js build <repo> --no-gitignore --no-ignore
node dependencies/upstream/graft/dist/cli.js check <repo> --json
node dependencies/upstream/graft/dist/cli.js map <repo> --json --no-refresh
node dependencies/upstream/graft/dist/cli.js ask "Where is the request flow?" <repo> --source --json --no-refresh
node dependencies/upstream/graft/dist/cli.js callers "Symbol" <repo> --depth all --json --no-refresh
```

实际支持的参数、JSON 字段和退出码必须以锁定 Submodule 的 `--help`、运行输出和失败测试为准。命令示例不能绕过 SelfWorkFlow 的项目绑定、环境控制、输出限制和收据封装。

当前正式 Adapter 已覆盖 Provider 状态、结构查询、显式结构维护和失败诊断；项目生命周期层覆盖预检、事件合并和 Worker，所有查询接口固定 no-refresh。

## 7. MCP 使用边界

Graft MCP 是交互和代码理解的主入口。SelfWorkFlow 仍要求宿主提供已校验的项目根目录，并在任务状态中记录 freshness。MCP 不负责替代工作流的 Plan、Review 或测试门禁；代码写入后的更新由 SelfWorkFlow 触发官方 Graft CLI/官方机制完成。

MCP 不应：

- 因查询自动 build 或 refresh。
- 代替正式 Provider 的能力检查和 Review/Verify 收据。
- 读取项目外图或机器级缓存。
- 绕过输出上限、路径绑定、凭据脱敏或任务权限。
- 把固定项目路径写入机器级 MCP 配置。

## 8. Deep 语义分析

结构索引和结构查询是默认本地路径；Deep 仅在任务明确需要时调用。当前实现的桥接边界是：

- 当前 Agent 显式提供模型和 reasoning effort；两者不能缺省或由桥接器猜测。
- Graft 仍使用官方 OpenAI wire format；SelfWorkFlow 只把 loopback Base URL 和一次性本地 token 注入该次官方进程。
- bridge → `codex exec --ephemeral --sandbox read-only`，Codex 复用本机已保存登录态；不读取、保存或要求 `OPENAI_API_KEY`。
- bridge 不对外监听，只接受本次进程的随机 bearer token；请求/响应大小、工具调用结构、超时和错误均有界。
- 成功必须同时满足官方 Deep build、manifest 和 `check --json` freshness；失败不报告成功。

Agent 修改后的 Worker 和普通查询不调用 `build --deep`；只有主 Agent 在 Review SubAgent 创建前显式调用 `provider graft-deep` 才会执行它。Review SubAgent 只读取主 Agent 绑定的 Graft evidence，不得调用 Graft MCP、`graft-deep`、event、worker 或 provider 维护。桥接不能共享当前对话缓存或对话实例，只能使用相同的模型标识和 reasoning effort；因此缓存命中不能作为保证。

## 9. 故障处理

| 情况 | 普通任务 | 明确要求新鲜 Graft 证据的任务 |
| --- | --- | --- |
| Graft 未安装/运行时损坏 | 预检返回 unverified，不建图，降级到 `rg` | 失败关闭 |
| 图过期但可读 | 明确标记 stale，只作参考 | 不满足新鲜证据 |
| Worker 构建失败 | 保留旧图并标记 stale/failed，允许后续重试 | 等待成功收据，否则失败 |
| 图路径边界无效 | 暂停自动更新，查询使用 `rg` | 失败关闭 |
| 查询命令失败/输出损坏 | 使用无图读取并保留诊断 | 失败关闭 |
| Deep 能力未配置 | 结构能力继续可用 | 缺少当前模型/推理等级或 Codex 登录时拒绝 |
| 知识后端失败 | 保留 Graft 结构查询结果，按知识模块规则处理 | 不得绕过知识模块确认或自动发布 |

不通过重新安装、隐式 refresh、网络下载或自动 Deep 来“修复”一次普通查询失败；知识后端的选择和写入由通用知识模块单独负责。

## 10. 回退策略

Graft 是唯一代码图 Provider。必须先通过 Provider runtime 预检；仅有 `graft/` 图目录或手工解析图文件不算 Provider 可用。Graft 缺失、过期、不可用或未覆盖目标时，普通任务明确标记限制并回退到 `rg`；`rg` 只提供精确文本和未覆盖文件读取，不冒充结构证据。要求新鲜 Graft 图的任务在无法满足时失败关闭。

## 11. 支持范围与限制

第一版计划用 C++、TypeScript、Python 合成项目和 Codex Native Hook 做原生验收。是否覆盖 Unreal 工程中的生成代码、宏、模块边界、clangd 和引擎特有结构，必须依据实际锁定版本的测试结果声明；文档不会提前宣称完整 Unreal 支持。

设计边界和验收条件见 [Graft Provider 设计](../superpowers/specs/2026-09-10-graft-provider-design.md)，未来实施步骤见 [Graft Provider 实施计划](../superpowers/plans/2026-09-10-graft-provider.md)。
