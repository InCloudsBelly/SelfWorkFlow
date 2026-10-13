# 代码任务模块

- 代码读取阶段加载 `codegraph-read.md`，用 `provider preflight` 确认当前项目级 `.codegraph/` 已初始化且 fresh；缺失时自动全量初始化，stale 时自动同步并在必要时重建。
- 每个读取阶段及外部手动编辑、分支/HEAD、dirty/未跟踪漂移后自动检查并失效相关旧证据；跨项目查询遵循读取模块，不逐行重复。CodeGraph 不依赖 Deep、Topic 或 conversation 状态。
- 工作流产生任何实际代码批次（含部分失败、撤回、删除、重命名）后，主 Agent 合并路径，在后续结构化读取或交付前调用一次 `provider sync`，核对工作区并验证 fresh；官方跳过未变文件解析。自动维护由读取/更新模块界定，不要求用户提醒，不自行拼接 Worker、Watcher 或第二套图逻辑。
- CodeGraph 失败保留真实状态和待重试动作，不静默回退或把部分缓存称为 fresh；纯文本定位不能替代结构化证据。
- 代码任务按需加载 Ponytail 和 `cpp-core`；项目级 Review Skill 在匹配且 hash 校验通过时优先，不能覆盖硬规则。
- 代码实施契约先说明修改预期、责任层、侵入性、影响半径、性能、可维护性、兼容性和回滚；确认后才编辑。不得为小功能引入全局宏、公共枚举、非必要调用者或独立子系统。
- 代码写入完成后仍须 Review 和最窄充分验证；项目 CodeMap 的 freshness 由 `codegraph-update.md` 的 `provider sync` 一并报告。
