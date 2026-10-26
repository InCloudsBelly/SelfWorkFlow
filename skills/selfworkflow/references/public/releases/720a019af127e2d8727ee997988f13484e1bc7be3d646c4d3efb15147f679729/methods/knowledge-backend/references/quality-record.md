# Wiki 评价记录示例

这是格式示例，不是已执行结果或 MCP 发布状态。正式记录展开全部十二项（含不适用项），并绑定规则、候选、关联契约及来源。评分含义由[主标准](wiki-quality.md)统一规定。

| 字段 | 取值与含义 |
| --- | --- |
| applicability | applicable：适用；not-applicable：不适用，必须给理由。 |
| checkStatus | checked：已检查；unverified：未核实；not-applicable：不适用。 |
| score | 已检查项为 0–5 整数；未核实/不适用为 null，二者权重处理不同。 |
| decision | 按顺序判断：有必需项未核实为 unverified；全部核实但未达标为 revise；全部达标条件满足才为 pass。未核实不抹掉已确认的缺口。 |

保留逐项锚点/方法/观察/限制、分档理由、缺口/修订、分歧、四维/总分、范围与四类覆盖、三类走查、L1 路径和实际视觉/运行状态。技术主题另记文档初版/题单、来源核对、单元/问答对应、既有来源暴露和未解项。
`coverage` 仅表示评分项完成度；范围、单元和条件见 contentCoverage；L1 不增加加权分。未知计数为 null，不填成 0 或 100%；技术事实给来源位置/版本。记录留在既有任务/审查材料，不放 Wiki 开篇，不新增后端状态。

在既有逐项 evidence 或 visualCheck.scope 中补记：条目/步骤与图的对应、每图场景差异及说明、请求字体/实际字体/回退、强调与底色、列表标记及长标识符完整性。未实际观察的呈现记未核实，不把字体声明或格式解析作为验收证据。

```json
{
  "rubricId": "personal-wiki-deep-clarity-v5",
  "rubricBinding": "<任务绑定revision或本标准内容hash>",
  "candidateBinding": "<页面/包路径与内容hash，含关联契约>",
  "articleType": "technical",
  "reviewerKind": "independent",
  "scope": {"plannedPages": [], "evaluatedPages": [], "unchecked": []},
  "metrics": [
    {
      "id": "H1",
      "applicability": "applicable",
      "reason": "<本页承担的问题与职责>",
      "checkStatus": "unverified",
      "score": null,
      "scoringAnchor": "<逐项评分依据中的指标及分档>",
      "scoreReason": "<观察结果、为何支持本档及尚不支持更高档的原因>",
      "additionalWalkthroughEvidence": [],
      "evidence": [],
      "gaps": ["<待核对章节、影响及修订动作>"]
    }
  ],
  "applicableWeight": null,
  "coverage": null,
  "contentCoverage": {
    "baselineBinding": "<授权范围、预期单元/条件清单及来源的内容身份>",
    "rangeCheck": "unverified",
    "unitCounts": {"verified": null, "required": null},
    "conditionCounts": {"verified": null, "required": null},
    "unchecked": [],
    "exclusions": []
  },
  "scoringDisagreements": [],
  "linkClarityReview": {
    "checkId": "L1", "status": "unverified",
    "requiredPaths": [], "optionalAndEvidence": [], "gaps": []
  },
  "axisScores": {"human": null, "visual": null, "agent": null, "trust": null},
  "totalScore": null,
  "walkthroughs": {"human": "unverified", "diagram": "unverified", "agent": "unverified"},
  "designBoundaryReview": {
    "initialDocumentBinding": "<仅凭文档提出问题时的候选/关联契约版本>",
    "questionPlanBinding": "<源码核验前的问题清单版本或内容hash>",
    "sourceBindings": [],
    "implementationCoverage": [
      {"unitId": "<范围基准ID>", "unit": "<具体实现单元>", "questionIds": [], "wikiAnchors": [], "gaps": []}
    ],
    "priorSourceExposure": "<作者/Reviewer实际接触来源的情况>",
    "docOnlyCheck": "unverified",
    "sourceCheck": "unverified",
    "unresolved": []
  },
  "visualCheck": {"status": "unverified", "readingWidth": null, "scope": []},
  "runtimeCheck": {"status": "not-run", "reason": "<实际情况>"},
  "decision": "unverified"
}
```
