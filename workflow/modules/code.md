# 代码模块

命中代码、配置消费者、持久化、跨层行为、Bug、重构或 C/C++/UE 任务时加载。

- 先追踪最小完整链路：输入 → owner → 状态/缓存/临时产物 → 输出；区分 root cause owner 与 detection point，优先在最早拥有不变量的层修复。
- 以影响半径判断侵入性，不以行数判断。公共 API/ABI/Schema、持久化、全局宏/Build variant、共享热路径和非必要调用者是高风险信号；先比较更窄方案。
- 仅对 C/C++/UE 任务默认加载 `cpp-core`，再按类型、并发、ABI、性能、安全、构建或 UE 信号读取专项引用；其他代码任务不加载。测试不得反向推动生产架构。
- 新对话首次命中代码任务时做一次 Graft preflight。已绑定且索引新鲜时优先结构化查询；缺图时只为当前项目惰性初始化并补充锚定 `/graft/` Ignore，安装阶段不扫描项目。过期时明确询问：显式更新后使用、以旧索引作只读参考、或本对话不用。用户选择写入会话级状态，后续不重复询问；缺失或 runtime-unavailable 时不阻塞基础分析，更新失败继续标为过期，`rg` 只补未覆盖和精确文本，不得冒充新鲜证据。Graft 查询固定 `--no-refresh`，不得隐式 build；需要新鲜图证据的任务失败关闭。CodeGraph 仅作为遗留/用户显式指定 Provider，不作为默认路径。
- Agent 完成代码写入后，Host 必须发送一次 `agent_write` 事件（项目根目录 + 本次变更路径摘要）并调用 SelfWorkFlow Graft Worker；Worker 合并重复路径、使用每项目单锁、只执行结构 build，并在失败时保留可重试队列和旧图。没有原生 Host Hook 的 Agent 使用等价 CLI 入口，不启动文件 Watcher、全局 daemon 或 Graft 自带 Hook。查询、读取、Review 和测试读取不发送事件。
- 行为变更必须记录 TDD RED/GREEN、失败路径、状态不变量和最窄回归；不扩大稳定调用者或无关模块。
