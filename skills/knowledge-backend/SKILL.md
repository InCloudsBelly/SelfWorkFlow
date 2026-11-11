---
name: knowledge-backend
description: SelfWorkflow 的 knowledge 接入：Wiki 生成与审查加载 Wiki 工作流，选定后端后按需读写；普通代码、临时状态或泛化知识词不触发。
---

# Knowledge 接入

宿主调度与授权沿本任务已绑定的 SelfWorkflow 根下的 `workflow/modules/knowledge.md`：文档模式用 documentRoot，runtime 模式用宿主声明且已核验的 snapshot 根。不要按原生 Skill 安装目录反推该路径；缺绑定或主模块不可读时报告缺口，不换旧版本。同版已读不重入。

生成、维护或审查 Wiki 时加载独立的 [Wiki 工作流](../wiki-workflow/SKILL.md)；由它拥有生成、质量、审查及可选发布规则，本入口不复制标准。来源和发布目标独立，未选服务时交付本地完整候选，knowledge profile 不自动选择后端。

仅选定后端后才加载当前操作的 adapter。read 只读、propose 不发布；update 绑定有效授权、版本/来源、独立复审和真实后端协议。直接更新要求复用同范围授权；冲突、漂移或必要 Review 未通过时保留候选。缺能力只阻对应动作，代码交付继续并列 knowledge-sync-todo；不静默换后端，不猜 API、OAuth 或路径。

SelfOpenWiki 是可选来源/发布 adapter；其 SelfWorkflow 接线沿知识模块，personal_call/personal_status、read 和 visualizer_spec 分别核验能力。DocHub 等目标沿 Wiki 工作流的相应扩展；不要求具备 SelfOpenWiki。来源身份、版本与证据按实际操作保留，不存凭据、私人推理或整份敏感原文。
