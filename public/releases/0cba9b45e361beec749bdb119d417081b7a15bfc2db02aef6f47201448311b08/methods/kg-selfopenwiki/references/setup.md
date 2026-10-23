# 接入、安装与绑定

仅显式安装、重绑或检查接入时加载。SelfWorkflow 源根必须明确；用 `selfworkflow wiki inspect --repository <absolute-source-root>` 检查集成模块。`source-ready` 不等于宿主已注册，缺源码/构建/新鲜证据报告 `setup-required`。不从 snapshot 猜 dist，不扫描旧独立仓库。

源根 `Manage_SelfWorkFlow_Wiki.bat` 分发 setup/install/visualize/register/doctor；以下 Setup/Install 均是 `extensions/knowledge/selfopenwiki/` 内的模块入口：

```text
Setup.bat
Setup.bat --with-mcp
Install.bat --wiki-root "<absolute wiki-root>" --confirm-data-safety
Install.bat --wiki-root "<absolute git wiki-root>" --confirm-data-safety --confirm-git-authorization
```

Install 前核对绝对 Wiki root、数据安全及该目录的技术写入授权；同范围既有确认复用，缺失才询问。允许写入 Git 工作区不等于授权 commit/push。路径或必要授权缺失时仅暂停绑定/写入，不猜目录、不迁移或执行未授权 Git 操作；已绑定的读取和其他独立工作可继续。adapter 仅校验和构造调用，执行由获得授权的宿主负责。

配置保存在 `%LOCALAPPDATA%/SelfOpenWiki`，这是本机配置位置，不是源码 Git。MCP entry 属于集成模块的 `self-openwiki/mcp-server/dist/index.js`；不改 Wiki `.git`。导入现有 Wiki 是绑定独立 Git 根，长期 Markdown、Claims、可分享来源保留，来源在本机重新验证；按当前 runtime 的 WIKI_LAYOUT.md 执行。

实际调用核对本会话已暴露工具；SDK doctor 可证明进程接线和读取，不能冒充当前会话的 native MCP 挂载。已注册但会话无工具时报告此缺口。

宿主应支持为快照、来源准备和发布等长操作配置调用端等待预算。大型 Wiki 的候选初始化可能超过 60 秒；维护客户端可先采用 300 秒，再依据实际规模和耗时调整。该预算只改变客户端等候，不改变生产限额、来源核验或发布门禁。

调用端超时或断线不证明后端没有推进。重连后先查 status，按原 run 和真实恢复状态继续；不据此另建更新、删除运行区或伪造 abort。未知恢复义务仍保留保护，先诊断其实际阶段。
