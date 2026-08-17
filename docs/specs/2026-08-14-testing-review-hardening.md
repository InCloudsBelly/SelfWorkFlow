# 测试与 Review 强化设计

## 目标

在不恢复 Superpowers 默认依赖的前提下，保留其有效质量不变量：行为修改强制真实 TDD、完成声明绑定新鲜验证证据、Full/Deep 使用 TEA、复杂任务执行独立双轴 Review。

## 责任层与边界

- SelfWorkflow 核心策略负责流程强制性、授权、严重级别和完成门禁。
- 生效策略写入根 `WORKFLOW.md`；Runtime builder 对 `core`、`knowledge`、`maintainer` 三种 profile 均从该文件生成制品根 `WORKFLOW.md`，并以逐字节测试锁定。Git revision 绑定的旧 `workflow/core.md` 在当前脏工作树中保持原字节，避免伪造来源证明；它只保留为 V2 Catalog provenance，不能再作为 profile 的生效策略来源。后续正式提交可在同一提交链中同步该目录源。
- Matt `tdd` 提供测试接缝、纵向切片和反模式；SelfWorkflow 补充强制触发与 RED/GREEN 证据契约。
- Matt `code-review` 提供 Standards/Spec 双轴方法；SelfWorkflow 负责完整工作树 diff、最终文档包、严重级别和 0C/0I 门禁。
- TEA 上游保持只读 Submodule；新增一个薄适配 Skill，从固定 commit 打包五个必要工作流，避免要求用户项目安装 BMAD 运行目录。
- `tea-quality` 是 SelfWorkflow 本地入口：由模块传入 stage、项目根、规格/计划/测试上下文和输出位置；路径只从已安装 Skill 根解析。它明确跳过上游交互问候、`_bmad` 配置和项目脚本 bootstrap，在无 `_bmad` 沙箱中按 supplied context 进入对应 Create/Validate 步骤；任何未解析变量或越界路径 fail-closed。
- `testing-review-quality` 是新增的本地质量门 Skill，调用 deterministic quality helper。它必须拥有独立 V2 Catalog source entry，`revision` 指向只包含该 Skill 的真实 Git commit，`contentHash` 与当前 `SKILL.md` 字节一致；V3 module `sourceHash`、index hash 和 Runtime manifest 同时绑定同一字节。任一层漂移阻止构建。既有 hash-bound `workflow-quality` 保持不变，避免把脏源误报为已验证 revision。

## 强制行为

1. 对 `writeTask:true` 的执行任务，`behaviorChange` 不由调用者自由声明：`operationType in {implement, debug}` 或 `taskArchetype in {bounded-feature, bugfix, behavioral-refactor, architecture-change, migration}` 任一命中即为 true，并必须选择独立 `implement.tdd` 槽；诊断方法继续位于 `implement.method`，不得通过冲突绕过 TDD。写任务的非行为 operation 与行为 archetype 组合属于分类冲突并暂停，不允许靠 operation 绕过。`review`、`verify` 等只读任务可保留被审对象的行为 archetype，但不反向进入实现/TDD 阶段。仅 `mechanical-change` / `spec-document` 且分类证据明确不改变消费者行为时豁免 TDD，但仍执行解析、消费者和回归验证。RED 证据包含命令、预期失败、实际失败原因和非基础设施错误；GREEN 重跑同一路径并执行最窄相关回归。
2. Full 最低 T2；Deep 最低 T3。V2/V3 的 Full/Deep 测试设计与测试 Review 必须静态选择 TEA；能力缺失时暂停，不得静默跳过。V2 为 `implement/debug` 增加独立 `implement.tdd` 槽，诊断方法不能与 TDD 互斥。
3. 实施前 Review 是“最终设计 + 测试设计 + 计划 + 文档包 hash”的独立整体门禁。实施后 Review 使用本地 `review-input builder`：编辑前记录任务起点、批准路径的工作树与 Git index 字节和 Git file mode，以及整个工作树的 dirty/untracked 内容指纹；最终生成可读取的规范化内容包，覆盖实际规范，以及 committed、staged、unstaged、untracked、删除、二进制 hash 和 mode-only 变化。工作树与最终 index 分别保存内容/hash/mode/patch，“暂存后恢复或删除工作树文件”及纯执行位变化不能漏审。批准路径之外相对起点发生变化时 fail-closed。
4. Review package 与每份收据必须绑定同一个 `workflowMode`。Light 接受一份绑定当前 package 的结构化 `self_attested` 自审；Full/Deep 使用两个新的独立上下文：Standards 与 Spec。两者必须接收同一个 review package，并由 Host 回传 `host_attested` 收据、Host 观察到的不同 execution ID 与 package hash；模式不匹配、任一路缺失、输入不同或 Host 不能提供独立上下文时暂停。该收据是流程护栏，不是身份、模型或密码学证明，质量门不得夸大为自行认证。结果保留双轴分组，并冻结严重级别映射：`critical -> Critical`，`high/medium -> Important`，`low/info -> Minor`。Critical/Important 未清零不得进入完成门禁。
5. Verify 由本地 deterministic runner 执行 package 内至少一项已绑定的结构化计划。runner 使用无 shell/stdin、固定环境、超时和硬上限流式读取；Windows 在启动前绑定 Kill-on-close Job Object，POSIX 绑定独立进程组。无论顶层进程是否先退出，都终止容器、先回收组长，再确认剩余容器为空；后台子进程、输出超限或无法确认终止均 fail-closed。进程启动后的全部退出路径统一通过 `finally` 清空容器、等待 reader 并关闭管道；清理失败升级为 termination failure。runner 执行前后重建 package 并生成结构化结果。Complete 不接收外部 Verify 收据，而是自行执行全部绑定计划并再次重建 package；Critical/Important 为零、全部 Verify 成功且无 `unverified` 才通过。
6. Review package 的语义 hash 域只包含规范化的相对路径、baseline 内容指纹、实际 spec/delta 和验证计划；不含 `createdAt`、绝对仓库路径、临时目录或执行时间。`createdAt` 只用于 freshness 校验。同一 baseline/spec/工作树/验证计划重复生成必须得到相同 package hash。
7. Light 不自动启用 Grill；Full 自动启用 Matt `grilling`；Deep 自动启用 Matt `grill-me`，由上游内部执行更全面的 `grilling` frontier。自动或显式 Grill 完成后使用厂商无关的独立设计 Review，不再引用 Brainstorming/Superpowers。
8. V2 与 V3 同步收敛：两者都按 Light/Full/Deep 路由 Grill，且不重复加载 Deep 内部已包含的 `grilling`；V2 增加行为 TDD、Full/Deep TEA plan/review 槽，Review/Verify/Complete 改用 `testing-review-quality` Skill。不得保留一条可绕过新门禁的旧默认执行路径。

## 侵入性与替代方案

- 采用现有 Runtime builder、Catalog、Pipeline 和 Skill 安装路径，不新增守护进程、数据库或公共网络接口。
- 不修改 Matt/TEA 上游文件；Runtime 构建同时核对 Matt commit、完整 Git tree 与 dirty 状态，不能只锁入口 `SKILL.md`；不删除用户机器上的外部 Superpowers。
- 拒绝直接修改 Matt TDD/Review Skill：会造成上游合并冲突。
- 拒绝把整个 TEA 仓库装入 Runtime：上下文和制品膨胀。只复制五个固定工作流及许可证。

## 验收

- 行为修改的 V3 PlanGraph 必选 TDD；非行为写入不被错误强制。
- 有效强度取 `complexity × risk × projectMinimums` 的最高要求：C2/R2/Full 至少 T2，C3/R3/Deep 必须 T3；约束 fail-closed，TEA 设计与 Review 必选。
- Runtime 中五个 TEA 工作流完整存在，整个 TEA Submodule 不进入制品。
- `tea-quality` 对五个固定 workflow 生成仅含已提供 context、相对输出位置和固定引用 hash 的 invocation package，并校验对应输出契约；无 `_bmad` 沙箱五路 E2E 均通过。此证据证明适配/文件/runtime dispatch，不伪称证明任意模型的语义质量；语义结果仍由 Review/Verify 把关。

### TEA 五路适配契约

公共 invocation 固定为 `{schemaVersion:1, workflowId, referenceHash, inputHash, context, outputRelative}`；`referenceHash` 绑定已打包 workflow 目录，`inputHash` 绑定规范化 context 与输出相对路径。输出为 UTF-8 Markdown 和 `{workflowId,inputHash,outputRelative,outputHash,status:"validated"}` 收据，最大 2 MiB，路径必须位于项目根内且非 reparse/symlink。五路最小字段与必需标题如下：

| workflowId | context 必需字段 | 输出 | 必需标题 |
| --- | --- | --- | --- |
| `test-design` | requirements, acceptanceCriteria, design, risk | `test-design.md` | Scope, Risks, Coverage, Cases |
| `atdd` | requirements, acceptanceCriteria, implementationPlan, testDesign | `atdd.md` | Red Evidence, Acceptance Tests, Fixtures |
| `test-review` | acceptanceCriteria, implementationDelta, testDesign, verificationEvidence | `test-review.md` | Coverage Review, Failure Paths, Findings |
| `trace` | acceptanceCriteria, testInventory, verificationEvidence | `trace.md` | Trace Matrix, Gaps |
| `nfr` | design, nfrRequirements, verificationEvidence | `nfr.md` | Performance, Security, Reliability |

未知 workflow、字段缺失/空值、未解析模板变量、引用 hash 漂移、绝对/越界/重解析路径、输出缺失/过大/非 UTF-8、必需标题缺失或收据 hash 不匹配均 fail-closed。适配器不读取项目 `_bmad`，也不执行上游脚本。
- `core`/`knowledge`/`maintainer` Runtime 的根 `WORKFLOW.md` 与仓库根策略逐字节一致；V2/V3 都按强度自动路由受门禁的 Grill，不保留占位 Review/Verify/Complete。
- Review 覆盖完整工作树，不依赖必须存在的 issue-tracker 文件。
- Review builder 能生成实际可读内容包并拒绝批准范围外漂移；Complete gate 自行重建当前包并自行运行全部绑定 Verify，对外部伪造收据、过期 Review、失败命令、开放 Important、缺失和 `unverified` 证据 fail-closed。
- Verify/Complete 不再引用占位 agent-native 能力。
- 活跃策略与 post-Grill 契约中没有默认 Superpowers/Brainstorming 流程节点。
