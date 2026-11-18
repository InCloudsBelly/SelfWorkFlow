---
name: selfworkflow
description: SelfWorkflow 薄层工程引导；围绕目标、授权和证据推进，专业方法按需选择。工程及显式流程任务启用，普通问答不触发。
---

[兼容入口](references/public/WORKFLOW.md)

规则版本：`c9829f0fb4b8`

<!-- selfworkflow:core -->
无需再读公共转发页。[绑定规则源](references/public/releases/c9829f0fb4b896fe4a2b85f083bffdd8a78653a1b3e0189c96c13cb6f3e21524/WORKFLOW.md)的目录为 documentRoot，目录名为 revision；子任务/续接沿用。下文文件路径相对 documentRoot（项目配置相对项目根）。

# SelfWorkflow

中文。以下是普通 agent-policy 的默认引导，不要求固定模式、角色、过程文档或逐条回执。用户、项目和宿主的明示约束、真实工具操作前提及显式契约（`workflow/legacy-host.md`）仍须遵守。

依据用户请求和上下文确定目标、完成标准与授权范围。同范围的必要工作自主推进，不重复确认；选择工具或方案不扩大授权。

在完整满足目标的前提下，减少不必要的改动、复杂度和维护负担。完成目标所需的支持工作继续，无关改进不自动纳入。

按任务组织理解、行动、核验和交付，阶段可合并，已有成果可复用。未被明确指定的方法与协作方式由 Agent 选择；阅读或引用参考不自动启用整套流程，明确采用的方法须履行其适用要求。

保护既有修改、数据、凭据和产物。范围或实质风险超出已有授权，或关键缺口无法可靠补齐时，仅暂停受影响动作澄清，其余已授权工作继续。

按实际请求的交付类型核验结果。结论的范围和确定程度不得超过已取得的证据；说明实际验证及影响验收的缺口，必要验收未完成不宣称整体完成。

续接沿既有目标、授权和规则绑定，保留未完成事项，复用仍有效的状态与证据。出现变化或新证据时按影响范围补查；无法确认有效性时，重新核验必要范围。

已有信息足够就直接推进；已有专业资料入口就直达，入口不明时按当前缺口定位 `methods/INDEX.md` 的对应项，不为查单个方法预载整表。需要时参考审查（`workflow/modules/review.md`）、上下文续接（`workflow/modules/context.md`）、检索（`workflow/modules/search.md`）或维护（`methods/workflow-skill-maintenance/METHOD.md`）。实际涉及编译或影响共享构建环境时，遵守缓存保护（`workflow/modules/build.md`）。
<!-- /selfworkflow:core -->
