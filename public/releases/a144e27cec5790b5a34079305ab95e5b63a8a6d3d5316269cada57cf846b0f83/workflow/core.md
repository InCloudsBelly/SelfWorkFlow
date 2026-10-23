# SelfWorkFlow：核心策略

本文件是核心策略的展开参考；普通任务已加载 `WORKFLOW.md` 和选定模式时不重复读取，仅策略核对或契约 Host 明确引用时加载。仅加载当前阶段需要的规则；普通轻量模式不使用 PlanGraph/RunLedger，显式契约管理模式才使用确定性解析和账本。

## 输出与代码任务增强

所有沟通和工程文档使用中文；代码、命令、错误、路径和协议字段按事实保留。代码任务加载 Ponytail；非代码任务不自动加载。Ponytail 的 mode 为 `full` 时仍受当前代码任务范围约束。项目级 `.codegraph/` 是全局 CodeMap：缺失时自动初始化，stale（过期）自动同步并在必要时全量重建；细则读取 `codegraph-read` 和 `codegraph-update`。Agent 写入及撤回后自动同步 Map；外部漂移在下次读取前检查。失败或文本回退须说明并标为 `unverified`，不冒充新鲜结构证据。

## 核心流程

`Discover → Capability Check → Classify → Design → Plan → Implement/Debug → Review → Verify → optional Knowledge → Complete`。

按复杂度 × 风险 × 副作用选择 Light、Full、Deep；边界不明向上升级。流程深度与能力 Skill 选择相互独立；加载能力 Skill 不会自动创建 Design、Plan、Review 或 Verify 流程。TEA 和完整 grilling 全部仅显式点名启用；Full/Deep、测试等级和项目默认不自动触发。行为修改保留 TDD、失败路径与最窄回归，完成只依据新鲜证据。

## 发散与收敛

设计阶段允许发散，实施阶段必须收敛。Plan 是实施边界：只修改允许修改的组件；发现问题不等于获得解决授权，计划外发现不得自动进入实现。相邻改进记录并延后，不实施；只有主目标、根因修复或验收条件需要时才处理。阻塞当前验收时停止编辑，修订 Plan、范围、测试和侵入性预算后重新确认；支持性改动若形成独立接口、状态、生命周期或构建变体，必须重新取得用户确认。任何阶段都优先选择更窄方案，并完成当前目标；必要时执行有界的收敛检查。

## 代码实施契约

只读分析和文档修订不改变行为代码契约；第一次编辑测试或生产代码前，形成紧凑实施契约并取得明确授权：目标、责任层、允许文件/组件、替代方案、影响半径、侵入预算、安全/性能/兼容性、回滚与测试接缝。普通设计/测试设计/计划合并自审；只有重大架构、安全、持久化、不可逆风险或显式请求才前置独立 Review。已有同范围授权复用，随后 TDD Red/Green 与实施；重大变化重新确认。

## 侵入性预算

按影响半径评估，不按行数。公共 API/ABI/Schema、公共枚举、持久化、全局编译宏/Build variant、共享热路径和测试来源的生产改动默认高侵入；超出预算或有更窄方案时禁止重方案。测试覆盖不能反向驱动生产架构；不必要消费者不得迁移。只处理当前目标，不自由发散。

## 进度反馈

需要工具、修改或副作用时首条进度更新同时包含 `SelfWorkflow active: <profile>；mode: <Light|Full|Deep>`、已完成主阶段/总主阶段、当前、剩余、预计和粗略区间；不输出单点精确百分比，不得按每个命令刷屏。暂无法可靠估算时明说，阶段变化、阻塞或完成时重新估算并保持单调，不伪造时间。

## 实施前整体 Review

普通中间文档不单开审查；高风险前置审查只接收完整必要包。落地后执行 post-landing Review：Full/Deep 由一个独立 Reviewer 综合 Standards/Spec；Light 窄结构化自审。所有模式取消双 Reviewer；修复复核复用同一上下文、只看影响项，不因预算中止未完成任务。Review 结果绑定 `design.gate`、`plan.gate`、`decision-record`，关键决策要求 `selectedId == recommendationId` 或记录用户选择、local component、easy rollback 和 critical decision。Review SubAgent 只读 hash-bound package/evidence，不调用 CodeGraph、provider、验证、写入、知识更新或下级 Agent，不导入作者历史；继承主 Agent 模型/推理配置，不使用专属覆盖。

## 按需能力

代码任务按需读 `workflow/modules/code.md`，CodeGraph 读/写后分别按 `codegraph-read.md` / `codegraph-update.md`；Review、留痕、知识到阶段才加载。Matt grilling 与所有 TEA 能力仅显式选择，已执行的同一 Skill/阶段/证据组合复用。简单环境事实由主 Agent 批量查明，不强制派发 SubAgent；辅助 Agent 不递归、不重做主流程。工具结果先过滤，保持必要前缀稳定，不为缓存保温发请求。

## 安全底线

不得虚构能力、Review 或测试结果或 evidence；禁止静默降级（不得静默降级）；保护凭据、用户已有修改和副作用授权。任务外异常隔离：发现无关异常时立即停止当前任务并向用户报告，不得在原任务对话中处理无关工作流、安装或环境问题；只有用户明确回复授权才另行处理，当前任务自身的根因除外。知识后端可选且与代码图解耦；可复用的技术知识在任务完成后主动提示一次是否沉淀，每个任务最多提示一次，用户拒绝后不再重复；简单问答、机械修改、临时状态不沉淀。临时记录放项目 `./selfworkflow/`，不自动 Git add。
