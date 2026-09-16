# 代码任务模块

- 代码任务优先使用官方 Graft MCP 的全局非 Deep Code Map，并加载 `graft-read.md`；新对话先发现并处理 Deep Topic 选择，已绑定专题时必须传入当前稳定 `conversation-id`。全局 `graft/manifest.json` 不属于 Topic 前置条件。不主动回退 `rg`；仅简单文本定位在明确报告 `unverified` 后临时使用，结构理解不降级。
- 修改代码后由 SelfWorkflow 自动发送一次 `agent_write` 事件，并以当前 `conversation-id` 调用写后 Worker；缺少该 ID 必须失败关闭。Worker 先按 conversation 绑定检查 Topic：过期时先由同一次 Host 调用用当前 conversation 模型/推理等级刷新原 scope，暂缓全局非 Deep Code Map；Topic fresh 时再尝试独立更新全局 Map。全局 Map 失败或延后不得阻塞 Topic/主任务，但必须返回待重试状态；Topic freshness 只由 Topic 自身 manifest/context/source hash 决定。主 Agent 不需要记住无关的第二次调用。不启用额外 Watcher、daemon 或第二套图逻辑。
- Full/Deep 或用户明确要求专题 Deep 时加载 `graft-deep.md`。Deep 只能针对当前专题的明确文件清单；禁止把整个大仓库无条件 `build --deep`。
- 代码任务按需加载 Ponytail 和 `cpp-core`；项目级 Review Skill 在匹配且 hash 校验通过时优先，不能覆盖硬规则。
- 代码实施契约先说明修改预期、责任层、侵入性、影响半径、性能、可维护性、兼容性和回滚；确认后才编辑。不得为小功能引入全局宏、公共枚举、非必要调用者或独立子系统。
- 代码写入完成后仍须 Review、最窄充分验证和 freshness 检查；失败只报告真实状态，不把部分缓存称为新鲜图。
