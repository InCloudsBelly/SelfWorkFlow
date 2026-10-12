# SelfOpenWiki Viewer 默认路由设计

## 状态

已获用户确认，进入实现。

## 背景与边界

当前 SelfWorkflow 的 SelfOpenWiki 适配器仍把可视化入口固定为旧的
`.work/openwiki/dist/cli/cli.js visualize`。SelfOpenWiki 仓库已经提供新的
`visualizer/zxh_wiki_viewer`，其正式启动入口是仓库根目录的 `Visualize.bat`，
并由 `scripts/visualize.mjs` 负责启动 Next.js Viewer。

本次只解决两个路由问题：

1. “打开 Wiki 可视化”默认使用 SelfOpenWiki 声明的新 Viewer。
2. 已加载 `knowledge` profile 的对话在“总结/整理/更新 Wiki”语义下默认路由
   到 SelfWiki personal backend，不读取 Agent 自己的 Markdown Wiki，也不静默
   切换到 legacy provider 或其他 Wiki。

不把 Viewer 代码复制进 SelfWorkflow，不修改 `upstream/openwiki`，不把个人 Wiki
路径、运行时 receipt 或凭据写入公共工作流仓库。

## 方案

### 1. SelfOpenWiki 持有 Viewer 契约

SelfOpenWiki 的 `openwiki_status` 增加可选的实时 `visualizer` 描述。新版本在状态
中提供：

- 固定 ID `selfopenwiki.zxh_wiki_viewer` 和 Viewer contract schema 版本；
- 已解析且已校验的 `Visualize.bat` 绝对路径；
- `loopbackOnly=true`、`autoOpen=false`；
- Wiki root 通过 `--wiki-root` 参数注入；
- URL 模板 `http://127.0.0.1:{port}/wiki/local`。

状态仍保持 MCP contract schema 2；旧运行时没有 `visualizer` 时，普通知识更新不
被无故破坏，但请求默认可视化必须 fail closed，不能回退到旧 OpenWiki CLI。

`Visualize.bat`/`visualize.mjs` 接受绝对 `--wiki-root`，启动前验证它是存在的目录，
并将同一路径注入 `SELFOPENWIKI_WIKI_ROOT`。未提供覆盖路径时才读取 SelfOpenWiki
本地 storage 配置。Viewer 仍只监听 loopback，不自动打开浏览器。

### 2. SelfWorkflow 只消费实时契约

`SelfOpenWikiAdapter` 新增严格的 Viewer 状态校验和默认启动命令构造：

- 先调用 `openwiki_status`，并使用返回的 `paths.wikiRoot`；
- 必须存在匹配的 Viewer ID、contract schema、loopback、注入方式和 URL 模板；
- 必须验证 launcher 是现存绝对普通文件；
- 命令通过 `cmd.exe` 调用 SelfOpenWiki 的 `Visualize.bat`，传入 live Wiki root
  和用户选择的端口；
- 返回对应 loopback URL，供宿主浏览器打开；
- 任一字段缺失、路径变化、端口非法或 root 不匹配均失败关闭。

SelfWorkflow 不再拼接 `.work/openwiki/dist/cli/cli.js`，也不根据
`paths.openWikiRoot` 猜测 SelfOpenWiki 仓库位置。

### 3. 默认知识路由

`knowledge` profile 加载时，知识模块把以下自然语言意图绑定到 `selfopenwiki`：

- 打开/可视化 Wiki；
- 总结/整理 Wiki；
- 更新/沉淀到 Wiki。

路由第一步始终是 `openwiki_status`。个人 Wiki 操作继续使用
`selfopenwiki:personal-openwiki-v1`；`legacy_provider` 仅在用户明确指定时启用。
当前 external-agent 没有安全通用 query 能力时，“总结 Wiki”报告 SelfWiki read
能力 `unverified`，而不是读取本地 Agent 文档或静默切换后端。

## 验证策略

### SelfOpenWiki

- Viewer CLI 参数、绝对 Wiki root 覆盖、环境变量注入和 URL 模板测试；
- MCP status schema 接受新 Viewer 描述，并拒绝错误 ID、非 loopback、错误注入方式；
- runtime/minimal status 都不会虚构 Viewer；
- 现有 SelfOpenWiki MCP、skill、source/版本门禁保持通过。

### SelfWorkflow

- Adapter 测试 live status → launcher command 的完整绑定；
- 缺失 Viewer、旧 Viewer、root mismatch、非绝对 launcher、非法端口均失败关闭；
- 旧 CLI 字符串不再出现在适配器和知识 Skill 的默认路径；
- knowledge module 行为测试确认 SelfWiki 默认路由、legacy 显式边界和无 fallback。

## 不做的事情

- 不实现新的 Wiki query MCP 工具；
- 不自动 commit/push SelfWiki；
- 不把 Viewer 加入普通代码任务的默认门禁；
- 不保留旧 OpenWiki visualizer 作为隐式 fallback；
- 不修改或清理用户在两个仓库中的其他未提交改动。
