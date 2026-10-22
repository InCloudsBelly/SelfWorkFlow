# CodeGraph Provider

CodeGraph 是 SelfWorkFlow 唯一的代码图 Provider。它维护当前项目根目录下的
`.codegraph/` 全局 CodeMap，不依赖 Deep、Topic 或 conversation 图。

## 路由

代码任务读取前调用：

```bat
Manage_SelfWorkFlow_Providers.bat preflight --project-root D:\project
```

SelfWorkFlow 在读取和写后边界自动检查状态，不等待用户提醒。缺少索引时执行 `codegraph init`，
已有索引在本次边界执行一次 `sync` 核对文件系统。要求 reindex 时保留旧库并停止自动维护；
同步后仍不 fresh 时报告失败，不自动执行 `index --force`。不能仅凭 status fresh 跳过核对；
indexing/busy 不发起竞争维护。只有成功核对且 fresh
状态才允许结构化查询：

```bat
Manage_SelfWorkFlow_Providers.bat query --project-root D:\project --query "Where is the request flow?"
```

工作流写入、撤回、删除或重命名代码后，主 Agent 合并同一批实际路径并调用一次：

```bat
Manage_SelfWorkFlow_Providers.bat sync --project-root D:\project --changed-path Source\main.cpp
```

该入口先检查状态并执行一次必要的增量核对；官方 watcher 已更新的未变文件会跳过解析，
不会因此要求重写节点。`updated` 表示维护动作已执行，不代表一定有节点变化。
重命名包含旧、新路径，部分失败或回滚留下的实际代码变化也纳入本批。

## 自动触发边界

| 场景 | 主 Agent 自动执行的动作 |
| --- | --- |
| 首次结构化阅读、新读取阶段或项目根切换 | 按准确根目录 preflight，再查询；同阶段无漂移的证据复用 |
| 目标仓库分支/HEAD 切换，checkout/reset/rebase/merge | 旧证据失效；下一次查询前检查当前工作区并自动更新，复核受影响计划 |
| 手动修改、新增未跟踪源码、删除或重命名 | 无需提交或 git add；官方 watcher/扫描发现差异，下一读取边界自动补齐 |
| 工作流实际源码批次，包括子 Agent、脚本、部分失败与撤回 | 主 Agent 按根合并路径，在后续图查询或交付前调用一次 sync 入口 |
| 仅计划、普通文档/日志、无实际源码变化、官方配置忽略的文件 | 不触发写后更新；发生结构化代码阅读仍执行读取边界 |
| indexing、明确 busy 或锁占用 | 不重建；同根、同阶段共用两次自动重试预算，间隔 5/15 秒，耗尽为 unverified |
| CodeGraph 工具自身的源身份变化 | 与目标仓库漂移分开；inspect、审查，在明确授权内重新绑定，不自动采纳来源 |

支持的源码、未跟踪文件、ignore 和扩展名沿用官方实际配置，不在 SelfWorkflow
复制第二份清单。更新使相关旧图证据和代码结论失效；新的 fresh 状态也不能
替代本次查询成功，或自动批准已经不适用的旧实施计划。

`.codegraph/` 是项目级可再生缓存，不自动 Git add、commit 或 push。用户明确要求
清理旧版本时，可以删除同一仓库下遗留的 `<repo>\graft\` 缓存；不把它迁移成
CodeGraph 的输入。

## 运行时与生命周期

安装器默认使用个人维护的 [CodeGraph UE 子模块](../../extensions/codegraph/README.md)，
由父仓库 gitlink 和 `dependencies/locks/codegraph-ue.lock.yaml` 固定真实源码。
`-CodeGraphBackend official` 显式选择原有锁定的官方
`@colbymchenry/codegraph` `v1.6.2` 发布运行时；构建或身份验证失败不自动回退。
两种后端都注册 `codegraph serve --mcp`。CodeGraph watcher/daemon 负责索引进程、锁和并发；
SelfWorkFlow 不创建第二个 supervisor，也不重复实现图数据库。

UE 后端先实际探测 Node 的内建 SQLite，拒绝 Node 25 或不可用的运行时；
首次使用固定源码执行 `npm ci` 和 `npm run build`。回执绑定真实 Node、
dist、node_modules 和 UI workspace 内容，相同源码、Node 与运行内容全部通过校验时复用构建。
已有构建回执但身份漂移时停止，不原地覆盖可能正在使用的后端；受控停止旧后端后，
归档旧回执，再显式 prepare 和注册。具体命令见子模块说明。
已有个人 `-CodeGraphPath` 绑定继续保留；切换它需显式传入 `-ReplaceCodeGraphOverride`。

官方 MCP 默认项目有 watcher；通过 `projectPath` 打开的其他项目不能假定持续监听，
默认根/监听健康状态未验证时也按无 watcher 处理，每次新的结构化查询前由工作流自动 preflight。连接关闭或 watcher 降级时，下一次
读取/写后边界会自动补齐。此模块保证工作流使用时维护，不承诺没有连接时仍有
常驻监听服务，也不增加定时轮询。

当前官方 status 的 Git 快速路径可能在 clean checkout 后报告零 pending changes、
complete，却保留旧分支节点；官方 sync 使用文件系统与索引比较，能处理此差异。
因此每个边界一次核对是正确性需要，性能优化放在主 Agent 合并调用、复用已返回证据
及官方跳过未变解析。生命周期没有阶段缓存；独立 CLI query 每次仍核对，不对
同一问题重复调用 CLI 和 MCP。未承诺免 CLI 启动或目录枚举成本。

人为同时恢复文件原 size/mtime 是官方增量核对的特殊盲点；有此线索时由主 Agent
在独立候选库中重建、验证后安全切换，不直接覆盖旧库，也不要求用户周期性执行维护。
大型 UE 项目耗时尚未实测。

用户可以显式绑定一个本地 CodeGraph checkout：

```bat
Manage_SelfWorkFlow_Providers.bat configure --codegraph-path <local-codegraph-root>
```

本地 checkout 需要 `dist\bin\codegraph.js`；管理运行时需要
`bin\codegraph.cmd`。配置记录命令前缀、版本、源身份和绑定 hash，并在每次
Provider 调用前重新验证源身份。配置文件位于机器本地，不进入仓库。

## 失败边界

`provider-source-inspection-failed` 表示读取身份失败；诊断保留检查阶段、Git 操作、退出码及受限原因（如 timeout、dubious-ownership），不输出源码、凭据或完整 stderr。先恢复读取能力并重新 inspect，不重绑定。Git 只对已明确绑定的 canonical 根启用命令级 safe.directory，不写全局配置。

`provider-source-identity-drift` 只用于已成功读取身份且字段实际变化；诊断给出 changedFields 和前后 sourceHash。先 inspect 当前来源并审查变更，确有授权再 configure；不得自动替换 bindingHash。busy 表示队列状态，不据此删除或重建索引。

初始化、同步、重建或查询失败必须保留真实状态并标记 `unverified`；不得把旧索引、
手工解析或 `rg` 结果伪装成 fresh CodeGraph 证据。`rg` 不是默认阅读入口；简单文本定位仍可使用 `rg`，
但不能替代需要结构关系的新鲜 CodeGraph 结果。Reviewer 只消费主 Agent 绑定的
CodeGraph evidence，不调用 Provider 或维护命令。

status 返回 `indexingConfig.error` 时，Adapter 将索引视为 stale，自动边界以
`codegraph-indexing-config-invalid` 停止，不发起初始化、同步或重建，保留原数据库。

维护命令失败立即停止，不通过重建掩盖错误。命令成功但实际状态仍为
stale/partial/failed/pending 时保留真实状态并报告 `unverified`；要求 reindex 时在同步前停止，
不自动重建；indexing 始终按忙碌处理。读取与写后维护的规则分别在
`workflow/modules/codegraph-read.md`、`workflow/modules/codegraph-update.md`。

CLI `sync` 在锁获取失败时必须退出非零，不能将未完成的同步称为成功。
Adapter 仅将 CodeGraph 的受限锁占用错误行映射为
`codegraph-project-busy`，由主 Agent 使用同一有界预算恢复；其他错误保持失败关闭。
watcher 的重试与锁恢复由 CodeGraph 管理。

## 检查命令

默认安装入口使用已验证的冻结 Host，`--host-info` 可确认当前 artifact 与 CLI 路径：

```powershell
& "$env:LOCALAPPDATA\SelfWorkFlow\bin\selfworkflow.cmd" --host-info
& "$env:LOCALAPPDATA\SelfWorkFlow\bin\selfworkflow.cmd" provider inspect --codegraph-path <configured-root>
```

开发源码修改须重新 build/install 才会改变默认入口。Host 启动拒绝快照、指针或 Python 漂移，不自动改用开发源码。维护源码仍可显式使用仓库 `.venv\Scripts\python.exe -m selfworkflow.cli`。

```bat
Manage_SelfWorkFlow_Providers.bat list
Manage_SelfWorkFlow_Providers.bat doctor --provider-id codegraph
Manage_SelfWorkFlow_Providers.bat status --provider-id codegraph --project-root D:\project
```
