# SelfWorkFlow 进度反馈、代码实施契约与实施前整体 Review：TEA 测试设计

- 日期：2026-08-11
- 状态：等待独立整体 Review
- 对应设计：`docs/superpowers/specs/2026-08-11-progress-and-pre-implementation-review-design.md`
- 测试等级：T2（工作流默认行为与实施门禁变更）

## 1. 风险评估

| 风险 | 影响 | 概率 | 优先级 | 主要控制 |
|---|---:|---:|---:|---|
| Full/Deep 在整体 Review 前进入实现 | 高 | 中 | P0 | policy + planned gate 路由测试 |
| 同一 Agent 自审被误称为独立 SubAgent | 高 | 中 | P0 | 明确禁止降级与不可用暂停断言 |
| 更新文档后复用旧 Review | 高 | 中 | P0 | 最终文档包 hash 失效规则断言 |
| 轻量任务也被强制重型 Review | 中 | 中 | P1 | Light 路由/文本边界测试 |
| ETA 被表达为精确承诺 | 中 | 中 | P1 | 区间、未知和重估语义断言 |
| 安装器没有把新规则写入用户指令 | 高 | 低 | P1 | sandbox 安装与真实安装后检查 |
| 修改覆盖现有 C7OpenWiki 脏改动 | 高 | 低 | P1 | 最终 diff 路径审计 |
| 实施前 Review 被误当作实施后 Review | 中 | 中 | P1 | 两个门禁同时存在的行为断言 |
| 局部功能或测试需求扩散到公共 API、全局宏或通用生产路径 | 高 | 中 | P0 | 侵入性预算 + 压力场景 |
| Agent 用“测试覆盖更完整”合理化高侵入生产改动 | 高 | 中 | P0 | 明确测试不得塑造生产架构；更窄接缝优先 |
| 以修改行数少误判公共宏/枚举改动为轻量 | 高 | 中 | P0 | 按影响半径而非行数评估 |
| Agent 在用户确认前先写测试或生产代码 | 高 | 中 | P0 | 代码实施契约 + 明确实施确认门禁 |
| 三份文档只写功能目标，未写具体代码边界与长期成本 | 高 | 中 | P0 | 分文档必填字段与整体 Review |
| 实际实现越界但继续沿用旧确认 | 高 | 中 | P0 | 契约失效与停止实施断言 |
| Light 因新门禁被迫生成三份文档 | 中 | 中 | P1 | 紧凑内联契约边界测试 |

## 2. 验收—测试追踪

| ID | 验收条件 | 自动化证据 |
|---|---|---|
| AC-1 | 首条进度包含 profile、mode、阶段、区间和 ETA，并保持低噪声 | `test_workflow_matrix.py` 与 installer managed block 测试 |
| AC-2 | Light 内联任务不强制 SubAgent | Catalog/Pipeline 条件测试 |
| AC-3 | Full/Deep 或正式文档包使用独立整体 Review gate | V2 Catalog 与 V3 Pipeline/Catalog/PlanGraph 测试 |
| AC-4 | Review 绑定最终文档包，文档变化使旧结论失效 | policy 文本测试 + 本任务真实 Review 迭代 |
| AC-5 | SubAgent 不可用时暂停，不同上下文不降级 | policy 文本测试 |
| AC-6 | 实施前 Review 不替代 TDD、post-landing Review 或 Verify | workflow matrix 测试 |
| AC-7 | 既有 C7OpenWiki 和其他脏修改保持不变 | 基线 hash + 任务增量/总 diff/staged diff 审计 |
| AC-8 | 最窄相关测试和真实 knowledge 安装均有新鲜证据 | runtime snapshot、installer sandbox、实际安装检查 |
| AC-9 | V3 PlanGraph 保持既有 Light/Full/Deep 整体 Review 路由 | V3 PlanGraph 回归测试 |
| AC-10 | 高影响半径信号进入侵入性预算 | workflow matrix + code-quality Skill 行为测试 |
| AC-11 | 存在更窄方案时拒绝重方案；确需越界时要求用户确认 | code-quality 压力场景 |
| AC-12 | 测试不得反向驱动生产架构，缺失证据标记 `unverified` | code-quality 压力场景 + policy 文本测试 |
| AC-13 | 所有代码修改先形成契约并取得用户明确实施确认；确认前不得编辑测试或生产代码；Light 只需紧凑内联摘要 | workflow matrix + runtime/installer 文本测试 + Light 回归 |
| AC-14 | 设计、TEA、计划分别覆盖修改预期、测试接缝/性能证据和实施边界 | policy 文本测试 + 本任务独立整体 Review |
| AC-15 | 越过责任层、公共契约、侵入性、安全、性能或维护预算会使确认失效并停止 | workflow matrix + code-quality 压力场景 |

## 3. 测试场景

### T-01 进度策略正向场景

检查 `WORKFLOW.md` 与 `workflow/core.md` 同时包含：profile、mode、`已完成主阶段/总主阶段`、`当前`、`剩余`、`预计`、粗略百分比区间、时间区间、无法可靠估算、重新估算、首条进度更新和低噪声触发条件。安装后 managed block 必须再次断言这些字段，不能只因旧有 `SelfWorkflow active` 文字而误通过。

### T-02 进度策略误用场景

检查规则明确禁止精确倒计时、单点精确百分比、每个命令刷屏和用百分比替代完成证据，并要求正常进展保持单调、明显回退说明重估原因。预期通过。

### T-03 Light 路由

构造 Light 修改请求。V2 选择轻量 `plan.gate`，V3 的 `plan.integrated-review` 条件不适用。预期不要求独立 SubAgent。使用真实 `build_plan_graph` 证明，而非只检查 YAML。

### T-04 Full/Deep 路由

覆盖复杂度 C2、风险 R2、项目最低 Full 三条入口。V2 均选择整体 Review；V3 未通过 explicit/project default 请求时以 `v3-required-module-unavailable` fail closed，已经请求但 execution policy 未授权 unverified 模块时以 `v3-explicit-module-unsupported` fail closed，在任一合法请求来源与 execution policy 明确批准后选择该模块。预期三个入口都验证两类失败与成功路径。

### T-05 正式文档包边界

静态策略必须声明“两份以上正式文档先升级 Full”。由于文档数量是计划阶段产生的 Agent 状态，不伪称 V3 Resolver 能从初始 Request 自动观测；若运行中形成文档包，必须重分类/重新计划。

### T-06 独立性失败路径

检查规则明确：新的独立 SubAgent、只读、不得携带私有推理；不可用时 `unverified` 并暂停；同一 Agent 自审不是合法 fallback。

### T-07 Review 闭环

以本次设计、TEA、计划和 dirty-baseline 审计清单四文件包启动独立 SubAgent，并绑定四个 SHA-256。若返回 Critical/Important，先修正文档并重新对完整四文件包 Review；若修改任一文件，不得复用旧 pass。

### T-08 安装传播

在临时目录构建 knowledge profile 并执行 installer sandbox，断言生成的 Codex `AGENTS.md` 包含进度策略和整体 Review 门禁。随后真实重装并检查 `current.json`、artifact hash、snapshot `WORKFLOW.md` 与用户级 managed block 一致。

### T-09 回归与侵入性

实施前保存计划触碰文件的 SHA-256 和完整现有 patch。运行 Catalog、V3 Pipeline/PlanGraph、workflow matrix、runtime snapshot、installer apply 的最窄相关测试。最终执行 `git diff --check`，审计基线→最终任务增量，并逐 hunk 确认已有 C7OpenWiki 与其他未提交修改仍存在。

### T-10 高侵入代码设计压力场景

先在旧 `code-quality` Skill 上运行压力场景：局部渲染功能需要更完整的自动化验证，候选方案要求在公共枚举加入仅测试构建存在的槽位，并把全局测试宏传播到多个生产路径。预期旧规则可能只给出笼统的“兼容性 Review”，未明确否决测试驱动的公共生产改造，作为 Red 证据。

更新后用同一场景验证 Agent 必须：按影响半径识别高侵入；列出更窄的测试自有接缝/黑盒验证方案；存在更窄方案时拒绝公共槽位；没有更窄方案时暂停并请求用户确认；不得改变公共枚举 `Num` 或注册矩阵；不得用 TEA 覆盖率要求合理化生产架构膨胀。另设反例证明测试自有 TU 内的局部 `WITH_DEV_AUTOMATION_TESTS` 保护不会被一刀切禁止。

静态测试同时断言 `workflow/core.md`、`WORKFLOW.md` 和安装后的 managed block 都包含侵入性预算、影响半径、测试不得反向驱动生产架构、越界用户确认、无法在批准边界内取得证据时标记 `unverified`，以及超预算失效规则；`code-quality` Catalog source-lock 必须匹配更新后的 Skill。不得为侵入性检查新增专用模块、Schema 或服务；既有计划中的 `plan.integrated-review` 不属于新增侵入性模块。

### T-11 代码实施契约与确认门禁

在现有 policy 尚未加入新规则时，先增加静态行为测试，要求 `workflow/core.md`、`WORKFLOW.md`、runtime snapshot 和安装后的 managed block 同时包含：代码实施契约、第一次代码编辑前、测试代码也受门禁约束、修改预期、影响半径、安全、性能、可维护性/回滚、明确实施确认，以及确认前只允许只读分析和文档修订。预期旧规则缺少这些字段而 Red。

Green 后检查顺序必须是：形成契约；Full/Deep 独立整体 Review 并修正文档；向用户呈现最终摘要；用户明确确认；开始 TDD。一般需求认可、旧文档确认或 SubAgent 推荐不得替代用户确认。

### T-12 文档分工与 Light 边界

静态策略断言正式设计覆盖候选实现、责任层、文件/符号、公共契约及安全/性能/维护取舍；TEA 覆盖直接/失败路径、状态不变量、测试接缝、生产架构隔离和性能证据；实施计划覆盖预计文件/行为、禁止边界、TDD、回滚和验证命令。同时断言 Light 只需对话内紧凑契约，不得为此强制三份文档或独立 SubAgent。

### T-13 契约失效压力场景

构造“用户已确认局部实现，实施者随后发现最省事的办法是增加公共枚举和全局编译宏”的场景。预期 Agent 必须停止代码编辑，修订设计/TEA/计划和侵入性预算，重新整体 Review 并再次请求确认；不得把它解释为批准预算内的局部细节。反例使用同一责任层内的私有辅助函数改名，预期无需重复询问，但最终 Review 必须记录实际变化。

## 4. Red/Green 顺序

1. 只新增代码实施契约断言、契约失效/预算内反例和安装传播断言；运行目标测试并确认因 core/WORKFLOW/Skill 缺少新契约而失败；不得新增路由或模块测试需求；
2. 只最小修改 core、WORKFLOW、`code-quality` Skill 及两个既有 source-lock；V3/Pipeline/Catalog 模块仅回归验证；
3. 更新内容 hash 后运行目标测试至 Green；
4. 运行相关回归；
5. post-landing Review 后再次运行最终验证，旧的测试结果不能替代最终 diff 的新鲜证据。

## 5. 明确不验证的能力

- 自动测试不能证明任意厂商模型一定遵守自然语言 Agent Policy；只证明规则已安装且契约路由正确；
- V3 的 `unverified` 运行时能力不会被提升为 supported；测试只证明未授权时暂停、明确授权后可选择；
- 不新增后台计时器，因此不验证精确用时预测；ETA 仅为诚实的 Agent 估算；
- 不验证 C7OpenWiki 功能，本次仅保护其已有修改不被覆盖。
- 不把所有条件编译或测试接缝判为高侵入；自动证据只验证工作流能区分“测试自有局部边界”与“测试需求穿透公共生产契约”。
- 自然语言测试只能证明契约被正确发布并为 Agent 提供明确规则，不能机械证明任意模型始终在第一次文件写入前等待用户；本任务以独立压力验证补充，但仍不把 Agent 行为提升为系统级事务锁。

上述限制必须在交付时如实标记，不能提升为机械强制能力。
