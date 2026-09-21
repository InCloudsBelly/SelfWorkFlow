# Graft Provider 使用说明

**定位：**官方 Graft MCP 是代码阅读入口；SelfWorkFlow 只负责项目边界、能力检查、任务路由、写后更新和显式 Deep 的受控桥接，不复制 Graft 的图、查询、Watcher 或 daemon。

## 默认代码流程

1. 只有已绑定 Deep Topic 的 conversation 才使用官方 MCP 的 Topic 查询和全局非 Deep Code Map；未绑定或选择 `no-deep-topic` 时不调用 Graft。全局 `graft/manifest.json` 不是 Topic 流程的前置条件或门禁，`rg` 不是默认阅读入口。
2. 已绑定 Topic 的新对话或继续对话先调用一次 `provider graft-ensure`。两张图都 fresh 时不构建；只更新 stale/missing 的层并在返回前重新核验。
3. 通过 MCP 按需使用 `graft_repo_map`、`graft_file_api`、`graft_find_code`、`graft_trace_calls`、`graft_find_all`。
4. Agent 修改代码后通过 SelfWorkFlow 的 `provider graft-sync` 薄入口发送一次 `agent_write` 并调用 Worker。Worker 先检查当前 conversation 绑定的 Topic：Topic 需要刷新时优先用当前模型执行原范围 Topic Deep，并自动收尾一次全局非 Deep Code Map；Topic 已 fresh 时再维护全局 Map。全局 Map 失败不阻塞 Topic，但必须单独返回待重试状态。
5. 两张图均重新验证成功才报告 `fresh`；查询、Review 查询和纯读取不触发写后更新。

MCP 缺失、图过期或项目边界无效时，必须明确标记 `unverified`；仅简单文本定位可在说明后临时使用 `rg`，需要新鲜 Graft 结构证据的任务失败关闭。手工读取 `graft/` 文件不属于正式 Graft 查询证据。

## 来源、安装与图位置

正式来源是锁定的 `dependencies/upstream/graft` Submodule，身份由 `dependencies/locks/graft.lock.yaml` 绑定。安装器从锁定来源构建官方运行时，不使用未锁定的全局 PATH、`npx` 或临时网络包。

官方 MCP 按当前项目目录绑定，项目结构 Map 默认位于 `<repo>/graft/`。全局 Code Map 是项目本地可再生缓存，不自动 Git add、commit 或 push；它不是 Topic Deep 的 freshness 依据。不使用 C 盘机器缓存，也不把固定项目路径写入全局配置。

SelfWorkFlow Host CLI 仅用于安装、预检、写后同步、显式维护和失败恢复；Agent 查询应使用官方 MCP。没有有效 Provider 或图边界时，不自动安装、扩大目录或猜测缓存路径。

## 写后结构更新

正式入口示例：

```powershell
%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd provider graft-sync --config-file <machine-config> `
  --project-root D:\project --conversation-id <current-conversation-id> --changed-path Source\a.cpp
```

`graft-sync` 只是把事件入队和一次 Worker 调用合并为一个入口；官方 Graft MCP 仍负责查询，不被改造为写入服务。

对话开始/继续时的最小检查入口：

```powershell
%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd provider graft-ensure --config-file <machine-config> `
  --project-root D:\project --conversation-id <current-conversation-id>
```

`graft-ensure` 不创建第二套图，也不重复构建 fresh 图；它只按绑定的
Topic scope 执行必要的 Deep，并对全局 Code Map 执行一次非 Deep structural
更新。两张图的最终状态必须分别报告；任一层失败都返回 `partial` 和下一步，
不把旧缓存冒充为 fresh。

Worker 合并重复事件、校验项目边界；不调用全局 `build --deep`。只有已绑定 Topic 的 conversation 才能进入 Worker；未绑定或 `no-deep-topic` 在入队前失败关闭，不构建全局 Map。`conversation-id` 是写后 Worker 的必需身份，缺失即失败关闭。Worker 先返回绑定 Topic 的 `topicRefresh`：`refresh-required` 时优先由同一次 Host Worker 调用使用当前模型执行原 scope Deep，并将全局 Map 标记 `deferred`；Topic fresh 后自动收尾一次官方非 Deep `build`。`fresh` 无后续动作。全局 Map 失败或延后返回 `partial`/`retry-global-map`，不阻塞 Topic/普通对话；Topic Deep 暂时失败返回 `partial`、`topicFreshness=unverified`、`nextAction=retry-topic-deep`。Topic freshness 只校验 Topic context、Topic `manifest.json` 和源文件 hash，不检查或要求项目根 `graft/manifest.json`。普通对话可以继续但不得静默回退 `rg` 或声称 Graft fresh。Worker 每次调用最多尝试一次全局更新，不实现后台 Watcher、daemon 或重试循环。

## 专题 Deep

Deep 不是全仓库默认步骤。一个稳定 `conversation-id` 只绑定一个 `topic-id`；专题上下文持续复用，不按 Git hash 建目录。绑定索引位于项目 `./selfworkflow/graft-deep/.conversation-bindings/`，只保存 conversation hash，不保存原始对话 ID。全局 `<repo>/graft/` 保留非 Deep structural Map，专题上下文位于：

```text
<repo>/.selfworkflow/graft-deep/<topic-id>/graft/
```

绑定后的 Deep 必须使用稳定 `conversation-id`、已绑定的 `topic-id` 和非空的项目内相对文件清单；后续可省略 `topic-id`，SelfWorkFlow 从绑定索引自动恢复，并拒绝切换到另一个 topic。每次调用结果都必须明确回显 `conversationId → topicId`。SelfWorkFlow 将每个文件作为官方 Graft 的重复 `--only-dir`，并沿 quoted local `#include` 做有限的 C/C++ 闭包，`.inl/.ipp` 按 include 出现顺序纳入上下文。它不会创建临时 Git 仓库，也不会因为范围不清而扫描整个项目。`.inl/.ipp` 目前属于 `context-only`：可进入 Deep 的文件语境，但不伪报官方结构符号节点。源文件 hash 用于识别不变、变更、新增和删除文件；专题只在明确使用该 topic 时惰性更新。

新对话首次接触 Graft 时先调用：

```powershell
%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd provider graft-topics `
  --project-root D:\project --conversation-id <current-conversation-id>
```

它只读取项目 `.selfworkflow/graft-deep/<topic-id>/` 下已有专题并返回 freshness，不调用 Provider、不创建图。用户选择已有专题后调用 `provider graft-topic-select --topic-id <id>` 自动绑定；用户明确不使用 Deep/Graft 时调用同一命令的 `--disable`，本对话记为 `no-deep-topic`。两种选择都不能被后续普通消息静默改变；没有已有专题时不猜测新范围。

Topic 读取必须显式绑定当前 `conversation-id` 对应的 `<repo>/.selfworkflow/graft-deep/<topic-id>/graft`；`provider status/query --conversation-id` 自动解析该绑定，显式 `--context-dir` 只能用于一致性核对，不会读取或检查项目根 `<repo>/graft/`。根图和 Topic 图是两个独立上下文。缺少绑定时失败关闭。

Topic status 返回 `topicFreshness=stale` 或 `topicStaleFiles` 时，写后 Worker 会使用同一 `conversation-id`、当前 Host model/reasoning effort 自动调用一次 `provider graft-deep`；省略 `--scope-file` 即复用已绑定 Topic manifest 的原 scope，只更新已绑定范围，不扩大扫描。成功且重新验证 fresh 前，旧 Topic 只能作为 stale reference。

调用入口必须带专题和范围：

```powershell
%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd provider graft-deep `
  --project-root D:\project `
  --conversation-id <current-conversation-id> `
  --topic-id kgpr-coverage `
  --scope-file Source\Renderer.cpp `
  --scope-file Source\Renderer.h
```

Deep bridge 默认传入 `--concurrency 1`，降低大型 C++/WASM 任务的资源竞争；这不能掩盖官方 Tree-sitter 的解析失败。只有官方 build 成功、专题 context 的 `manifest.json` 存在、`check --json` 的 context/graph 均为 fresh 且源文件 hash 未漂移，才报告 Deep `fresh`。旧专题结果可保留为 stale reference；失败不得扩大范围或宣称成功。Topic 的 `lastRun.model`/`lastRun.reasoningEffort`（以及旧顶层字段、官方 manifest 的 `model`）只表示上次执行，不得覆盖本次当前 Host 模型；bridge 只能记录 Host 传入的参数，不能自行验证父对话模型，缺少当前模型信息时失败关闭。

仅主 Agent 可执行 Deep bridge。Deep 由当前任务模式或用户意图触发，但不要求用户填写模型。主 Agent/Host 在本次进程内通过 `SELFWORKFLOW_HOST_CURRENT_MODEL` 和 `SELFWORKFLOW_HOST_CURRENT_REASONING_EFFORT` 自动注入当前 conversation 的 `model` 和 `reasoning-effort`；CLI 的同名参数仅是旧宿主兼容入口，与 Host 上下文冲突时失败关闭。bridge 为官方 Graft 提供本次调用的 loopback OpenAI wire transport；每个请求转为一次只读、临时 `codex exec`，使用该 Host 上下文。Host 无法提供当前上下文或只提供一项时失败关闭，不读取 Topic/Graft 历史模型，也不静默询问或回退。Codex 复用本机登录态，不需要 OpenAI API Key。Reviewer 只消费主 Agent 绑定的 evidence，禁止调用 Graft、provider 或 Deep。

## 与 Wiki 的关系

知识后端是独立可选模块。Wiki 可以把专题 Deep 的结构结果作为来源参考，但 Graft 不触发 Wiki、不依赖 Wiki，也不承担知识发布；知识仍按 `knowledge.read → knowledge.propose → knowledge.update` 和自己的确认规则执行。

## 故障与回退

| 状态 | 普通代码任务 | 明确要求新鲜 Graft 证据 |
| --- | --- | --- |
| Provider/MCP 缺失 | 标记 `unverified`，回退 `rg` | 失败关闭 |
| 全局 Code Map 缺失/过期 | 单独标记 `globalMap=unverified`，必要时更新；不阻塞 Topic | 不影响 Topic 门禁 |
| 专题 Deep 失败或源文件漂移 | 保留旧专题状态并报告 | 等待成功收据 |
| 范围、Reparse Point 或路径边界无效 | 暂停 Graft，回退 `rg` | 失败关闭 |

不得因查询失败而自动下载、安装、切换到未锁定 Provider、读取项目外目录或把手工解析结果冒充 Graft。运行时错误必须保留可诊断的阶段和失败原因，但不泄露凭据、完整提示词或敏感源码。

## 官方命令参考

以下命令只用于维护者对锁定 Submodule 的本地 smoke test；正式 Agent 查询仍使用官方 MCP：

```powershell
node dependencies/upstream/graft/dist/cli.js build <repo> --no-gitignore --no-ignore
node dependencies/upstream/graft/dist/cli.js check <repo> --json
node dependencies/upstream/graft/dist/cli.js map <repo> --json --no-refresh
node dependencies/upstream/graft/dist/cli.js ask "Where is the request flow?" <repo> --source --json --no-refresh
```

实际参数、JSON 字段和退出码以锁定 Submodule 的 `--help`、运行输出和测试为准；文档示例不能绕过 SelfWorkFlow 的边界和证据门禁。当前对话 ID 必须由 Host 明确提供；不可获得时报告 `unverified`，不得用任务标题、进程 ID 或上一次调用猜测。
