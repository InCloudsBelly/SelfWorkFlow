---
name: kg-selfopenwiki
description: 已选 SelfWiki 后读取/提议/更新/恢复/绑定/浏览个人Wiki，或Relay/代理/iframe预览加载、空白、静态脚本403的知识查询；另选后端时服从。普通代码/Markdown/Obsidian不触发。
---

# SelfOpenWiki 操作入口

SelfWorkflow 管阶段/授权/Review，本方法只路由；下述限制不约束其他模块或 SelfWorkflow 源 Git。只读当前操作引用，换操作补缺，同版已读复用；不因profile/链接预载全部引用、内部Writer或完整MCP契约。

| 本轮操作 | 必需引用 |
| --- | --- |
| 读取、查询、总结；整理成方案且不写入 | [read.md](references/read.md) |
| 生成更新候选或已确认知识写入 | [update.md](references/update.md) |
| 诊断、恢复、已确认中止事务 | [recovery.md](references/recovery.md) |
| 打开或可视化 Wiki | [visualize.md](references/visualize.md) |
| 开发预览经 Relay/反向代理持续加载、空白或静态脚本 403：查询排障知识 | [preview-troubleshooting.md](references/preview-troubleshooting.md) |
| 安装、重绑、检查接入 | [setup.md](references/setup.md) |
| 明确选择旧 external 或 legacy_provider 协议 | [compatibility.md](references/compatibility.md) |

“整理Wiki”未明确写入先只读/提议；直接要求总结到Wiki/更新/发布即对应范围授权，不重问。read只读，propose不发布，update绑定来源/版本、独立Review与CAS；Writer只写分配候选，Reviewer只读，不直接写正式Wiki、不造hash/receipt/来源/验证或成功。
本次Wiki首次MCP调用openwiki_status；以实时strict schema、结构化状态和操作capability为准，默认schema2/external_agent/authRequired=false。缺工具/能力/可验证路径或漂移仅对应动作unverified，不猜字段/切后端/legacy fallback；ready=false可诊断，安全读/有效Viewer分别判门禁。
工作流沿原documentRoot/revision；Wiki运行身份只绑定模块/依赖/Skill/协议/执行构建及能力证据，整仓dirty/无关变动/暂存/父仓或公共版本不单独失效。规则经模块验证后可热加载；换执行构建需重连MCP。若recovery.message明确“Reconnect this MCP server”，先重连再status，不能在旧连接反复retry。
一致性读、个人发布/写恢复要求version.mcpServer>=0.1.2；旧版仅status/只读诊断，不凭安装推断连接升级。只核对本次及已知同Wiki参与者，不枚举其他会话/进程；已知不兼容并发无法安全排除则对应读写unverified。
唯一Wiki根为paths.wikiRoot，不读Agent自己的Wiki或猜目录。正式Markdown/长期Claims/可分享来源属独立Wiki Git，同级<根>.selfopenwiki仅本机事务。实现属显式SelfWorkflow源根extensions/knowledge/selfopenwiki及固定submodule，不从snapshot猜dist或扫描磁盘；仅安装/迁移读其WIKI_LAYOUT.md。
发布不自动commit/push，两者各查授权并复用同范围授权；不把个人路径、凭据、私有receipt/运行数据写公共Git。专业规则不另起完整工作流。

restore_required 禁止不一致读取/写入，Viewer直接文件浏览不承诺快照一致；读取用 verified openwiki_read，先目录/revision再选页。已选SelfWiki时预览排障只读查既有知识，不建发布事务；普通网页慢、模型或任意API403不触发，知识不可用不阻原诊断。
