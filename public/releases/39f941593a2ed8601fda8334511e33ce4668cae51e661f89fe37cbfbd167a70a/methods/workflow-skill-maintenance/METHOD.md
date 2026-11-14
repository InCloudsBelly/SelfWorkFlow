---
name: workflow-skill-maintenance
description: 仅新增、改造或集成 Skill/工作流时使用；纯审查及使用现有能力不触发。
---

# 工作流与 Skill 维护

沿既有范围/授权/阶段/Review，只改命中职责、路由与引用。日常维护只读本方法及受影响文件。
新增实质 Skill 或确需创建/评测方法才读绑定根 `references/anthropic-skills/skill-creator/`：文档模式 `METHOD.md`，runtime 模式 `SKILL.md`；评测角色/schemas 再按需读。缺失/漂移记 unverified，不找旧安装。源码维护可从获准 repositoryRoot 的 `dependencies/locks/anthropic-skills.lock.yaml` 与固定 submodule `skills/skill-creator` 取同版材料，不改/更新上游。

1. 复盘先归纳可重复的失效机制，区分规则缺口、执行偏差与能力限制；只在最窄 owner 合并/修订触发、完成、失效或停止条件。已有覆盖先修导航/歧义/证据，不堆同义禁令，不把个案细节或固定轮数固化为通则。不重做 Discover/Grill、Review 调度或确认；定义意图、输入输出、能力与排除，短 description 管触发，细则按需读，保留许可/固定来源。
2. 用少量中文正例、邻近反例和同名歧义核对触发/约束，区分创建与使用；复盘增加结论来源以外的对照案例，相关任务链不冒充独立样本，证据不足的限制不升级为全局通则。不自动追加模型对评/Agent；宿主支持时保留窄隐式触发，仅用户要求才关闭 implicit invocation。
3. 沿既有设计/TDD/Review/验证。文本变更必做紧凑性审查：记录入口与命中加载链改前后字符数，核对触发/排除、按需路由、有效证据复用；消除冗余/无关/重复/循环加载，必要增量说明用途。不通过先修正，并入本轮自审/同一 Reviewer，不增角色或全包扫描。静态结构检查、历史适用性与部署实测分开；字符/调用数只提示开销，不冒称 token、耗时或误触发收益。

CLI/API、Task、评测命令/模型须真实可用，只核必要能力；实测、安装、发布、消息各核授权，不重走接入。交付来源、职责/复用、触发样例、改动及证据/缺口，不额外产模板包或把维护规则扩散到日常任务。
触发：优化 Skill description、接入方法；不触发：用现有能力写报告/画图/修复 C++、只读审查工作流。
