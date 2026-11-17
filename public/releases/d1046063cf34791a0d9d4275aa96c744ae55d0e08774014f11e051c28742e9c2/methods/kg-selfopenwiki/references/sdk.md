# SelfWiki SDK 调用

仅批量或需重连的 SDK 调用读本页。使用已确认 SelfWorkflow 源仓库的 `scripts/personal-wiki-mcp.mjs` 中的 `openPersonalWikiMcp()`。每连接读取 status 与工具表，核对实际 Wiki 根及既有绑定。

`call` 接收绝对路径的 `.request.json`，格式为 `{name,args}`，按实时 schema 校验。执行身份按 schema 表示，回执与绑定由原角色提供。完整 `.result.json` 留在任务目录，主对话只收状态、下一步和证据路径。

结果绑定 Wiki、运行目录和上游根。同目标同请求可复读，旧回执只证明原操作。新动作建新请求文件，勿重发已接受的操作。`pending` 或断连表示结果未知，按[恢复](recovery.md)核对已接受阶段。结束后关闭会话。
