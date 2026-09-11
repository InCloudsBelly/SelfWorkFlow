# Review 模块

Review 是独立门禁，不是当前对话换模型或形式化自夸。

- 实施前完整设计/测试/计划文档用一个独立临时 SubAgent 做 `plan-integrated-review`；落地后 Full/Deep 用两个独立临时 SubAgent，分别 Standards/Spec，接收同一个 hash-bound 完整包。
- 匹配的项目 `.selfworkflow/review.yaml` 中的 Skill 按序优先，通用 Review Skill 只补充；profile、Skill 内容或项目身份漂移即拒绝旧证据。
- Review 模型按 Agent 从机器本地配置选择，父对话模型不变；SubAgent 必须 `created → executed → cleaned`，只返回结构化结果和中文摘要，不保存私人推理。
- Review 包包含批准请求、验收条件、最终文档、适用规则、完整 delta、Plan/阶段/尝试和 Skill hash。Critical/Important 必须修复，Minor 必须记录处置；文档或代码变化后重审。
- 无独立能力、模型/执行回执不匹配、清理失败或输入漂移均为 `unverified`，不得声称 Review 通过。
