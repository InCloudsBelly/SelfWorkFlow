# 代码任务模块

- 已有全局非 Deep Code Map 时加载 `graft-read.md`，用 `graft-ensure` 只读检查：fresh 自动使用，无须选择；stale 询问更新。缺失不自动初始化；明确禁用时跳过。
- 每个读取阶段及外部编辑/分支切换后检查，不逐行重复；拒绝更新时说明限制并使用文本定位。
- Agent 修改、撤回、删除、重命名后合并实际操作路径调用一次 `provider graft-sync`，只维护已有全局非 Deep Code Map。缺少身份或变更路径必须失败关闭；主 Agent 不自行拼接 Worker、Watcher 或第二套图逻辑。
- 只有用户明确要求专题 Deep 且对话已有 Topic 绑定时才加载 `graft-deep.md` 并调用 `provider graft-deep`。普通 Graft freshness 不读取任何 Deep manifest。
- Graft 失败保留真实状态和待重试动作，不静默回退或把部分缓存称为 fresh；全局 Map freshness 独立验证。
- 代码任务按需加载 Ponytail 和 `cpp-core`；项目级 Review Skill 在匹配且 hash 校验通过时优先，不能覆盖硬规则。
- 代码实施契约先说明修改预期、责任层、侵入性、影响半径、性能、可维护性、兼容性和回滚；确认后才编辑。不得为小功能引入全局宏、公共枚举、非必要调用者或独立子系统。
- 代码写入完成后仍须 Review 和最窄充分验证；绑定对话的 freshness 由 `graft-sync` 一并报告。
