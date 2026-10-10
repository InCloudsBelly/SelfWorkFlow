# Graft Provider 使用说明

**定位：**官方 Graft MCP 是代码阅读入口；SelfWorkFlow 只负责项目边界、能力检查、任务路由、写后更新和显式 Deep 的受控桥接，不复制 Graft 的图、查询、Watcher 或 daemon。

## 默认代码流程

1. 已有可用且 fresh 的全局非 Deep Code Map 自动使用，无论是否绑定 Topic；无须启用记录。明确禁用仍尊重，缺失图不自动初始化。
2. 每个代码读取阶段调用一次 `provider graft-ensure`，默认只读检查全局 Map；stale 时询问更新，同意后传 `--allow-update`。用户主动要求刷新视为本次确认。外部编辑或分支切换后重新检查，不检查任何 Deep freshness，不以根 Deep manifest 判定结构图。
3. 通过 MCP 按需使用 `graft_repo_map`、`graft_file_api`、`graft_find_code`、`graft_trace_calls`、`graft_find_all`。
4. Agent 修改、撤回、删除或重命名代码后，合并实际操作路径（含重命名前后路径）调用一次 `provider graft-sync`；最终 Git diff 为空也不能漏掉撤回。Worker 只维护已有全局非 Deep Map，不自动检查或更新 Topic Deep。
5. 全局 Map 重新验证成功才报告 `fresh`；查询、Review 查询和纯读取不触发写后更新。Deep 仅由用户明确要求时单独调用 `provider graft-deep`。

MCP 缺失、图过期或项目边界无效时，必须明确标记 `unverified`；`rg` 不是默认阅读入口，仅简单文本定位可在说明后临时使用 `rg`，需要新鲜 Graft 结构证据的任务失败关闭。手工读取 `graft/` 文件不属于正式 Graft 查询证据。

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

`graft-ensure` 默认只检查；stale 返回 `confirmation_required` 和
`confirm-global-map-update`，不写图；missing 返回
`global-map-initialization-required`，不自动创建。用户确认后加
`--allow-update` 才构建并重新验证。fresh 不重建。Deep 不在该入口中检查或更新。

Worker 合并重复事件、校验项目边界；不调用全局 `build --deep`，也不检查 Topic manifest。已有全局 Map 的代码修改才进入 Worker；`conversation-id` 是写后 Worker 的必需身份，缺失即失败关闭。全局 Map 失败返回 `partial`/`retry-global-map`，不实现后台 Watcher、daemon 或重试循环。

## 专题 Deep

Deep 不是全仓库默认步骤。一个稳定 `conversation-id` 只绑定一个 `topic-id`；专题上下文持续复用，不按 Git hash 建目录。绑定索引位于项目 `./selfworkflow/graft-deep/.conversation-bindings/`，只保存 conversation hash，不保存原始对话 ID。全局 `<repo>/graft/` 保留非 Deep structural Map，专题上下文位于：

```text
<repo>/.selfworkflow/graft-deep/<topic-id>/graft/
```

绑定后的 Deep 必须使用稳定 `conversation-id`、已绑定的 `topic-id` 和非空的项目内相对文件清单；后续可省略 `topic-id`，SelfWorkFlow 从绑定索引自动恢复，并拒绝切换到另一个 topic。每次调用结果都必须明确回显 `conversationId → topicId`。SelfWorkFlow 将每个文件作为官方 Graft 的重复 `--only-dir`，并沿 quoted local `#include` 做有限的 C/C++ 闭包，`.inl/.ipp` 按 include 出现顺序纳入上下文。它不会创建临时 Git 仓库，也不会因为范围不清而扫描整个项目。`.inl/.ipp` 目前属于 `context-only`：可进入 Deep 的文件语境，但不伪报官方结构符号节点。源文件 hash 用于识别不变、变更、新增和删除文件；专题只在明确使用该 topic 时惰性更新。

仅用户显式要求 Deep 且需要恢复/选择 Topic 时调用：

```powershell
%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd provider graft-topics `
  --project-root D:\project --conversation-id <current-conversation-id>
```

它只读取项目 `.selfworkflow/graft-deep/<topic-id>/` 下已有专题并列出选项，不调用 Provider、不创建图。用户选择已有专题后调用 `provider graft-topic-select --topic-id <id>` 自动绑定；用户只使用全局 Map 时调用 `--global-only`；用户明确不使用 Graft 时调用 `--disable`，本对话记为 `no-deep-topic`。两种选择都不能被后续普通消息静默改变；没有已有专题时不猜测新范围。

Topic 读取必须显式绑定当前 `conversation-id` 对应的 `<repo>/.selfworkflow/graft-deep/<topic-id>/graft`；`provider status/query --conversation-id` 自动解析该绑定，显式 `--context-dir` 只能用于一致性核对，不会读取或检查项目根 `<repo>/graft/`。根图和 Topic 图是两个独立上下文。缺少绑定时失败关闭。

只有用户明确要求 Deep 时，才使用同一 `conversation-id`、当前 Host model/reasoning effort 调用一次 `provider graft-deep`；省略 `--scope-file` 即复用已绑定 Topic manifest 的原 scope，只更新已绑定范围，不扩大扫描。成功且重新验证 fresh 前，旧 Topic 只能作为 stale reference。

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

### 命令失败诊断

通过 SelfWorkFlow Provider CLI 执行的 Graft 命令失败时，JSON 结果包含
`reason` 和 `diagnostics`。异常路径仍保留 stderr 上的稳定错误摘要；成功结果格式不变。

| SelfWorkFlow CLI 退出码 | 类别 | 说明 |
| --- | --- | --- |
| 74 | `timeout` | `graft-command-timeout`，子命令超过运行窗口 |
| 75 | `start-failed` | `graft-command-start-failed`，进程未能启动 |
| 76 | `nonzero-exit` | `graft-command-failed`，保留子进程原始退出码 |
| 77 | `response-invalid` / `output-too-large` | JSON 无法解析、结构不符合要求或输出超限；保留原有具体原因码 |

`diagnostics` 包含 `operation`、`failureKind`、`childExitCode`、`durationMs`、
`timeoutMs`、`exceptionType`、`stdoutTail` 和 `stderrTail`。
`operation` 是实际失败的 Graft 子命令，例如 `check` 或 `build`，不是外层
`graft-ensure`。启动失败和超时没有可用的原始退出码，`childExitCode` 为 `null`，
不把执行器内部的 `9009` 当作子进程退出码。非 CLI 注入端口未提供的计时字段为 `null`。

输出先脱敏再截断，每个尾部最多 4096 UTF-8 字节。脱敏覆盖常见凭据字段所在行、
私钥块、HTTP URL 中的用户名密码和敏感环境变量值；不输出完整命令行或异常对象。
诊断仅随本次响应返回，不写入 Provider 配置或图缓存。

`graft-ensure`、`status`、`graft-preflight` 和 `graft-sync` 等入口会保留这些诊断；
即使结果以 `unverified` 或 `partial` 返回，也使用对应非零退出码。
其他失败继续使用既有退出码。此改动不增加重试、不调整 120 秒超时，
也不改变独立 Deep bridge 或官方 MCP 的执行策略。

### 维护者命令

以下命令只用于维护者对锁定 Submodule 的本地 smoke test；正式 Agent 查询仍使用官方 MCP：

```powershell
node dependencies/upstream/graft/dist/cli.js build <repo> --no-gitignore --no-ignore
node dependencies/upstream/graft/dist/cli.js check <repo> --json
node dependencies/upstream/graft/dist/cli.js map <repo> --json --no-refresh
node dependencies/upstream/graft/dist/cli.js ask "Where is the request flow?" <repo> --source --json --no-refresh
```

实际参数、JSON 字段和退出码以锁定 Submodule 的 `--help`、运行输出和测试为准；文档示例不能绕过 SelfWorkFlow 的边界和证据门禁。当前对话 ID 必须由 Host 明确提供；不可获得时报告 `unverified`，不得用任务标题、进程 ID 或上一次调用猜测。
