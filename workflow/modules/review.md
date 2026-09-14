# Review 模块

Review 是独立门禁，不是当前对话换模型或形式化自夸。

- 实施前完整设计/测试/计划文档用一个独立临时 SubAgent 做 `plan-integrated-review`；落地后 Full/Deep 用两个独立临时 SubAgent，分别 Standards/Spec，接收同一个 hash-bound 完整包。
- 匹配的项目 `.selfworkflow/review.yaml` 中的 Skill 按序优先，通用 Review Skill 只补充；profile、Skill 内容或项目身份漂移即拒绝旧证据。
- Review 模型按 Agent 从机器本地配置选择，父对话模型不变；Review payload 固定 `modelScope=review-only`，`reviewModel`/one-time override 仅在本次 Review dispatch 生效，不写入通用 SubAgent 默认值；其他 SubAgent 不继承该 override。SubAgent 必须 `created → executed → cleaned`，只返回结构化结果和中文摘要，不保存私人推理。
- 角色隔离：主 Agent 在创建 Reviewer 前完成需要的 Graft 查询/Deep 并绑定 evidence；Review SubAgent 只读取 hash-bound Review package 并返回报告。Reviewer 不得调用任何 Graft 查询、Deep、event、worker 或 provider 维护，不得修改工作区、运行验证、写入知识库或创建 SubAgent。缺少 Graft evidence 时只返回 `unverified`，不得自行补做。
- Review 包包含批准请求、验收条件、最终文档、适用规则、完整 delta、Plan/阶段/尝试和 Skill hash。Critical/Important 必须修复，Minor 必须记录处置；文档或代码变化后重审。
- 无独立能力、模型/执行回执不匹配、清理失败或输入漂移均为 `unverified`，不得声称 Review 通过。
