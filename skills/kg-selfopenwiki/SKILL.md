---
name: kg-selfopenwiki
description: Use when the knowledge profile routes local project knowledge to the SelfOpenWiki backend.
---

# SelfOpenWiki knowledge backend

这是 SelfWorkflow 的可选知识后端适配。`knowledge` profile 加载后，Wiki 相关意图默认
路由到 SelfOpenWiki；普通代码任务不加载，不能替换 SelfWorkflow 的 Design、Plan、Review
或 Verify 门禁。

## 仓库与数据边界

- 官方 OpenWiki 是 SelfOpenWiki 仓库中 clean、pinned 的 `upstream/openwiki` submodule。
- SelfOpenWiki 自有 MCP、Skill、配置和构建逻辑位于 submodule 外；不要直接修改或猜测 upstream 的未冻结接口。
- 个人 Wiki 必须是外部绝对 `wiki-root`，不能写入 public checkout 或 `upstream/openwiki`；运行时状态位于 `<wiki-root>.selfopenwiki`。选中本 module 后不要求 Conversation 猜测或重复询问路径；先调用 `openwiki_status`，以返回的 `paths.wikiRoot` 作为唯一 override Wiki root。
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

## MCP v2 个人 Wiki 流程

当前默认协议是 `selfopenwiki:personal-openwiki-v1`，不是旧的 provider 查询/更新
协议。第一次调用仍必须是 `openwiki_status`，并且除了 schema 2、external mode、
OAuth-free、`externalAgent.ready=true` 和旧 external capability 对，还必须确认以下
个人能力全部已 verified：

- `personal.lifecycle.begin`
- `personal.wiki-root.explicit`
- `personal.skill-adaptation.bound`
- `personal.lifecycle.plan`
- `personal.page-job.queue`
- `personal.lifecycle.next-page`
- `personal.candidate.write-package`
- `personal.claims.inspect`
- `personal.claims.binding`
- `personal.page.validate-assigned`
- `personal.claims.sparse-decisions`
- `personal.lifecycle.finish`
- `personal.c7-review-cas-publish`

默认知识更新固定按以下顺序，循环处理每个 PageJob：

1. `openwiki_status`：读取 SelfOpenWiki module 的 live binding；`paths.wikiRoot` 是本轮
   `openwiki_begin` 的唯一 override Wiki root。status 缺失、恢复未闭环或路径不合法时停止。
2. `openwiki_begin`：由 module 注入已绑定的 `wikiRoot`，绑定 Wiki revision、Skill 和
   upstream revision。调用方若传入不同路径，必须 fail closed。
3. `openwiki_submit_plan`：只提交页面/删除计划，生成持久化 PageJob 队列。
4. `openwiki_next_page`：一次取一个 PageJob；Writer 只能写返回的 candidate package。
5. `openwiki_inspect_page_claims`：修改或撤回已有 Claim 前读取绑定页面的完整 Claim 集。
6. `openwiki_submit_page`：提交候选页面和 sparse Claim decisions；不写正式 Wiki。
7. `openwiki_finish`：按 candidate receipt → 独立 Review receipt → C7 CAS publish 推进。

只有 `openwiki_finish` 返回结构化 `status: complete` 且 `published: true`，才能报告
个人 Wiki 已更新。`review_required`、`publish_pending`、`repair_ready` 和
`needs_clarification` 都是未完成或可恢复状态，不能提前报告成功。

SelfWorkFlow 的 `knowledge.propose` 仍只生成候选，不发布；`knowledge.update` 在
`knowledge` profile 下默认走上述六阶段。external 模式没有安全的通用 query，不能把
`openwiki_begin` 或本地路径读取伪装成 `knowledge.read`；`openwiki_query`、旧
`openwiki_update` 和模型工具只在用户明确选择 `legacy_provider` 时使用。

## 旧 MCP external-agent 兼容流程

第一次调用必须是 `openwiki_status`。只有同时满足 `version.contractSchema=2`、`executionMode=external_agent`、`authRequired=false`、`externalAgent.ready=true` 和两个 capability 才能继续：

- `update.external-agent.begin`
- `update.external-agent.reviewed-finalize`

固定顺序是：Writer begin(start) → 仅写 candidate → prepare_review → 独立 Reviewer → reviewed finalize/publish。失败只能走冻结接口的 failure/resume；`needs_clarification` 需用户确认。外部模式不调用 OAuth、provider/model/reasoning 验证或 legacy fallback；legacy query/update/model 只能在显式 `executionMode=legacy_provider` 下使用。

知识发布不自动 commit/push。commit 前再次询问用户并只做一次 dedicated commit；push 需要单独授权。

## 默认 Wiki 路由

当用户说“打开/可视化 Wiki”“总结/整理 Wiki”或“更新/沉淀到 Wiki”时，目标固定为
SelfWiki：

1. 第一调用永远是 `openwiki_status`，并以 `paths.wikiRoot` 作为唯一 Wiki root。
2. 不读取 Agent 自己的 Markdown Wiki，不猜测其他 Wiki 目录。
3. “总结 Wiki”若没有 verified 的 SelfWiki 安全 query 能力，报告 `unverified` 并停止；
   不切换 `legacy_provider`。
4. “打开可视化”必须使用 status 的新版 Viewer contract；缺失时 fail closed。

## 可视化

SelfOpenWiki status 必须提供 `visualizer.id=selfopenwiki.zxh_wiki_viewer`、绝对
`launcherPath`、`loopbackOnly=true`、`autoOpen=false`、`--wiki-root` 注入方式和
`http://127.0.0.1:{port}/wiki/local`。适配器通过 `Visualize.bat --wiki-root <root>`
启动 Viewer，并返回该 loopback URL；不得调用旧的 `.work/openwiki/dist/cli.js`，也不得
自动打开非 loopback 地址。
