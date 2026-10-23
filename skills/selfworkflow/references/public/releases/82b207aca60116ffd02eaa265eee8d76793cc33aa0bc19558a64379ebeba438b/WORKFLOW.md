文档入口模式：本任务 documentRoot 为本文件所在的 releases/<revision> 目录；继承入口绑定。方法仅提供专业补充，不另起流程或执行上游安装、hooks、菜单；不读取历史宿主副本。

# SelfWorkFlow 启动入口

厂商无关；沟通和工程文档用中文，代码、命令、路径和协议字段保留原文。

## 启动：只读当前任务需要的规则

每个用户顶层任务一次 Discover → Capability Check → Classify；实际读取固定入口并绑定 revision/documentRoot。子任务、独立 Reviewer、阶段切换和续接继承绑定，不重选 latest。相对链接从声明文件解析，项目根另行明确。

- 已安装通用 Skill 且入口可读，即已接线；新会话不等于首次宿主接入。仅用户要求安装/迁移、入口不可读或必要宿主能力改变时读 [接入指南](workflow/onboarding.md)。Capability Check 只核对当前动作需要的工具，不枚举未用服务。
- 低复杂度、低风险、边界清楚的查询或小修改用 [Light](workflow/modes/light.md)；中高复杂度/风险用 [Full](workflow/modes/full.md)；高风险、复杂边界或显式深度分析用 [Deep](workflow/modes/deep.md)。只读选定的 `workflow/modes/<mode>.md`，模式不自动加载其他方法；knowledge profile 不自动升级 Full。
- 路径、版本/hash、输入未变且正文完整时跨阶段/相邻轮次复用；正文缺失只补受影响内容，摘要不冒充已读完整规则。缺失、不可读、hash 漂移标 `unverified`，不得省略必需规则冒充优化。
- 普通任务不加载安装 manifest、`workflow/core.md`、PlanGraph/RunLedger 或 package/receipt/runner；仅显式 contract-managed task 或 conforming Host 已按契约承接当前任务时读 [兼容 Host](workflow/legacy-host.md)，保留正式回执、防伪和完成门禁。能力存在本身不激活契约。

工具/修改任务首报 `SelfWorkflow active: <profile>；mode: <Light|Full|Deep>`；Full/Deep 简报当前阶段和剩余，不能估时就说明。后续只报告阶段变化、阻塞、重估或完成，遵守宿主频率。

## 按操作加载，不按阶段名或关键词叠加

已知方法直接读取下列链接；仅明确需要其他专业方法且路径未知时，在 `methods/INDEX.md` 中检索匹配条目，不把整表当启动依赖。不因“分析、审查、验收、完成”等阶段词加载方法或其引用。

| 当前操作 | 必需补充 |
| --- | --- |
| 追踪或修改行为源码 | [代码模块](workflow/modules/code.md)与[责任层方法](methods/code-quality/METHOD.md)；配置、文档、日志、精确常量查询直接读目标路径 |
| 行为变更 TDD、测试设计或明确核验测试执行证据 | [测试方法](methods/testing-review-quality/METHOD.md)；只读分析、普通 Review、机械文档校验不触发 |
| 实际文件变更、安装/发布或外部副作用的保护与验收 | [操作证据](methods/workflow-quality/METHOD.md)；只读说明验收条件不触发 |
| 新增/改造/集成 Skill 或工作流 | [工作流维护](methods/workflow-skill-maintenance/METHOD.md)；使用现有能力和纯审查不触发 |
| 执行编译检查或改动共享头、构建规则、工具链 | [编译缓存保护](workflow/modules/build.md)，动作前读取 |

Ponytail、C++、项目 Review、真实 UI、研究长文、Obsidian、Wiki 等只在实际操作命中时加载最窄方法；知识按 read → propose → update，update 需明确写入授权，直接要求更新/发布即覆盖对应范围。完整 `grilling` 和 TEA 仅用户显式点名；不因 Full/Deep、项目默认或阶段变化启用，不重启已完成访谈。Superpowers 仅显式启用。

同职责由最窄匹配 Skill 承接，通用 Skill 只补缺项；关键词重叠不叠加编排。模块限制仅约束命中的操作、产物和角色；局部失败不传播为无关模块的前置条件，必要依赖失败只阻塞对应动作。

## 实施、Review 与授权

Light 窄结构化自审；Full/Deep 交付前一个独立 SubAgent，所有模式禁止双 Reviewer。仅到 Review 阶段读 [Review 模块](workflow/modules/review.md)；重大架构、安全、持久化、不可逆风险或显式要求才提前读。普通设计/计划/测试设计合并自审。

首次编辑测试/生产代码前明确紧凑实施契约：范围、owner、侵入预算、替代方案、兼容/安全/性能、回滚和测试接缝。Plan 是实施边界；必要测试不能反向扩张生产架构。已有同范围授权直接复用；关键决策未定、越权或实质扩大公共接口/持久化/副作用/风险时需重新确认，不伪造能力或降级冒充通过。

用户实现/修复/维护请求授权范围内必要、可逆工作，紧凑方案后执行；不重复索要自拟计划批准，不扩权到不可逆操作、共享宿主重启或未要求的外部发布。只有关键选择无法查明、真实越权或并发修改冲突才暂停受影响动作；先完成独立工作，等待时间不是授权。缺能力可采用已授权等效方法并如实标记，不伪造独立 Review、图新鲜度或来源确认。

## 证据、复用与交付

保护用户已有修改、凭据与授权；只读任务 `writeTask=false`，不得编辑或产生副作用，CodeGraph 定义的索引维护例外。任务外异常隔离：非当前目标根因或完成验收必需的故障，必须用户明确授权后另行处理。

独立只读查询批量执行；大清单/日志先在工具端按问题投影，仅输出必要身份、计数、失败和原文。不先输出全清单再截断；已完整证据不重取。输入未变不追加同样的审查、测试或全仓扫描，失败先定位再有依据重试；长命令用可中断长等待，避免秒级空轮询。

仅需跨压缩/交接时，在已有记录保留目标与授权、当前阶段、规则路径/hash与正文是否仍在、有效证据及其输入、待办/运行任务/Reviewer 标识。压缩本身不撤销授权或使未变证据失效，不为短任务新增记录，不为缓存保温复制历史。临时记录放 `./selfworkflow/`，不自动 Git add。

完成前核对新鲜证据：直接路径、失败路径、最窄回归和副作用复读；禁编译/测试时记 not-run/unverified。本次目标相关 Critical/Important 必须解决（只读审查以发现为结果）；其他问题说明处置，不因 Token/次数预算耗尽中止未完成任务。
