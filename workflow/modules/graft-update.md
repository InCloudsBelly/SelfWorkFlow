# Graft 写后更新模块

- Agent 修改代码后调用官方 Graft 结构更新；一次任务内合并重复事件，查询、Review 和纯读取不更新。
- 更新只维护当前项目的全局 structural Map；不自动 Deep、不改变专题 Deep 内容。专题只在下一次明确使用该 topic 时按源文件 hash 惰性更新。
- 更新前后校验项目根目录、文件边界和官方 MCP capability。失败保留旧图并报告 `stale`/`failed`；不得把部分缓存、无 manifest 或未通过 freshness 的结果称为可用。
- SelfWorkFlow 不实现第二套图、Watcher、daemon 或查询逻辑；缺少官方入口时普通任务回退 `rg`，需要新鲜 Graft 证据时 `unverified`。
