# SelfWorkFlow：核心策略

仅加载当前阶段需要的规则；普通轻量模式不使用 PlanGraph/RunLedger，显式契约管理模式才使用确定性解析和账本。

## 输出与代码任务增强

所有沟通和工程文档使用中文；代码、命令、错误、路径和协议字段按事实保留。代码任务加载 Ponytail（mode 为 `full` 或 `deep` 时仍只按需加载）；非代码任务不自动加载。代码阅读优先使用新鲜官方 Graft 查询，按需读取 `graft-read`；缺失或过期时普通任务回退 `rg`，需要新鲜图证据则 `unverified`。

## 核心流程

`Discover → Capability Check → Classify → Design → Plan → Implement/Debug → Review → Verify → optional Knowledge → Complete`。

按复杂度 × 风险 × 副作用选择 Light、Full、Deep；边界不明向上升级。流程深度与能力 Skill 选择相互独立；加载能力 Skill 不会自动创建 Design、Plan、Review 或 Verify 流程。Full 和 Deep 必须加载 TEA；行为修改使用 TDD，落地前后都要 Review，完成只依据新鲜证据。

## 发散与收敛

设计阶段允许发散，实施阶段必须收敛。Plan 是实施边界：只修改允许修改的组件；发现问题不等于获得解决授权，计划外发现不得自动进入实现。相邻改进记录并延后，不实施；只有主目标、根因修复或验收条件需要时才处理。阻塞当前验收时停止编辑，修订 Plan、范围、测试和侵入性预算后重新确认；支持性改动若形成独立接口、状态、生命周期或构建变体，必须重新取得用户确认。任何阶段都优先选择更窄方案，并完成当前目标；必要时执行有界的收敛检查。

## 代码实施契约

只读分析和文档修订不改变行为代码契约；第一次编辑测试或生产代码前，必须形成明确实施确认，写明目标、责任层、允许修改的组件、文件/符号、替代方案、影响半径、批准的侵入性预算、安全、性能、可维护性、兼容性、回滚和关键测试接缝。设计/规格 + TEA/测试设计 + 实施计划先经 Review，再执行 `Review → 用户确认 → TDD Red/Green → 实施`；重大变化需用户明确确认，确认失效即回到设计。实施计划、侵入性预算和回滚必须绑定同一契约；Light 采用紧凑门禁。

## 侵入性预算

按影响半径评估，不按行数。公共 API/ABI/Schema、公共枚举、持久化、全局编译宏/Build variant、共享热路径和测试来源的生产改动默认高侵入；超出预算或有更窄方案时禁止重方案。测试覆盖不能反向驱动生产架构；不必要消费者不得迁移。只处理当前目标，不自由发散。

## 进度反馈

需要工具、修改或副作用时首条进度更新同时包含 `SelfWorkflow active: <profile>；mode: <Light|Full|Deep>`、已完成主阶段/总主阶段、当前、剩余、预计和粗略区间；不输出单点精确百分比，不得按每个命令刷屏。暂无法可靠估算时明说，阶段变化、阻塞或完成时重新估算并保持单调，不伪造时间。

## 实施前整体 Review

正式设计、测试设计和实施计划在实施前由独立 SubAgent Review；至少两份正式文档时必须提交完整文档包和最终文档包 hash，不能由同一 Agent 冒充独立 Review，发现关键问题先暂停实施。Full/Deep 需完整文档包 Review；落地后执行 post-landing Review，Full/Deep 使用独立 Standards/Spec Review 和 TEA Review，Light 做窄结构化自审。Review 结果绑定 `design.gate`、`plan.gate`、`decision-record`，关键决策要求 `selectedId == recommendationId` 或记录用户选择、local component、easy rollback 和 critical decision。Review SubAgent 只读 hash-bound package/evidence，不调用 Graft、provider、验证、写入、知识更新或下级 Agent。Review 模型只作用于该 SubAgent。

## 按需能力

按任务命中模块：代码读取/写入加载 `workflow/modules/code.md`；Graft 查询、专题 Deep、写后更新分别加载 `graft-read.md`、`graft-deep.md`、`graft-update.md`；Review、留痕和知识加载对应模块。Matt `grilling` 只在 Full/Deep 的 Design/Plan 自动一次；显式 `grill-me` 才额外加载。Full/Deep 必须加载 TEA，但 `tea-atdd`、`tea-trace`、`tea-nfr` 仅显式选择。

## 安全底线

不得虚构能力、Review 或测试结果或 evidence；禁止静默降级（不得静默降级）；保护凭据、用户已有修改和副作用授权。任务外异常隔离：发现无关异常时立即停止当前任务并向用户报告，不得在原任务对话中处理无关工作流、安装或环境问题；只有用户明确回复授权才另行处理，当前任务自身的根因除外。知识后端可选且与代码图解耦；可复用的技术知识在任务完成后主动提示一次是否沉淀，每个任务最多提示一次，用户拒绝后不再重复；简单问答、机械修改、临时状态不沉淀。临时记录放项目 `./selfworkflow/`，不自动 Git add。
