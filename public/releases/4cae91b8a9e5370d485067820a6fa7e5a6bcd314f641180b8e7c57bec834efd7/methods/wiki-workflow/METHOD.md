---
name: wiki-workflow
description: 指导 Agent 生成、维护、审查有来源、可理解、可实施的 Wiki；默认原理／实现详解，按需生成使用／排障指南及适配 DocHub、SelfOpenWiki。普通问答、仅诊断当前故障或未要求成文的临时笔记不触发。
---

# Wiki 工作流

这是一套指导 Agent 的生成、质量、审查和可选发布规范。以读者的问题和真实来源生成 Wiki，默认交付本地完整候选。完整目录可独立使用，不要求某个 Wiki 服务、MCP、SelfWorkflow、个人目录或已有文章 ID；宿主已有的授权与工程流程继续适用。

首次接入读 [使用与依赖](references/start.md)。生成或实质修订读 [生成流程](references/generation.md)、[内容验收](references/wiki-quality.md)和[正文契约](references/article-contract.md)。已选指南的操作反馈或排障结论按[问题增量维护](references/operations-guide.md)续接。已有稿件沿其版本与有效证据继续，不从零重写。纯浏览、局部格式修复只检查影响项。

先确定来源、读者、内容用途、范围、交付目标及操作是只读、候选还是正式更新。默认生成**原理与实现详解**，按完整质量标准讲清机制、必要推导、实现、契约与细节边界。**使用与排障指南**仅在明确选用或 DocHub 适配时按[指南规则](references/operations-guide.md)生成；明确需要两套时分别完整交付并互链。既有稿件沿用已绑定用途，局部维护核关联影响，不自动增建另一套。

数学、参数或几何解释读 [公式约定](references/wiki-math.md)；实际配图读 [图解规范](references/diagrams.md)。复杂覆盖、跨篇依赖、边界争议及用户明确要求的数值评分，按内容验收中的对应引用渐进加载。生成量、图数和工具成功不证明质量。

已有信息和有效正文、旧入口及版本边界继续保留；修订沿用已选用途与正文深度。内容、公式语义、两端呈现和发布回执分验，必要缺口未关时保留标明状态的候选。交付沿[可选发布](references/backends.md)，来源服务与发布目标分别核验。

## 可选扩展

| 用户目标 | 入口 |
| --- | --- |
| 从已连接的 SelfOpenWiki 读取，或发布到该后端 | [SelfOpenWiki 适配](extensions/selfopenwiki/ADAPTER.md)：默认发布原理／实现全文，指南仅按明确要求纳入 |
| 交付到 DocHub，包括“一键适配 DocHub” | [DocHub 适配](extensions/dochub/ADAPTER.md)：默认使用／排障指南，明确指定原理全文或已有稿件用途时沿用 |

只加载本次选择的扩展。先绑定交付稿及用途，再对完整稿做格式适配，产出媒体、定位映射与验收记录。扩展保留源稿，不削弱质量或代替目标服务授权。其他目标按同样边界补入口；正式发布仍按目标规范审阅具体稿件。
