# CodeGraph 读取模块

- Windows 安装后的公共入口是 `$env:LOCALAPPDATA\SelfWorkFlow\bin\selfworkflow.cmd`，PowerShell 用 `& "$env:LOCALAPPDATA\SelfWorkFlow\bin\selfworkflow.cmd" provider preflight --project-root <repo>`。先检查该文件存在；仓库维护入口为 `Manage_SelfWorkFlow_Providers.bat`。不要猜 `python -m selfworkflow`，内部模块实际为 `selfworkflow.cli`，系统 Python 不一定含其依赖。入口缺失按安装问题报告，不扫描磁盘找替代 provider。
- 主 Agent 自动执行本模块，不等待用户提醒。代码任务首次进入结构化阅读、进入新的读取阶段或切换项目根目录时，以当前项目绝对根目录调用一次 `provider preflight --project-root <repo>`。同阶段、同根目录且无漂移信号时复用有效证据，不逐文件或逐行检查。
- 观察到目标仓库分支/HEAD 切换（checkout、reset、rebase、merge）、外部手动编辑、Git dirty/未跟踪变化，或 CodeGraph 的 worktree/stale/pending/degraded 通知时，立即失效相关旧图证据；下一次结构化查询前自动重新 preflight。文件内容变化即适用，不依赖用户提交或 `git add`。重新 fresh 后复查受影响的代码结论和实施计划，不能仅刷新图就继续旧计划。
- `preflight` 统一核对当前工作区：缺少 `.codegraph/` 时执行 CodeGraph `init`；已有索引在本次读取/漂移边界执行一次官方 `sync`，再检查状态。不能仅凭 `status` 的表面 fresh 跳过核对：其 Git 快速路径可能漏掉 clean checkout 后的已提交差异，官方 `sync` 才比较文件系统与索引，跳过未变文件的解析。成功完成后仍 stale/partial/failed/pending 或要求重建才执行一次 `index --force`；命令失败立即保留错误，不继续重建掩盖失败。成功核对且 fresh 才允许结构化查询。
- `indexState=indexing`、官方 MCP 明确 `busy` 或明确的锁占用都是忙碌信号，不是损坏证据；不启动竞争的 init/sync/rebuild。由主 Agent 用宿主可中断等待，间隔 5 秒、15 秒最多追加两次重试。相同根目录、阶段的 preflight/查询/写后维护共用该预算，不相互重置；每次重试先重查状态。耗尽后报告 `busy/unverified` 和待重试动作，不删除缓存或声称 fresh。图 fresh 也不能证明本次查询成功。
- 查询优先用已暴露的官方 CodeGraph MCP，明确 `projectPath` 和具体文件/符号，按需限制 `maxFiles`；CLI `provider query --provider-id codegraph --project-root <repo> --query <text>` 是另一入口，同一问题不调用两遍。CodeGraph 的项目级 `.codegraph/` 是唯一全局 CodeMap；不读取 conversation、Topic、Deep 或跨仓库图。
- 主 Agent 负责复用已返回的完整源码与依赖证据、合并同一问题的文件/符号，不再次查询相同内容；截断只补缺失片段。生命周期没有阶段缓存；独立 CLI `provider query` 每次仍自动核对，不与同问题的 MCP 查询重复执行。宽泛查询命中上游依赖时先收窄目标；明确 `busy` 只按共享预算处理，不叠加其他重试；其他可恢复失败最多一次有依据的重试，仍失败标 unverified，不循环消耗上下文。配置、文档、日志直接读精确路径，无需代码图。
- 官方 watcher/daemon 负责底层索引进程、锁和并发。官方 MCP 默认项目有 watcher；通过 `projectPath` 打开的其他项目不能假定有 watcher，默认根或监听健康状态未验证时也按无 watcher 处理。这类项目每次新的结构化查询前自动 preflight；复用已返回证据不产生新查询。连接关闭、watcher 不可用或降级时，在下一次工作流读取/写后边界自动补齐索引；不承诺无连接时持续监听。SelfWorkflow 不创建第二套 watcher、supervisor、定时轮询或缓存协议。
- 人为同时恢复文件原 size/mtime 是官方增量核对的已知特殊盲点；有此线索时使用现有 `index --force` 后重新验证，不宣称普通增量检查已覆盖。普通编辑/checkout 沿用上述自动路径，不要求用户定期手动维护。
- 支持的源码、未跟踪文件、ignore 与扩展名由官方 CodeGraph 的实际扫描配置决定，不在工作流复制白名单；忽略文件不自动扩大为输入。目标仓库代码/Git 差异走上述自动维护；CodeGraph 工具自身 `provider-source-identity-drift` 是不同边界，须 inspect、审查并在已有明确授权内重绑，不能自动替换 bindingHash。
- 状态、初始化或查询失败必须保留真实失败并标为 `unverified`；不得用旧索引、手工解析或 `rg` 结果冒充新鲜结构证据。简单文本定位可以单独使用 `rg`，但不替代 CodeGraph 证据。
- 只读阶段不得修改 `.codegraph/` 以外的项目文件；CodeGraph 的初始化和同步属于已授权的项目索引维护副作用。
