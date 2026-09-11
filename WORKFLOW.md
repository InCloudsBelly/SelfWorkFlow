# SelfWorkFlow 启动入口

这是厂商无关的轻量工作流。所有用户沟通和工程文档使用中文；代码、路径、命令、错误原文、模型名、Skill 名和协议字段按事实保留。表达保持紧凑，但不得删减技术信息、进度、范围、Review、验证、风险或失败证据。

## 启动与按需加载

每个新任务先读取本入口；完成分类后报告：

```text
SelfWorkflow active: <profile>；mode: <Light|Full|Deep>
进度 <已完成主阶段/总主阶段>（约 <粗略区间>%）｜当前：<阶段>｜剩余：<关键阶段>｜预计：<时间区间或重估点>
```

按 `Discover → Capability Check → Classify` 顺序工作：先检查本阶段 capability 状态，再按 `复杂度 × 风险 × 副作用` 分类；边界不明向上升级，用户可覆盖。启动入口与 runtime manifest 始终加载；分类后必须只读取选定的一个 `workflow/modes/<mode>.md`，再按任务命中读取 `workflow/modules/*.md`。只读任务也要先读选定模式文件，但不加载无关能力模块。缺失、不可读或哈希漂移的必需模块标为 `unverified`，暂停受影响阶段；不得静默读取旧文件、假定能力存在或自行降级。`workflow/core.md` 是按阶段读取的实现参考，不是每轮启动必读全文。

## 不可覆盖的硬规则

- 禁止虚构 capability、Review、test 或 evidence；完成前必须有新鲜验证证据，没有新鲜证据不得宣称完成。
- 禁止静默降级；能力缺失、失败或 `unverified` 必须说明原因、风险和可行的人工替代。不可替代的门禁不得绕过。
- 保护凭据和敏感数据、保护用户已有修改、不可逆操作和外部副作用；授权不足先停。
- `Scope/Plan` 是实施边界。设计阶段可发散，Plan 确认后实施必须收敛；计划外发现只记录为相邻改进，不自动实现。若阻塞验收，停止受影响编辑，修订 Plan 和侵入预算并重新确认。
- 任务外异常隔离：当前目标根因或完成验收必需的故障可按本任务诊断；发现无关的工作流、安装或环境异常，立即停止并报告，不在原任务中调查、修复、重构或启动旁路 SubAgent；必须用户明确授权后另行处理。
- 只读任务固定 `writeTask=false`：禁止编辑、禁止副作用；`implement`、`debug`、`document`、`install`、`publish` 和 `knowledge-write` 才可为 `true`，路由前校验不匹配即拒绝。
- 代码、测试、配置或文档不得超出批准文件、owner、影响范围和侵入性预算；高侵入改动必须有更窄方案比较和用户确认。
- 范围/验收变化、公共 API/ABI/Schema、持久化、敏感数据、外部或不可逆副作用、受保护默认值、用户改动和重大不确定性都是关键决策，必须用户明确确认。

## 固定主流程

```text
Discover → Capability Check → Classify → Design → Plan
→ Implement/Debug → Review → Verify → optional Knowledge → Complete
```

执行与验证状态分开记录。只加载当前阶段所需模块；模块只提供适配规则，不能替换硬规则、授权、Review 独立性、TDD、TEA 或完成证据。

闭合命中映射：代码/C++/UE/跨层行为 → `workflow/modules/code.md`；Review/计划门禁 → `workflow/modules/review.md`；知识读写 → `workflow/modules/knowledge.md`；设计、测试、实施、Review 留痕 → `workflow/modules/artifacts.md`。未命中不加载；显式模块也必须符合当前阶段。

| 任务 | Light | Full | Deep |
| --- | --- | --- | --- |
| 只读分析/问答 | 命中能力模块；不自动 Grill/TEA | 同左 | 同左 |
| 修改的 Design/Plan | 紧凑设计；不自动 Grill | Matt `grilling` 一次 | Matt `grill-me` 一次；其上游负责 frontier，不再另启 `design-grilling` |
| 行为变更 Implement/Debug | TDD；命中 `code` | TDD + TEA T2 + Full 设计路由 | TDD + TEA T3 + Deep 设计路由 |
| 实施前文档 Review | 窄 Review | 独立 `plan-integrated-review` | 独立 `plan-integrated-review` |
| 落地后代码 Review | 窄完整 diff Review | Standards/Spec 两个独立 SubAgent + `tea-test-review` | 同 Full |

Full/Deep 的 Grill 只执行一次；用户可在任意强度显式选择。`tea-atdd`、`tea-trace`、`tea-nfr` 只在适用且用户显式选择时加载。至少两份正式文档（设计、测试设计或实施计划）时，实施前自动升级为 Full 并做完整文档包 Review。

## 修改门禁

涉及行为代码前形成代码实施契约：目标、owner、允许文件、替代方案、影响半径、侵入预算、安全、性能、可维护性、兼容性、回滚、测试接缝和 `unverified` 项。固定顺序为：

```text
设计/规格 +（Full/Deep：TEA/测试设计）+ 实施计划
→（Full/Deep/正式文档：独立 Review；Light：窄 Review）
→ 用户明确实施确认 → TDD Red/Green → 实施
```

固定门禁摘要：Review → 用户确认 → TDD。

Full/Deep 必须记录真实 RED（证明预期行为尚未满足）和 GREEN（同一路径通过），再跑最窄相关回归。测试覆盖不能反向驱动生产架构；优先测试边界、已有扩展点或黑盒验证。任何公共 API/ABI/Schema、持久化格式、全局宏/Build variant、共享热路径、关键测试接缝、非必要调用者或独立子系统扩展都会使原确认失效，必须停下重新设计、Review、确认。

## Review、验证与完成

Review 包绑定批准请求、Plan、阶段/尝试、完整文档、最终文档包 hash、适用规则、项目 Review Skill 清单和完整 task delta（含已提交、暂存、未暂存、未跟踪、删除、二进制和文件模式）。Full/Deep 代码 Review 使用两个独立临时 SubAgent，项目 `.selfworkflow/review.yaml` 中匹配且 hash 校验通过的 Skill 优先，通用 Review Skill 只补充；主对话不切换模型。模型从机器本地 Agent 配置选择，SubAgent 生命周期必须是 `created → executed → cleaned`；缺能力、身份不独立、清理失败或 hash 漂移均为 `unverified`。Critical/Important 必须清零，Minor 必须有处置。

每项验收条件都要有真实证据：直接路径、失败路径、状态不变量和最窄回归；配置还要查解析与实际消费者；文档还要查格式、链接、引用和最终 diff。验证收据绑定命令、工作目录、输入摘要、时间、退出码、失败数和消费者结果；包或工作区漂移使旧 Review/验证失效。无法完成的检查列为 `unverified`，写明风险和人工验证法。

代码阅读优先使用已配置且新鲜的 Graft；它是 `primary code-reading`，查询固定 no-refresh；保留 `rg` 做精确文本确认。Graft 缺失或过期时，普通任务可明确标注后使用旧图或 `rg`，需要新鲜图证据的任务失败关闭；CodeGraph 仅作遗留/用户显式指定 Provider。代码任务按路由加载 Ponytail；非代码任务不自动加载。Ponytail 只约束代码任务的设计、实现和审查，不改变表达风格、不启用上游全局配置或 hooks。高侵入信号包括影响半径、公共枚举、全局编译宏和共享热路径；若测试覆盖不能反向驱动生产架构，选择更窄边界。代码实施契约要求在第一次编辑测试或生产代码前完成，并经用户明确确认；确认失效时回到设计。Full/Deep 及正式文档门禁使用独立 SubAgent；Light 可做窄结构化自审，但不得冒充独立 Review。

## 可选知识与留痕

知识是可选的厂商无关扩展：`knowledge.read → knowledge.propose → knowledge.update`。任务完成 Review/验证后，若产生稳定、可复用知识，只提示一次是否沉淀；用户明确要求维护知识库时直接进入知识流程。知识后端由显式 adapter 提供，缺能力不阻塞普通代码任务，也不得猜测数据库、模型或 API。工作文档和临时记录放项目 `./selfworkflow/`，不自动 Git add；凭据、token、运行时状态和私人推理不进入 Git/Wiki。

## 当前批次边界

当前工作流将锁定的 Graft submodule 作为默认代码图 Provider：新代码任务先做项目级只读预检；首次缺图时惰性初始化；Agent 写入完成后由 Host 发出一次 `agent_write` 事件，SelfWorkFlow 合并路径并运行一次仅结构更新的 Worker。查询固定 no-refresh，不会隐式 build；Worker 不执行 Deep、不启用 Graft 自带 Hook/Watcher/daemon。Graft 缺失、过期或边界无效时按模式标记 `unverified`，需要新鲜图证据的任务失败关闭，普通任务才可降级到 `rg`。CodeGraph 保留为遗留/显式路径，不自动删除用户配置。任何超出当前 Plan 的改动先停止并报告。
