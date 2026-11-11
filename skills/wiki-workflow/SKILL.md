---
name: wiki-workflow
description: 指导 Agent 生成、维护、审查有来源、可理解、可实施的高质量 Wiki；仅在选择目标时加载 SelfOpenWiki、DocHub 等发布适配。普通问答、仅查一个本地文件或未要求入库的临时笔记不触发。
---

# Wiki 工作流

这是一套指导 Agent 的生成、质量、审查和可选发布规范。以读者的问题和真实来源生成 Wiki，默认交付本地完整候选。完整目录可独立使用，不要求某个 Wiki 服务、MCP、SelfWorkflow、个人目录或已有文章 ID；宿主已有的授权与工程流程继续适用。

首次接入读 [使用与依赖](references/start.md)。生成或实质修订读 [生成流程](references/generation.md)、[内容验收](references/wiki-quality.md)和[正文契约](references/article-contract.md)。已有稿件沿其版本与有效证据继续，不从零重写。纯浏览、局部格式修复只检查影响项。

先确定来源、目标读者、范围、交付后端及操作是只读、候选还是正式更新。已有信息直接复用；新 Wiki 从问题到交付组织导航、专题和来源，既有 Wiki 保留有效正文、旧入口及版本边界。默认生成完整的可审阅稿和证据，不能用摘要、公式源码或未渲染图块代替完整成品。

数学、参数或几何解释读 [公式约定](references/wiki-math.md)；实际配图读 [图解规范](references/diagrams.md)。复杂覆盖、跨篇依赖、边界争议及用户明确要求的数值评分，按内容验收中的对应引用渐进加载。生成量、图数和工具成功不证明质量。

交付与正式写入沿 [可选发布](references/backends.md)。来源可以是授权文件、仓库、网页或已选知识库，来源后端与发布目标分别核验。内容、公式语义、源端呈现、目标端呈现和发布回执分开留证；必要缺口未关闭时交付标明状态的候选。

## 可选扩展

| 用户目标 | 入口 |
| --- | --- |
| 从已连接的 SelfOpenWiki 读取，或发布到该后端 | [SelfOpenWiki 适配](extensions/selfopenwiki/ADAPTER.md) |
| 适配、检查或发布到 DocHub，包括“一键适配 DocHub” | [DocHub 适配](extensions/dochub/ADAPTER.md) |

只加载本次选择的扩展。扩展读取既定 Wiki 快照，产出独立目标稿、媒体、定位映射与验收记录，保留源稿；不得削弱主质量要求或代替目标服务的授权。其他扩展按同样边界补入口，无需改生成流程。正式发布仍按目标规范审阅具体稿件。
