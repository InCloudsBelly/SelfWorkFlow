# Graft Provider 使用说明

**定位：**官方 Graft MCP 是代码阅读入口；SelfWorkFlow 只负责项目边界、能力检查、任务路由、写后更新和显式 Deep 的受控桥接，不复制 Graft 的图、查询、Watcher 或 daemon。

## 默认代码流程

1. 新代码任务检查官方 MCP 和 `graft_check_freshness`。
2. 通过 MCP 按需使用 `graft_repo_map`、`graft_file_api`、`graft_find_code`、`graft_trace_calls`、`graft_find_all`。
3. Agent 修改代码后自动发送一次 `agent_write`，由 SelfWorkFlow 调用官方结构更新。
4. 更新成功才重新报告 `fresh`；查询、Review 查询和纯读取不触发更新。

MCP 缺失、图过期或项目边界无效时，普通任务明确标记并回退到 `rg`；需要新鲜 Graft 证据的任务失败关闭。手工读取 `graft/` 文件不属于正式 Graft 查询证据。

## 来源、安装与图位置

正式来源是锁定的 `dependencies/upstream/graft` Submodule，身份由 `dependencies/locks/graft.lock.yaml` 绑定。安装器从锁定来源构建官方运行时，不使用未锁定的全局 PATH、`npx` 或临时网络包。

官方 MCP 按当前项目目录绑定，项目结构 Map 默认位于 `<repo>/graft/`。图是项目本地可再生缓存，不自动 Git add、commit 或 push；不使用 C 盘机器缓存，也不把固定项目路径写入全局配置。

SelfWorkFlow Host CLI 仅用于安装、预检、事件、Worker、显式维护和失败恢复；Agent 查询应使用官方 MCP。没有有效 Provider 或图边界时，不自动安装、扩大目录或猜测缓存路径。

## 写后结构更新

正式入口示例：

```powershell
%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd provider graft-event --config-file <machine-config> `
  --project-root D:\project --changed-path Source\a.cpp
%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd provider graft-worker --config-file <machine-config> `
  --project-root D:\project
```

Worker 合并重复事件、校验项目边界并调用官方结构 `build`；它不调用 `build --deep`。失败保留旧图并标记 `stale`/`failed`，不把部分缓存称为新鲜图。Worker 不实现后台 Watcher 或 daemon。

## 专题 Deep

Deep 不是全仓库默认步骤。一个对话只绑定一个 `topic-id`；专题上下文持续复用，不按 Git hash 建目录。全局 `<repo>/graft/` 保留非 Deep structural Map，专题上下文位于：

```text
<repo>/.selfworkflow/graft-deep/<topic-id>/graft/
```

每次 Deep 必须传入非空的项目内相对文件清单；SelfWorkFlow 将每个文件作为官方 Graft 的重复 `--only-dir`。它不会创建临时 Git 仓库，也不会因为范围不清而扫描整个项目。源文件 hash 用于识别不变、变更、新增和删除文件；专题只在明确使用该 topic 时惰性更新。

调用入口必须带专题和范围：

```powershell
%LOCALAPPDATA%\SelfWorkFlow\bin\selfworkflow.cmd provider graft-deep `
  --project-root D:\project `
  --topic-id kgpr-coverage `
  --scope-file Source\Renderer.cpp `
  --scope-file Source\Renderer.h `
  --model <current-agent-model> `
  --reasoning-effort <current-effort>
```

只有官方 build 成功、专题 context 的 `manifest.json` 存在、`check --json` 的 context/graph 均为 fresh 且源文件 hash 未漂移，才报告 Deep `fresh`。旧专题结果可保留为 stale reference；失败不得扩大范围或宣称成功。

仅主 Agent 可执行 Deep bridge。bridge 为官方 Graft 提供本次调用的 loopback OpenAI wire transport；每个请求转为一次只读、临时 `codex exec`，使用主 Agent 显式提供的同一 `model` 和 `reasoning-effort`。Codex 复用本机登录态，不需要 OpenAI API Key。Reviewer 只消费主 Agent 绑定的 evidence，禁止调用 Graft、provider 或 Deep。

## 与 Wiki 的关系

知识后端是独立可选模块。Wiki 可以把专题 Deep 的结构结果作为来源参考，但 Graft 不触发 Wiki、不依赖 Wiki，也不承担知识发布；知识仍按 `knowledge.read → knowledge.propose → knowledge.update` 和自己的确认规则执行。

## 故障与回退

| 状态 | 普通代码任务 | 明确要求新鲜 Graft 证据 |
| --- | --- | --- |
| Provider/MCP 缺失 | 标记 `unverified`，回退 `rg` | 失败关闭 |
| 全局图 stale | 标记 stale，必要时先更新 | 不满足新鲜证据 |
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

实际参数、JSON 字段和退出码以锁定 Submodule 的 `--help`、运行输出和测试为准；文档示例不能绕过 SelfWorkFlow 的边界和证据门禁。
