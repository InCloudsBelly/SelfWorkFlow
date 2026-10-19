# 个人 Wiki

这是一个可独立阅读、从 Git 分享和导入的知识仓库。正文与 `.claims` 是正式知识；本机候选、锁、回执和恢复记录不属于分享内容。

请在这里维护主题导航、知识适用版本、来源仓库及更新范围。文内链接使用相对路径，代码来源使用仓库身份、版本与仓库内路径。

拉取后可直接阅读 Markdown。需要继续维护时，使用 SelfWorkflow 的 Wiki 模块把当前 Git 根作为本机 Wiki root 绑定；原机器的配置和运行区无需复制。新增来源需要重新验证和确认。

提交页面时，应同时提交对应 `.claims` 和分享所需的 Markdown 来源说明；附件通过独立来源仓库链接。发布通过候选、独立 Review 与 CAS；Git commit/push 由仓库拥有者明确执行。

仓库 `.gitattributes` 为 Markdown/JSON 禁用自动换行转换，以保持 `.claims` 对正文精确字节的绑定；不要未经核对批量 renormalize 已有知识。
