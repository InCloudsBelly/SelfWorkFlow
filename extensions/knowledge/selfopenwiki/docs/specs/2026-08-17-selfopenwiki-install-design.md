# SelfOpenWiki 安装入口设计

## 目标

克隆 SelfOpenWiki 后，Agent 必须先取得用户确认的外部 Wiki root，完成数据安全提示，并在目标是 Git 仓库时确认用户拥有该知识库的技术写入授权，之后才能绑定本地 MCP/Agent 集成。

## 边界

- `Setup.bat` 继续只负责构建；`Setup.bat --with-mcp` 继续构建 MCP、Win32 helper 并运行能力校验。
- 新增 `Install.bat` 与 `scripts/install.mjs` 作为绑定入口。
- Install 不迁移知识、不修改 Wiki `.git`、不 commit、不 push。
- Install 复用 `configure-storage.mjs` 的原子配置写入，不新增持久化 schema。

## Agent 前置协议

Agent 在调用 Install 前必须向用户确认：

1. 要使用的绝对 Wiki root 路径；
2. 用户已理解该目录会被 MCP 读写，已自行完成备份或接受相应风险；
3. 如果该目录是 Git 仓库，用户拥有该知识库的相关技术写入/提交授权。

Install 接收显式 `--wiki-root`、`--confirm-data-safety`，并在检测到 `.git` 时额外要求 `--confirm-git-authorization`。任何确认缺失都在构建、配置和文件写入前失败。

## 安装流程

1. 解析参数并校验绝对、存在且为非链接目录；
2. 检测目标目录是否为 Git 工作树；
3. 验证安全确认和 Git 授权确认；
4. 执行既有 `Setup.bat --with-mcp` 等价计划；
5. 调用 `configure-storage.mjs` 绑定 Wiki root；
6. 输出 MCP 入口与 Agent 调用约束。

失败路径保持 fail-closed：目标路径、确认、构建或配置任一步失败，都不修改 Wiki `.git`，且不继续后续步骤。

## 验收

- 缺少 `--wiki-root`、安全确认或 Git 授权确认时，命令返回非零并不启动构建；
- 普通目录和 Git 目录都能绑定；
- 配置只写 `%LOCALAPPDATA%\\SelfOpenWiki`；
- 现有 Setup 行为和 MCP 构建入口保持兼容；
- README 同时提供 Agent 前置协议、命令、MCP 入口和 legacy/external 调用边界。
