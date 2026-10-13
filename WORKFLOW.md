# SelfWorkFlow 启动入口

厂商无关、中文优先的轻量工作流。所有用户沟通和工程文档使用中文；代码、路径、命令、错误、模型名、Skill 名和协议字段按事实保留。

## 启动

每个新任务只做一次：runtime manifest 始终加载（确定路径为安装 snapshot 根目录的 `artifact-manifest.json`），只提取身份与本次模块 hash，不把整份文件清单注入上下文、不搜索历史日志。读取本入口后执行 `Discover → Capability Check → Classify`，报告：

```text
SelfWorkflow active: <profile>；mode: <Light|Full|Deep>
进度 <阶段>/<总阶段>（已完成主阶段/总主阶段，约 <粗略区间>%）｜当前：<阶段>｜剩余：<阶段>｜预计：<时间或重估点>
```

分类后必须只读取选定的一个 `workflow/modes/<mode>.md`，再读取命中的模块正文和必要引用；只读任务也要先读选定模式文件。普通任务不创建 PlanGraph/RunLedger，也不重复加载 `workflow/core.md` 或契约 Host 的 package/receipt/runner 细则；仅显式 contract-managed task 或由 conforming Host 按契约承接的任务加载它们；宿主具有契约能力本身不切换任务模式。缺失、不可读或哈希漂移的必需模块标为 `unverified`，不得静默跳过。

profile 表示能力集合，不决定模式：`knowledge` 不自动升级 Full。局部修复按实际复杂度、风险和项目最低要求分类；不能仅因涉及代码或已有审查就要求整项目设计。进入所选阶段前预检必需适配器的引用闭包；缺失时报告具体文件和影响，不转嫁为项目缺少 `_bmad`。

## 固定流程

```text
Discover → Capability Check → Classify → Design → Plan
→ Implement/Debug → Review → Verify → optional Knowledge → Complete
```

按任务和模式按需加载：

- Skill/工作流维护：仅明确新增、改造或集成个人 Skill/工作流，或优化触发描述时加载 `skills/workflow-skill-maintenance/SKILL.md`；日常使用现有能力不加载，Anthropic 上游只按需作为方法引用。

- 界面设计：真实 UI 的视觉、布局、交互或可访问性设计命中 `skills/ui-ux-pro-max/SKILL.md`；纯崩溃/性能排查、普通文档和科学绘图不触发。
- 研究写作：文章、教程、专题报告的研究、结构或实质改写命中 `skills/content-research-writer/SKILL.md`；短问答、摘要、翻译、工作报告和流程内部留痕不触发；文件导出沿用既有产物 Skill。
- Obsidian 格式：明确 Obsidian 笔记语法、Bases/.base 或 JSON Canvas/.canvas 产物时，分别加载 `skills/obsidian-markdown/SKILL.md`、`skills/obsidian-bases/SKILL.md`、`skills/json-canvas/SKILL.md`；普通 Markdown、通用表格或流程图不触发，也不自动选择知识后端。

- 代码/C++/UE/跨层行为：`modules/code.md`；C++/UE、Ponytail、项目 Review Skill 仅在命中时加载；非代码任务不自动加载，并按需读取 `codegraph-read.md`。
- Design/Plan：按选定模式读取当前阶段的设计模块；Full/Deep 的 Design/Plan 或行为实现/调试按模式自动一次 `grilling`，纯分析不自动加载。
- 行为变更：TDD；Full/Deep 按阶段再加载 TEA test-design / test-review，非行为任务不自动加载。`tea-atdd`、`tea-trace`、`tea-nfr` 仅显式需要时加载。
- 可选增强：仅显式启用 `tea-framework`、`tea-ci`、`ponytail-debt`、`implement-spec` 时读取 `modules/optional-integrations.md`；不改变普通任务默认路径。
- Review、知识、文档留痕：只加载各自模块；知识是可选扩展，不阻塞普通交付。
- CodeGraph：项目级 `.codegraph/` 是全局 CodeMap；读取边界与实际代码批次自动核对工作区，missing 初始化、增量同步后验证及必要重建、indexing/busy 有界等待；有效证据复用与触发边界只见 `codegraph-read.md` 和 `codegraph-update.md`。

只读任务保持 `writeTask=false`，禁止编辑、禁止副作用（代码任务仅允许 `codegraph-read.md` 定义的项目 `.codegraph/` 缓存维护例外）。非代码任务按 operationType 执行。契约模式能力未验证时失败关闭，不静默转普通模式或产生副作用；普通任务不要求契约专用回执，必要工具不可用仍报告阻塞。

## 职责与调用复用

- 在宿主 system/developer 指令与用户授权边界内，SelfWorkflow 唯一决定模式、阶段、授权与能力选择；专业 Skill 只提供方法和检查项，不重新启动流程。`code-quality` 管代码责任层；`workflow-quality` 管证据与副作用；`testing-review-quality` 管 TDD/验证；Review 统一归 `workflow/modules/review.md`。Superpowers 仅显式启用，不叠加第二套流程。
- 同一任务只读一次当前入口、runtime manifest 和选定模式；模块正文首次命中才读，同路径同版本且上下文仍完整时复用。范围、模式、规则版本、运行时身份变化或上下文丢失时只补读受影响内容；不能用摘要替代未读的必需规则。
- 只加载当前阶段所需模块及其必要引用；出现链接、安装某能力或 profile 含该能力不等于触发。后续阶段到达时再加载，能力缺失标为 `unverified`，不靠省略规则节约 token。
- 独立只读查询尽量批量执行，限定目录、字段和输出量；依赖操作按序执行。相同输入的有效证据复用；相关变更、失败或外部漂移才重查，不无变化轮询、不因重复门禁再请求已获得的授权。
- 已注入且完整的入口不重复读取；同一 Skill、阶段、输入证据和版本组合只执行一次；同阶段不同职责的 Skill 仍按需调用，证据变化只重做受影响项。按名称出现不等于需要加载。Design/Plan 可合并为一份文档；Grill 只处理未决的重要选择，环境事实自行查明，已授权范围内的实现细节不重复问人。规则不能代替宿主权限隔离。
- 主 Agent 负责 CodeGraph 生命周期；Reviewer 不调用 provider。全局图检查和写后同步分别按 `workflow/modules/codegraph-read.md`、`codegraph-update.md` 执行；不能永久缓存 fresh 或绕过漂移确认。CodeGraph 失败不得静默伪造 fresh 或无声降级。

## 质量门禁

Full/Deep/正式文档：独立 Review；Light：窄 Review。Full/Deep 及正式文档门禁使用独立 SubAgent，Light 可做窄结构化自审。正式设计、测试设计和实施计划由独立 SubAgent Review；至少两份正式文档时提交完整文档包和最终文档包 hash。按影响半径执行侵入性预算；测试覆盖不能反向驱动生产架构。代码实施契约要求第一次编辑测试或生产代码前形成明确实施确认，完成 `Review → 用户确认 → TDD` 后再实施；确认失效即回到设计。关键决策必须用户明确确认；Scope/Plan 是实施边界，简化或可选能力不能替换硬规则。官方 CodeGraph MCP 是代码阅读入口，SelfWorkFlow 只负责项目边界、生命周期路由和写后更新。

## 硬规则

- 同范围已有明确实施授权可复用，记录请求、批准范围、计划版本/内容 hash 和禁止项；阶段变化、补齐环境事实或窄豁免不自动撤销授权。范围、owner、侵入预算或关键风险变化才重新确认。用户明确禁止编译/测试时遵守，记录 `not-run/unverified`；普通任务可交付已授权的修改及验证缺口，但不得称测试通过。细则见 `testing-review-quality`，契约完成门禁不变。
- 禁止虚构 capability、Review、test 或 evidence；完成前必须有新鲜验证证据。
- 禁止静默降级；不可用能力必须明确标记 `unverified` 或失败关闭。
- Plan 是实施边界；计划外问题只记录。越界、侵入性、公共接口、持久化、安全或副作用变化时停止并重新确认。
- 代码首次编辑前形成实施契约；完成前执行适用的 Review、最窄充分验证和失败路径检查。
- 保护凭据和敏感数据，保护用户已有修改、不可逆操作和外部副作用。任务外异常隔离：任务外异常立即报告，不在当前任务旁路修复。
- 非当前目标根因或完成验收必需的故障，必须用户明确授权后另行处理。
- 任何 fallback、压缩或可选能力不能替换硬规则；发现当前目标根因或完成验收必需的故障时，先记录证据再处理。
- 工具、修改或副作用任务首条进度必须包含 profile、mode、进度、当前、剩余和预计；只在阶段变化、阻塞、重估或完成时更新。
- 知识遵循 `knowledge.read → knowledge.propose → knowledge.update`；update 需用户确认。临时记录放项目 `./selfworkflow/`，不自动 Git add。
