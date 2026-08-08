# SelfWorkFlow V3 自适应质量模块设计

- 日期：2026-08-09
- 状态：已批准进入实施
- 基线：SelfWorkFlow 编排契约 V2
- 范围：OpenSpec、TEA、选择性 Review、Quality Playbook/安全审查模块及其 Git 依赖管理
- 不在本轮范围：Spec Kit、C7OpenWiki MCP 的具体实现、非 Codex Agent 的完整行为认证

代码理解、C++ 增强、Provider 本地覆写和维护操作由规范性设计增量
[`2026-08-09-cpp-code-intelligence-providers-v3-design.md`](2026-08-09-cpp-code-intelligence-providers-v3-design.md)
定义。该增量与本文共同组成 V3 设计与实施计划依据；发生冲突时，增量只能收紧 Provider、维护授权、独立 Review
和证据边界，不能降低本文的受保护不变量。

## 1. 目标与约束

SelfWorkFlow 继续保持固定的轻量代码主干，不把所有 Skill 注入每次任务。V3 在此基础上增加：

- 按任务原型选择 Design 模块；
- 按复杂度、风险和最终代码特征选择测试设计强度；
- 在最终 diff 形成后选择必要的专项 Review；
- 对 Heavy/Forensic 模块实行显式授权、隔离执行和按需加载；
- 让外部 Git 模块可复现、可随 SelfWorkFlow 父仓库提交和更新；
- 以正确性为首要目标，同时避免日常任务无意义的上下文和执行成本。

V3 保留以下受保护不变量：

- 不虚构能力、测试结果、Review 结果或支持状态；
- 不静默降级；
- 不绕过用户对副作用、安装、联网、凭据和正式知识写入的授权；
- 不覆盖用户已有修改；
- 完成前必须具有绑定最终产物的新鲜验证证据；
- 运行期选择器不得越过静态 PlanGraph 的允许边界。
- 显式 Grill-me 后的 Brainstorming 交叉 Review 必须由新建的独立 SubAgent 执行，只接收规范化设计摘要；
  宿主不支持时必须先取得用户授权，并永久标记 `independence=unverified`。

## 2. 架构决策

比较过三种方案：

1. 实现后重新解析整张 PlanGraph。它会改变计划身份、破坏 RunLedger 连续性，不采用。
2. 静态 PlanGraph 声明候选集合，运行期类型化选择器只从候选集合中选择。它兼顾安全边界、最终产物信息和按需加载，采用。
3. 解析时预选所有可能模块，执行时再跳过。它会扩大上下文、弱化审计语义，不采用。

V3 的核心结构为：

```text
Resolve Request V3
  -> immutable PlanGraph V3
       stages / gates / selected modules
       eligible modules / selection policy hash
       coverage obligations / failure routes
  -> Host executes fixed modules
  -> typed runtime signals become available
  -> bounded selector emits SelectionReceipt
  -> Host validates receipt and executes selected subset
  -> ReviewAggregate / VerificationAggregate
  -> completion gate validates content-addressed evidence
```

运行期选择器不是第二个 Resolver。它不能更改阶段、Gate、Primary、依赖版本或候选集合。

## 3. V3 契约边界

V2 继续保持原语义。V3 不原地修改任何 V2 Schema、Pipeline、Catalog 或 Ledger。版本化文件边界为：

```text
schemas/*.schema.json               # 永久保留的现有 V2 兼容入口，不移动
schemas/v3/resolve-request.schema.json
schemas/v3/resolve-result.schema.json
schemas/v3/plan-graph.schema.json
schemas/v3/run-ledger.schema.json
schemas/v3/pipeline.schema.json
schemas/v3/catalog.schema.json
schemas/v3/module.schema.json
schemas/v3/selection-receipt.schema.json
schemas/v3/diff-signal-set.schema.json
schemas/v3/review-finding.schema.json
schemas/v3/review-aggregate.schema.json
schemas/v3/test-strategy.schema.json
workflow/pipeline.yaml              # 永久保留的现有 V2 兼容入口，不移动
workflow/v3/pipeline.yaml
catalog/index.yaml                  # 永久保留的现有 V2 兼容入口，不移动
catalog/domains/**                  # 永久保留的现有 V2 兼容入口，不移动
catalog/modules.yaml                # 永久保留的现有 V2 兼容入口，不移动
catalog/v3/index.yaml
catalog/v3/domains/**
catalog/v3/modules.yaml
```

Resolver 通过请求的 `schemaVersion` 分派到独立 V2/V3 入口；输出、PlanGraph 和 RunLedger 的版本必须一致。
V2 Host 遇到 V3 请求或计划时返回稳定的 `unsupported-contract-version`，不得忽略未知插槽。V3 Host 不得把
V2 Ledger 续接到 V3 PlanGraph。V2 到 V3 只允许显式迁移：Host 先生成完整的 V3 分类证据和能力快照，再
产生新 PlanGraph，并把旧 Ledger 标记为 superseded。

现有 V2 文件、Python 默认路径、CLI 默认行为和 fixture 在 V3 落地中保持原位且继续回归测试。V3 代码必须
通过显式版本分派读取 `schemas/v3`、`workflow/v3` 和 `catalog/v3/index.yaml`；不得通过移动 V2 文件、软链接
替换旧入口或根据文件是否存在猜测版本。Catalog V3 的 index 显式列出 V3 domains 与 modules，并对其内容
计算独立 catalogHash。

以下能力只通过显式 V3 契约引入：

### 3.1 ResolveRequest V3

新增规范化字段：

```text
taskArchetype
requirementsMaturity
scopeShape
durableSpec
classificationConfidence
classificationEvidence[]
testLevelFloor
```

`taskArchetype` 初始枚举：

```text
mechanical-change
bounded-feature
bugfix
behavioral-refactor
exploratory-design
architecture-change
migration
spec-document
cross-project
```

V3 分类是 Host 在调用 Resolver 前执行的纯、无副作用预处理步骤。它生成规范化分类字段、证据引用和
分类器版本/hash，随后作为 ResolveRequest V3 的一部分进入 requestHash。Pipeline V3 仍保留
`classified` 阶段，但该阶段只验证并确认已有分类证据的新鲜度，不再决定路由；验证失败时 supersede
计划并重新执行预分类。这样 Design/Test 路由在静态 PlanGraph 生成前已经确定，同时保留运行记录中的
分类审计点。V2 的 `classify.task` 行为不变。

只有低置信度且不同分类会改变 Primary、安全边界或验收结果时才询问用户；普通局部差异由 Agent 选择并记录。

### 3.2 PlanGraph V3

插槽可以是静态执行或受限延迟选择：

```text
selectionMode: static | bounded-runtime
selectedModules[]
eligibleModules[]
selectionPolicyRef
selectionPolicyHash
coverageObligations[]
```

`eligibleModules` 是 Resolver 根据受保护规则、项目规则、显式选择、能力快照和冲突关系计算出的
封闭集合。Host 不得在运行期向集合外追加模块。需要集合外能力时，模块只能返回
`nextStageRequest`，由 Host 生成新请求并 supersede 原计划。

### 3.3 SelectionReceipt

运行期选择结果必须绑定：

```text
planHash / stageId / slotId / attemptRef
selectorModuleId / selectorSourceHash
inputArtifactId / inputArtifactHash
eligibleModuleIds[]
selectedModuleIds[]
selectionReasons[]
signalEvidenceRefs[]
estimatedContextCost / estimatedExecutionCost
coverageDecisions[]
receiptHash
```

选择器只能读取类型化输入，输出结构化选择结果；不得安装、联网、执行测试、修改文件或发布内容。
Host 必须机械校验所选模块是 `eligibleModules` 的子集、hash 新鲜、依赖闭包满足且覆盖义务没有被丢弃。

### 3.4 运行证据

新增或扩展以下内容寻址工件：

- `DiffSignalSet`：绑定最终 diff/hash 的文件、语言、边界、状态、并发、安全和性能信号；
- `ReviewFinding`：包含失败路径、证据位置、严重度、责任层和稳定指纹；
- `ReviewAggregate`：去重、冲突裁决、根因归属、覆盖结论和残余风险；
- `TestStrategy`：测试等级、技法选择、理由、授权要求和验证映射；
- `CoverageResult`：每项风险覆盖义务的 fulfilled、unverified 或 blocked 结果。

完成 Gate 不能只接受普通字符串 `resultRef`；它必须解析并验证工件内容、模块身份、输入 hash、
输出 Schema、attempt 和能力快照。

### 3.5 Pipeline、Catalog、ResolveResult 与 RunLedger V3

- Pipeline V3 新增 `bounded-runtime` 插槽、selector 前置 Gate、aggregate 插槽和覆盖 Gate；
- Catalog V3 新增 selector 身份、eligible 规则、风险覆盖标签、上下文成本和副作用声明；
- ResolveResult V3 只携带 PlanGraph V3，保留 active/paused 语义并增加稳定的 selector/coverage 原因码；
- RunLedger V3 记录 SelectionReceipt、模块级执行/跳过、ReviewAggregate、CoverageResult 和工件 hash；
- V3 的 `failureRoute` 可以按 finding/coverage 的 `rootCauseOwner` 回到 design、plan、implemented、reviewed
  或 verified，不再用一个阶段级 `failureOwner` 假装表达全部根因；
- V2 代码路径和测试作为兼容回归保留，V3 测试不得通过修改 V2 fixture 来获得通过。

### 3.6 Provider 绑定边界

V3 代码增强增量把能力、模块和具体 Provider 分离。PlanGraph 必须静态绑定允许的
`(moduleId, providerId, operationId, adapterHash)` 元组；运行期选择器不得发现本地工具、拼接任意命令、
安装 Provider 或切换到计划外实现。Provider 的稳定支持证据与项目索引等动态状态分别建模，详细契约见代码
增强增量。

## 4. Design 模块路由

| 任务原型 | 默认倾向 | 说明 |
|---|---|---|
| mechanical-change | Design Light | 不为纯机械修改制造规格文档 |
| bounded-feature | OpenSpec | 需求成熟且长期规格有价值时优先 |
| bugfix | Systematic Debugging | OpenSpec 默认关闭，先固定 failure envelope 和根因 |
| behavioral-refactor | OpenSpec 或 Brainstorming | 边界稳定时用规格保行为；不确定时先 Brainstorming |
| exploratory-design | Brainstorming | 先解决目标、范围和替代方案 |
| architecture-change / migration | Brainstorming | Deep 时推荐 Grill-me，由用户决定 |
| spec-document | OpenSpec | 目标就是维护长期规格 |
| cross-project | Brainstorming | Spec Kit 延后到独立适配任务 |

OpenSpec 有两种模式：

- Native：目标仓库已经初始化 OpenSpec，或用户明确要求提交长期规格；
- Ephemeral：未初始化时只在 `.selfworkflow/runtime/openspec/<run-id>/` 生成临时工件。

不得为了使用 OpenSpec 静默修改目标项目。Brainstorming 已消除不确定性但需要长期规格时，
OpenSpec 作为下游规格固化模块，不重复盘问用户。

Grill-me 仍只由用户明确要求，或 Deep 任务推荐后由用户确认。完成共同理解后必须进行独立上下文的
Brainstorming 交叉 Review。

## 5. 分层测试设计与 TEA

测试设计与测试执行分离。初始分类给出 `testLevelFloor`，最终 `DiffSignalSet` 只能升级，不能降级：

| 等级 | 适用范围 | 最低要求 |
|---|---|---|
| T0 | 不改变行为的文案/纯元数据 | 格式、解析、链接、消费者检查 |
| T1 | 局部线性行为 | 直接路径、失败路径、状态不变量、最窄相关回归 |
| T2 | 多边界或较高风险行为 | TEA 风险测试设计、优先级、边界、追踪和 Test Review |
| T3 | 高风险、复杂状态或安全关键 | T2 全部要求，并按信号选择高级技法 |

启用 Grill-me 并进入实现的任务最低为 T2，但不因此自动启用所有高级测试。

T3 技法的确定性倾向：

- 三个以上相互作用配置：组合测试/PICT；
- roundtrip、幂等、规范化、排序、容器不变量：Property-based Testing；
- 不可信输入、解析器、协议、序列化、Native 边界：Fuzzing 与 Sanitizer；
- 关键稳定单元行为：限定范围的 Mutation Testing；
- 共享状态或异步协作：Concurrency Testing；
- 热路径或资源预算：Performance Testing。

V3 的目标是为锁定版本的 TEA 建立全部上游工作流的候选适配条目，但每个条目必须分别记录
sourceIntegrity、adapterSupport、runtimeCapability 和 behaviorEvidence。在精确 commit、映射测试和真实行为
证据完成前，条目只能是 planned/unverified，不能被 Required 插槽选中。达到支持条件后仍按任务选择执行：

- T2/T3 的 Plan 自动进入 Test Design；
- T2/T3 的 Review 自动进入 Test Review；
- T3/Deep 进入 Trace/Gate；
- ATDD 只用于用户可见行为、公共 API 或验收场景；
- NFR、框架、CI、自动化和教学工作流只在任务信号或用户要求命中时加载。

需要安装工具、联网、长时间 CPU、外部环境或持久产物时必须先征得授权。已安装、只读、隔离且有界的
工具可以自动执行。TEA 不可用而 T2/T3 需要其唯一能力时暂停；只有用户明确批准一次性受限降级后，
才能继续并标记 `unverified`。

## 6. 选择性 Review

固定 Review 顺序：

```text
structured self-review
-> review.select(final DiffSignalSet)
-> independent general review
-> selected specialist reviews
-> review.aggregate
-> remediation
-> fresh review for changed diff
```

初始专项能力包括：

- 测试缺口；
- 静默失败与错误处理；
- 类型、状态与不变量；
- 规格与代码一致性；
- C/C++ 正确性和内存安全；
- 安全、凭据与误报验证；
- 并发；
- 性能；
- 文档与注释；
- 根因责任层、侵入性和下游失效范围。

Review 数量是指导值而非硬上限：T1 为自审加独立通用 Review；T2 通常增加 1–3 个专项；T3
通常增加 2–5 个专项。正确性需要时允许超过预算，但必须记录成本理由。

`review.aggregate` 按稳定指纹、证据和失败路径去重。它不得以多数票裁决；冲突发现必须回到可运行探针、
权威规格或最早拥有数据与不变量的责任层。最终 diff 变化后，旧选择回执、Review 回执和完成证据全部失效。

## 7. Heavy/Forensic 模块

Quality Playbook 和 Trail of Bits Skills 是 Heavy 候选来源；其中可能适配的深度需求包括规格审计、
C/C++ 安全审查、CodeQL/Semgrep 和类似流程。只有锁定来源、逐模块映射和行为证据均通过后，Catalog 才能
把具体能力标记为 supported。普通 Deep 任务也不得自动运行完整 Forensic 流程。

触发规则：

- “全面 Review”等模糊表达：只推荐并展示时间、Token、文件写入和工具风险；
- 用户明确确认“启用 Forensic 深度审查”：才允许初始化依赖并运行；
- 没有精确确认：零下载、零执行、零目标项目写入。

Heavy 任务在隔离工作树中运行，默认输出到：

```text
.selfworkflow/runtime/forensic/<run-id>/
```

不得读取凭据，不得直接发布结果或修复。需要进入正式仓库的报告、测试或修复必须通过普通 Review、Verify
和用户已有修改保护流程。

## 8. Git 依赖与远程同步

### 8.1 布局

父仓库使用 Git Submodule 保存外部来源身份：

```text
dependencies/
  upstream/
    superpowers/                  # 官方 Superpowers 基线
    openspec/                     # OpenSpec
    tea/                          # BMAD Test Architecture Enterprise
  heavy/
    quality-playbook/             # 显式 Forensic 才初始化
    trailofbits-skills/           # 选择性安全/测试专项能力
  locks/
    <module>.lock.yaml            # URL、commit、tree/hash、许可和适配证据
```

官方来源：

- [obra/superpowers](https://github.com/obra/superpowers)
- [Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec)
- [bmad-code-org/bmad-method-test-architecture-enterprise](https://github.com/bmad-code-org/bmad-method-test-architecture-enterprise)
- [andrewstellman/quality-playbook](https://github.com/andrewstellman/quality-playbook)
- [trailofbits/skills](https://github.com/trailofbits/skills)

具体支持状态只由实际锁定 commit、许可证检查、适配器测试和真实行为证据决定。仓库知名或可克隆不等于
SelfWorkFlow 已支持。

### 8.2 Clone、Push 与 Pull 语义

父仓库只提交 `.gitmodules`、Gitlink 和锁文件，不复制外部完整历史。因此：

- 可以把依赖身份随 SelfWorkFlow 分支提交并 push 到 `origin`；
- 推荐先执行普通、非递归 `git clone`，再由一键安装器按 Profile 使用明确的子模块 pathspec 初始化；
- 禁止文档和安装器把无 pathspec 的 `git clone --recurse-submodules` 作为默认入口，因为它会下载 Heavy；
- 默认一键安装只初始化用户首次配置选择的普通依赖；Heavy 子模块保持未初始化；
- 父仓库 `git pull` 得到新的 Gitlink 后，安装器执行 `git submodule sync` 和按 Profile 的
  `git submodule update --init -- <allowed-paths>`，使本地目录切换到父仓库锁定版本；
- 单纯 `git pull` 不承诺把外部上游追到最新 commit；这是刻意的供应链保护。

上游升级使用独立命令：

```text
Update_SelfWorkFlow_Dependencies.bat
  -> fetch selected upstream
  -> show old/new commit, dirty state, license and hash delta
  -> run adapter/behavior tests
  -> update gitlink and lock
  -> leave an ordinary parent-repo diff for Review and commit
```

只有父仓库提交并 push 新 Gitlink 后，其他机器的 pull 才会取得同一版本。禁止安装器在普通 pull/install
期间静默执行 `submodule update --remote`。

### 8.3 本地定制来源

Superpowers 或其他模块允许用户在首次配置时选择：

- 父仓库锁定的官方 Submodule；
- 已存在的本地路径或本地 fork。

本地来源必须报告路径、commit、dirty 状态和文件 hash。dirty 时询问用户使用当前 dirty 内容还是先自行
提交；用户批准后可使用，但支持证据绑定实际内容 hash。父仓库不会把该本地目录误作为自身内容提交。

### 8.4 安全规则

- Clone 后不自动执行上游脚本、Hook、包管理器或 Skill 指令；
- 安装前先检查来源 URL、commit、文件清单、许可证、敏感文件和可执行入口；
- 锁文件与 Gitlink 不一致时 fail closed；
- 子模块位于 Gitlink commit 的 detached HEAD 是正常状态；只有 dirty、HEAD 与 Gitlink 不匹配、URL 漂移、
  非预期 branch 配置或锁文件不一致时才停止更新并输出日志；
- 不提交 token、缓存、运行日志、上游生成物或用户项目材料。

## 9. 失败处理

优先级固定为：

```text
protected gates
> project mandatory
> explicit user selection
> deterministic routing
> bounded semantic supplement
> context/execution cost
```

Primary、Gate 或唯一风险覆盖能力不可用时阻塞。存在独立冗余覆盖的可选模块失败时，可以继续，但必须：

- 标记对应 coverage 为 `unverified`；
- 记录失败原因和残余风险；
- 不把未执行模块写成已通过；
- 在完成报告中给出人工验证方法。

失败必须回到最早拥有数据和不变量的责任层，不用下游补偿掩盖上游错误。相同 failure fingerprint 在输入、
diff 和证据均未变化时只允许有界重试。

## 10. 支持状态

第一阶段以 Codex CLI/Desktop 为完整实现目标。只有真实行为测试通过后才能标记 supported。

- Codex：完成 Schema、Resolver、Host、安装器和真实行为测试后可升级状态；
- Claude Code、Cursor、OpenCode：先提供适配入口，真实行为测试前为 unverified；
- GitHub Copilot：仅提供 Instructions 兼容层；
- OpenSpec、TEA、Quality Playbook、Trail of Bits：锁定和契约测试不等于真实执行支持；
- CodeGraph、Serena/clangd、DebugMCP、C++ Heavy Provider：只能按“能力 × 操作 × 平台 × Adapter 版本”
  分别升级支持状态；本地路径存在、工具可启动或上游热度均不等于受支持；
- C7OpenWiki：本轮不修改，保持独立适配任务。

## 11. 验收策略

### 11.1 Schema 与路由

- V2 兼容边界和 V3 拒绝未知字段；
- 任务原型 × C/R × T0–T3 路由矩阵；
- OpenSpec、TEA、Review 专项模块的正触发、误触发、冲突和组合；
- 低置信度但不改变关键路由时不打断用户；
- 最终信号只能升级测试等级。

### 11.2 延迟选择器

- 只能选择 eligible 子集；
- 集合外请求生成 `nextStageRequest`；
- 选择回执绑定 plan、attempt、输入 hash 和策略 hash；
- Selector 通过注入的只读 ArtifactPort 运行；单元测试使用 EffectPort spy，断言安装、网络、进程和写入调用均为零；
- Host 生成内容寻址的 `ModuleLoadTrace`，记录实际读取的模块 ID、source hash 和字节数；Heavy 未选择场景
  机械断言轨迹中不存在 Heavy 模块。

### 11.3 Test 与 Review

- T1/T2/T3 最低验证要求；
- 每个 T3 技法的一对一触发、误触发和“不会全部启用”；
- Review 去重、证据冲突、根因归属和非多数票裁决；
- 唯一覆盖失败阻塞，冗余失败只产生显式残余风险；
- 修正 diff 后旧回执失效。

### 11.4 Git 与安装器

- 在临时 bare Git 远端和启用 `GIT_ALLOW_PROTOCOL=file` 的离线测试中，普通 clone 后 Heavy 路径未初始化；
- Profile 初始化、离线失败、URL 漂移、hash 不一致和 dirty 冲突；
- install/update 的 dry-run、幂等、失败日志和回滚；
- 父仓库更新 Gitlink 后可在另一临时 clone 中同步到相同 commit；
- 上游升级不会在普通 pull/install 中自动发生；
- 官方、本地 clean、本地 dirty 三种来源选择。

### 11.5 Forensic 隔离

- 未确认测试使用 Git/Process/FileSystem spy，断言零 clone、零进程、零目标项目写入；
- 确认后对目标仓库和 runtime 目录做执行前后 manifest/hash 对比，只允许临时工作树和 runtime allowlist 变化；
- 凭据访问必须由 Host 沙箱或文件访问审计证明；宿主无法拦截或记录时，本项保持 `unverified`，不得宣称
  “未读取凭据”；发布 API 使用拒绝型 test double，断言没有调用；
- 选定产物重新进入普通 Review/Verify。

### 11.6 完成条件

- 聚焦单元和集成测试通过；
- 安装器在全新临时 clone 中通过；
- 至少一条固定 Codex CLI/Desktop 场景生成可保存的 planHash、diffHash、SelectionReceipt、StageResult 和
  ModuleLoadTrace；通过 oracle 同时校验 Schema、预期模块集合、禁止副作用和完成 Gate；
- 最终完整 diff 的独立 Review receipt 必须包含不同 context/agent identity、最终 diff hash、结构化 findings
  和验证结论；同一上下文回退时标记 independence=unverified；
- 显式 Grill-me 后的 Brainstorming Review 必须创建 `fork_context=false` 的独立 SubAgent，只传入规范化设计
  摘要并绑定 `inputSummaryHash`、`designHash`、`reviewerPolicyHash` 和 Host 可提供的 identity attestation；宿主
  不支持时必须先暂停取得用户授权，且同一 Agent Review 不得标记为 independent；
- 不能执行的外部能力保留 `unverified`，并记录原因和人工验证方法。
