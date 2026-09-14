# 代码任务模块

- 代码任务默认先检查官方 Graft MCP，代码读取优先加载 `graft-read.md`；只在 MCP 缺失、过期或边界无效时明确回退 `rg`。
- 修改代码后由 SelfWorkflow 自动发送一次 `agent_write` 事件，加载 `graft-update.md` 触发官方结构更新；不启用额外 Watcher、daemon 或第二套图逻辑，不调用 Deep。
- Full/Deep 或用户明确要求专题 Deep 时加载 `graft-deep.md`。Deep 只能针对当前专题的明确文件清单；禁止把整个大仓库无条件 `build --deep`。
- 代码任务按需加载 Ponytail 和 `cpp-core`；项目级 Review Skill 在匹配且 hash 校验通过时优先，不能覆盖硬规则。
- 代码实施契约先说明修改预期、责任层、侵入性、影响半径、性能、可维护性、兼容性和回滚；确认后才编辑。不得为小功能引入全局宏、公共枚举、非必要调用者或独立子系统。
- 代码写入完成后仍须 Review、最窄充分验证和 freshness 检查；失败只报告真实状态，不把部分缓存称为新鲜图。
