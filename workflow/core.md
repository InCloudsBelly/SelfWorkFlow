# SelfWorkFlow：核心策略

本文件是核心策略的展开参考；普通任务已加载 `WORKFLOW.md` 和选定模式时不重复读取，仅策略核对或契约 Host 明确引用时加载。仅加载当前阶段需要的规则；普通轻量模式不使用 PlanGraph/RunLedger，显式契约管理模式才使用确定性解析和账本。

## 输出与代码任务增强

所有沟通和工程文档使用中文；代码、命令、错误、路径和协议字段按事实保留。代码任务按需加载 Ponytail；非代码任务不自动加载。Ponytail 的 mode 为 `full` 时仍受当前代码任务范围约束。项目级 `.codegraph/` 是唯一 CodeMap：缺失时初始化，已有索引增量同步，不自动全量重建；细则读取 `codegraph-read` 和 `codegraph-update`。失败保留原库并标记图证据 `unverified`；普通任务可继续直接源码核对和验证，不冒充图新鲜或查询成功。

## 核心流程

`Discover → Capability Check → Classify → Design → Plan → Implement/Debug → Review → Verify → optional Knowledge → Complete`。

按复杂度 × 风险 × 副作用选择 Light、Full、Deep；先查明环境事实，只有实际复杂度或风险需要时升级。流程深度与能力 Skill 选择相互独立；加载能力 Skill 不会自动创建 Design、Plan、Review 或 Verify 流程。TEA 和完整 grilling 全部仅显式点名启用；Full/Deep、测试等级和项目默认不自动触发。行为修改保留 TDD、失败路径与最窄回归，完成只依据新鲜证据。

## 发散与收敛

设计阶段允许发散，实施阶段必须收敛。Plan 是实施边界，服务于用户批准的目标；新增必要私有实现、测试或补齐漏列文件时同步计划，不自动产生新确认轮次。相邻改进记录延后；真正新增目标、超出授权或实质扩大公共接口、持久格式、共享状态、构建变体及风险时，只暂停受影响编辑，展示具体增量后确认。持续推进与确认统一遵循 `WORKFLOW.md`。

## 代码实施契约

只读分析和文档修订不改变行为代码契约；第一次编辑测试或生产代码前，形成紧凑实施契约：目标、责任层、允许文件/组件、替代方案、影响半径、侵入预算、安全/性能/兼容性、回滚与测试接缝。用户的实施请求及已有同范围授权复用，不等待对自拟计划的重复批准。普通设计/测试设计/计划合并自审；重大架构、安全、持久化、不可逆风险或显式请求才前置独立 Review。随后按需 TDD Red/Green；真实越界才重新确认。

## 侵入性预算

按影响半径评估，不按行数。公共 API/ABI/Schema、公共枚举、持久化、全局编译宏/Build variant、共享热路径和测试来源的生产改动默认高侵入；超出预算或有更窄方案时禁止重方案。测试覆盖不能反向驱动生产架构；不必要消费者不得迁移。只处理当前目标，不自由发散。

## 进度反馈

需要工具、修改或副作用时首条进度更新同时包含 `SelfWorkflow active: <profile>；mode: <Light|Full|Deep>`、已完成主阶段/总主阶段、当前、剩余、预计和粗略区间；不输出单点精确百分比，不得按每个命令刷屏。暂无法可靠估算时明说，阶段变化、阻塞或完成时重新估算并保持单调，不伪造时间。

## 实施前整体 Review

普通中间文档不单开审查；高风险前置审查只接收完整必要包。Full/Deep 交付前一个独立 Reviewer 综合 Standards/Spec；Light 窄自审。所有模式取消双 Reviewer，修复只复核影响项；能力缺失及交付边界按 `workflow/modules/review.md` 处理。仅显式契约的 Review 结果绑定 `design.gate`、`plan.gate`、`decision-record`，关键决策要求 `selectedId == recommendationId` 或记录用户选择、local component、easy rollback 和 critical decision；普通任务不创建这些回执。Review SubAgent 只读绑定材料，不调用 CodeGraph、provider、验证、写入、知识更新或下级 Agent，不导入作者历史；继承主 Agent 模型/推理配置，不使用专属覆盖。

## 按需能力

代码任务按需读 `workflow/modules/code.md`，CodeGraph 读/写后分别按 `codegraph-read.md` / `codegraph-update.md`；Review、留痕、知识到阶段才加载。Matt grilling 与所有 TEA 能力仅显式选择，已执行的同一 Skill/阶段/证据组合复用。简单环境事实由主 Agent 批量查明，不强制派发 SubAgent；辅助 Agent 不递归、不重做主流程。工具结果先过滤，保持必要前缀稳定，不为缓存保温发请求。

## 安全底线

不得虚构能力、Review 或测试结果或 evidence；禁止静默降级（不得静默降级）；保护凭据、用户已有修改和副作用授权。任务外异常隔离：无关异常记录延后，继续当前目标；必要依赖失败仅暂停受影响动作。任务外修复另取授权，当前目标的根因与必要验收工作沿用既有授权。知识后端可选且与代码图解耦；可复用结论每个任务最多提示一次是否沉淀，拒绝后不重复；简单问答、机械修改、临时状态不沉淀。临时记录放项目 `./selfworkflow/`，不自动 Git add。
