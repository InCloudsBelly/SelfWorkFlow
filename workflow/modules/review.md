# Review 模块

Review 是独立门禁，不是当前对话换模型或形式化自夸。

- 实施前完整设计/测试/计划文档用一个独立临时 SubAgent 做 `plan-integrated-review`；落地后 Full/Deep 用两个独立临时 SubAgent，分别 Standards/Spec，接收同一个 hash-bound 完整包。
- 匹配的项目 `.selfworkflow/review.yaml` 中的 Skill 按序优先，通用 Review Skill 只补充；profile、Skill 内容或项目身份漂移即拒绝旧证据。
- Review 模型按 Agent 从机器本地配置选择，父对话模型不变；Review payload 固定 `modelScope=review-only`，`reviewModel`/one-time override 仅在本次 Review dispatch 生效，不写入通用 SubAgent 默认值；其他 SubAgent 不继承该 override。SubAgent 必须 `created → executed → cleaned`，只返回结构化结果和中文摘要，不保存私人推理。
- 模型边界与调用预算：主 Agent 的 Design、Plan、Implement、Verify、Knowledge 始终使用当前 Host 模型，不切换、不读取 Review 模型配置。只有 `dispatch_post_grill_review`、`dispatch_plan_review`、`dispatch_code_review` 可以创建 Reviewer 并传入 `reviewModel`；它只绑定该次 Reviewer，禁止传播给任何其他 Agent。实施前文档包调用一次独立 Reviewer；Full/Deep 落地后仅保留 Standards/Spec 两个必要的独立 Reviewer，不能因“再确认一次”无限追加昂贵调用。
- Review 必须紧凑：Reviewer 只接收同一个 hash-bound package、必要的 Graft evidence 和项目 Review Skill，不接收完整主对话历史、Wiki 或无关文件；不得重新发现、刷新 Graft、调用 provider、运行验证、写入或创建下级 Agent。两个轴复用同一 package/evidence；只有 package、diff、规则、Skill hash 或未关闭发现变化时才重新 Review。TEA 质量检查复用该证据，不自动增加第三个昂贵 Reviewer。
- 角色隔离：主 Agent 在创建 Reviewer 前完成需要的 Graft 查询/Deep 并绑定 evidence；Review SubAgent 只读取 hash-bound Review package 并返回报告。Reviewer 不得调用任何 Graft 查询、Deep、event、worker 或 provider 维护，不得修改工作区、运行验证、写入知识库或创建 SubAgent。缺少 Graft evidence 时只返回 `unverified`，不得自行补做。
- Review 包包含批准请求、验收条件、最终文档、适用规则、完整 delta、Plan/阶段/尝试和 Skill hash。Critical/Important 必须修复，Minor 必须记录处置；文档或代码变化后重审。
- 无独立能力、模型/执行回执不匹配、清理失败或输入漂移均为 `unverified`，不得声称 Review 通过。
