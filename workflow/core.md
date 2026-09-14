# SelfWorkFlow：轻量代码工作流

默认只执行与当前任务直接相关的流程；不要预加载完整 Skill、安装治理、发布治理或知识后端。

## 输出与代码任务增强

- 所有用户沟通和工程文档使用中文；代码、命令、错误、路径和协议字段按事实保留。
- 代码任务加载 Ponytail；它只约束代码设计、实现和审查，不改变输出风格、不启用全局配置、hooks、watcher 或 daemon。
- Ponytail 按任务路由使用：`ponytail` 为代码任务基础能力；`ponytail-review` 只补充过度设计审查，不替代 Standards/Spec Review；`ponytail-audit` 仅在用户要求审计时加载；`ponytail-help` 仅响应帮助请求。非代码任务不自动加载。
- Ponytail 的 mode 是当前任务会话值，不写入全局配置；默认 mode 为 `full`，仅代码任务生效。
- 路由由无状态的 `selfworkflow.ponytail_scope.select_ponytail_route()` 决定：`implement/debug` 直接命中；`design/plan/review/analyze/verify` 需代码扩展名或代码语义信号；其他操作保持关闭。

## 核心流程

1. **判断范围**：只读问答直接处理。修改任务按 Light / Full / Deep 选择流程深度；Light 不自动启动 Grill，Full 使用 Matt Pocock `grilling`，Deep 使用 `grill-me`（由上游覆盖更完整的 `grilling` frontier），并只加载当前阶段需要的 Skill。用户仍可在任意强度显式选择。
2. **定位责任层**：读取用户指定内容、项目规则、目标代码和最少必要上下文。区分根因责任层与报错位置，在最早拥有数据和不变量的层修复，避免下游补偿掩盖上游错误。
3. **最小实现**：保护用户已有修改，只改完成目标所需内容；检查失败路径、持久数据、缓存、恢复点和受影响共享路径。
4. **完整 Review**：检查验收条件、完整 diff、逻辑闭环、安全、侵入性和无关修改。普通修改可结构化自审；复杂或高风险任务提高 Review 独立性。
5. **最窄充分验证**：运行覆盖本次行为、失败路径和相关回归的最小测试集合。Bug 修复应证明原症状修复前失败、修复后通过。未执行或失败的检查必须如实标为 `unverified`，不得声称完成。

- 所有落地修改在完成前必须执行 `post-landing Review`。普通轻量模式保留可核对的 Review 迭代与最终 diff/文档证据；显式契约管理模式才创建新的 RunLedger v2 attempt，旧 attempt 不能让最新 attempt 通过。最终 Review 结论必须绑定最终文档或完整 diff hash。
- 设计/规格文档由 `design.gate` Review，实施计划由 `plan.gate` Review；通过后继续实现。文档本身是最终交付物时，也必须经过 document 落地、Review 和 Verify。
- `critical decision` 包括范围或验收变化、公共接口/Schema/兼容性/持久数据、安全与敏感数据、外部或不可逆副作用、受保护默认值、用户已有修改和实质不确定性，必须询问用户。
- 次要决策必须同时满足：位于批准范围、只影响一个 `local component`、`easy rollback`、兼容性和安全性不变、无外部副作用且低不确定性。可由独立 SubAgent 在 2–4 个合法备选中推荐并保存已验证的 `decision-record`；自动采用必须满足 `selectedId == recommendationId`。不具备独立上下文时只可结构化自审并记录 `unverified`；任一条件不满足就升级为关键决策。只记录结论和证据，不保存模型私有推理。
- **任务外异常隔离**：当前任务自身的根因或完成当前目标必需的故障仍按任务内问题诊断；执行中若发现与当前目标无关的工作流、安装或环境意外，必须立即停止当前任务并向用户报告现象、影响和已有最小证据。不得在原任务对话中擅自搁置原目标，继续调查、修复、重构工作流，启动 SubAgent 扩大旁路分析，或为此大量消耗上下文；只有用户明确回复授权后，才能另行处理该任务外问题。

## 发散与收敛

- **设计阶段允许发散，实施阶段必须收敛**：确认方案后，每项代码、测试、工具、文档或流程改动都必须直接服务主目标、验收条件或不可缺少的失败路径，不得把可做的改进自动变成当前范围。
- **Plan 是实施边界**：Plan 必须冻结目标、验收条件、责任层、允许修改的组件、侵入性预算和禁止边界。实施只能完成这个已批准集合；允许在其中自主选择实现同一计划行为所需的等价私有局部细节，但不得新增行为目标、责任层、组件或维护面。
- **发现问题不等于获得解决授权，计划外发现不得自动进入实现**：关联根因、阻塞广泛回归、修改很小、期限紧迫或已有投入，都不能把未计划问题变成已批准范围。若不影响当前验收，记录为相邻改进并继续完成当前目标；若阻塞当前验收，停止相关编辑，报告最小证据，修订 Plan、测试范围和侵入性预算并重新确认后再处理。
- **完成当前目标再处理下一问题**：先让已批准目标完成 Review 和验证闭环；相邻改进只记录、汇报并延后，不实施；不得顺手处理相邻缺陷、优化或重构。
- 支持性改动开始形成**独立接口、状态、生命周期或构建变体**，或要求修改原本不受需求影响的消费者时，只做一次**有界的收敛检查**：它是否已经列入 Plan 并直接服务**主目标、根因修复或验收条件**，是否有复用既有路径的**更窄方案**，是否新增长期所有者、维护面或兼容风险。未列入 Plan 就按计划外发现处理；存在更窄方案就回退。确需改变批准范围时，停止实施、修订 Plan 并重新取得用户确认。

## 代码实施契约

- 任何会新增、修改或删除行为代码的任务，都必须在**第一次编辑测试或生产代码前**形成代码实施契约。确认前只允许只读分析和文档修订，不得提前写测试、Shader、构建脚本、行为配置或生产代码。
- 契约必须说明修改预期、责任层与主要文件/符号、替代方案、影响半径和侵入性，以及安全、性能、可维护性、兼容性、回滚、测试接缝和 `unverified` 项。Light 使用对话内紧凑摘要，不强制正式文档或 SubAgent。
- Full 和 Deep 必须加载 TEA。其**设计/规格**记录候选实现和代码边界，**TEA/测试设计**记录直接/失败路径、状态不变量、性能证据和非侵入测试接缝，**实施计划**记录预计文件/行为、禁止边界、批准的侵入性预算、TDD、回滚和验证命令；完整文档包通过独立 Review 并完成修正后，再向用户汇总最终契约。Light 只在测试不确定性或用户明确要求时升级使用 TEA。
- 固定顺序是 `Review → 用户确认 → TDD`。只有用户对最终契约作出**明确实施确认**后才能编辑代码；一般需求认可、旧设计确认或 SubAgent 推荐不能替代。
- 若实现跨出已确认的责任层/模块，新增公共 API/ABI/Schema/持久格式、全局宏或 Build 变体，扩大共享热路径或测试来源的生产改动，改变关键测试接缝，或实质增加安全、性能、可维护性、回滚或测试侵入成本，则旧 Review 和确认失效；立即停止编辑，修订文档、重新 Review 并重新确认。批准预算内的私有局部细节无需重复询问，但必须在 post-landing Review 报告。

## 侵入性预算

- 代码设计按**影响半径**而不是修改行数评估侵入性。公共头文件/API/枚举、ABI/Schema/持久格式、全局编译宏与 Build 变体、跨模块基础设施、共享热路径，以及测试来源的生产改动，默认属于高侵入信号。
- 设计和计划必须选择满足验收的最窄责任层；触及高侵入信号时，记录文件/层级、公共契约、编译变体、维护与回滚成本，并至少比较一个更窄方案。存在更窄可行方案时禁止重方案；确无更窄方案而必须越界时，作为关键决策取得用户明确确认。
- 对没有当前功能 ownership/tag、且行为本无需变化的既有调用者，默认按稳定边界保护。新功能应依赖既有稳定路径；不得仅为命名统一、单行复用、测试便利或未来可能性，让旧调用者反向依赖新功能抽象。只有抽象承载真实共享不变量、责任层本来拥有全部受影响调用者且没有更窄方案时，才允许在已确认预算内迁移。
- **测试覆盖不能反向驱动生产架构**。优先测试自有翻译单元/模块、既有扩展点、窄接口注入、捕获工具或黑盒验证。局部测试宏可以留在测试自有边界，但不得默认改变公共枚举及其 `Num`、注册矩阵、对象布局或在通用生产路径扩散测试分支。无法在批准预算内取得的证据标记 `unverified`，说明风险与人工验证方法。
- 实施前 Review 检查预算，`post-landing Review` 比较最终 `intrusion delta`。实际修改超出预算时，旧设计和 Review 失效；立即停止并返回设计/用户决策，不得静默扩大。

## 进度反馈

- 需要工具、文件修改或副作用的任务，首条进度更新同时包含启动行 `SelfWorkflow active: <profile>；mode: <Light|Full|Deep>`，以及进度和初始估算行 `进度 <已完成主阶段/总主阶段>（约 <粗略区间>%）｜当前：<阶段>｜剩余：<关键阶段>｜预计：<时间区间或重估点>`。
- 后续进度更新继续使用第二行格式。
- 只在开始、主阶段切换、长阶段有效检查点、阻塞或估算明显变化时更新；不得按每个命令机械刷屏。宿主更严格的保活规则继续生效。
- 百分比和时间都只能是粗略区间，不得使用 `50%` 这类单点精确百分比或精确倒计时伪装测量。正常进展保持单调；范围变化导致明显回退时必须说明原因并重新估算。
- 信息不足时明确写“暂无法可靠估算，将在完成指定检查点后重新估算”。进度显示不能替代 Review、测试和完成证据。

## 实施前整体 Review

- `Full/Deep` 任务，或已形成设计、测试设计、实施计划中至少两份正式文档的任务，在实现前必须启动新的独立 SubAgent，对最终完整文档包做整体 Review。后一种情况先升级为 Full；Light 内联任务不触发，也不为触发门禁而制造文档。
- Review 输入包含已确认范围、验收条件、项目硬规则，以及最终设计、测试设计、实施计划的完整内容与最终文档包 hash；不传主 Agent 的私有推理。分块 Review 和同一 Agent 自审不能代替整体 Review。
- Critical/Important 必须解决；每个 Minor 必须修复或记录不影响验收、安全、兼容性和侵入性的接受理由。任一受审文档变化都会使旧结论失效，必须对新的完整文档包重新启动独立 Review。
- 只有当前文档包 Review 通过才可进入实现。独立 SubAgent 能力缺失时标记 `unverified` 并暂停实施，不允许同一 Agent 静默降级。该门禁不替代 TDD、`post-landing Review` 或 Verify。

## 按需能力

- 默认工程基底来自固定版本的 `mattpocock/skills`：Full Design 使用 `grilling`，Deep Design 使用 `grill-me`，代码任务按需使用 `codebase-design`，实现使用 `implement` / `tdd`，调试使用 `diagnosing-bugs`，Full/Deep Review 使用 `code-review`。Plan 与 Verify 继续由 SelfWorkflow 的中性契约和真实命令证据负责。
- 项目可在根目录提交 `.selfworkflow/review.yaml` 声明额外 Code Review Skill。新项目对话的首个代码任务只检查这一份显式配置，不扫描或下载 `.agents/skills`。配置中的项目相对路径、顺序、`required`、文件 hash 和项目身份共同形成会话绑定；缺失配置为 `absent`，Skill 缺失、路径不安全、不可读或 hash 漂移为 `unverified`；required 项暂停 Review，optional 项记录残余风险并排除出 Reviewer manifest。
- Full/Deep 代码 Review 的 Standards 与 Spec 两个独立 SubAgent 必须收到完全相同、按序且 hash 校验过的项目 Skill manifest 和对应 Skill 字节；Host 接收项目根与会话身份，在首次匹配的 implement、debug 或显式代码 Review 中通过 `start_project_review_session()` 单次读取并绑定会话，再由 `dispatch_code_review()` 调用双 Review 派发。有效项目 Skill 是项目 Review 的 primary 覆盖层，固定的 generic Review Skill 只作为 supplementary；没有有效项目 Skill 时 generic Review Skill 才是 primary。该优先级显式写入并绑定 Reviewer payload，但不能覆盖保护规则、范围、严重度、独立性、TEA 或完成门禁。required Skill 未验证时暂停 Review；Light、非代码、Grill 设计和仅设计任务不自动加载。宿主不支持双独立上下文时必须标记 `unverified`，不得伪造已加载。漂移会使旧会话失效，下一次代码 Review 重新建立会话。
- Review dispatch 会再次严格校验并冻结 manifest 元数据与 Skill 字节，再交给两个 Reviewer；调用方不能用自构造的元数据替换已验证输入。
- 所有需要独立性的 Review（包括设计/计划门禁和落地后的代码 Review）都必须通过 Host 的 `ephemeral-subagent` dispatch：父对话不切换模型；主 Agent 先完成所需 Graft 查询/Deep 并绑定 evidence，SubAgent 使用已验证的 Agent 专用模型，只接收 hash-bound 的完整 Review package，返回结构化结果和 hash 绑定的 Markdown 摘要，并在返回前完成清理。`reviewModel`/one-time override 仅限该 Reviewer dispatch，不得传播给其他 SubAgent 或写入通用默认模型。Reviewer 禁止调用 Graft、provider、验证、写入、知识更新或创建下级 Agent；缺少能力、模型回显不一致、摘要非法或清理失败都 fail-closed，不得回退父对话。
- 非-Grill 代码 Review 由 Host 的双派发入口分别执行 Standards 和 Spec；两轴必须针对同一 package、同一有序 Skill manifest 和同一 primary/supplementary 优先级返回独立且 Host attested 的 L2/L3 `approve`，否则 Review 门禁失败。Plan Review 复用同一 SubAgent seam。项目级 Review Skill 在匹配时覆盖 generic Review Skill 的主职责，但仍受保护规则约束。
- Matt 的用户调用型 Skill 只作为对应阶段的编排模板；其中的 commit、工单发布、文档写入或其他副作用不能绕过 SelfWorkflow 授权。特别是 `implement` 的结束提交不是默认许可，只有用户明确要求提交时才执行。
- 流程深度与能力 Skill 选择相互独立：复杂度、风险和副作用决定流程深度；显式请求以及语言、文件和任务语义决定是否加载通用能力 Skill。明显相关时加载 compact core，中等相关时先看元数据，专项引用只在直接信号命中时读取。
- 加载能力 Skill 不会自动创建 Design、Plan、Review 或 Verify 流程。只读任务只应用 reasoning core；实际修改才应用 change rules；真实副作用、高成本或高风险操作继续遵循既有授权护栏。
- 设计、计划、实现、调试、Review 和验证阶段只读取当前阶段命中的 Matt Skill 与必要专项模块，不预加载整个上游仓库。
- Light 不自动启动 Grill；Full 自动使用 Matt 上游 `grilling`，Deep 自动使用 `grill-me`（由上游覆盖更完整的 `grilling` frontier）。用户仍可在任意强度显式选择。Full/Deep 在共同理解确认后仍必须通过独立整体 Review；Light 做有界交叉检查。
- Superpowers 不属于 SelfWorkflow 默认依赖、路由或安装内容。只有用户明确点名时，外部 Agent 才可把它作为本次指定能力使用；不得自动 fallback，也不得因此降低 SelfWorkflow 安全门禁。
- C/C++/UE 任务默认加载 `cpp-core`，再按 ownership、并发、ABI、性能、安全、构建、调试或 Unreal 信号读取必要专项引用；非 C/C++ 任务不加载。
- 代码任务默认使用已配置且新鲜的 Graft 作为唯一代码图 Provider；查询固定 no-refresh。Graft 缺失、过期或边界无效时明确标记并回退 `rg`；需要新鲜图证据的任务失败关闭，不得把 `rg` 或过期结果伪装成结构证据。
- 项目规则可以提高要求，不能降低本文件的安全底线。
- 任务完成 Review 和验证后，若形成可复用的技术知识，主动提示一次是否沉淀到已配置的知识后端；简单问答、机械修改、临时状态和未形成稳定结论的任务不提示。每个任务最多提示一次，用户拒绝后不再重复；用户明确要求维护知识库时直接进入知识流程。
- 知识读取和沉淀是可选扩展；写入必须由用户明确确认，失败不阻塞已经验证的代码交付。

## 安全底线

不得虚构能力、Review 或测试结果；不得静默降级；不得泄露凭据或敏感信息；副作用、不可逆操作和知识写入必须获得相应授权；不得覆盖或删除用户无关修改。安装、迁移、发布、原生 Agent 验收和知识后端维护只有在任务明确要求时才加载其专项流程。
