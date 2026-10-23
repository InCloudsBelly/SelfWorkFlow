---
name: kg-selfopenwiki
description: 在 SelfWorkflow knowledge profile 下读取、总结、更新、恢复、绑定或可视化个人 Wiki 时使用；也用于开发预览经 WheelMaker/Relay、反向代理或 iframe 后持续加载、空白，或静态脚本 403 时查询相关排障知识。明确另选知识后端时服从该选择。其他普通代码任务、普通 Markdown 编辑、仅生成 Obsidian 产物不触发；改造 Skill/工作流由 workflow-skill-maintenance 负责。
---

# SelfOpenWiki 后端入口

SelfWorkflow 管模式、阶段、授权、Review 和验证；本 Skill 只路由 Wiki 操作。
下文的 status/readiness、发布确认、CAS 和 Wiki Git 限制仅作用于 Wiki 操作与 Wiki 仓库，不约束其他模块或 SelfWorkflow 源 Git。
先判断本轮操作，只读下表对应引用。任务换操作时补读所需引用，已读且版本未变的规则复用。
不要因 `knowledge` profile 或出现链接而加载全部引用、模块内部 Writer Skill 或完整 MCP 契约。

| 本轮操作 | 必需引用 |
| --- | --- |
| 读取、查询、总结；整理成方案且不写入 | [read.md](references/read.md) |
| 生成更新候选或已确认知识写入 | [update.md](references/update.md) |
| 诊断、恢复、已确认中止事务 | [recovery.md](references/recovery.md) |
| 打开或可视化 Wiki | [visualize.md](references/visualize.md) |
| 开发预览经 Relay/反向代理持续加载、空白或静态脚本 403：查询排障知识 | [preview-troubleshooting.md](references/preview-troubleshooting.md) |
| 安装、重绑、检查接入 | [setup.md](references/setup.md) |
| 明确选择旧 external 或 legacy_provider 协议 | [compatibility.md](references/compatibility.md) |

未说明是否写入的“整理 Wiki”先按只读/提议处理；发布仍需用户确认。

## 共用边界

- 本次 Wiki 操作的第一次 MCP 调用是 `openwiki_status`，以实时 strict schema、结构化状态和 capability 为准。默认是 schema 2、`external_agent`、`authRequired=false`；只检查本次操作需要的能力，缺工具/能力、路径不可验证或证据漂移时仅对应动作 `unverified`，不猜字段、不切换后端或 legacy fallback。`ready=false` 仍允许恢复诊断，不自动禁止 verified 的安全读取或有效 Viewer；各自遵守一致性与能力门禁。
- 一致性读取、个人发布和写恢复要求 `version.mcpServer >= 0.1.2`。旧版只用于 status/只读诊断；不以安装成功推断当前连接已升级。核对本次实际使用及已知参与同一 Wiki 操作的连接，不为证明“没有旧连接”枚举其他会话/进程。已知不兼容的并发参与者不能安全排除时，仅对应读写保持 `unverified`；诊断和独立工作继续。
- `paths.wikiRoot` 是唯一 override Wiki root；不读 Agent 自己的 Wiki、不猜其他目录。正式 Markdown、长期 `.claims` 和可分享来源属于独立 Wiki Git；同级 `<wiki-root>.selfopenwiki` 只保存本机事务状态。迁移阅读/导入规范见当前 runtime 根 `extensions/knowledge/selfopenwiki/WIKI_LAYOUT.md`，仅安装/迁移时读取。
- Wiki 实现属于 SelfWorkflow 源 Git 的 `extensions/knowledge/selfopenwiki/`，上游依赖由根 `.gitmodules` 固定；不依赖独立 SelfOpenWiki 源仓库。snapshot 保存规则与受控源码；实际 MCP/Viewer 构建使用显式 SelfWorkflow 源根，不能从 snapshot 猜 `dist` 或扫描磁盘找源码。
- `knowledge.read` 只读，`knowledge.propose` 不发布；`knowledge.update` 需有效写入授权、版本/来源校验、独立 Review 和 CAS。直接要求总结到 Wiki、更新或发布即覆盖对应范围，不重问同一授权；格式修正与无语义冲突的 revision 刷新只重新核验技术绑定。Writer 只写返回的候选包，Reviewer 只读候选；不直接写正式 Wiki，不虚构来源、hash、receipt、模型验证或发布成功。
- 发布不自动 commit/push；两者各需明确授权，已有同范围授权复用。个人路径、凭据、私有 receipt 和运行数据不写入 SelfWorkflow 公共 Git。专业规则复用 SelfWorkflow 门禁，不另起完整工作流。
