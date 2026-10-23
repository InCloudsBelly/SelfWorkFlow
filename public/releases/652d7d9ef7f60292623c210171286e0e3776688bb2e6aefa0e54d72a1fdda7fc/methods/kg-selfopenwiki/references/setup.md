# 接入、安装与绑定

仅显式安装、重绑或检查接入时加载。SelfWorkflow 源根必须明确；用 `selfworkflow wiki inspect --repository <absolute-source-root>` 检查集成模块。`source-ready` 不等于宿主已注册，缺源码/构建/新鲜证据报告 `setup-required`。不从 snapshot 猜 dist，不扫描旧独立仓库。

源根 `Manage_SelfWorkFlow_Wiki.bat` 分发 setup/install/visualize/register/doctor；以下 Setup/Install 均是 `extensions/knowledge/selfopenwiki/` 内的模块入口：

```text
Setup.bat
Setup.bat --with-mcp
Install.bat --wiki-root "<absolute wiki-root>" --confirm-data-safety
Install.bat --wiki-root "<absolute git wiki-root>" --confirm-data-safety --confirm-git-authorization
```

Install 前确认绝对 Wiki root、用户理解目录读写并已处理备份/数据安全，Git 目录还需技术写入/提交授权；同范围既有确认复用，缺失才询问。路径或确认缺失时失败关闭，不猜目录、不创建、不迁移、不 commit/push。adapter 仅校验和构造调用，执行由获得授权的宿主负责。

配置保存在 `%LOCALAPPDATA%/SelfOpenWiki`，这是本机配置位置，不是源码 Git。MCP entry 属于集成模块的 `self-openwiki/mcp-server/dist/index.js`；不改 Wiki `.git`。导入现有 Wiki 是绑定独立 Git 根，长期 Markdown、Claims、可分享来源保留，来源在本机重新验证；按当前 runtime 的 WIKI_LAYOUT.md 执行。

实际调用核对本会话已暴露工具；SDK doctor 可证明进程接线和读取，不能冒充当前会话的 native MCP 挂载。已注册但会话无工具时报告此缺口。
