---
name: obsidian-bases
description: "在创建或编辑 Obsidian Bases/.base 文件、或明确为 Obsidian 笔记建立可筛选表格/卡片视图时使用。Excel/CSV、SQL、Redmine 表格、普通 Markdown、C++ base class 和未指定后端的知识库不触发。"
---

# Obsidian Bases

从本任务已绑定的引用根（文档模式 documentRoot；显式契约用已核验 runtime 根）读取 `references/community-skills/obsidian-skills/skills/obsidian-bases/METHOD.md`，复用当前版本与所需引用身份。此入口处理 Obsidian 笔记的 .base 视图，不接管电子表格、SQL 或任务平台查询。

读取给定 .base、可用笔记属性与目标视图；保留现有 filters、formulas、properties、summaries 和 views。只按授权调整筛选、分组、公式或展示，不创建猜测的 vault 或重写笔记内容。

验证 YAML/表达式结构和被引用属性，说明缺少实际 Obsidian 渲染/求值能力的部分；语法解析不等于真实视图已运行。需要改变笔记正文或产物格式时再使用相应入口。

当前知识后端与存储/确认规则保持由现有 owner 决定，不能自动切换到 Obsidian。
