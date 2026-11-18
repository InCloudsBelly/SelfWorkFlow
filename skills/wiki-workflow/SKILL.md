---
name: wiki-workflow
description: 指导 Agent 生成、维护、审查有来源、可理解、可实施的 Wiki；默认原理／实现详解，按需生成使用／排障指南及适配 DocHub、SelfOpenWiki。普通问答、仅诊断当前故障或未要求成文的临时笔记不触发。
---

# Wiki 工作流

围绕读者的问题和可核实的来源写作，默认交付完整本地候选。此 Skill 可独立使用，沿用宿主已有授权和工程约束。安装或接入时参考[使用与依赖](references/start.md)。

新写或实质修订 Wiki 时，按[生成流程](references/generation.md)确定问题和证据，依[正文契约](references/article-contract.md)讲清主线，再用[内容验收](references/wiki-quality.md)检验实际稿件。审查已有稿件可直接从内容验收开始。浏览按需取文，局部修订核改动及其影响。

按约定的读者、范围和用途写作。默认交付**原理与实现详解**，讲清机制、必要推导、实现契约和边界。明确选用或 DocHub 默认采用**使用与排障指南**时，按[指南规则](references/operations-guide.md)生成或增量维护。既有稿件保留已选用途、有效正文和旧入口。明确需要两套时分别完整交付并互链。

解释数学关系时参考[公式约定](references/wiki-math.md)，配图时参考[图解规范](references/diagrams.md)。

来源服务与发布目标分别确定。只读请求交付发现，候选请求止于候选。需要适配或发布时按[交付规则](references/backends.md)核对实际目标、稿件与授权。

## 可选扩展

| 用户目标 | 入口 |
| --- | --- |
| 从已连接的 SelfOpenWiki 读取，或发布到该后端 | [SelfOpenWiki 适配](extensions/selfopenwiki/ADAPTER.md)：默认发布原理／实现全文，指南仅按明确要求纳入 |
| 交付到 DocHub，包括“一键适配 DocHub” | [DocHub 适配](extensions/dochub/ADAPTER.md)：默认使用／排障指南，明确指定原理全文或已有稿件用途时沿用 |

只加载所选扩展。适配保留源稿、用途和内容深度，正式发布遵守目标协议。
