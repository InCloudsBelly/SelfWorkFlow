# CodeGraph 读取模块

主 Agent 只用项目唯一 `.codegraph/`；不查 conversation/Topic/Deep/跨仓库图。跨文件行为理解、符号/调用/依赖分析先查询已计算图；配置、文档、日志及精确源码路径复核直接读。图不替代最终源码核对。

## 核对边界

只用实际可用且绑定项目的 MCP/CLI，不因配置/进程存在宣称可调用。优先官方 MCP，给绝对 projectPath、文件/符号及 maxFiles；首次/换阶段/换项目查询前一次 preflight，同阶段/根无漂移复用。健康且已验证的默认 watcher 可复用核对，否则新 MCP 查询前核对。
CLI 路径：`provider query --provider-id codegraph --project-root <绝对repo> --query <text>`；它已包含核对，不先另跑 preflight。成功核对且 fresh 后才查询，不再用 MCP 重复。独立 CLI 调用不共享阶段缓存。
未暴露 MCP 时用已安装 Windows 桥接 `$env:LOCALAPPDATA\SelfWorkFlow\bin\selfworkflow.cmd`，始终给绝对 --project-root；桥接也缺失才报告。不扫描替代入口、不猜 Python、不用 PATH 的其他副本，不自动安装或创建 watcher/supervisor。
分支/HEAD、外部编辑、dirty/未跟踪、stale/pending/degraded 使相关证据失效；下次重核对并复查影响结论，不依赖提交或 git add。

## Freshness 与失败

- preflight 仅对 `initialized=true` 且 `indexState=complete` 的已有库做官方增量 sync 后查状态；未变文件跳过解析，不能只信可能漏掉 clean checkout 的 status。缺失/未知/损坏/不完整库保留并报需显式初始化/恢复，首次使用也不自动 init。
- `<索引目录名>.publication.json`/`.publication.lock` 存在、不可读或异常即停止普通访问；正式目录暂缺也不能初始化。默认与 CODEGRAPH_DIR 候选分别保护；跟踪表/节点表一侧非空同样停止。初始化/发布共用独占租约，残留显式恢复，不按超时删锁。
- stale/partial/failed/pending 或需重建：保留原库、报 not-fresh/unverified。禁止自动 init/index/index --force/recreate/删库；初始化/重建需明确授权，独立候选验证后才替换，保留可恢复旧库。fresh 不等于查询成功。
- 覆盖与新鲜度分开：仅 `inputsVerified=true` 且无漂移时可带 `cpp-include-coverage-incomplete` 限制查询；未知旧 provider、输入不可读/未核验/变化不放行。fresh 不证明 UE Build.cs/include 全覆盖。
- indexing/busy/锁占用不并发 init/sync/rebuild。可中断等5秒、15秒，最多追加两次，每次先查状态；同根/阶段 preflight/query/sync 共享预算。耗尽 busy/unverified，不删缓存；其他可恢复故障最多一次有据重试。
- 失败仅阻依赖图的动作。普通任务可用直接源码、手工追踪和测试继续，rg 只定位文本，不冒充图证据；缺口 unverified，不请求安装/重建/豁免。显式契约图门禁保留。完整证据复用，截断补缺，宽查询收窄。

size/mtime 人为恢复属盲点，有线索提出保留旧库的重验方案，不自动重建；扫描/ignore/扩展名遵官方配置。provider-source-identity-drift 先 inspect/审查，再于已有授权内重绑，不自动换 bindingHash。只读任务仅允许图索引维护副作用。
