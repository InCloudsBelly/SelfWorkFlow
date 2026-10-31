---
name: selfworkflow
description: 按 SelfWorkflow 执行工程任务；选用或设为默认时启用，闲聊和概念讨论不触发。
---

[兼容入口](references/public/WORKFLOW.md)

规则版本：`106a8a850dd8`

<!-- selfworkflow:core -->
无需再读公共转发页。[绑定规则源](references/public/releases/106a8a850dd867c911d5c3ff98a1a6a3c2187d06de4b1dd24478ab9e5398dffb/WORKFLOW.md)的目录为 documentRoot，目录名为 revision；子任务/续接沿用。下文文件路径相对 documentRoot（项目配置相对项目根）。

# SelfWorkflow

中文。工程：范围/方案→实施→审查验证→交付；只读不写（CodeGraph 索引例外）。首报模式/动作，变化时更新。

Light：低风险小任务，分析/最小修改、窄自审；其余读 Full（`workflow/modes/full.md`），高风险/深分析读 Deep（`workflow/modes/deep.md`）。单选，profile 不提级。

按操作读：
- 知识读写/浏览：知识（`workflow/modules/knowledge.md`）。
- 源码行为/测试设计与证据：代码（`methods/code-quality/METHOD.md`）。
- 数学推理/建模/算法/公式：数学（`methods/sympy/METHOD.md`）。
- 文件变更/副作用：操作（`methods/workflow-quality/METHOD.md`）。
- 明确审查或项目 `.selfworkflow/review.yaml` 匹配：审查（`workflow/modules/review.md`）。
- 改工作流/Skill：维护（`methods/workflow-skill-maintenance/METHOD.md`）。
- 编译/共享头/构建规则/工具链变更：先读缓存保护（`workflow/modules/build.md`）。
- 安装/迁移/能力变化：接入（`workflow/onboarding.md`）；显式契约或 Host 已承接：契约（`workflow/legacy-host.md`）。

其他能力查 `methods/INDEX.md`；同责用最窄，引用不触发。TEA/grilling/Superpowers 仅显式点名；不另起流程/安装/hooks/菜单，不遍历引用树/探测未用服务。模块失败仅阻依赖动作。

保护已有修改/凭据并沿授权；仅关键选择/越权/并发冲突才问。无关故障另获授权；必需缺口/未执行标 unverified，不编造/跳过；先解决相关 Critical/Important。

版本/输入/完整正文未变则复用补缺；续接/换阶段不重启。查询定向投影，无新证据不重复重试/扫描/审查/测试。并行合计守外层预算；截断补缺段。长命令可中断。交接仅目标/授权、绑定、有效证据及待办；未完成不因预算停工。
<!-- /selfworkflow:core -->
