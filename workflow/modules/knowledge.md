# 知识模块

仅约束 knowledge.read/propose/update 与 Wiki，不适用于普通代码、Markdown、方案留痕或其他模块。知识可选，不阻塞代码交付；稳定结论每任务仅提示一次，不因 profile/链接自动启动。

## 操作与后端

read 只读；propose 只产候选；update 要写入授权、版本/来源核验、独立 Review 与可恢复发布，CAS/恢复遵循所选 adapter 协议。直接要求“总结到 Wiki/更新/审核后发布”即对应范围授权，不重复确认；草稿/方案/意图不明先不发布。正文/来源用中文，不写凭据、私人推理、临时事务、完整敏感原文或无效结论。
显式后端优先。已选 selfopenwiki 或 knowledge profile、个人 Wiki 未另选后端时用 [skills/kg-selfopenwiki/SKILL.md](../../skills/kg-selfopenwiki/SKILL.md)，只读当前操作引用；不加载内部 Writer/完整 MCP 契约。其他后端走显式 adapter，不猜模型/数据库/OAuth/路径。
SelfOpenWiki 的 status、根路径、读/Viewer、恢复和独立运行身份规则只由其后端入口管理。显式选择其他 adapter 时仅遵循该 adapter 契约，不调用 SelfWiki 工具或依赖其路径。缺能力/漂移记 unverified，普通交付继续并列待同步。

## 写作与评价

仅新增、实质更新或明确评估 Wiki 才读[统一质量标准](../../skills/knowledge-backend/references/wiki-quality.md)及[正文契约](../../skills/knowledge-backend/references/article-contract.md)，条件性细则由二者单向路由；读取/打开不加载写作/评分材料，措辞修正仅查影响项。
Writer/PageJob 与同一 Reviewer 接收适用指标、范围/单元/条件、目标锚点、来源和缺口，按同版规范完成写作、评分、质询与走查；修订只复核影响项。质量达标与发布成功分别判断，不新建评分/MCP字段或确认流程。写作要解释充分、可学习和可实施，不能为节省工作流 token 省正文关键细节。
