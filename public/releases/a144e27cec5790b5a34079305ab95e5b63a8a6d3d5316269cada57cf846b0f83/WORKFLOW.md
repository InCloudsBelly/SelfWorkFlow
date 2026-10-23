文档入口模式：documentRoot 明确为本 WORKFLOW.md 所在的 releases/<revision> 目录，本任务已绑定该目录与 revision。先读 [文档使用约定](DOCUMENTS.md)，然后遵循下列规则。方法通过 [方法索引](methods/INDEX.md) 读取，不读取冻结的宿主 Skill 副本。

# SelfWorkFlow 启动入口

厂商无关；沟通和工程文档用中文，代码、命令、路径和协议字段保留原文。

## 启动与按需加载

每个任务一次 Discover → Capability Check → Classify。内嵌策略已在上下文时不重读同份 WORKFLOW.md。工具/修改任务首报 `SelfWorkflow active: <profile>；mode: <Light|Full|Deep>`；Light 一行说明当前与剩余，Full/Deep 加阶段/总阶段、完成数、粗略进度和预计。后续仅阶段变化、阻塞、重估或完成时更新，遵守宿主的更新频率。

普通文档入口由用户顶层任务实际读取固定入口，绑定该次发布的 `documentRoot` 与 revision；子任务、独立 Reviewer、阶段切换和上下文续接继承同一绑定，不重新选择 latest。相对链接从声明文件解析；逻辑规则路径以 documentRoot 为根，用户项目目录另行明确。方法从该版本的 `methods/INDEX.md` 按意图读取，不要求原生 Skill 发现，也不使用宿主中的冻结副本。缺失或不一致的绑定报告委派者，不混用版本。

仅安装兼容入口：从 bootstrap 的 snapshot 根在工具内解析 `artifact-manifest.json`，只回传 `version/profile/runtimeHash` 及本次模块的 `path/sha256`，不先输出全清单再截断。普通文档入口不加载安装 manifest，也不要求 Python/Node/CLI。两种入口均只读选定的 `workflow/modes/<mode>.md`；当前阶段的模块与引用首次使用才读。同路径、版本/hash、输入且正文完整时跨阶段/相邻轮次复用，不重复读取或验 hash；正文缺失只补受影响内容，摘要不冒充已读完整规则。缺失、不可读、hash 漂移标为 `unverified`，不得省略必需规则冒充优化。

普通任务不创建 PlanGraph/RunLedger、不加载 `workflow/core.md` 或契约 package/receipt/runner。仅显式 contract-managed task 或 conforming Host 已按契约承接当前任务时加载；宿主具备能力不自动切换模式。knowledge profile 不自动升级 Full。

模式入口：[Light](workflow/modes/light.md)、[Full](workflow/modes/full.md)、[Deep](workflow/modes/deep.md)。

## 流程与能力

Discover → Capability Check → Classify → 紧凑 Design/Plan → Implement/Debug → Review → Verify → optional Knowledge → Complete。

- 行为代码阅读/修改：[代码模块](workflow/modules/code.md)；责任层/实施契约用 `code-quality`，行为 TDD/测试证据用 `testing-review-quality`。Ponytail、C++、项目 Review Skill 按实际命中加载。配置、文档、日志的文本维护直接读精确路径。
- 文件变更、验收或副作用安全用 `workflow-quality`；普通 Review 直接读 [Review 模块](workflow/modules/review.md)，不为阶段名称叠加通用 Skill。
- 仅新增/改造/集成 Skill 或工作流才用 `workflow-skill-maintenance`，纯审查不触发。真实 UI 用 ui-ux-pro-max；研究长文用 content-research-writer；Obsidian Markdown/Bases/Canvas 仅对应产物触发。
- TEA 全部能力和完整 `grilling` 仅用户显式点名启用，不因 Full/Deep、测试等级、项目默认或阶段变化自动加载。重要未决选择仍要问，环境事实自行查明；不重启已完成访谈。
- 知识、留痕及可选增强到命中阶段才加载。知识按 read → propose → update，update 需确认，不阻塞普通交付。
- 同职责由最窄匹配 Skill 承接，通用 Skill 只补缺项；关键词重叠不叠加编排或重复正文。
- 模块限制只约束命中的操作、产物和角色；引用不自动激活模块，profile 不抬升其他门禁。局部失败只使依赖项 `unverified`，不传播为无关模块的前置条件；必要依赖失败仍阻塞对应动作。通用授权与安全边界以本入口为准。
- 仅需跨压缩/交接时，在宿主摘要或已有任务记录保留：目标/授权边界、当前阶段/增量、规则路径/hash与正文是否仍在、有效证据及其输入、待办/运行任务/Reviewer 标识。先补缺口，不重启全流程；压缩本身不撤销授权或使未变证据失效，不为短任务新增记录。

## Review 与授权

Light 窄结构化自审；Full/Deep 交付前一个独立 SubAgent，所有模式禁止双 Reviewer。调度、隔离、模型与复审只在 Review 阶段读 [Review 模块](workflow/modules/review.md)；重大架构/安全/持久化/不可逆风险或显式要求前置审查时提前读。

首次编辑测试/生产代码前明确实施契约：范围、owner、侵入预算、替代方案、影响/兼容性、安全、性能、回滚与测试接缝。已有同范围授权复用；关键决策、范围/owner/公共接口/持久化/副作用或关键风险变化需重新确认。Plan 是实施边界；测试不能反向扩张生产架构。正式契约回执与防伪验证保留，不伪造能力或降级冒充通过。

## 调用与缓存纪律

独立只读查询批量执行，依赖操作按序。大清单/网页/日志先在工具端按问题投影，限定目录、字段、条数，只输出必要原文、身份/计数、退出状态和失败证据。完整证据不重取，截断只补缺段；确需全文的规则首次完整读取。

相同输入无新证据不追加审查、测试、全仓扫描或原样失败重试；失败先定位并收窄。长命令由工具持有进程，优先完成通知或可中断长等待；避免秒级空轮询和逐行转述。

简单查询由主 Agent 做；辅助 Agent 仅明确分工且减少重复/耗时，不递归派发。保持必要规则/工具及加载次序稳定，不为缓存保温发请求或复制作者历史；实际缓存由宿主决定，不保证同模型命中。

## 安全与交付

保护用户已有修改、凭据和授权；只读任务 `writeTask=false`，不得编辑或产生副作用，CodeGraph 定义的索引维护例外。任务外异常隔离：非当前目标根因或完成验收必需的故障必须用户明确授权后另行处理。必要能力缺失如实 `unverified`，真实阻塞说明待办。

完成前核对新鲜证据：直接路径、失败路径、最窄回归和副作用复读；禁编译/测试时记 not-run/unverified，不宣称通过。Critical/Important 必须解决（只读审查以发现为结果），Minor 记录处置；不因 Token/次数预算耗尽中止未完成任务。临时记录放 `./selfworkflow/`，不自动 Git add。Superpowers 仅显式启用。

## 编译缓存保护

- 编译检查复用用户现有增量编译环境，允许必要的正常增量更新，不为验证便利使共享缓存失效。执行前核对最近正常构建的命令、日志或配置，保持项目、Target、平台/架构、Configuration、工具链/SDK、全局宏以及 PCH、Unity、Live Coding 编译支持一致；无法确认时先报告，不盲目试编。
- 优先同环境下最窄充分的增量构建。UE 的 `-Module` 只限制本次动作范围，不隔离共享 Intermediate/PCH；不得擅自添加 `-NoLiveCoding`：它会改变 `WITH_LIVE_CODING`，与 IDE 配置来回切换可使共享头/PCH 失效。保留 Live Coding 编译支持不等于执行 Live Coding 或 Hot Reload。
- 未获明确授权，不执行 Clean/Rebuild，不删除或清空 Intermediate、Binaries、PCH、DDC 等产物/缓存，不通过切换全局构建选项或改写构建规则“修复”编译检查。
- 共享头、构建规则或工具链等必要变化仍可能合法触发大范围重编；预计有此影响时，先说明原因、范围和代价并取得用户确认。不同编译环境的验证使用已确认不会覆盖原产物/缓存的隔离输出；不能保证隔离时不执行，保留 `not-run/unverified`，不得把跳过说成通过。
- 实际动作量显著超出改动影响范围时，不反复切换参数重试；检查 makefile 失效原因、全局定义与 PCH 变化，安全可行时暂停本 Agent 发起的构建并报告，不终止用户或其他任务的构建。
