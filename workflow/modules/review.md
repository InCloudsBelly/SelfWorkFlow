# Review 模块

本模块唯一负责 Review 调度、材料、角色隔离和复审条件；代码、测试与专业 Skill 提供检查项，不另外创建 Reviewer。到 Review 阶段才加载；进入新阶段本身不触发重复审查。

Light 使用一次窄结构化自审并如实标记；Full/Deep 和正式文档适用独立门禁。Review 是独立门禁，不是当前对话换模型或形式化自夸。普通 agent-policy 与契约模式使用同一质量要求，执行证据分别如下。

## 普通 agent-policy

- 使用宿主实际提供的独立 SubAgent；完整包可为有 hash 的文件或消息，包含请求、验收、适用规则、最终文档/实际增量、主 Agent 已取得的必要证据。不要创建 PlanGraph/RunLedger，不调用契约 Host API。
- 正式设计/测试/计划可合并成一份文档，实施前文档包调用一次独立 Reviewer；Full/Deep 写入任务落地后使用 Standards/Spec 两个轴。纯分析任务一次独立 Reviewer 即可，不套用“落地后”代码审查、TDD 或 TEA。
- 仅在 Review dispatch 时读取机器本地 Review 模型配置。普通记录中的 `modelScope=review-only` 是 override 作用域约束，不是所有工具共有的参数；按宿主实际 schema 映射。原生 `collaboration.spawn_agent` 使用 `model`、`reasoning_effort`，指定 override 时使用 `fork_turns=none` 的独立上下文，不传入未声明的 `modelScope` 字段。其他宿主使用其声明字段；不支持指定模型时如实报告限制。区分请求的模型/effort 与实际可观察执行证据，没有实际模型回执不虚构。主 Agent 的 Design、Plan、Implement、Verify、Knowledge 始终使用当前 Host 模型；禁止传播给任何其他 Agent。
- 宿主返回的真实完成状态可以作为普通独立审查证据；宿主未提供销毁工具或 cleanup 回执时注明“不验证资源销毁”，不得把任务结束说成已销毁。不因缺少契约清理回执阻塞普通交付。独立上下文本身不可用则该门禁 unverified，不能冒充独立 Review。
- 已有实施授权与当前请求/范围一致时复用，审查不额外发起同一确认；重要决策、越界或风险变化仍需确认。新证据只重审受影响部分。

## 共同材料与调用预算

- 匹配的项目 `.selfworkflow/review.yaml` 中的 Skill 按序优先，通用 Skill 只补充；项目身份、规则或 Skill hash 漂移使对应旧证据失效，不扫描无关目录找替代规则。

- Reviewer 只读取主 Agent 绑定的材料，不接收完整主对话历史、Wiki 或无关文件；不得调用 CodeGraph 或 provider、运行验证、写入或创建下级 Agent。
- 主 Agent 负责 CodeGraph evidence；仅结构化代码结论需要它。纯文档/分析不适用时记录原因，不凭空要求代码图。Review SubAgent 缺少 CodeGraph evidence 且该结论确实依赖它时，返回该项 unverified。
- 两个轴复用同一 package/evidence；只有 package、diff、规则、Skill hash 或未关闭发现变化时才重新 Review。TEA 质量检查复用该证据，不自动增加第三个昂贵 Reviewer。Full/Deep 落地后仅保留 Standards/Spec 两个必要的独立 Reviewer，不能因“再确认一次”无限追加昂贵调用。
- Critical/Important 必须处理，Minor 记录处置。对“审查一个有问题的系统”的纯分析任务，发现本身是交付结果，不要求先修复被审查系统才能完成分析。

## 仅 contract-managed task / conforming Host

- 只有 `dispatch_post_grill_review`、`dispatch_plan_review`、`dispatch_code_review` 可以创建 Reviewer 并传入 `reviewModel`。其他 SubAgent 不继承该 override。SubAgent 必须 `created → executed → cleaned`，模型/执行回执不匹配或清理失败均为 `unverified`，不得声称契约门禁通过。
- 首次构造门禁前读取 `skills/testing-review-quality/references/contract-host.md`，使用真实 hash-bound package、receipt、runner 与 cleanup 证据；完整 delta、规格、Plan/阶段/尝试、Skill hash 由 Host 绑定，禁止用普通摘要或自行填写回执替代。能力不可用则停止契约门禁，不静默转普通任务。
