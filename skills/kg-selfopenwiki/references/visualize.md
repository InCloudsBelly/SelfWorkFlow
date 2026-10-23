# 可视化

开发预览经 WheelMaker/Relay、反向代理或 iframe 后持续加载、空白，或静态脚本 403 时，
按 [预览故障提示](preview-troubleshooting.md) 查询已记录的来源白名单问题；HTML 200 不代表正文可用。
仅提示可能原因并核对资源，不因此放宽来源、认证或网络边界。

只在打开或可视化时加载。先调用 `openwiki_status`；唯一 Wiki root 为 `paths.wikiRoot`，launcher 使用返回的绝对路径。

确认 `visualizer.id=selfopenwiki.zxh_wiki_viewer`、`loopbackOnly=true`、`autoOpen=false`、`wikiRootInput.flag=--wiki-root` 和 `http://127.0.0.1:{port}/wiki/local` URL 模板。adapter 经模块 `Visualize.bat --wiki-root <root>` 启动并返回 loopback URL；打开仅限该 URL。Viewer 不改 Markdown taxonomy，不执行 Git commit/push。

缺失或不匹配的 live contract 报告 `unverified` 并停止，不猜旧仓库路径、不调用 `.work/openwiki/dist/cli.js` fallback。只浏览无需加载读取正文、更新、安装或 legacy 规则。

启动 Viewer 不要求发布 capability 对、完整个人生命周期或 `externalAgent.ready=true`；只检查当前 status 身份、绑定根、launcher 和 Viewer contract。Viewer 不可用只暂停浏览，不停止其他已授权工作。

0.1.2 个人发布保持正式目录稳定，Viewer/目录监听可以常开。Viewer 和文件面板直接读文件，不参与 MCP 读取锁，提交窗口可能看到文件陆续变化；需要一致版本时，改用新版 MCP 读取或已核对的静态审查副本。只读浏览不会自动发布；不要由浏览任务持有写事务。
