# CodeGraph 读取模块

行为源码的跨文件理解、符号定位、调用与依赖分析默认先查询项目已计算的图谱；配置、文档、日志与已给定精确路径的源码复核直接读取。主 Agent 维护项目唯一 `.codegraph/`，不读取 conversation、Topic、Deep 或跨仓库图。

## 核对边界

- 只用实际提供、绑定项目且获授权的 MCP/CLI 协议。已有 Windows 桥接 `$env:LOCALAPPDATA\SelfWorkFlow\bin\selfworkflow.cmd` 可执行 `provider preflight --project-root <repo>`；它不是文档启动前提。缺能力仅该结构化操作 `unverified`，不扫描替代入口、不猜系统 Python、不伪造 fresh。安装另用 `Manage_SelfWorkFlow_Providers.bat`。
- MCP 路径：首次/新阶段/换项目查询前，以绝对项目根做一次 `preflight`；同阶段/根无漂移则复用。优先官方 MCP，明确 `projectPath`、具体文件/符号和 `maxFiles`。
- CLI 路径：`provider query --provider-id codegraph --project-root <repo> --query <text>`；它已包含核对，不先另跑 preflight。成功核对且 fresh 后才查询，不再用 MCP 重复。独立 CLI 调用不共享阶段缓存。
- 当前会话没有暴露 CodeGraph MCP 工具时，默认使用上述已安装 Windows 桥接执行 CLI 查询，始终传绝对 `--project-root`；配置文件或后台进程存在不等于工具已可调用。桥接也缺失时才报告该能力缺口并按失败边界继续源码分析，不以 PATH 中的其他 `codegraph` 副本替代已绑定 provider。
- 分支/HEAD、外部编辑、dirty/未跟踪或 stale/pending/degraded 漂移使相关证据失效；下次查询重新核对，并复查受影响结论，不依赖提交或 `git add`。

## Freshness 与失败

- `preflight`：数据库确实缺失才官方 `init`；已有库先官方 `sync` 再查状态，未变文件跳过解析。不能仅信可能漏掉 clean checkout 的 `status`。异常、仍 stale/partial/failed/pending 或要求重建时，保留原库并报 `not-fresh/unverified`。禁止自动 `index`、`index --force`、`recreate` 或删库；全量重建须明确授权，保留可恢复旧库直到新库验证完成。核对 fresh 才查询，图 fresh 不等于查询成功。
- indexing、MCP 明确 busy 或锁占用只表示忙碌，不并发 init/sync/rebuild。宿主可中断等待 5 秒、15 秒，最多追加两次，每次先重查状态；同根/阶段的 preflight、查询、写后维护共享预算。耗尽报 `busy/unverified` 及待办，不删除缓存。其他可恢复失败最多一次有依据重试。
- 失败如实 `unverified`，不以旧索引或 `rg` 冒充图证据；`rg` 只定位文本。普通任务可直接读源码、手工追踪和测试，标明证据来源，无法查明的依赖保留待办；不自动阻止其余编辑/审查/交付，不为此请求安装、重建或豁免。显式契约图门禁保留。完整证据复用，截断补缺，宽查询收窄。

## Watcher 与范围

- 官方 watcher/daemon 管进程、锁与并发；仅健康且已验证的默认项目 watcher 可复用阶段核对，否则 MCP 每次新查询前 preflight，CLI 自身核对。断连在下个边界补齐，不另建 watcher/supervisor/轮询。
- 人为恢复 size/mtime 是盲点：有线索则报告并提出保留旧库的重验方案，不自动重建。扫描、ignore、未跟踪/扩展名遵循官方配置。
- `provider-source-identity-drift` 先 inspect、审查再于既有授权内重绑，不自动换 bindingHash。只读仅允许 `.codegraph/` 维护副作用。
