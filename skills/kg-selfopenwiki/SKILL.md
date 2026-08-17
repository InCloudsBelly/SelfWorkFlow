---
name: kg-selfopenwiki
description: Use when the optional SelfOpenWiki knowledge backend is explicitly selected for local project knowledge.
---

# SelfOpenWiki knowledge backend

这是 SelfWorkflow 的可选知识后端适配。它只在用户明确选择 SelfOpenWiki 时加载；普通代码任务不加载，不能替换 SelfWorkflow 的 Design、Plan、Review 或 Verify 门禁。

## 仓库与数据边界

- 官方 OpenWiki 是 SelfOpenWiki 仓库中 clean、pinned 的 `upstream/openwiki` submodule。
- SelfOpenWiki 自有 MCP、Skill、配置和构建逻辑位于 submodule 外；不要直接修改或猜测 upstream 的未冻结接口。
- 个人 Wiki 必须是外部绝对 `wiki-root`，不能写入 public checkout 或 `upstream/openwiki`；运行时状态位于 `<wiki-root>.selfopenwiki`。
- 不把个人 Wiki 路径、私有 receipt、本地运行时证据、凭据或整份本地运行数据写入 SelfWorkflow 的公共 Git 历史。

## 安装前置

调用 Install 前必须先确认：绝对 Wiki root；用户理解 SelfOpenWiki 将读取/写入该目录并已处理备份与数据安全；目标是 Git 仓库时用户拥有技术写入/提交授权。缺少任一确认或路径不可验证时 fail closed：不猜目录、不创建、不迁移、不 commit、不 push。

已确认后才可构造并执行以下命令；适配器本身只负责校验和构造，不替用户执行：

```text
Setup.bat
Setup.bat --with-mcp
Install.bat --wiki-root "<absolute wiki-root>" --confirm-data-safety
Install.bat --wiki-root "<absolute git wiki-root>" --confirm-data-safety --confirm-git-authorization
```

配置只写 `%LOCALAPPDATA%/SelfOpenWiki`，不得修改 Wiki 的 `.git`。MCP entry 为 `self-openwiki/mcp-server/dist/index.js`。

## MCP 外部 Agent 流程

第一次调用必须是 `openwiki_status`。只有同时满足 `version.contractSchema=2`、`executionMode=external_agent`、`authRequired=false`、`externalAgent.ready=true` 和两个 capability 才能继续：

- `update.external-agent.begin`
- `update.external-agent.reviewed-finalize`

固定顺序是：Writer begin(start) → 仅写 candidate → prepare_review → 独立 Reviewer → reviewed finalize/publish。失败只能走冻结接口的 failure/resume；`needs_clarification` 需用户确认。外部模式不调用 OAuth、provider/model/reasoning 验证或 legacy fallback；legacy query/update/model 只能在显式 `executionMode=legacy_provider` 下使用。

知识发布不自动 commit/push。commit 前再次询问用户并只做一次 dedicated commit；push 需要单独授权。

## 可视化

只允许 loopback：

```text
node .work/openwiki/dist/cli/cli.js visualize "<wiki-root>" --port 4321 --no-open
```

适配器不添加未提供的 CLI 参数；若无法证明命令实际绑定 loopback，结果标记 `unverified`，不得声称已安全暴露。
