---
name: selfworkflow
description: SelfWorkflow 工程流程；选用或默认时启用，闲聊和概念讨论不触发。
---

[兼容入口](references/public/WORKFLOW.md)

规则版本：`0ab53d141853`

<!-- selfworkflow:core -->
无需再读公共转发页。[绑定规则源](references/public/releases/0ab53d14185304c525ce7137dcf5994f89613daf6537f916f9b5f0bb9d99d5c2/WORKFLOW.md)的目录为 documentRoot，目录名为 revision；子任务/续接沿用。下文文件路径相对 documentRoot（项目配置相对项目根）。

# SelfWorkflow

中文。工程：范围/方案→实施→审查验证→交付。首报模式/动作，变化再报；只读不写（CodeGraph 索引例外），精确本地文件/配置/日志查询直接处理。

按目标/验收/非目标定投入与交付；关键事实先查，合并澄清影响结论的缺口/实质选择，不为告警扩目标。

低风险小任务用 Light 窄自审；其余 Full（`workflow/modes/full.md`），高风险/深分析 Deep（`workflow/modes/deep.md`）。单选，profile 不提级。

按操作读：
- 知识（`workflow/modules/knowledge.md`）。
- 行为/测试（`methods/code-quality/METHOD.md`）。
- 数学/算法（`methods/sympy/METHOD.md`）。
- 变更/副作用（`methods/workflow-quality/METHOD.md`）。
- 审查（`workflow/modules/review.md`）：明确审查或项目 Review 匹配。
- 交付（`workflow/modules/delivery.md`）：可拆分且有分工收益的仓库实施/PR正文/复盘。
- 维护（`methods/workflow-skill-maintenance/METHOD.md`）：工作流/Skill 变更。
- 缓存保护（`workflow/modules/build.md`）：编译/共享头/新模块/构建环境。
- 接入（`workflow/onboarding.md`）：安装/迁移/能力变化；契约（`workflow/legacy-host.md`）：显式契约/契约 Host。

路由不足才查 `methods/INDEX.md`；只读最窄命中项，引用不触发。TEA/grilling/Superpowers 仅显式；不另起流程/安装/hooks/菜单、遍历引用树或探测未用服务。

保护既有修改/凭据，沿用授权；越权/并发冲突只停受影响动作确认，无关修复另获授权。缺口/未执行标 unverified，失败只阻依赖项，先解决相关 Critical/Important。

证据充分即推进，只补影响方案/验收/风险的缺口。既有交接状态保留目标/授权、revision/documentRoot、范围/输入版本、环境/消费者、结论/证据/缺口/待办及准确路径/标识；合并新增、替换失效项。续接核绑定/输入/未关闭项/下一步，直达原路径，不重选规则/重启阶段。计数不替代验收/收益证据，必要工作不因预算放弃。

检索先定缺口/用途/范围/来源；多轮/歧义/跨源/扩围或输出量不明读通用搜索（`workflow/modules/search.md`）。工具内投影，批量合计限量，无新依据不重扫/重审/重测。后台进度沿原作业回主对话，等待/长命令可中断。
<!-- /selfworkflow:core -->
