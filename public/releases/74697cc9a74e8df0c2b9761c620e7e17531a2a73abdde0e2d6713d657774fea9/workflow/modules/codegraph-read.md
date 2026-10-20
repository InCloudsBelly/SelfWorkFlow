# CodeGraph 读取模块

仅行为源码的结构化阅读使用；配置、文档、日志直接读精确路径，无需代码图。主 Agent 自动维护当前项目级 `.codegraph/`，这是唯一 CodeMap；不读取 conversation、Topic、Deep 或跨仓库图。

## 入口与核对边界

- 按当前会话实际提供、已绑定项目且获授权的 CodeGraph MCP/CLI 能力执行核对与查询，检查真实工具协议，不按 Agent 名称猜测方法。已有 Windows 桥接入口 `$env:LOCALAPPDATA\SelfWorkFlow\bin\selfworkflow.cmd` 可继续使用：`provider preflight --project-root <repo>`。该程序不是工作流文档的启动前提；未提供等价的必要核对/查询能力时，仅该结构化操作保持 `unverified`，不扫描替代入口、不猜系统 Python、不伪造 fresh。工具安装与配置是独立操作，维护入口为 `Manage_SelfWorkFlow_Providers.bat`。
- MCP 路径：首次/新阶段/换项目的结构化读取前，以绝对项目根做一次 `preflight`；同阶段、同根且无漂移复用核对证据。优先官方 MCP，明确 `projectPath`、具体文件/符号与适当的 `maxFiles`。
- CLI 路径：直接用 `provider query --provider-id codegraph --project-root <repo> --query <text>`；它已包含核对，不先另跑 preflight。成功核对且 fresh 后才查询；该次成功满足此读取边界，不另调用 MCP 回答同一问题。独立 CLI 调用不共享阶段缓存，每次仍核对。
- 分支/HEAD、外部编辑、dirty/未跟踪漂移或 worktree/stale/pending/degraded 通知，立即失效相关旧证据；下一次新查询按所选路径重新核对。fresh 后复查受影响结论/计划，不能只刷新图；不依赖提交或 `git add`。

## Freshness 与失败

- `preflight`：仅数据库文件不存在时官方 `init`；数据库存在但无法识别时报告错误并保留原库。已有索引先官方 `sync` 再查状态。不能仅信 `status`，其 Git 快速路径可能漏掉 clean checkout；`sync` 核对文件系统并跳过未变解析。成功后仍 stale/partial/failed/pending 或要求重建时，保留原库并报告 `not-fresh/unverified`；禁止自动执行 `index`、`index --force`、`recreate` 或删除旧库。全量重建须另有用户明确授权，并保留可恢复旧库直到新库验证完成；命令失败保留错误，不重建掩盖。核对成功且 fresh 才允许结构化查询，图 fresh 不等于查询成功。
- indexing、MCP 明确 busy 或锁占用只表示忙碌，不并发 init/sync/rebuild。宿主可中断等待 5 秒、15 秒，最多追加两次，每次先重查状态；同根/阶段的 preflight、查询、写后维护共享预算。耗尽报 `busy/unverified` 及待办，不删除缓存。其他可恢复失败最多一次有依据重试。
- 状态/初始化/查询失败如实 `unverified`，不将旧索引、手工解析或 `rg` 冒充新鲜结构证据；`rg` 仅作文本定位。已返回完整证据复用，截断只补缺段；宽泛查询命中上游时收窄，不重复全文。

## Watcher 与范围

- 官方 watcher/daemon 管进程、锁和并发。仅已验证的默认项目 watcher 可复用阶段核对；其他项目、默认根/监听健康未验证时，MCP 每次新查询前 preflight，CLI 使用自身核对。断连/降级在下个读取/写后边界补齐，不承诺离线持续监听，不另建 watcher/supervisor/轮询协议。
- 原 size/mtime 被人为恢复是增量检查盲点，有此线索时报告缺口并提出保留旧库的重验方案，不自动全量重建；普通编辑/checkout 沿增量路径。扫描范围、未跟踪/ignore/扩展名遵循官方配置，不复制白名单或扩大忽略输入。
- `provider-source-identity-drift` 须 inspect、审查并在已有授权内重绑，不自动换 bindingHash。只读阶段仅允许 `.codegraph/` 索引维护副作用，不改其他项目文件。
