# 知识模块

知识沉淀是可选扩展，不是普通代码任务的阻塞条件。接口语义固定为：

```text
knowledge.read → knowledge.propose → knowledge.update
```

- 只在用户明确维护知识库，或任务完成后形成稳定、可复用结论时启用；后者每个任务只提示一次。
- `read` 只读；`propose` 只生成候选，不发布；`update` 需要用户明确确认、来源/版本校验和可恢复发布。
- 后端必须是显式 adapter，声明能力、失败语义和 Skill；不得猜测模型、数据库、OAuth 或路径，不把私人推理写入知识库。
- 工程文档、知识正文和来源说明使用中文。凭据、token、临时事务、完整原始敏感材料和无效结论不写入正式知识。
- 后端缺失、能力不明或证据漂移时标记 `unverified`；普通代码交付可继续，并记录待同步事项。

## `knowledge` profile 默认路由

当当前 SelfWorkflow artifact 的 profile 为 `knowledge`，且用户提到“打开/可视化 Wiki”、
“总结/整理 Wiki”或“更新/沉淀到 Wiki”时，默认 backend 固定为 `selfopenwiki`：

1. 第一调用永远是 `openwiki_status`。
2. Wiki root 只接受 status 返回的 `paths.wikiRoot`；不读取 Agent 自己的 Wiki Markdown，
   不猜测其他 Wiki 目录。
3. 可视化使用 SelfOpenWiki status 中声明的新版 Viewer contract；旧 OpenWiki CLI 不
   是 fallback。
4. `knowledge.read` 当前没有 verified 的安全 query 能力时，报告 `unverified` 并停止；
   不切换 `legacy_provider`。只有用户明确指定 `legacy_provider` 才能进入旧 provider 路径。
5. 写入仍必须经过 SelfWiki personal lifecycle、用户确认、Review 和 CAS 发布。
