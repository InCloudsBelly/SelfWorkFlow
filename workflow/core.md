# SelfWorkFlow：核心策略

仅加载当前阶段需要的规则；普通轻量模式不使用 PlanGraph/RunLedger，显式契约管理模式才使用确定性解析和账本。

## 输出与代码任务增强

所有沟通和工程文档使用中文。代码任务加载 Ponytail；非代码任务不自动加载。代码阅读优先使用新鲜官方 Graft MCP，按需读取 `graft-read`；缺失或过期时普通任务回退 `rg`，需要新鲜图证据则 `unverified`。

## 核心流程

`Discover → Capability Check → Classify → Design → Plan → Implement/Debug → Review → Verify → optional Knowledge → Complete`。

按复杂度 × 风险 × 副作用选择 Light、Full、Deep；边界不明向上升级。Full 和 Deep 必须加载 TEA；行为修改使用 TDD，落地前后都要 Review，完成只依据新鲜证据。

## 发散与收敛

设计阶段可发散；Plan 确认后只实现批准目标。计划外问题记录并延后；阻塞验收时停止编辑，修订范围、测试和侵入预算后重新确认。支持性改动若形成新接口、状态、生命周期、构建变体或非必要调用者，先做一次有界收敛检查，优先回到更窄既有路径。

## 代码实施契约

第一次编辑测试或生产代码前，必须明确目标、责任层、文件/符号、替代方案、影响半径、侵入预算、安全、性能、可维护性、兼容性、回滚和测试接缝。固定门禁：`Review → 用户明确确认 → TDD Red/Green → 实施`。确认失效即回到设计。

## 侵入性预算

按影响半径评估，不按行数。公共 API/ABI/Schema、持久化、全局宏/Build variant、共享热路径和测试来源的生产改动默认高侵入；有更窄方案时禁止重方案。测试覆盖不能反向驱动生产架构；不必要消费者不得迁移。只处理当前目标，不自由发散。

## 进度反馈

需要工具、修改或副作用时首条报告 `SelfWorkflow active: <profile>；mode: <Light|Full|Deep>` 及进度格式；阶段变化、阻塞、完成或预计变化时更新。预计不可靠必须报告并重估，不伪造时间。

## 实施前整体 Review

正式设计、测试设计和实施计划在实施前由独立 SubAgent Review；Full/Deep 需完整文档包 Review。落地后 Full/Deep 使用独立 Standards/Spec Review 和 TEA Review；Light 做窄结构化自审。Review SubAgent 只读 hash-bound package/evidence，不调用 Graft、provider、验证、写入、知识更新或下级 Agent。Review 模型只作用于该 SubAgent。

## 按需能力

按任务命中模块：代码读取/写入加载 `workflow/modules/code.md`；Graft 查询、专题 Deep、写后更新分别加载 `graft-read.md`、`graft-deep.md`、`graft-update.md`；Review、留痕和知识加载对应模块。Matt `grilling` 只在 Full/Deep 的 Design/Plan 自动一次；显式 `grill-me` 才额外加载。Full/Deep 必须加载 TEA，但 `tea-atdd`、`tea-trace`、`tea-nfr` 仅显式选择。

## 安全底线

禁止虚构能力、Review、测试或证据；禁止静默降级；保护凭据、用户已有修改和副作用授权。任务外异常立即停止并报告，不在当前任务里处理无关工作流、安装或环境问题。知识后端可选且与代码图解耦；临时记录放项目 `./selfworkflow/`，不自动 Git add。
