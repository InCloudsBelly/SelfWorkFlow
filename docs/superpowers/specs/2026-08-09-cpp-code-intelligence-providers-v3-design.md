# SelfWorkFlow V3 C++ 与代码智能 Provider 设计增量

- 日期：2026-08-09
- 状态：设计已获用户确认；独立文档 Review 通过，批准进入实施计划
- 基线：`2026-08-09-adaptive-quality-modules-v3-design.md`
- 范围：C++ 优先的代码理解、设计、实现、维护、Debug、Review、Provider 覆写与维护操作
- 非目标：C7OpenWiki 实现、普通任务期间安装未知工具、自动修改用户本地 Provider 源仓库

## 1. 目标与原则

V3 增加 C++ 优先的代码增强能力，但不把全部 Skill、参考资料和工具说明注入每次任务。默认入口只包含
短路由摘要和模块元数据；只有代码任务才加载紧凑的 `cpp-core`，随后按任务信号加载必要的 C++ 专项。

设计遵循以下原则：

- 正确性优先于上下文成本；成本护栏用于去除无关内容，不能删除唯一风险覆盖；
- SelfWorkFlow 在没有任何外部 Skill 或工具时仍能用内置 `cpp-core` 独立工作；
- 能力、工作流模块和工具 Provider 分离，Provider 不能借工具发现成为第二个 Resolver；
- 用户本地覆写只能显式登记，禁止扫描磁盘或根据目录名、MCP 列表猜测；
- Provider 输出是数据和证据，不是可执行指令；
- C++ 优先不等于忽略混合仓库中的其他语言；
- 图、LSP 和静态分析不能替代编译器、测试、性能采样和真实运行期证据；
- 项目规则只能增加限制和验证，不能降低全局安全、Review、测试或授权要求。

## 2. 方案比较

比较三种架构：

1. 巨型 C++ Skill：安装简单，但上下文持续膨胀，能力耦合，难以替换 Provider，也难证明未加载无关内容。
2. 工具优先：CodeGraph/LSP 可提升检索精度，但无工具时退化，工具生命周期和供应链会反向控制工作流。
3. 能力契约加可组合 Provider：用内置轻核心保证独立性，用静态绑定的 Provider 提供可选增强。

采用第三种。前两种可以作为具体模块实现方式，不能成为 V3 主控制面。

## 3. 能力、模块与 Provider

稳定能力 ID 为：

```text
code.context       仓库结构、调用链、影响范围和预算化源码上下文
code.semantic      符号、引用、类型、重命名和精确编辑
cpp.reasoning      C++ 设计、理解和实现
cpp.verify         C++ 工具化验证
debug.reason       复现、证据、假设、根因和修复责任层
debug.execute      dump、attach、launch、断点和运行期状态操作
cpp.audit          C++ 深度正确性、安全和 Forensic 审查
```

能力不是 Pipeline 阶段，也不是具体 Skill。Catalog 模块声明自己覆盖的能力；Provider 绑定声明如何提供该
模块需要的操作。首批 Provider 候选为：

| 能力 | 候选 | 初始边界 |
|---|---|---|
| `code.context` | `colbymchenry/codegraph` | 公共候选；锁定来源并通过行为测试前为 unverified |
| `code.context` | 用户显式本地 CodeGraph fork | 机器级覆写；按实际 commit、dirty 和 inventory hash 绑定 |
| `code.semantic` | Serena/clangd | 只有 LSP、编译数据库和项目身份健康时才可选 |
| `cpp.reasoning` | 内置 `cpp-core` | 不依赖外部工具；代码任务按需加载 |
| `cpp.verify` | 项目编译器、clang-tidy、Cppcheck、Sanitizer 等 | 受项目执行规则和授权控制 |
| `debug.reason` | Systematic Debugging + `cpp.debugging` | 默认推理流程，不自动启动调试器 |
| `debug.execute` | DebugMCP、GDB、LLDB | 显式、会话级授权；按操作拆分风险 |
| `cpp.audit` | Trail of Bits c-review/Trailmark、Joern | Heavy；显式确认、隔离、锁定来源 |

上游热度只用于进入候选池，不能产生支持证据。外部内容通过 Adapter 或锁定 Git 依赖接入；不得在普通
任务中联网安装。

## 4. `cpp-core` 与专项路由

`cpp-core` 安装时始终包含，但非代码任务只看到短路由摘要。只有代码任务加载其共同不变量正文：

- 生命周期、所有权、RAII、值语义和移动语义；
- 未定义行为、边界、整数、别名、迭代器和异常安全；
- 类型、接口、状态不变量、错误路径和可测试性；
- 并发、ABI、性能和工具链风险的识别入口。

专项模块按信号选择：

```text
cpp.ownership       生命周期、资源、指针和引用
cpp.type-system     模板、Concept、重载、推导和元编程
cpp.concurrency     线程、锁、原子、内存序和异步
cpp.abi             ODR、布局、虚表、导出、序列化和兼容
cpp.performance     分配、缓存、拷贝、SIMD 和复杂度
cpp.safety          UB、整数、边界、别名、迭代器和异常
cpp.build           编译、链接、宏、条件编译和工具链
cpp.debugging       Native Crash、堆栈、符号和 Sanitizer
cpp.engine.unreal   UBT/UHT、UObject、模块、线程和渲染边界
```

`cpp.engine.unreal` 必须区分 Target、Platform、Configuration、unity build、PCH、生成头、MSVC 扩展、
反射/GC、Game/Render/RHI 线程、模块 ABI 和序列化兼容性。clangd 或普通 AST 结果不能默认代表 UE 的真实
构建语义。

初始路由倾向：

| 任务 | 默认能力 |
|---|---|
| 大型 C++ 仓库阅读 | `code.context` |
| 精确符号、引用或重命名 | `code.semantic` |
| C++ 行为设计或实现 | `cpp.reasoning` + 命中的专项 |
| C++ Bug/Crash | `debug.reason` + `cpp.debugging` |
| 普通 C++ Review | 最终 diff 命中的 C++ Review Lens |
| 高风险内存、安全或复杂并发 | 推荐 `cpp.audit`，用户确认后启用 |
| 真实运行期调试 | 推荐 `debug.execute`，授权后启用 |

## 5. Provider 类型与关闭契约

Provider 类型为：

```text
prompt-skill
mcp-provider
cli-provider
reference-pack
agent-native
```

V3 新增关闭 Schema：

```text
schemas/v3/provider-descriptor.schema.json
schemas/v3/provider-local-config.schema.json
schemas/v3/provider-binding-snapshot.schema.json
schemas/v3/provider-support-matrix.schema.json
schemas/v3/provider-source-identity.schema.json
schemas/v3/provider-project-state-receipt.schema.json
schemas/v3/provider-operation-plan.schema.json
schemas/v3/provider-approval-receipt.schema.json
schemas/v3/provider-operation-receipt.schema.json
schemas/v3/provider-query-plan.schema.json
schemas/v3/provider-query-receipt.schema.json
schemas/v3/provider-mutation-evidence.schema.json
schemas/v3/workspace-fingerprint.schema.json
schemas/v3/design-review-summary.schema.json
schemas/v3/review-fallback-authorization.schema.json
schemas/v3/review-independence-receipt.schema.json
```

`ProviderDescriptor` 至少声明：

```text
providerId / kind / capabilities[]
sourceIdentityRef / license / adapterRef / adapterHash
operations[] / supportMatrixRef
dataBoundary / remoteSourceTransfer
```

每项 operation 声明：

```text
operationId / triggerLevel / risk / sideEffects
ownershipDomain / mutationTargets[]
argvTemplate / cwdPolicy / envAllowlist / networkPolicy
lockScope / timeout / outputLimit
preconditions / verification / rollback
```

`ProviderSourceIdentity` 是 tagged union，只允许以下一种身份：

```text
git-tree                 remote URL / commit / tree hash / dirty inventory hash
binary-or-package-build  package identity / version / integrity / executable hash / build identity
service                  endpoint identity / protocol / server attestation / data boundary
host-native              host capability / host version / attestation
```

本地绝对路径只存在于机器配置，不进入共享身份工件。支持状态通过关闭的 `ProviderSupportMatrix` 按
“能力 × 操作 × 平台 × Adapter 版本 × SourceIdentity”记录：

```text
state: supported | unverified | unsupported | needs-revalidation
observedAt / validUntil / behaviorEvidenceRef / matrixHash
```

只有 `supported` 记录可以自动进入 eligible 集合。`unverified` 只有用户为当前任务显式批准一次性受限使用后
才能成为显式候选。Host 先从不含例外授权的 base request 计算 `baseRequestHash`，再从 baseRequestHash、精确
SupportMatrix entry/hash、允许的 capability/operation/platform/adapter、任务范围和有效期计算
`selectionExceptionSubjectHash`；`provider-selection-exception` ApprovalReceipt 绑定该前置 hash。Approval hash
随后进入 ProviderBindingSnapshotHash 和最终 requestHash，不形成自引用；执行结果继续标记 unverified。`unsupported` 和
`needs-revalidation` 不可选择。不给整个 Provider 一个笼统的 supported。

## 6. 静态绑定与回退

Provider 身份和项目动态状态必须分离。Host 在 Resolver 前只从已登记机器配置、锁定 Adapter 和持久支持证据
生成静态 `ProviderBindingSnapshot`；该步骤不扫描路径、不启动 Provider 进程。ResolveRequest/PlanGraph V3
增加：

```text
providerPreferenceSetHash
providerBindingSnapshotHash
executionPolicySnapshotHash
eligibleProviderBindings[]
selectedProviderBindings[]
```

Provider 绑定是封闭元组：

```text
moduleId / providerId / capabilityId / operationId
adapterHash / sourceIdentityHash / supportMatrixEntryRef / supportMatrixEntryHash
requirementMode: required | preferred
```

Selector 只能选择 PlanGraph 中已声明的完整元组，不能运行时发现路径、拼接自由 CLI 参数或切换未知 MCP。
动态查询参数必须进入关闭的 ProviderQueryPlan，由 Adapter 按绑定模板渲染。计划外能力只能返回
`nextStageRequest`，由 Host 重新生成能力快照和 PlanGraph。

执行顺序固定为：

```text
machine config + source/adapter/support evidence
-> static ProviderBindingSnapshot
-> Resolver and immutable PlanGraph
-> Host obtains bounded ProviderProjectStateReceipt for the next eligible binding
-> state/capability gate
-> bounded selector consumes typed receipt, without starting processes
-> ProviderQueryPlan or ProviderOperationPlan
-> execution and content-addressed receipt
```

`ProviderBindingSnapshotHash` 进入 planHash；它只包含身份、Adapter、允许操作和支持证据。动态
`ProviderProjectStateReceipt` 包含索引 revision、health 和 workspace identity，不进入 planHash，只控制依赖它的
查询与下游工件新鲜度。静态身份变化必须 supersede PlanGraph；普通状态时间戳变化不重建计划。

Host 只可自动取得经行为测试证明为 `automatic-readonly` 的状态 Receipt，并按优先级惰性检查候选。状态检查
有写入、启动服务或联网副作用时，必须先走 ProviderOperationPlan；未知状态不能被自动解释为 ready。

优先级为：

```text
本次任务显式指定
> 项目引用
> 用户机器默认
> V3 锁定公共 Provider
> 可报告的内置能力
```

本次显式选择默认为 `required`，失败不回退。项目、机器和公共默认默认为 `preferred`；允许回退时必须生成
SelectionReceipt、记录 coverage 差异并在完成报告展示，不能静默发生。

项目配置只能引用机器配置中已批准的稳定 `providerId`，不能提供可执行路径、任意 argv、远程地址或把
`manual-only` 提升为自动执行。

## 7. 本地覆写与 Windows 路径

安装器不得扫描磁盘寻找本地覆写。首次安装集中询问用户是否存在本地版本；默认选择“没有本地覆写”。
用户提供路径后才执行只读检查并展示来源、commit、dirty 状态、inventory hash、许可证和入口。

本机配置位于：

```text
%LOCALAPPDATA%\SelfWorkFlow\config\providers.local.yaml
```

共享 Catalog、项目配置、生成的薄 Agent 入口和可分享日志不得包含本地绝对路径。机器级快照可以绑定规范化
路径 hash，但公开摘要只记录 Provider ID 和脱敏身份。

Windows 路径必须是规范化绝对路径；拒绝 drive-relative、ADS、设备路径、尾随点/空格和未批准的 reparse
跳转。YAML 生成器负责安全序列化，不能要求用户手工拼接转义。

SelfWorkFlow 永不对用户自有 Provider 源仓库执行 `git pull`、切分支、提交、清理或 upgrade。源码变化后
进入 `needs-revalidation`。`upgrade` 只适用于 `%LOCALAPPDATA%` 下由 SelfWorkFlow 管理的安装和 Adapter。

## 8. Provider 生命周期与维护触发

标准操作为：

```text
inspect
initialize-project-state
sync-project-state
rebuild-project-state
upgrade-managed-install
repair-managed-state
unregister-provider
uninitialize-project-state
remove-managed-install
```

不使用含义模糊的 `remove`。每项操作的触发等级为：

- `automatic-readonly`：该具体操作经行为测试证明零写入、零联网且有界时才可自动执行；
- `recommend-before-use`：检测到确定问题时推荐并取得授权；
- `manual-only`：只有用户明确要求才能执行。

操作名称不产生信任；名为 `status` 的命令如果启动服务、写缓存或联网，就不能标为 automatic-readonly。

维护是独立管理事务，不在 bounded selector 内偷偷执行。普通任务消费静态 ProviderBindingSnapshot 和动态
ProviderProjectStateReceipt；发现需要维护时产生显式维护请求。维护完成后更新对应工件：

- Adapter、来源或能力身份变化：supersede PlanGraph；
- 索引 revision 或工作区内容变化：只使依赖旧 revision 的查询、选择、Review 和 Verify 工件失效；
- 普通 status 时间戳变化：不重建整张 PlanGraph。

ProviderOperationPlan 必须绑定 Provider、操作、规范化目标、Adapter 渲染 hash、argv hash、cwd、环境白名单、
网络策略、锁、超时、输出上限和 mutationTargets。mutation target 是关闭类型：

```text
exact-file | directory-subtree | managed-state-root | process | service
canonicalTargetHash / containmentRootHash / recursion / reparsePolicy
```

需要确认的操作使用独立 `ProviderApprovalReceipt`，至少绑定：

```text
subjectKind: operation-plan | query-plan | provider-selection-exception
authorizationSubjectHash / decision=approved
confirmationSource / optionalActorAttestationRef
scope / targetHashes[] / issuedAt / expiresAt
nonce / revocationState / receiptHash
```

`authorizationSubjectHash` 总是从不含 approval 引用和最终对象 hash 的 canonical subject body 计算。三种
subject 的附加绑定为：

- `operation-plan`：`operationAuthorizationSubjectHash`，覆盖除 approval 引用和最终 operationPlanHash 外的完整计划；
- `query-plan`：`queryAuthorizationSubjectHash`，覆盖 typed input、预算、副作用和除 approval 引用、最终
  queryPlanHash 外的完整计划；
- `provider-selection-exception`：`selectionExceptionSubjectHash`，覆盖 baseRequestHash、SupportMatrix
  entry/hash、受限 capability/operation/platform/adapter 和任务范围。

计算顺序固定为：

```text
canonical subject body without approval/final hash
-> authorizationSubjectHash
-> ProviderApprovalReceipt and approvalReceiptHash
-> final OperationPlan / QueryPlan / ProviderBindingSnapshot
-> final operationPlanHash / queryPlanHash / requestHash
```

`confirmationSource` 是防误操作证据，不伪称身份认证。执行前重新校验 Receipt 未过期、未撤销且目标未漂移；
OperationReceipt 或 QueryReceipt 引用 approval，并使用 tagged `ProviderMutationEvidence` 对账实际副作用：

```text
filesystem-manifest     路径、类型、size/hash、reparse identity 的 before/after
managed-state-manifest  Provider 状态对象、revision 和内容 identity 的 before/after
process-state-delta     process identity、execution state、breakpoint、memory/register observation/mutation
service-state-delta     service identity、lifecycle、endpoint/session 和持久状态变化
```

每类 Evidence 绑定对应 mutationTargetHash，实际变化必须是声明目标和允许动作的子集。Adapter 或 Host 无法观察
并证明某类 mutation 时，要求该证据的操作必须阻塞；如果该证据只是冗余验证，则保持 unverified 并报告残余
风险。Receipt 不能复用于变化后的命令、项目或目标。

所有 MutationEvidence 共享关闭 envelope：

```text
subjectKind: operation-plan | query-plan
subjectPlanHash / executionNonce / attemptRef
providerBindingHash / canonicalProjectRootHash
observedAt / preStateIdentity / postStateIdentity
mutationTargetHash / payloadHash / evidenceHash
```

OperationReceipt/QueryReceipt 必须与 envelope 的 plan、execution nonce、attempt、Provider 和项目身份完全一致，
并验证 observedAt 位于本次执行窗口。旧 attempt、旧 nonce 或其他执行产生的 Evidence 一律拒绝。

项目增量自动同步需要机器配置对 `(providerId, canonicalProjectRoot)` 保存一次性、可撤销授权。项目仓库只能
提出请求，不能自行授权本机命令执行。

锁使用 provider+project 粒度 lease，至少绑定 owner PID、process start time、host/boot identity、heartbeat
和 operation nonce。Windows 上不能只凭 PID 不存在就判定 stale lock。

## 9. CodeGraph 适配边界

CodeGraph 默认操作映射：

| 操作 | 策略 |
|---|---|
| `status` | 只有经适配器证明为只读时，才可在候选预执行检查中自动执行 |
| 正常查询 | 优先禁用 auto-sync 并消费既有 state receipt；不能禁用时声明为 local-write 查询并使用机器级项目授权、QueryPlan 和 Receipt |
| `sync` | 索引明确过期、watcher 关闭或用户要求时推荐；可使用机器级项目授权 |
| `init` | 当前项目未初始化时推荐，确认后执行 |
| 完整重建 | manual-only，展示文件范围、排除规则和预计成本 |
| `upgrade --check` | Provider 管理或用户明确检查时只读执行 |
| `upgrade` | 用户自有源禁用；仅管理安装可执行 |
| `unlock` | 机械证明 stale lock 并确认目标后执行 |
| `uninit` | 破坏性确认，绑定实际索引目录 |

普通查询使用关闭的 `ProviderQueryPlan`，不能把自然语言直接拼接成 argv 或 MCP 参数。QueryPlan 绑定：

```text
plan/provider/adapter/binding identity
operationId / typedInputSchemaRef / typedInputHash
adapterRenderHash / canonical workspace root
projectStateReceiptHash / workspaceFingerprintHash
query/return byte budget / call limit / timeout
sideEffects / mutationTargets / queryAuthorizationSubjectHash / approvalReceiptRef
queryPlanHash
```

Adapter 只把通过 Schema 的 typed input 渲染成固定命令模板或 MCP tool input；Host 校验渲染结果与
adapterRenderHash。QueryReceipt 绑定 `queryPlanHash`，并必须包含：

```text
provider/adapter/source identity / projectStateReceiptHash
canonical workspace root / workspaceFingerprintHash
index revision / extraction version
index completeness / pending files / parse failures
indexing and exclusion configuration hash
query / returned files / byte ranges / content hashes
truncated / heuristic provenance
pre-query and post-query workspace identity
actual side effects / mutationEvidenceRefs[]
```

`WorkspaceFingerprint` 不是路径列表摘要。它规范化绑定 Git HEAD tree、Git index、相关 dirty/untracked 文件的
路径、状态、大小与内容 hash、索引/排除配置、ignored/generated 边界和查询依赖闭包。查询前后重新计算同一
scope；任何依赖内容变化都会使 Receipt 失效。

新鲜度分两级：

- `source-content-fresh`：返回文件未截断，逐文件内容 hash 与当前文件一致，目标无 pending；这些源码可视为
  已读取；
- `relationship-fresh`：Provider 还必须给出完整查询依赖闭包，且该闭包的 WorkspaceFingerprint 与索引 revision
  一致；只有这一级才能把结构关系作为当前工作区证据。

Provider 无法给出依赖闭包时，调用链和影响分析保持 unverified，不影响对已核对返回源码的读取结论。启发式
边始终保留 provenance，不能作为 ABI、并发、内存安全、模板实例化、宏展开、条件编译、UHT 生成代码或运行期
性能的唯一证明。

CodeGraph 的 auto-sync 不能绕过维护授权。如果 Adapter 能禁用 auto-sync，过期状态先走独立
`sync-project-state`。如果当前版本无法禁用，查询操作必须声明本地索引写入、限制 mutationTargets，并引用
机器级 `(providerId, canonicalProjectRoot)` 授权；它不得标为 `automatic-readonly`。持续授权减少重复询问，
但每次仍生成 QueryPlan、QueryReceipt 和实际索引变更对账。

用户可将本地 `E:\kg-code-graph` 显式配置为机器级 `code.context` 首选 Provider；共享仓库只保存示例和契约，
不保存该路径、索引或个人状态。

## 10. Pipeline 映射与上下文预算

能力通过模块映射到阶段：

```text
Discover          code.context / code.semantic
Design            cpp.reasoning / debug.reason
Implement         cpp.reasoning augmenters
Review            selected C++ lenses / cpp.audit
Verify            cpp.verify
Explicit debug    debug.execute 的受限操作槽
```

Provider 的 install、`initialize-project-state`、`sync-project-state`、`rebuild-project-state`、
`upgrade-managed-install`、`uninitialize-project-state` 和 `remove-managed-install` 不进入 Selector；它们走独立
维护事务。

Catalog 记录模块摘要字节数、正文估计成本、参考资料成本、查询次数和输出上限。ModuleLoadTrace 记录实际读取的
模块、source hash、字节数、查询次数和返回字节数。成本预算是可观察护栏，不得因预算删除唯一风险覆盖；超过
预算时记录理由并继续正确性所需的最小闭包。

## 11. Debug 与 Heavy

`debug.reason` 默认遵循 Systematic Debugging，先建立可复现 failure envelope、定位 last-good/first-bad、
区分 root-cause owner 与 detection point，再在最早拥有数据和不变量的责任层修复。

`debug.execute` 拆分为独立操作：

```text
inspect-dump
attach-process
launch-process
control-execution
inspect-state
evaluate-expression
mutate-memory-or-registers
```

每项单独声明权限。attach 也不是只读。进程身份绑定 PID、process start time、映像规范路径与 hash、用户/
会话身份和启动参数摘要；任一身份漂移立即使授权失效。`evaluate-expression` 默认按可执行且可能修改状态处理，
只有 Adapter 能机械限制并证明只读表达式子集时才可降低风险。授权同时绑定项目、调试会话、操作集合和超时；
同一会话内非关键步骤不重复询问。项目禁止构建、运行或 attach 时，Gate 必须拒绝相应操作，不能由 C++ Skill
绕过。

Trail of Bits、Trailmark、Joern 等 Heavy Provider 只有锁定来源、许可、Adapter 和行为证据后才可成为候选；
普通 Review 不自动启用。安全关键、复杂内存破坏或深度审查可以强烈推荐，用户确认后在隔离环境执行。

## 12. 独立 Post-Grill Brainstorming Review

目标 `policyVersion` 为 `2.0.0`，新增受保护规则：

```yaml
id: require-independent-post-grill-brainstorming-review
strength: enforced
gate: design.post-grill-review
evaluator: post-grill-review-independence-v1
reasonCodes:
  - post-grill-independent-review-required
  - post-grill-review-input-invalid
  - post-grill-review-attestation-missing
  - post-grill-review-user-authorization-required
```

显式 Grill-me 完成并确认共同理解后，必须创建新的独立 SubAgent，`fork_context=false`，只传规范化设计摘要、
约束和验收条件，不传 Grill-me 的盘问记录或推理过程。摘要必须符合关闭的
`design-review-summary.schema.json`。Host/Collector 从实际 spawn 参数和发送 payload 计算 summary hash，并生成
ReviewIndependenceReceipt；Agent 自报字段不能升级独立性。Receipt 绑定：

```text
forkContext=false
contextIdentity / agentIdentity / hostAttestationRef
inputMode=summary-only
parentContextImported=false
grillReasoningReceived=false
inputSummaryHash / designHash / reviewerPolicyHash
fallbackAuthorizationRef / independence / receiptHash
```

Agent 自报身份不是身份认证。只有 Host attestation 可以把结果标记为 independent；没有 attestation 时即使
工具调用声明 `fork_context=false`，也如实标记 `independence=unverified`。宿主不支持独立上下文时必须暂停并
取得用户授权，才可由同一 Agent 开启新的结构化 Review；该结果同样固定为
`independence=unverified`，不得事后补签或声称 independent。

`ReviewFallbackAuthorization` 是独立 typed 工件，绑定 designHash、reviewerPolicyHash、降级原因、精确
`fallbackMode`、confirmationSource、issuedAt/expiresAt、nonce 和 revocationState；`fallbackMode` 是关闭
union：`independent-context-without-attestation | same-agent-structured-review`。它是
防误操作授权，不伪称用户身份认证。Evaluator 真值表固定为：

| 独立上下文 | Host attestation | 有效 fallback authorization | Gate 结果 |
|---|---|---|---|
| 是 | 是 | 不需要 | 通过，`independence=independent` |
| 是 | 否 | 否 | 暂停，原因 `post-grill-review-attestation-missing` |
| 是 | 否 | 是，且 mode 匹配 | 继续，`independence=unverified` |
| 否 | 任意 | 否 | 暂停，原因 `post-grill-review-user-authorization-required` |
| 否 | 任意 | 是，且 mode 匹配 | 继续同 Agent 结构化 Review，`independence=unverified` |

Fallback authorization 过期、撤销、designHash 或 reviewerPolicyHash 漂移时一律无效。

该受保护规则的实现属于破坏性工作流变更，必须同时具备 owner-confirmation、SemVer major、独立 Review 和
行为测试工件；普通项目规则和 Skill 不得覆盖。

## 13. 安装与管理入口

`Install_SelfWorkFlow.bat` 首次安装集中询问 Provider 本地覆写，不扫描默认路径。它展示来源、commit、dirty、
hash、许可证、预计写入和冲突，确认后写机器配置。

后续使用：

```text
Manage_SelfWorkFlow_Providers.bat
```

它提供 list、configure、doctor、status、initialize、sync、rebuild、update-check 和日志查看。底层复用 SelfWorkFlow
已有的事务、锁、计划、确认、回滚和日志实现，不创建第二套非原子配置路径。

日志只记录命令 hash、退出码和脱敏摘要，不记录源码正文、完整环境、凭据、Debugger 内存或本地绝对路径。

## 14. 支持状态与失败语义

外部 Provider 的某个 SupportMatrix 维度达到 supported 必须同时满足：

- 对应 tagged source identity：Git tree、binary/package build、service 或 host-native attestation；
- 适用时具备许可证、完整性和来源锁；
- ProviderDescriptor 与 Adapter 契约测试；
- 正触发、误触发、冲突、组合和上下文轨迹测试；
- 不可用、漂移、过期索引、失败和权限拒绝路径；
- 对应能力、操作、平台和 Adapter 版本的真实行为证据；
- 至少一个受支持 Agent 的原生验收。

显式 required Provider 失败时暂停，不回退。preferred Provider 失败时只有计划内候选可回退，必须留下
SelectionReceipt、coverage 差异和完成报告。任何未执行能力均不能写成通过。

## 15. 验收策略

### 15.1 Schema 与路由

- Selector 永远不能选择 PlanGraph 外的 module/provider/operation；
- 只有 supported SupportMatrix entry 可自动 eligible；unverified 必须显式一次性授权；
- 优先级矩阵覆盖显式、项目、机器、公共、内置及 unavailable、drifted、conflict、fallback；
- C++ 专项执行正触发、误触发、冲突和组合测试；
- 非 C++ 与非代码任务不读取 `cpp-core` 正文或专项内容；
- ModuleLoadTrace 证明未命中的 C++ 与 Heavy 模块未加载。

### 15.2 Fake Provider 与维护

- Fake Provider 覆盖全部生命周期、超时、崩溃、回滚、并发、stale unlock 和权限拒绝；
- Process/FileSystem/Network EffectPort spy 证明未授权路径零写入、零安装、零未知进程、零联网；
- OperationPlan/QueryPlan 漂移、argv/MCP 参数注入、cwd 逃逸、环境注入、路径异常和过期 approval 被拒绝；
- ApprovalReceipt 的过期、撤销、目标漂移和 actual mutation 越界被拒绝；
- operation/query/provider-selection-exception 三种 approval subject 的交叉复用被拒绝；
- authorization subject 到 approval 再到最终 hash 的计算顺序可复现且不存在自引用；
- filesystem、managed-state、process 和 service MutationEvidence 分别执行 subset 校验；不可观察的 required
  mutation 被阻塞；
- MutationEvidence 的 stale、跨 attempt、跨 nonce、跨 Provider、跨项目复用被拒绝；
- Provider 管理入口 dry-run、确认、幂等、失败日志、恢复和回滚通过。

### 15.3 新鲜度与 CodeGraph

- 覆盖 dirty/untracked 内容 hash、查询依赖闭包、查询期间修改、排除规则、解析失败、截断、索引滞后和并发 sync；
- auto-sync 可关闭和不可关闭两条路径分别验证，后者必须产生受限本地写入 Receipt；
- 只有满足 QueryReceipt 完整条件的源码可以替代重复 Read；
- 启发式关系不会升级成高风险 semantic proof；
- 本地覆写优先但不写入共享配置，源码变化后进入 needs-revalidation。

### 15.4 C++ 与 Unreal

- 小型合成仓库覆盖 ownership、type-system、ABI、concurrency、performance 和 safety；
- Native Crash 选择 `debug.reason` 和 `cpp.debugging`，不自动启动真实调试器；
- UE 原生验收覆盖 UBT/UHT、unity/PCH、多 Target/Platform/Configuration、UObject 生命周期和线程归属；
- 项目禁止编译、运行或 attach 时，相关操作被 Gate 拒绝；不能执行的项目级验证保持 unverified。

### 15.5 独立 Review

- 行为测试创建 `fork_context=false` SubAgent，只传 canonical summary；
- 验证 Host/Collector 从实际 dispatch payload 生成新 context、摘要与设计 hash、Reviewer policy 和身份凭据；
- Host 不支持独立上下文时先暂停，只有用户授权 Receipt 存在才继续，并保持 independence=unverified；
- 独立上下文但 Host attestation 缺失时同样先暂停；真值表五条路径、fallbackMode 不匹配和 authorization
  漂移全部测试；
- Grill-me 推理过程不会出现在独立 Reviewer 输入中。

### 15.6 原生验收

CodeGraph、Codex、UE 和 Debug Provider 分别保存原生验收记录。Schema、Fake Provider、上游自述或热度不得
替代真实行为证据。无法执行的检查列出原因、风险和人工验证方法，不宣称通过。

## 16. Review 历史与证据边界

本设计历史上先经 Grill-me 形成共同理解，再通过工具调用创建 `fork_context=false` 的 SubAgent 执行只读
Brainstorming Review。该次工具结果认可“能力契约 + Provider + 内置 cpp-core”方向并提出 Provider 静态绑定、
CodeGraph 新鲜度、operation ownership、机械授权、供应链和独立 Review Gate 修正；四项关键行为已由用户按
推荐确认。

仓库当前没有由目标 V3 Host/Collector 签发的 ReviewIndependenceReceipt，因此该历史活动只能记录为
`independence=unverified`，不能作为未来受保护 Gate 的通过工件。本文是否批准进入实施计划以修正后的独立
文档 Review 结论为准。即使文档 Review 通过，也不代表任何 Provider、C++ Skill、维护命令、测试或原生验收
已经可用。

修正后的实际文档经过四轮只读 Review，最终结论为 `Approved`，没有剩余 Critical 或 Important；该结果只证明
设计文档质量，不替代未来 V3 Host 签发的 Post-Grill ReviewIndependenceReceipt。
