---
name: obsidian-markdown
description: "在创建或编辑 Obsidian/vault 笔记及其 wikilinks、callouts、embeds、properties 时使用。普通 Markdown、README、SKILL.md、通用 YAML frontmatter 或仅提及 Obsidian 不触发。"
---

# Obsidian 笔记格式

只处理明确的 Obsidian 笔记语境。从本任务已绑定的引用根（文档模式 documentRoot；显式契约用已核验 runtime 根）读取 `references/community-skills/obsidian-skills/skills/obsidian-markdown/SKILL.md`，复用绑定身份并只核对所需引用。按实际语法再读该目录 references 中的 PROPERTIES、EMBEDS 或 CALLOUTS，不全部预加载。

先确认输入、目标笔记/vault 和现有格式，保留正文技术事实、已有属性、链接与用户修改。用 vault 内 wikilinks、外部 Markdown 链接与所需 Obsidian 扩展；不因普通 .md 或 frontmatter 自动套用这些格式。

只改授权的笔记。不能从提及 Obsidian 推断知识后端，也不迁移 SelfOpenWiki 或扫描/更新未指定 vault。知识生命周期和确认由现有 owner 管理。

研究与成文交给需要时的 content-research-writer；.base 视图用 obsidian-bases，明确 .canvas 产物用 json-canvas。组合任务只在对应阶段加载相关方法并复用已有事实。
