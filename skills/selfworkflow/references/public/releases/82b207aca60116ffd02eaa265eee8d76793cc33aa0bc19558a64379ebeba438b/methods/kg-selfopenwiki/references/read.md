# 安全读取

只在读取、查询、总结或不发布的整理方案时加载。复用入口的 status、唯一 Wiki root 和失败关闭规则。

1. 从 `openwiki_status` 确认实现至少 0.1.2、默认 schema 2、external mode、OAuth-free，以及 verified 的 `knowledge.read.safe`。不要求发布 capability 对、完整个人生命周期或 `externalAgent.ready=true`；实际读取仍须通过后端恢复状态与一致性锁检查。
2. 调用 `openwiki_read {}` 取得正式页面目录和 revision；按问题选页面，再用 `paths` 与 `expectedWikiRevision` 分批读取正文。单批 1–32 页，每页最多 256 KiB，合计最多 1 MiB；只读取目录列出的正式根内 Markdown。
3. 引用返回的 `sourceId/revision/contentHash/verificationStatus`。`unverified` 表示内容语义尚未重新验证；正文和 Claims 不能证明新机器上的来源已验证。空页面不用于总结，revision 冲突先刷新目录再选择。

此路径不调用 provider、不创建候选或发布事务，也不加载更新六阶段、Writer Skill 或完整 MCP 契约。缺读取能力报告 `unverified`；不能以 begin/update 或显式 legacy query 代替。读取失败若需要恢复诊断，再切到 recovery 引用。

新版 MCP 在发布锁内读取；`busy` 等待当前操作结束后重试，`restore_required` 先处理同一事务恢复。普通读取不把正式 Wiki 当作工作目录，也不自动打开正式文件面板。确需一致的文件预览时使用已核对 revision/hash 的现有任务审查副本；直接文件浏览的边界见 visualize 引用，仅在该操作时补读。
