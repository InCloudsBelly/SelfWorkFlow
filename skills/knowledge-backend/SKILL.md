---
name: knowledge-backend
description: Use for the optional, vendor-neutral knowledge.read, knowledge.propose, and knowledge.update lifecycle after a concrete knowledge backend has been explicitly selected.
---

# Generic knowledge backend

知识沉淀是 SelfWorkflow 的可选扩展，不是核心代码交付的前置条件。这个 Skill 只定义宿主 Agent 与后端之间的通用边界，不假设任何厂商、MCP 工具名、模型、登录方式或数据库结构。

## 选择与能力

1. 先确认本次是否需要知识读取、提议或写入；简单问答、机械修改和临时状态不自动进入知识库。
2. 用户明确选择一个后端适配器。适配器必须提供自己的契约、能力检查、失败语义和安装说明；不能从本 Skill 推断 API。
3. 调用前只读取当前阶段和命中的适配器 Skill；实际调用必须经过该 adapter 声明的宿主接线和调用边界，不能由 Conversation 直接猜测 MCP 工具或 Wiki 路径。能力缺失、契约漂移或运行时未验证时 fail closed，并报告 `unverified`，不静默切换后端。

## 通用生命周期

`knowledge.read` 只读现有知识；`knowledge.propose` 只生成不发布的整理方案；`knowledge.update` 必须有明确写入授权，并绑定当前版本/修订、来源标识和独立复审结果。用户直接要求更新/发布即是该范围的授权，沿用 SelfWorkflow 的确认规则；技术标识刷新不自动产生新授权事件。后端不可用时，代码任务继续交付并记录 `knowledge-sync-todo`。

整理后的材料应同时带有关键原始来源的标识、hash 和必要短摘录，使后端可以去重、筛选和发现冲突；不得保存模型私有推理或无必要的整份原文。发生冲突、漂移、阻塞性信息缺失或复审未通过时不得发布。

Wiki 候选规划、写作与质量 Review 按[知识模块](../../workflow/modules/knowledge.md)应用
[个人 Wiki 质量评价标准](references/wiki-quality.md)，统一解释深度、人类/图解理解和 Agent
实施目标及证据；读取、浏览不加载评分材料。指标不改变本 Skill 的厂商无关生命周期，
不额外授予写入、运行验证或扩大来源的权限。

## 后端替换

SelfOpenWiki 是当前提供的一个可选适配器，位于 `extensions/knowledge/selfopenwiki`，不会成为通用接口的硬依赖。宿主接线是 `selfworkflow.selfopenwiki:SelfOpenWikiAdapter`；个人更新使用 `personal_call` / `personal_status`，读取使用 `read`，浏览使用 `visualizer_spec`，不复用发布门禁。其他用户可以新增自己的 `extensions/knowledge/<backend>`、适配器 Skill 和能力测试，再绑定到同一生命周期；新后端不能修改本 Skill 的安全、确认、来源和失败关闭边界。
