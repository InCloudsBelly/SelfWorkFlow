# 方法索引

按用户意图和排除条件选择方法；仅读取本任务需要的内容。方法是普通文档，无需原生 Skill 发现。

- [code-quality](code-quality/METHOD.md)：追踪行为代码的责任层、状态与失效关系，用于解释、诊断或变更行为；纯文档和配置文本维护不触发。
- [code-review](matt-pocock/code-review/METHOD.md)：审查用户指定的 PR、分支、提交或未提交代码，综合检查 Standards/Spec、行为风险和测试证据。普通实现、测试执行或机械文档同步不触发；工作流内审查由 review 模块调度。
- [codebase-design](matt-pocock/codebase-design/METHOD.md)：Shared vocabulary for designing deep modules. Use when the user wants to design or improve a module's interface, find deepening opportunities, decide where a seam goes, make code more testable or AI-navigable, or when another skill needs the deep-module vocabulary.
- [content-research-writer](content-research-writer/METHOD.md)：在研究并撰写有来源的文章、教程、专题报告，或需要长文结构与实质改写时使用。普通检索问答、短摘要/翻译、自动工作报告、流程内部计划/Review留痕及仅格式导出不触发。
- [cpp-core](cpp-core/METHOD.md)：Use for reading, designing, implementing, debugging, maintaining, or reviewing C and C++ code. Load this compact core for C++ tasks, then read only the specialist reference files justified by ownership, template/type, concurrency, ABI, performance, safety, build, native-debugging, or Unreal Engine signals. Do not trigger for ordinary documentation or non-C++ tasks.
- [diagnosing-bugs](matt-pocock/diagnosing-bugs/METHOD.md)：仅用于根因不明、难复现、跨模块或性能回归等需要系统诊断的问题，或用户明确要求完整诊断循环。普通错误解释、静态日志分析、原因明确的小修复、机械配置和文档修订不触发；不能仅凭失败、报错、慢或 debug 字样加载。明确的领域问题优先由对应专业 Skill 处理。
- [grill-me](matt-pocock/grill-me/METHOD.md)：A relentless interview to sharpen a plan or design.
- [grill-with-docs](matt-pocock/grill-with-docs/METHOD.md)：A relentless interview to sharpen a plan or design, which also creates docs (ADR's and glossary) as we go.
- [grilling](matt-pocock/grilling/METHOD.md)：Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.
- [implement](matt-pocock/implement/METHOD.md)：Implement a piece of work based on a spec or set of tickets.
- [implement-spec](implement-spec/METHOD.md)：仅在用户显式要求 implement-spec 大型多任务实施编排，且 spec、至少两个 tickets 的依赖图、计划 Review 和实施确认齐备时使用。普通 implement、单 ticket、仅规划或仅审查不触发。
- [json-canvas](json-canvas/METHOD.md)：仅在明确创建或编辑 JSON Canvas、.canvas 文件或 Obsidian 画布产物时使用。泛称流程图/脑图、Mermaid、HTML/FCanvas、PNG/SVG、静态科学图和聊天内可视化不触发。
- [kg-selfopenwiki](kg-selfopenwiki/METHOD.md)：在 SelfWorkflow knowledge profile 下读取、总结、更新、恢复、绑定或可视化个人 Wiki 时使用；也用于开发预览经 WheelMaker/Relay、反向代理或 iframe 后持续加载、空白，或静态脚本 403 时查询相关排障知识。明确另选知识后端时服从该选择。其他普通代码任务、普通 Markdown 编辑、仅生成 Obsidian 产物不触发；改造 Skill/工作流由 workflow-skill-maintenance 负责。
- [knowledge-backend](knowledge-backend/METHOD.md)：Use for the optional, vendor-neutral knowledge.read, knowledge.propose, and knowledge.update lifecycle after a concrete knowledge backend has been explicitly selected.
- [obsidian-bases](obsidian-bases/METHOD.md)：在创建或编辑 Obsidian Bases/.base 文件、或明确为 Obsidian 笔记建立可筛选表格/卡片视图时使用。Excel/CSV、SQL、Redmine 表格、普通 Markdown、C++ base class 和未指定后端的知识库不触发。
- [obsidian-markdown](obsidian-markdown/METHOD.md)：在创建或编辑 Obsidian/vault 笔记及其 wikilinks、callouts、embeds、properties 时使用。普通 Markdown、README、SKILL.md、通用 YAML frontmatter 或仅提及 Obsidian 不触发。
- [ponytail](ponytail/METHOD.md)：Lazy senior dev mode: the smallest change that fully solves the task, and a reply a busy human understands in one read. Use on any coding task (writing, fixing, refactoring, reviewing, choosing dependencies) and when the user says "ponytail", "be lazy", "simplest solution", "yagni", or complains about over-engineering or bloat. Levels: lite, full (default), ultra. 
- [ponytail-audit](ponytail-audit/METHOD.md)：Quality audit of a whole repo: bugs, security holes, what breaks under real load, risky code without tests, slow paths, and what to delete, merge or split. Ranked, each finding explained in plain English. One-shot report, changes nothing. Use for "audit this codebase", "review the whole repo", "find bloat", "what can I delete", /ponytail-audit.
- [ponytail-debt](ponytail-debt/METHOD.md)：List every `shortcut:` comment (and older `ponytail:` ones) as a debt ledger. One-shot report, changes nothing. Use for "ponytail debt", "what did ponytail defer", "list the shortcuts", /ponytail-debt.
- [ponytail-help](ponytail-help/METHOD.md)：Quick reference for ponytail levels, skills and commands. One-shot display. Use for /ponytail-help, "ponytail help", "how do I use ponytail".
- [ponytail-review](ponytail-review/METHOD.md)：Review whether a code change is over-engineered, unnecessarily complex, or can be a smaller diff; also use for /ponytail-review. Generic PR/commit review uses code-review. Ordinary workflow Review does not automatically load this specialist.
- [tdd](matt-pocock/tdd/METHOD.md)：Test-driven development. Use when the user wants to build features or fix bugs test-first, mentions "red-green-refactor", or wants integration tests.
- [tea-quality](tea-quality/METHOD.md)：Use only when the user explicitly requests TEA test design, ATDD, test review, traceability, NFR, framework or CI assessment. Full/Deep tasks, test levels, ordinary testing and workflow maintenance do not trigger TEA. Uses pinned references without a project _bmad directory.
- [testing-review-quality](testing-review-quality/METHOD.md)：用于行为变更 TDD 和测试证据核验；普通 Review 直接读 review.md，纯分析或机械文档不因阶段名称加载。
- [to-spec](matt-pocock/to-spec/METHOD.md)：Turn the current conversation into a spec and publish it to the project issue tracker: no interview, just synthesis of what you've already discussed.
- [to-tickets](matt-pocock/to-tickets/METHOD.md)：Break a plan, spec, or the current conversation into a set of tracer-bullet tickets, each declaring its blocking edges, published to the configured tracker (edges as text in one file per ticket locally, or native blocking links on a real tracker).
- [ui-ux-pro-max](ui-ux-pro-max/METHOD.md)：在创建、改造或审查真实用户界面且需要视觉、布局、交互或可访问性设计时使用。纯崩溃/线程/GPU诊断、静态科学绘图、文档排版和按既有规则的微小机械修改不触发。
- [workflow-quality](workflow-quality/METHOD.md)：用于文件变更、验收或外部副作用的证据与既有修改保护；纯查询和普通 Review 不因阶段名称触发。
- [workflow-skill-maintenance](workflow-skill-maintenance/METHOD.md)：维护 Skill/工作流的职责、触发和按需加载；仅新增、改造、集成时启用，纯审查或使用现有能力不触发。
