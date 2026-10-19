# 可视化

只在打开或可视化时加载。先调用 `openwiki_status`；唯一 Wiki root 为 `paths.wikiRoot`，launcher 使用返回的绝对路径。

确认 `visualizer.id=selfopenwiki.zxh_wiki_viewer`、`loopbackOnly=true`、`autoOpen=false`、`wikiRootInput.flag=--wiki-root` 和 `http://127.0.0.1:{port}/wiki/local` URL 模板。adapter 经模块 `Visualize.bat --wiki-root <root>` 启动并返回 loopback URL；打开仅限该 URL。Viewer 不改 Markdown taxonomy，不执行 Git commit/push。

缺失或不匹配的 live contract 报告 `unverified` 并停止，不猜旧仓库路径、不调用 `.work/openwiki/dist/cli.js` fallback。只浏览无需加载读取正文、更新、安装或 legacy 规则。

0.1.2 个人发布保持正式目录稳定，Viewer/目录监听可以常开。Viewer 和文件面板直接读文件，不参与 MCP 读取锁，提交窗口可能看到文件陆续变化；需要一致版本时，改用新版 MCP 读取或已核对的静态审查副本。只读浏览不会自动发布；不要由浏览任务持有写事务。
