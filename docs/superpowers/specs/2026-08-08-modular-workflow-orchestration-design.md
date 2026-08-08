# SelfWorkFlow 模块化编排设计

- 日期：2026-08-08
- 状态：已批准进入实施
- 适用范围：SelfWorkFlow 核心编排、模块契约、Git 边界
- 不在本轮范围：C7OpenWiki MCP 的具体 Knowledge 实现与启用

## 1. 背景与目标

SelfWorkFlow 已有生命周期、复杂度与风险分类、Catalog、Superpowers 阶段映射、
无状态任务解析器、完成证据和 C7OpenWiki 实验适配，但这些能力尚未通过一个
清晰的模块编排契约连接起来。继续向现有入口堆叠规则会增加每个日常代码任务的
上下文和维护成本。

本设计采用“固定轻量主干 + 具名阶段插槽 + 无状态计划解析”。目标是：

- 保持 Design、Plan、Implement、Review、Verify 和 Knowledge 的顺序稳定；
- 允许阶段主模块替换和专项模块有序组合；
- 让 Codex 以外的 Agent 通过同一厂商无关契约执行；
- 默认只加载当前阶段实际选择的模块；
- 明确技术强制与 Agent Policy 的边界；
- 为未来模块保留清晰接入点，但不在 V1 实现动态插件系统；
- 保持仓库精简，不提交个人 Wiki、运行状态或会话原始记录。

本规格是模块编排和运行计划的唯一规范源。以下现有文件仍是各自领域的规范源：

- `workflow/protected-rules.yaml`：不可被模块、项目或宿主降低的受保护规则；
- `workflow/policies.yaml`：C/R 分类和能力门禁；
- `workflow/evidence.yaml`：完成证据；
- `capabilities/code-quality/*.md`：代码质量与责任层原则。

发生冲突时，受保护规则优先；本规格只取代旧设计中的编排、模块选择和 Knowledge
接入范围描述。其他历史设计是说明性记录，不再作为隐式实施需求。

## 2. 总体架构

三层职责如下：

```text
Pipeline       定义阶段、插槽、顺序、基数和 Gate
Catalog v2     注册模块、选择条件、调用方式和支持边界
Host Adapter   由具体 Agent 执行 Skill/MCP，并维护运行记录
```

标准主干是：

```text
Discover
-> Capability Check
-> Classify
-> Design
-> Plan
-> Implement / Debug
-> Review
-> Verify
-> Optional Knowledge
-> Complete
```

SelfWorkFlow 不实现守护进程、中央任务数据库或模型调用控制面。Resolver 生成静态
计划，外部 Agent 掌握对话和执行状态。只有实际验证计划身份、拒绝 paused 计划、
提交阶段结果并通过完成 Gate 的宿主可以声明为 conforming；仅加载 Instructions 的
宿主只能声明 agent-policy 支持。

## 3. Pipeline 与插槽

新增 `workflow/pipeline.yaml` 和对应 Schema。Pipeline 只保存：

- 阶段顺序；
- 具名插槽；
- 插槽基数：`exactly-one`、`zero-or-one`、`zero-or-many` 或 `gate`；
- 静态启用和不适用条件；
- 入口与出口 Gate；
- 失败责任阶段 `failureOwner`；
- 插槽允许的调用类型。

Pipeline 只引用稳定模块 ID，不重复模块来源、触发或能力元数据。

Pipeline 使用关闭的静态条件语言。条件只能读取规范化 Request 中的
`writeTask`、`operationType`、`complexity`、`risk`、`explicitModuleIds`、
`projectMinimums` 和 capability snapshot 状态；运算符仅支持 `all`、`any`、
`not`、`eq`、`gte` 和 `contains`。Resolver 在生成计划时一次性求值。缺少必需输入
是无效请求。Required Primary/Gate 的能力报告缺失或为 unsupported/unverified 时
返回 paused，不按 false 静默跳过；Optional 模块能力不足时只排除该模块、记录原因
和影响。普通代码任务缺少可选 Knowledge 后端同样不暂停主流程。Host 不得重新求值
静态 activation，只能根据已声明的运行期 Gate 读取 StageResult/Evidence。

阶段插槽的 V1 结构为：

```text
Discover:
  context -> optional knowledge.read -> module routing

Design:
  precheck -> primary -> specialists -> conditional cross-review -> gate

Plan:
  primary -> specialists -> design-consistency gate

Implement / Debug:
  method -> domain augmenters -> change result

Review:
  structured self-review -> required independent/domain review -> remediation

Verify:
  test selection -> execution -> acceptance/evidence gate

Knowledge:
  optional propose -> separately confirmed update

Complete:
  final evidence and residual-risk gate
```

Knowledge read 可以在 Discover 或 Design 阶段发生；Knowledge propose/update 是
Verify 后、Complete 前的可选钩子，不要求普通代码任务具备知识后端。

## 4. Catalog v2 模块契约

Catalog 继续是运行时唯一模块选择入口。每个可执行模块增加：

```text
contractVersion
stage
slot
activation
invocation.kind
invocation.ref
inputContract
outputContract
requiredCapabilities
sideEffects
dependencies
conflicts
priority
supportStatus
```

V1 的调用类型仅为：

- `agent-native`：宿主自身的结构化能力；
- `skill`：加载一个经过来源绑定的 Skill；
- `mcp`：调用一个经过契约和能力检查的 MCP 工具。

Catalog 的 checked-in source 只证明适配声明身份。外部能力分别由以下证据证明：

- Superpowers：选择锁、commit、dirty 状态、文件清单和内容 hash；
- MCP：适配器版本、工具契约 hash、服务/build 身份和实时能力；
- Agent：宿主能力声明及行为验证状态。

支持证明拆分为 `sourceIntegrity`、`adapterSupport`、`runtimeCapability` 和
`behaviorEvidence`。Primary 或 Gate 的任何必需层不是 supported 时，计划暂停。

## 5. PlanGraph、RunLedger 与身份绑定

Resolver v2 保持无状态，只输出静态、不可变的 `PlanGraph`：

```text
stage / slot order
condition expressions
selected modules
gate definitions
failureOwner
static not-applicable decisions
requestHash
capabilitySnapshotHash
pipelineHash
policyHash
catalogHash
planHash
```

Resolver API 返回 `ResolveResult`，而不是把执行状态混入 PlanGraph：

```text
schemaVersion: 2
status: active | paused
reasonCodes[]
diagnostics[]
planGraph
```

结构或 Schema 无效时抛出稳定、脱敏的 `ResolveError`，不返回 PlanGraph。输入有效但
能力、来源、选择或插槽不能满足时返回 paused，并保留不可执行的静态图和阻塞插槽。
V1 原因码至少包括：`required-capability-unavailable`、
`primary-module-unavailable`、`gate-unavailable`、`slot-cardinality-invalid`、
`module-conflict`、`source-evidence-stale`、`unsupported-contract` 和
`explicit-selection-invalid`。Diagnostics 只能使用有界、类型化字段，不回显不受信
请求正文。

首次解析不能预言运行期 Gate、动态跳过、修复次数或下一步执行结果，因此这些信息
不得写成 PlanGraph 事实。Host 使用显式 `RunLedger` 保存 StageResult、Gate 结果、
重试和运行期跳过。输入或证据变化后必须重新解析；旧 planHash 不得续跑。

RunLedger 使用独立 v2 Schema，但不要求中央持久化服务：

```text
schemaVersion: 2
planHash / requestHash
status: pending | active | paused | failed | completed | superseded
stages[]:
  stageId
  status: pending | active | passed | failed | paused | skipped
  attempts[]: {attemptRef, ordinal, previousAttemptRef}
  slotResults[]: {attemptRef, moduleId, resultRef}
  gateResults[]: {attemptRef, gateId, outcome, resultRef}
  runtimeSkips[]: {attemptRef, slotId, evidenceRef}
supersededByPlanHash?
```

同一时刻最多一个阶段为 active。阶段只能从 pending 进入 active，再进入终态；重试
追加 attempt，不覆盖旧结果。每个 slot result、Gate result 和 runtime skip 都绑定
产生它的 attemptRef；当前 attempt 是 `attempts[]` 的最后一项，阶段通过条件只读取
当前 attempt 的结果。追加新 attempt 后，旧结果保留审计但立即失去通过效力，直到
新 attempt 产生完整结果。slot/Gate 的 `resultRef` 在整个 Ledger 内不可复用，禁止把
旧产出换绑到新 attempt。Runtime skip 仅允许用于计划声明的 optional slot；它免除
该 slot 在当前 attempt 的模块结果要求，并且必须引用同一 attempt 的 Gate 结果，或
当前已校验且仍新鲜的 capability snapshot 证据。失败按 PlanGraph 的 failureOwner
回流。请求或能力证据变化时，旧 Ledger 标为 superseded 并绑定新 planHash，不能在
旧 Ledger 中继续。

`runtimeSkip.evidenceRef` 保留 capability evidence 的独立契约（非空、最多 256
字符），不得错误套用普通 Ledger ID 的字符集或 128 字符上限。普通 Ledger ID 与
写入 helper 则使用同一套含冒号的 128 字符契约。

attemptRef 在整个 Ledger 内唯一。首个 attempt 固定 `ordinal=1` 且 previous 为 null；
后续 ordinal 严格加一并引用紧邻前一个 attemptRef，形成可验证连续链。结构化结果的
attemptRef 必须属于同一 stage 的 attempts，未知、跨 stage、重复、删除、插入或重排
全部拒绝。只有最后一个合法 attempt 的结果参与阶段完成判定。旧 v1 结果没有可靠
attempt 归属，V2 CLI 和 API 以稳定的 `ledger-schema-version-unsupported` 拒绝，
不猜测迁移、不静默采用旧结果。

Host 写入帮助函数不得返回超出 RunLedger Schema 数组上限的对象；达到 attempt 或
结果数量上限时必须在追加前 fail closed。

模块返回最小 StageResult：

```text
status
summary
typedArtifacts
typedEvidenceRefs
issues
nextStageRequest
```

Artifact 和 Evidence 引用必须带稳定 ID、类型、hash 和大小，不接受任意路径或自由
文本作为权威证据。模块不得传播模型私有推理过程，也不得隐式调用计划外模块。
Skill 要求进入下一阶段时，只能形成 `nextStageRequest`，由 Host 按既有计划调度。

请求携带规范化 `capabilityEvidenceSnapshot`。每项固定：

```text
provider
subject kind / id / version / build / source-lock
state
observedAt / validUntil
evidenceRef / evidenceHash
```

快照 hash 是 requestHash 的组成部分；planHash 对完整规范化 PlanGraph 计算。Host 在
Primary 或 Gate 执行前复核相关证据的 identity、hash 和 freshness。变化或过期后
必须拒绝旧 planHash、更新快照并重新解析，RunLedger 不得自行刷新证据。

## 6. 复杂度、风险与流程强度

强度是 `writeTask × complexity × risk` 的纯函数，验收覆盖 32 种组合。修改任务的
基础矩阵为：

| C/R | R0 | R1 | R2 | R3 |
|---|---|---|---|---|
| C0 | Light | Light | Full | Deep |
| C1 | Light | Light | Full | Deep |
| C2 | Full | Full | Deep | Deep |
| C3 | Deep | Deep | Deep | Deep |

- Light：agent-native Design Check、内联 Plan、L0 自审和最窄充分验证；
- Full：Brainstorming、Writing Plans、最低 L2 独立实现 Review 和完整相关验证；
- Deep：Full 的全部要求，并推荐 Grill-me，由用户决定是否启用；
- 项目规则只能升级，不能降低；
- 非修改任务不进入 Implement 或修改 Review，但复杂设计分析仍按 C/R 选择 Design；
- 所有实际修改都必须 Review 和验证。

`C2/R2` 明确归入 Deep，避免同时命中 Full 和 Deep。`C3` 或 `R3` 也归入 Deep。

## 7. Design、Plan、Review 与 Verify

Design 默认 Primary 是 Superpowers Brainstorming。Grill-me 只允许用户显式请求，
或在 Deep 任务中推荐后由用户确认：

```text
Grill-me discussion
-> user confirms shared understanding
-> independent-context Brainstorming cross-review
-> design gate
```

Grill-me 永不静默自动启用。跨阶段的 Writing Plans 调用必须预先出现在 PlanGraph，
不能作为模块内部隐藏调用。

Plan 在 Light 使用内联计划，在 Full/Deep 使用 Writing Plans，并执行设计一致性
Gate。为控制 V1 成本，普通 Plan 不单独启动独立 Review；实现后的独立 Review
仍按强度执行。

Implement 使用 TDD，Debug 使用 Systematic Debugging，再按确定性条件加载领域增强
模块。Review 至少覆盖完整 diff、验收条件、逻辑闭环、失败路径、安全、侵入性和
无关修改。任何方案对应的实现落地后都必须进入 Review；Review 发现的问题修正后
必须重新 Review，不能用实现前的方案审查替代落地后的结果审查。Verify 执行任务
类型对应的最窄充分直接路径、失败路径和相关回归。

设计、规格和实施计划是中间产物：写入文档后先 Review 文档，再继续实现。用户明确
要求的交付物本身是文档时，文档仍作为一次修改进入 Review 和 Verify，通过后才能
交付；用户要求构建、修改或修复时，不得把“已输出方案文档”误当作完成。

前置文档 Review 不新增生命周期阶段：`design.gate` 负责设计/规格文档，`plan.gate`
负责实施计划。只要当前阶段产生了文档，对应 Gate 就必须取得绑定最终文档 hash 的
Review receipt；发现问题时阶段保持 active，修正文档并废弃旧 receipt，再对新 hash
Review。只有当前 hash 的 Review 通过后 Gate 才能通过并进入下一阶段，RunLedger
不记录中间稿为 passed。前置文档复用现有 Review receipt artifact envelope，以文档
ID/hash 作为 subject，不新增 Gate 专用 receipt 格式。纯文档交付使用
`operationType=document`，由内建
`implement-documentation` 模块落地，之后仍经过普通 `reviewed` 和 `verified` 阶段。

实现 Review 同样复用现有 receipt，并绑定当前完整实现 subject 和 diff/hash。Review
发现问题时 `reviewed` 阶段保持 active，在当前 RunLedger 追加 attempt；修正后旧
receipt 立即失效并重新 Review，只有最终 diff/hash 对应的 receipt 可使 Review Gate
通过。普通实现修正不重新解析静态计划；只有 Request、能力证据或其他 PlanGraph
输入变化时才 supersede/re-plan。任何修正都会使旧 Review 和完成证据失效，且最终
完成 subject 必须重新绑定最终 diff/hash。新 attempt 创建后，旧 attempt 的
slot/Gate 结果不能使阶段通过。

## 8. 模块选择与冲突

逐插槽选择顺序是：

```text
protected gates
-> project mandatory additions/upgrades
-> explicit per-task selection
-> repository default
-> deterministic augmenters
```

V1 不实现语义自动选择。语义信息最多形成建议，不能选择 Primary 或 Gate。
`activation` 的 V1 值只允许 `mandatory`、`default`、`explicit` 和
`deterministic`，并由 Resolver 按关闭条件语言求值。

- 依赖闭包后按稳定 ID 去重；
- Mandatory 高于 Explicit，Explicit 高于 Deterministic；
- 同级再按 priority 和稳定 ID 排序；
- Explicit 与 Mandatory 冲突时暂停；
- Unsupported Primary/Gate 暂停；
- Optional 模块不可用时明确排除并说明影响；
- 下游规则不得移除受保护 Gate。

V1 不实现持久化用户 Profile。Brainstorming 是仓库默认；Grill-me 只对当前任务
生效。未来 Profile 和外部动态模块包需要独立设计，不在本轮预留可执行实现。

## 9. 用户交互与修正闭环

仅以下关键决策询问用户：

- 范围或验收标准发生实质变化；
- 不可逆或外部副作用；
- 安全、凭据和敏感数据；
- 默认配置或受保护规则变化；
- 正式知识库写入；
- 现有证据无法回答的产品决策。

一般技术细节、可修复 Review 问题和测试失败由 Agent 在批准范围内自主闭环；必要
时使用独立 SubAgent Review，并在完成后汇报。修正必须回到最早拥有数据和不变量
的责任阶段。相同 failure fingerprint 在输入、diff 和证据均未变化时重复出现，
应停止自动循环并报告，不得伪称完成。

次要决策必须同时满足：处于用户批准范围内；只影响一个局部组件；可通过局部回退
轻易恢复；不改变公共接口、Schema、持久数据、兼容性或用户可见验收结果；不涉及
安全、凭据、敏感数据、外部副作用或用户已有修改；备选方案均满足受保护不变量；
不确定性为低。任一条件不满足或无法确认，就按关键决策询问用户。

满足上述全部条件时，可以交给独立 SubAgent 比较 2–4 个备选并采用推荐项，不需要
为每个细节打断用户。采用后必须把 `kind=decision-record` 的有界 artifact 作为
StageResult typed artifact 或任务证据保存。其内容由
`schemas/decision-record.schema.json` 约束：

```text
schemaVersion: 1
decisionId: stable ID, <= 128 chars
question: <= 1024 chars
alternatives: 2..4 {id, summary <= 1024 chars}
recommendationId: alternative ID
selectedId: alternative ID
rationaleSummary: <= 2048 chars
impact:
  scope: local-component
  rollback: easy
  compatibility: unchanged
  security: unchanged
  externalSideEffects: false
  uncertainty: low
reviewContext:
  mode: independent-subagent | structured-self-review
  contextId: stable ID
  independence: independent | unverified
verificationRefs: 0..16 bounded artifact references
```

Schema 关闭未知字段并约束字段长度、数量和枚举；语义校验器要求
`recommendationId`、`selectedId` 都引用 alternatives 中唯一 ID，并固定
`independent-subagent -> independent`、`structured-self-review -> unverified`。
自动落地时还要求 `selectedId == recommendationId`；若 Agent 希望采用其他备选，
必须升级为用户决策，不能使用次要决策路径自行偏离推荐。
记录只保存结论和可审计依据，不保存模型私有推理过程。SubAgent 不可用时允许同一
Agent 做结构化自审并标记 `independence: unverified`；一旦判断可能触及本节关键
决策边界，必须升级询问用户，不能借“次要决策”路径规避授权。V1 对记录结构和语义
提供机械校验，但“何时必须委托和记录”仍属于 `agent-policy`，不得虚构为 Resolver
或 RunLedger 的机械强制。

## 10. Knowledge 与 C7OpenWiki 边界

核心只保留：

```text
knowledge.read
knowledge.propose
knowledge.update
```

本轮只实现厂商无关的 Knowledge 插槽和接口类型，不实现或启用任何 C7OpenWiki
专属行为，不调用真实 C7 MCP，也不修改 `D:\openwikiC7`。完整自动回归可以只读
执行既有 FakeClient/契约测试，以证明冻结能力未被本功能破坏；该回归不构成 C7
专项验收，不得提升其支持状态。以下现有 SelfWorkFlow 路径同样冻结，不得出现在
本功能相对基线的 diff 中：

```text
extensions/knowledge/c7-openwiki/**
src/selfworkflow/c7_openwiki.py
tests/conformance/test_c7_openwiki_adapter.py
tests/fixtures/c7-openwiki/**
```

这些既有文件不是本功能的交付物，不因本规格获得更高支持状态。个人 Wiki、数据库
和运行状态始终由 C7OpenWiki 仓库管理，不进入 SelfWorkFlow。后续独立任务再定义
C7 adapter 的服务/build 身份、Schema、机械 CAS、冲突拒绝、恢复、来源保护、Review
receipt 和真实 MCP 行为。

普通代码任务缺少 Knowledge 后端不阻塞交付；仅在 Wiki 本身是主要交付目标时暂停。

## 11. 契约版本与迁移

Pipeline Schema、Catalog Schema、Resolver Output 和 Behavior Policy 分别版本化。
本次是契约 v2 变更：

- 提供 v1 单阶段请求到 v2 PlanGraph 请求的显式迁移器；
- 删除 `superpowers.py` 中与 Catalog 重复的运行时硬编码映射；
- Optional 字段或 Slot 默认视为 breaking；只有消费者显式声明可忽略未知项时才可
  作为向后兼容变更；
- RunLedger 从 v1 升级到 v2，attempt 和结果改为结构化绑定；由于 v1 无法恢复结果
  所属 attempt，CLI/API 稳定拒绝 v1，不提供猜测性迁移；
- 默认模块、Required Stage/Slot、顺序或 Gate 变化是 breaking change。

V1 仅支持 checked-in 模块。新增模块需要模块声明、Skill/适配器、Catalog 条目、
插槽绑定和契约/行为测试，然后重新构建和安装。

## 12. Git 首版边界

提交：

- 工作流、Pipeline、Schema、Catalog、Resolver；
- 内建 Skill、能力和适配器；
- 安装器、源码、测试和小型 fixture；
- 依赖锁；
- 批准设计、最终实施计划、ADR 和发布摘要。

本功能不得新增或修改第 10 节列出的 C7 专属路径。现有 tracked 文件保持原样，
不纳入本功能提交说明。

`.gitignore` 和 `workflow/git-policy.yaml` 使用明确规则。V1 禁止或忽略：

```text
.venv/**
build/**
dist/**
artifacts/**
logs/**
runtime/**
.pytest_cache/**
htmlcov/**
**/__pycache__/**
**/*.pyc
**/*.egg-info/**
.coverage
coverage.xml
**/.env
**/.env.local
**/.env.*.local
**/*.sqlite
**/*.sqlite3
**/*.db-wal
**/*.sqlite-wal
```

`.env.example`、`.env.sample`、测试用脱敏 fixture 和仓库内合法 manifest 不被名称规则
误禁。第三方 checkout、个人 Wiki、OAuth/Token/Cookie 文件若不命中固定路径，仍由
known-secret/path policy 报告并拒绝；规则不得读取或输出秘密内容。

Git Policy 检查 HEAD、Index 和 staged blob，规范化路径大小写，区分 symlink、
submodule 和 binary。只禁止明确运行时根目录，不泛禁 `manifest` 等正常文件名。
Secret heuristic 只能报告“未发现已知模式”，不能宣称不存在秘密。单文件超过 1 MiB
警告，超过 5 MiB 默认拒绝；Allowlist 必须记录 reason、hash、owner 和 expiry。

## 13. 验收标准

- Pipeline、Catalog v2、PlanGraph 和 StageResult Schema 通过正反向测试；
- `writeTask × C/R` 的 32 种组合全部验证；
- PlanGraph hash 和能力快照变化使旧计划失效；
- Slot 基数、排序、依赖、冲突、去重和 Unsupported 路径通过；
- Grill-me 后独立 Brainstorming 的顺序可证明；
- 方案实现后必经 Review，设计/计划文档分别经对应 Gate Review 后继续落地；
- 纯文档交付可解析并在落地后进入普通 Review/Verify；
- 实现修正使旧 Review receipt 失效，并在当前 active RunLedger 重新 Review；仅静态
  计划输入变化时 supersede/re-plan；
- 次要决策允许独立 SubAgent 推荐并形成有界记录，关键决策仍必须询问用户；
- conforming Host 与 agent-policy 边界准确；
- Superpowers 来源漂移会暂停相关 Primary/Gate；
- v1 请求迁移器保留现有调用兼容入口；
- Knowledge 插槽存在，但 C7 具体实现和 update 支持不被本轮误报；
- 本功能 diff 不包含任何冻结的 C7 专属路径，且不运行 C7 native MCP；
- Git Index Policy 覆盖禁止路径、已知秘密模式、生成物和体积；
- 现有自动化回归保持通过；
- 未执行的 Codex、其他 Agent 和 C7 native MCP 行为明确标记 unverified。

## 14. 规范化端到端示例

```text
Request(writeTask=true, C2/R2, operation=implement)
-> capabilityEvidenceSnapshot(Superpowers source and Host capabilities)
-> ResolveResult(active)
-> PlanGraph(Deep, Brainstorming, Writing Plans, TDD, L2 Review, Verify)
-> Host creates RunLedger bound to planHash
-> each StageResult and GateResult is appended
-> capability evidence expires before Review
-> Host rejects old planHash and marks Ledger superseded
-> updated snapshot is resolved to a new planHash
-> new Ledger resumes from evidence-backed stage inputs
```

若 Primary 不可用，ResolveResult 为 paused，reason code 是
`primary-module-unavailable`；Host 不创建可执行 Ledger。若 Request 缺少必需字段，
Resolver 返回脱敏 ResolveError，不产生 PlanGraph。

## 15. 验收追踪

| 验收主题 | 规范/API | 最低测试 |
|---|---|---|
| 阶段与插槽 | Pipeline v2 Schema | Schema 正反例、顺序和基数 |
| 模块选择 | Catalog v2 + Resolver | 默认、显式、强制、确定性、冲突、去重 |
| 强度 | classification pure function | `writeTask × 16 C/R` 共 32 格 |
| 计划身份 | ResolveResult + PlanGraph | hash 稳定、证据变化失效、paused 原因码 |
| 运行边界 | RunLedger v2 + StageResult | 状态转换、单 active、attempt-bound 结果、v1 拒绝、supersede |
| Grill 流程 | Design slot order | 显式/推荐确认、独立 Brainstorming 顺序 |
| 中间文档 Review | design/plan Gate + Host policy | 最终 hash receipt、修正后旧 receipt 失效、Review 后继续实现 |
| 纯文档交付 | `implement-documentation` + Review/Verify | document 请求可解析、落地后 Review、文档验证 |
| 实现后 Review | Review receipt + attempt-bound RunLedger results | 新 attempt 不复用旧结果、最终 diff/hash 绑定、重新 Review、静态输入变化才 re-plan |
| 次要决策 | `decision-record` Schema/validator + agent-policy | 引用一致性、独立性组合、委托与关键决策拒绝自动裁决 |
| Git 边界 | git-policy + index scanner | forbidden、allowlist、symlink/submodule/binary |
| Knowledge 边界 | Generic slot/interface | C7 冻结路径无 diff、无 MCP 调用 |
| 迁移 | v1 request migrator | 兼容输入、拒绝歧义输入 |

## 16. 独立 Review 结论

设计先后经过 Grill-me 压力测试和独立 Brainstorming Review。终审要求把动态运行事实
移出无状态 Resolver、把能力证据纳入 plan identity，并停止推断 C7 update 已受支持。
上述修订完成后，独立终审结论为 `Approved`。
