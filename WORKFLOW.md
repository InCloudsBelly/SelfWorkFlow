# SelfWorkFlow 启动入口

厂商无关；沟通和工程文档用中文，代码、命令、路径和协议字段保留原文。

## 启动与按需加载

每个任务一次 Discover → Capability Check → Classify。首条工具/修改进度报告 `SelfWorkflow active: <profile>；mode: <Light|Full|Deep>`，附阶段/总阶段、完成数、粗略进度区间、当前、剩余和预计；后续只在阶段变化、阻塞、重估或完成时更新。

从 bootstrap 指定的 snapshot 根读取 `artifact-manifest.json`，仅提取身份和本次模块 hash，不输出全清单或搜索历史日志。只读选定的 `workflow/modes/<mode>.md`，当前阶段命中的模块与必要引用首次使用才读。同路径、版本/hash、证据且正文仍完整时跨阶段/相邻轮次复用，不为“使用 Skill”重读或重复验 hash；范围/版本/输入漂移或压缩后正文缺失只补受影响内容，摘要不冒充已读完整规则。缺失、不可读、hash 漂移标为 `unverified`，不得省略必需规则冒充优化。

普通任务不创建 PlanGraph/RunLedger、不加载 `workflow/core.md` 或契约 package/receipt/runner 规则。只有显式 contract-managed task 或 conforming Host 按契约承接才加载；宿主具备能力不自动切换模式。knowledge profile 不自动升级 Full。

## 流程与能力

Discover → Capability Check → Classify → 紧凑 Design/Plan → Implement/Debug → Review → Verify → optional Knowledge → Complete。

- 代码/C++/UE/跨层行为：`modules/code.md`；责任层与实施契约用 `code-quality`，证据/副作用用 `workflow-quality`，行为变更 TDD/验证用 `testing-review-quality`。Ponytail、C++、项目 Review Skill 按实际命中加载。
- CodeGraph 是项目级唯一 CodeMap，官方 MCP 为结构化代码阅读入口。主 Agent 按 `codegraph-read.md` / `codegraph-update.md` 维护生命周期；Reviewer 不调用 provider，不虚构 fresh。
- 仅明确维护 Skill/工作流才用 `workflow-skill-maintenance`。真实 UI 用 ui-ux-pro-max；研究长文用 content-research-writer；Obsidian Markdown/Bases/Canvas 仅对应产物触发；普通 Markdown 不触发它们。
- TEA 全部能力和完整 `grilling` 仅用户显式点名启用，不因 Full/Deep、测试等级、项目默认或阶段变化自动加载。重要未决选择仍要问，环境事实自行查明；不重启已完成访谈。
- Review 唯一调度见 `modules/review.md`；知识、留痕及其他显式可选增强到相应阶段才加载。知识按 read → propose → update，update 需确认；不阻塞普通交付。
- 同职责由最窄匹配 Skill 承接，通用 Skill 只补缺项；关键词重叠不叠加编排或重复正文。上下文恢复保留目标、授权边界、当前增量、有效证据和待办引用，先补缺口，不重启全流程。

## Review 与授权

Light 窄结构化自审；Full/Deep 交付前一个独立 SubAgent 同时检查 Standards/Spec，所有模式禁止双 Reviewer。普通设计/计划/测试设计合并自审；重大架构、安全、持久化、不可逆风险或显式请求才前置独立 Review，尽量复用同一审查者。机械文档同步不单开审查。Review 继承主 Agent 模型/推理配置，不读取专属模型配置或传入覆盖；独立性来自上下文隔离，不导入主历史。

首次编辑测试/生产代码前明确实施契约：范围、owner、侵入预算、替代方案、影响/兼容性、安全、性能、回滚与测试接缝。已有同范围授权复用；普通任务不是一律 Review → 用户确认 → TDD，前置门禁仅按上述真实风险触发。关键决策、范围/owner/公共接口/持久化/副作用或关键风险变化需重新确认。Plan 是实施边界；测试不能反向扩张生产架构。正式契约回执与防伪验证保留，不伪造能力或降级冒充通过。

## 调用与缓存纪律

独立只读查询批量执行，工具结果先本地筛选字段/范围再输出；依赖操作按序。已返回完整证据不重取，截断只补缺段。相同输入无新证据不追加审查、测试、全仓扫描或原样失败重试；先定位原因、收窄、合并或换有效路径。修复只复核受影响项，继续到验收，不因 Token/次数预算耗尽中止未完成任务。

大清单/网页/日志先在工具端按问题投影，仅返回必要原文、身份/计数、退出状态与失败证据；摘要不替代确需完整读取的规则。长命令由工具持有进程，优先完成通知或可中断长等待，合并独立工作；避免秒级空轮询和逐行转述，遵守宿主等待上限及进度要求。

简单事实查询由主 Agent 做；辅助 SubAgent 仅用于分工明确且能减少重复或显著缩短耗时的任务，不递归派发、不与主 Agent 重做同一工作。稳定必要规则/工具及加载次序；不为缓存保温发请求、不保留无用历史、不通过复制作者上下文提高 Reviewer 命中率。实际缓存由宿主决定，不保证同模型必命中。

## 安全与交付

保护用户已有修改、凭据和授权；只读任务 `writeTask=false`，不得编辑或产生副作用，CodeGraph 定义的索引维护例外。任务外异常隔离：报告并延后，不旁路修复；非当前目标根因或完成验收必需的故障必须用户明确授权后另行处理。必要能力缺失如实 `unverified`，真实外部阻塞说明待办，不以预算替代完成责任。

完成前核对新鲜证据：直接路径、失败路径、最窄回归和副作用复读；禁编译/测试时遵守并记 not-run/unverified，不能宣称通过。Critical/Important 必须解决，Minor 记录处置。临时记录放 `./selfworkflow/`，不自动 Git add。Superpowers 仅显式启用，不叠加第二套流程。

## 编译缓存保护

- 编译检查复用用户现有增量编译环境，允许必要的正常增量更新，不为验证便利使共享缓存失效。执行前核对最近正常构建的命令、日志或配置，保持项目、Target、平台/架构、Configuration、工具链/SDK、全局宏以及 PCH、Unity、Live Coding 编译支持一致；无法确认时先报告，不盲目试编。
- 优先同环境下最窄充分的增量构建。UE 的 `-Module` 只限制本次动作范围，不隔离共享 Intermediate/PCH；不得擅自添加 `-NoLiveCoding`：它会改变 `WITH_LIVE_CODING`，与 IDE 配置来回切换可使共享头/PCH 失效。保留 Live Coding 编译支持不等于执行 Live Coding 或 Hot Reload。
- 未获明确授权，不执行 Clean/Rebuild，不删除或清空 Intermediate、Binaries、PCH、DDC 等产物/缓存，不通过切换全局构建选项或改写构建规则“修复”编译检查。
- 共享头、构建规则或工具链等必要变化仍可能合法触发大范围重编；预计有此影响时，先说明原因、范围和代价并取得用户确认。不同编译环境的验证使用已确认不会覆盖原产物/缓存的隔离输出；不能保证隔离时不执行，保留 `not-run/unverified`，不得把跳过说成通过。
- 实际动作量显著超出改动影响范围时，不反复切换参数重试；检查 makefile 失效原因、全局定义与 PCH 变化，安全可行时暂停本 Agent 发起的构建并报告，不终止用户或其他任务的构建。
