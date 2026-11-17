# 方法索引

按用户意图和排除条件选择方法；仅读取本任务需要的内容。方法是普通文档，无需原生 Skill 发现。

- [code-quality](code-quality/METHOD.md)：在需要理解代码行为、定位责任层或分析状态失效关系时提供指导；不因普通编辑、配置或文档维护自动开启完整流程。
- [code-review](matt-pocock/code-review/METHOD.md)：审查用户指定的 PR、分支、提交或未提交代码；围绕真实需求、项目标准、行为风险与验证证据，不自动增加独立审查团队或修复流程。
- [codebase-design](matt-pocock/codebase-design/METHOD.md)：Shared vocabulary for designing deep modules. Use when the user wants to design or improve a module's interface, find deepening opportunities, decide where a seam goes, make code more testable or AI-navigable, or when another skill needs the deep-module vocabulary.
- [content-research-writer](content-research-writer/METHOD.md)：在研究并撰写有来源的文章、教程、专题报告，或需要长文结构与实质改写时使用。普通检索问答、短摘要/翻译、自动工作报告、流程内部计划/Review留痕及仅格式导出不触发。
- [cpp-core](cpp-core/METHOD.md)：Use for reading, designing, implementing, debugging, maintaining, or reviewing C and C++ code. Load this compact core for C++ tasks, then read only the specialist reference files justified by ownership, template/type, concurrency, ABI, performance, safety, build, native-debugging, or Unreal Engine signals. Do not trigger for ordinary documentation or non-C++ tasks.
- [diagnosing-bugs](matt-pocock/diagnosing-bugs/METHOD.md)：仅用于根因不明、难复现、跨模块或性能回归等需要系统诊断的问题，或用户明确要求完整诊断循环。普通错误解释、静态日志分析、原因明确的小修复、机械配置和文档修订不触发；不能仅凭失败、报错、慢或 debug 字样加载。明确的领域问题优先由对应专业 Skill 处理。
- [grill-me](matt-pocock/grill-me/METHOD.md)：A relentless interview to sharpen a plan or design.
- [grill-with-docs](matt-pocock/grill-with-docs/METHOD.md)：A relentless interview to sharpen a plan or design, which also creates docs (ADR's and glossary) as we go.
- [grilling](matt-pocock/grilling/METHOD.md)：Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.
- [implement](matt-pocock/implement/METHOD.md)：Implement a piece of work based on a spec or set of tickets.
- [implement-spec](implement-spec/METHOD.md)：仓库实施中，用户明确选用，或主 Agent 判断目标明确、多个独立验收且低写冲突的工作包具有并行/上下文隔离收益时使用。已有领域分工不叠加；小任务、单票、高耦合、仅规划或审查不自动触发，维护/审查技能本身不触发。
- [json-canvas](json-canvas/METHOD.md)：仅在明确创建或编辑 JSON Canvas、.canvas 文件或 Obsidian 画布产物时使用。泛称流程图/脑图、Mermaid、HTML/FCanvas、PNG/SVG、静态科学图和聊天内可视化不触发。
- [kg-selfopenwiki](kg-selfopenwiki/METHOD.md)：已选 SelfWiki 后读取/提议/更新/恢复/绑定/浏览个人Wiki，或Relay/代理/iframe预览加载、空白、静态脚本403的知识查询；另选后端时服从。普通代码/Markdown/Obsidian不触发。
- [knowledge-backend](knowledge-backend/METHOD.md)：衔接用户要求的知识操作与所选后端，内容指导按需参考；普通代码、临时记录或泛化知识词不自动触发写作、协作或发布流程。
- [obsidian-bases](obsidian-bases/METHOD.md)：在创建或编辑 Obsidian Bases/.base 文件、或明确为 Obsidian 笔记建立可筛选表格/卡片视图时使用。Excel/CSV、SQL、Redmine 表格、普通 Markdown、C++ base class 和未指定后端的知识库不触发。
- [obsidian-markdown](obsidian-markdown/METHOD.md)：在创建或编辑 Obsidian/vault 笔记及其 wikilinks、callouts、embeds、properties 时使用。普通 Markdown、README、SKILL.md、通用 YAML frontmatter 或仅提及 Obsidian 不触发。
- [ponytail](ponytail/METHOD.md)：Lazy senior dev mode: the smallest change that fully solves the task, and a reply a busy human understands in one read. Use on any coding task (writing, fixing, refactoring, reviewing, choosing dependencies) and when the user says "ponytail", "be lazy", "simplest solution", "yagni", or complains about over-engineering or bloat. Levels: lite, full (default), ultra. 
- [ponytail-audit](ponytail-audit/METHOD.md)：Quality audit of a whole repo: bugs, security holes, what breaks under real load, risky code without tests, slow paths, and what to delete, merge or split. Ranked, each finding explained in plain English. One-shot report, changes nothing. Use for "audit this codebase", "review the whole repo", "find bloat", "what can I delete", /ponytail-audit.
- [ponytail-debt](ponytail-debt/METHOD.md)：List every `shortcut:` comment (and older `ponytail:` ones) as a debt ledger. One-shot report, changes nothing. Use for "ponytail debt", "what did ponytail defer", "list the shortcuts", /ponytail-debt.
- [ponytail-help](ponytail-help/METHOD.md)：Quick reference for ponytail levels, skills and commands. One-shot display. Use for /ponytail-help, "ponytail help", "how do I use ponytail".
- [ponytail-review](ponytail-review/METHOD.md)：Review whether a code change is over-engineered, unnecessarily complex, or can be a smaller diff; also use for /ponytail-review. Generic PR/commit review uses code-review. Ordinary workflow Review does not automatically load this specialist.
- [pr](matt-pocock/pr/METHOD.md)：撰写或更新 PR 正文时使用，包括已请求创建 PR 时准备正文；仅审查 PR 代码、普通交付、出现 PR 链接不触发。
- [retro](matt-pocock/retro/METHOD.md)：用户明确要求复盘当前或指定编码会话、审查工作流效率或 token 浪费时使用；普通代码审查、交付总结、每票结束不触发。
- [sympy](sympy/METHOD.md)：用于数学推理与建模、算法设计及其约束/复杂度/数值性质分析，或积分、微分、方程、矩阵、几何与 LaTeX 公式生成；包括 knowledge/Wiki 中的数学解释和公式写作。普通业务流程、机械代码改名、无数学内容的知识浏览或仅修正 Markdown 样式不触发。
- [tdd](matt-pocock/tdd/METHOD.md)：Test-driven development. Use when the user wants to build features or fix bugs test-first, mentions "red-green-refactor", or wants integration tests.
- [tea-quality](tea-quality/METHOD.md)：Use only when the user explicitly requests TEA test design, ATDD, test review, traceability, NFR, framework or CI assessment. Full/Deep tasks, test levels, ordinary testing and workflow maintenance do not trigger TEA. Uses pinned references without a project _bmad directory.
- [testing-review-quality](testing-review-quality/METHOD.md)：在需要选择、设计或核验测试与验证证据时使用；TDD 是可选方法，普通行为修改、分析或机械文档不自动开启固定测试流程。
- [to-spec](matt-pocock/to-spec/METHOD.md)：Turn the current conversation into a spec and publish it to the project issue tracker: no interview, just synthesis of what you've already discussed.
- [to-tickets](matt-pocock/to-tickets/METHOD.md)：Break a plan, spec, or the current conversation into a set of tracer-bullet tickets, each declaring its blocking edges, published to the configured tracker (edges as text in one file per ticket locally, or native blocking links on a real tracker).
- [ui-ux-pro-max](ui-ux-pro-max/METHOD.md)：在创建、改造或审查真实用户界面且需要视觉、布局、交互或可访问性设计时使用。纯崩溃/线程/GPU诊断、静态科学绘图、文档排版和按既有规则的微小机械修改不触发。
- [wiki-workflow](wiki-workflow/METHOD.md)：指导 Agent 生成、维护、审查有来源、可理解、可实施的 Wiki；默认原理／实现详解，按需生成使用／排障指南及适配 DocHub、SelfOpenWiki。普通问答、仅诊断当前故障或未要求成文的临时笔记不触发。
- [workflow-quality](workflow-quality/METHOD.md)：在需要判断验收证据、既有修改保护或副作用边界时提供指导；不因文件变更或阶段名称自动增加计划、审查和确认流程。
- [workflow-skill-maintenance](workflow-skill-maintenance/METHOD.md)：修改、集成或精简 Skill/工作流时提供维护指导；纯审查或使用现有能力不自动开启维护流程。
