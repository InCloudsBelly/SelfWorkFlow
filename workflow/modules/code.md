# 代码任务模块

- 代码任务默认先检查并使用新鲜官方 Graft MCP，代码读取优先加载 `graft-read.md`；新对话先发现并处理 Deep Topic 选择，已绑定专题时必须传入当前稳定 `conversation-id`。不主动回退 `rg`；仅简单文本定位在明确报告 `unverified` 后临时使用，结构理解不降级。
- 修改代码后由 SelfWorkflow 自动发送一次 `agent_write` 事件，并以当前 `conversation-id` 调用写后 Worker；缺少该 ID 必须失败关闭，不能只更新全局图。Worker 先更新全局 structural Map（根图绝不 Deep），发现绑定 Topic 过期后由同一次 Host 调用自动继续原 scope 的 Topic Deep，并使用当前 conversation 的模型/推理等级；主 Agent 不需要记住第二次调用。Worker 必须分别验证 global Map 与 Topic freshness；返回 `partial`/`unverified` 时明确报告 `retry-topic-deep`，不得静默回退 `rg`，普通对话可以继续但不能声称 Graft fresh。不启用额外 Watcher、daemon 或第二套图逻辑。
- Full/Deep 或用户明确要求专题 Deep 时加载 `graft-deep.md`。Deep 只能针对当前专题的明确文件清单；禁止把整个大仓库无条件 `build --deep`。
- 代码任务按需加载 Ponytail 和 `cpp-core`；项目级 Review Skill 在匹配且 hash 校验通过时优先，不能覆盖硬规则。
- 代码实施契约先说明修改预期、责任层、侵入性、影响半径、性能、可维护性、兼容性和回滚；确认后才编辑。不得为小功能引入全局宏、公共枚举、非必要调用者或独立子系统。
- 代码写入完成后仍须 Review、最窄充分验证和 freshness 检查；失败只报告真实状态，不把部分缓存称为新鲜图。
