# 可迁移的个人 Wiki 目录规范

个人 Wiki Git 仓库是完整知识的存储与分享边界。拉取仓库后应能直接阅读 Markdown；在另一台机器绑定到 SelfWorkflow 时，不需要携带原机器的运行区。

## 随 Git 保存的内容

```text
<wiki-root>/
  README.md              阅读入口、主题目录、适用版本与导入说明
  quickstart.md          可选的入门页
  <主题目录>/*.md        正式知识正文
  .claims/<页面路径>.json 长期 Claim、证据与正文版本绑定
  sources/*.md           可分享的来源说明、仓库/版本与相对路径
  .gitignore             仅排除本机运行产物
  .gitattributes         关闭知识文件的自动换行转换，保持 Claim 字节绑定
```

已有主题目录可以保留，不要求移动或统一重命名正文。页面之间使用仓库相对路径；代码来源用仓库身份、版本和仓库内相对路径说明。不能把阅读与导入绑定到某台机器的盘符、临时事务 ID 或未分享的原始来源文件。当前发布协议的正式内容只接受 Markdown 和 `.claims`；来源说明写成 Markdown，二进制附件通过独立来源仓库链接，不放入正式 Wiki 根目录。

`.claims` 是正式知识的一部分，应与对应 Markdown 一起提交。运行区中的 Claim 快照/决策是事务记录，不取代正式 sidecar。修改既有页面或撤回 Claim 仍通过候选、Review、CAS 和 sidecar 发布链路完成；不手工改 hash 来绕过绑定。

Claim 的 `pageVersion` 按正文的精确字节计算。跨 Windows/Linux 拉取时，Git 的 `core.autocrlf` 可能改变换行并使绑定失效。因此随仓库提交 `.gitattributes`，为 Markdown 和 JSON 使用 `-text` 禁用 Git 的自动换行转换；这不把文件变成不可读的二进制，也不改变 UTF-8 内容。新 Wiki 使用 `templates/wiki.gitattributes`。已有仓库先检查当前 Markdown/Claims 绑定与属性规则，避免无审查的批量 renormalize，保留已核对的知识文件精确字节。

## 本机运行数据

当前 MCP 布局把运行区放在同级 `<wiki-root>.selfopenwiki`，内容包括候选、锁、确认过的本机来源清单、回执与恢复状态。它不属于 Wiki 分享包，也不是第二份长期知识库。

从 MCP 0.1.2 起，默认个人发布保持正式根、既有主题目录、`.git` 和 `.claims` 稳定，只替换变更的 Markdown；恢复日志 v5 留在本机运行区。已审候选与回执继续驱动恢复，不能把半完成的文件更新当作发布成功。新版 MCP 读写通过同一锁串行；旧 MCP 读者及直接文件 Viewer 不提供跨文件一致性保证，参与一致性读写的所有连接都需升级。目录监听可保留，外部工具在提交期间同时改写正式文件仍不受支持。

- 直接阅读 Markdown 或使用 Viewer 的显式 `--wiki-root` 不需要该运行区。
- 新机器配置 MCP/发布链路后，由工具生成自己的运行状态；不能复制旧锁、旧候选或旧文件身份清单来宣称来源验证有效。
- 活跃事务或未完成恢复时，旧运行区仍需保留以恢复本机操作，不能当作随时可删除的缓存。
- 同级运行区天然位于 Wiki Git 根之外，无需为它修改 Wiki `.gitignore`。模板中的 `/.selfopenwiki/` 仅防止误提交；当前校验拒绝在正式根内放运行目录，集成也没有移动旧运行区。

运行状态可以重建，正式知识必须可从 Git 完整恢复。`.gitignore` 不得忽略 `.claims`、正式 Markdown 或分享所需的来源说明。

## 拉取后的阅读与导入

1. 拉取个人 Wiki Git 仓库，阅读根 README 与主题 Markdown。
2. 需要 Viewer 时，在已构建的 SelfWorkflow 源仓库执行：

   ```text
   Manage_SelfWorkFlow_Wiki.bat visualize --wiki-root "<absolute-wiki-git-root>"
   ```

   此显式目录路径不依赖原机器的 storage config 或 runtime。
3. 需要继续维护时，先构建工具，再将本机拉取的 Git 根绑定为 Wiki root。确认自己对目录有写入授权并已处理备份后执行：

   ```text
   Manage_SelfWorkFlow_Wiki.bat setup --with-mcp
   Manage_SelfWorkFlow_Wiki.bat install --wiki-root "<absolute-wiki-git-root>" --confirm-data-safety --confirm-git-authorization
   ```

   这里的“导入”是绑定已有 Wiki，不复制正文到工具仓库，不改 Wiki 的 Git refs，不自动 commit/push。
   绑定后还要在已安装的 knowledge 工作流中注册源模块 MCP：

   ```text
   selfworkflow wiki register --repository "<absolute-selfworkflow-source-root>"
   selfworkflow wiki register --repository "<absolute-selfworkflow-source-root>" --confirm-plan-hash "<returned-planHash>"
   selfworkflow wiki doctor --repository "<absolute-selfworkflow-source-root>"
   ```

   注册计划只替换 self-openwiki 服务，保留其他宿主配置并备份原字节。`source-ready` 表示源码/构建，
   `host-registered` 表示配置已注册，`wiki-ready` 才表示真实 status 与安全读取已通过。
   当前会话的原生工具列表可能需要新会话或重启刷新；不能把配置写入成功当作工具已暴露。
   主安装脚本选择 knowledge 且已有有效构建/绑定时也会执行注册；core 不注册 Wiki。
   此后更新继续使用正式的六阶段 personal lifecycle。总结/阅读通过 `openwiki_read`，无需 OAuth/provider。
4. 新的本地代码/文件来源需要在新机器重新 prepare 和确认；阅读既有知识无需访问那些本机来源，但不能把既有说明当作新的验证证据。

`templates/wiki-README.md`、`templates/wiki.gitignore` 与 `templates/wiki.gitattributes` 可用于新仓库。已有仓库应人工合并规范，保留现有文档和忽略规则。
