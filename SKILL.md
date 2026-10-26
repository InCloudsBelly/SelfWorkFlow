---
name: selfworkflow
description: 按 SelfWorkflow 执行工程任务；选用或设为默认时启用，闲聊和概念讨论不触发。
---

[兼容入口](skills/selfworkflow/references/public/WORKFLOW.md)供旧宿主；执行下方核心。

规则版本：`720a019af127`

<!-- selfworkflow:core -->
无需再读公共转发页。[绑定规则源](skills/selfworkflow/references/public/releases/720a019af127e2d8727ee997988f13484e1bc7be3d646c4d3efb15147f679729/WORKFLOW.md)的目录为 documentRoot，目录名为 revision；子任务/续接沿用。下文文件路径相对 documentRoot（项目配置相对项目根）。

# SelfWorkflow

中文。工程任务：范围/方案→实施→审查验证→交付；只读不写（CodeGraph 索引例外）。首报模式/动作，变化时更新。

Light：低风险小任务，分析/最小修改、窄自审；其余读 Full（`workflow/modes/full.md`），高风险/深分析读 Deep（`workflow/modes/deep.md`）。只选一种，profile 不提级。

按实际操作读取：
- 知识读写/浏览：知识（`workflow/modules/knowledge.md`）。
- 行为源码分析/变更、测试设计/执行证据：代码（`methods/code-quality/METHOD.md`）。
- 文件变更/外部副作用：操作（`methods/workflow-quality/METHOD.md`）。
- 明确审查或项目 `.selfworkflow/review.yaml` 匹配：审查（`workflow/modules/review.md`）。
- 改工作流/Skill：维护（`methods/workflow-skill-maintenance/METHOD.md`）。
- 编译/共享头/构建规则/工具链变更：动作前读缓存保护（`workflow/modules/build.md`）。
- 安装/迁移/能力变化：接入（`workflow/onboarding.md`）；显式契约或 Host 已承接：契约（`workflow/legacy-host.md`）。

其他能力定向检索 `methods/INDEX.md`；同职责用最窄，引用不触发。TEA/grilling/Superpowers 仅显式点名；不另起流程/安装/hooks/菜单，不遍历引用树或探测未用服务。模块失败仅阻塞依赖动作。

保护已有修改/凭据，沿授权；关键选择、越权、并发冲突才问。无关故障另获授权；必需缺口/未执行如实标 unverified，不编造或跳过，相关 Critical/Important 先解决。

版本/输入/完整正文未变则复用，只补缺口；续接/换阶段不重启。定向查询并投影，无新证据不重复重试/扫描/审查/测试。并行合计受外层预算约束；截断只补缺段。长命令可中断等待。交接仅留目标/授权、绑定、有效证据与待办。未完成不因预算停工。
<!-- /selfworkflow:core -->
