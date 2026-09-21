# 代码任务模块

- 先根据当前 `conversation-id` 选择唯一分支：已绑定 Deep Topic 才加载 `graft-read.md`，并在首次代码读取前调用一次 `graft-ensure`；未绑定或 `no-deep-topic` 不调用 Graft、不读根图、不构建全局 Map，继续原有 Light/Full/Deep 流程。
- 已绑定对话修改代码后只调用一次 `provider graft-sync`，由入口内部完成 `agent_write`、Topic Deep 和全局非 Deep Code Map 的维护与 freshness 校验。缺少身份或变更路径必须失败关闭；主 Agent 不自行拼接 Worker、Watcher 或第二套图逻辑。
- Graft 失败保留真实状态和待重试动作，不静默回退或把部分缓存称为 fresh；全局 `graft/manifest.json` 不是 Topic 前置条件。
- Full/Deep 或用户明确要求专题 Deep 时才加载 `graft-deep.md`；范围必须明确，禁止无条件全仓库 `build --deep`。
- 代码任务按需加载 Ponytail 和 `cpp-core`；项目级 Review Skill 在匹配且 hash 校验通过时优先，不能覆盖硬规则。
- 代码实施契约先说明修改预期、责任层、侵入性、影响半径、性能、可维护性、兼容性和回滚；确认后才编辑。不得为小功能引入全局宏、公共枚举、非必要调用者或独立子系统。
- 代码写入完成后仍须 Review 和最窄充分验证；绑定对话的 freshness 由 `graft-sync` 一并报告。
