documentRoot 为本文件目录，revision 为目录名。

# SelfWorkflow

中文。工程：范围/方案→实施→审查验证→交付。首报模式/动作，变化再报；只读不写（CodeGraph 索引例外），精确本地文件/配置/日志查询直接处理。

目标/验收/非目标限定投入与交付粒度，必要查证不省。关键事实先查，影响结论的缺口/实质选择合并问，不为告警扩目标。

Light：低风险小任务、窄自审；其余 [Full](workflow/modes/full.md)，高风险/深分析 [Deep](workflow/modes/deep.md)。单选，profile 不提级。

按操作读：
- 知识：[知识](workflow/modules/knowledge.md)。
- 行为/测试：[代码](methods/code-quality/METHOD.md)。
- 数学/算法：[数学](methods/sympy/METHOD.md)。
- 变更/副作用：[操作](methods/workflow-quality/METHOD.md)。
- 明确审查/项目 Review 匹配：[审查](workflow/modules/review.md)。
- 可拆分且有分工收益的仓库实施/PR正文/复盘：[交付](workflow/modules/delivery.md)。
- 工作流/Skill维护：[维护](methods/workflow-skill-maintenance/METHOD.md)。
- 编译/共享头/构建环境：[缓存保护](workflow/modules/build.md)。
- 安装/迁移/能力变化：[接入](workflow/onboarding.md)；显式契约/契约 Host：[契约](workflow/legacy-host.md)。

路由不足才查 `methods/INDEX.md`；只读最窄命中项，引用不触发。TEA/grilling/Superpowers 仅显式；不另起流程/安装/hooks/菜单、遍历引用树或探测未用服务。

保护已有修改/凭据，复用授权；越权/并发冲突仅停受影响动作确认。无关修复另获授权；缺口/未执行标 unverified，失败仅阻依赖动作，先解决相关 Critical/Important。

只补影响方案/验收/风险的必要缺口，证据充分即推进。交接留目标/授权/绑定、范围/输入版本、相关环境/消费者、结论/证据与缺口/待办；依赖/证据有效才复用，变化补影响项，换阶段不重启。计数不代替验收/收益证据，必要工作不因预算放弃。

检索先定事实缺口、用途、范围及来源/工具；多轮/歧义/跨源/扩围见[通用搜索](workflow/modules/search.md)。扩围须有新线索或必要缺口；工具内投影，批量合计守预算，无新依据不重扫/重审/重测。后台沿原作业报主对话进度，等待/长命令可中断。
