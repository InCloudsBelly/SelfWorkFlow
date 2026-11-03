# SelfWorkflow

中文。工程：范围/方案→实施→审查验证→交付；只读不写（CodeGraph 索引例外）。首报模式/动作，变化再更新。精确本地文件/配置/日志查询直接处理。

Light：低风险小任务，分析/最小修改、窄自审；其余读 [Full](workflow/modes/full.md)，高风险/深分析读 [Deep](workflow/modes/deep.md)。单选，profile 不提级。

按操作读：
- 知识读写/浏览：[知识](workflow/modules/knowledge.md)。
- 代码行为/测试：[代码](skills/code-quality/SKILL.md)。
- 数学推理/建模/算法/公式：[数学](skills/sympy/SKILL.md)。
- 文件变更/副作用：[操作](skills/workflow-quality/SKILL.md)。
- 明确审查或项目 `.selfworkflow/review.yaml` 匹配：[审查](workflow/modules/review.md)。
- 改工作流/Skill：[维护](skills/workflow-skill-maintenance/SKILL.md)。
- 编译/共享头/构建规则/工具链变更：先读[缓存保护](workflow/modules/build.md)。
- 安装/迁移/能力变化：[接入](workflow/onboarding.md)；显式契约或 Host 已承接：[契约](workflow/legacy-host.md)。

路由不足才查 `methods/INDEX.md`；同责用最窄，引用不触发。TEA/grilling/Superpowers 仅显式点名；不另起流程/安装/hooks/菜单，不遍历引用树/探测未用服务。

保护已有修改/凭据并沿授权；仅关键选择/越权/并发冲突才问。无关故障另获授权；模块失败仅阻依赖动作，必需缺口/未执行标 unverified；先解决相关 Critical/Important。

同版复用，换阶段/续接补缺。检索限定源码/绑定版，避开历史/生成副本/输出快照，查副本点名。工具内投影字段/行段，并行合计守外层预算，截断补缺段；无新证据不重复扫描/重试/审查/测试。交接仅目标/授权、绑定、证据引用及待办；长命令可中断，未完成不因预算停工。
