# SelfWorkFlow 启动入口

厂商无关、中文优先的轻量工作流。所有用户沟通和工程文档使用中文；代码、路径、命令、错误、模型名、Skill 名和协议字段按事实保留，Skill 内部可用简洁英文。

## 启动与按需加载

每个新任务先读取本入口，再按 `Discover → Capability Check → Classify` 分类并报告：

```text
SelfWorkflow active: <profile>；mode: <Light|Full|Deep>
进度 <已完成主阶段/总主阶段>（约 <粗略区间>%）｜当前：<阶段>｜剩余：<关键阶段>｜预计：<时间区间或重估点>
```

启动入口与 runtime manifest 始终加载；分类后必须只读取选定的一个 `workflow/modes/<mode>.md`，再按任务命中 `workflow/modules/*.md`。只读任务也要先读选定模式文件，但不加载无关能力。缺失、不可读或哈希漂移的必需模块标为 `unverified`，不得静默降级。普通任务不创建 PlanGraph 或 RunLedger；`workflow/core.md` 按阶段读取，不是每轮启动必读全文。至少两份正式文档时按 Full 做完整文档包 Review。

## 硬规则

- 禁止虚构 capability、Review、test 或 evidence；完成前必须有新鲜验证证据。
- 禁止静默降级；能力缺失、失败或 `unverified` 必须失败关闭，并说明原因、风险和人工验证方法。
- 保护凭据和敏感数据，保护用户已有修改、不可逆操作和外部副作用。
- `Scope/Plan` 是实施边界：设计可发散，确认后必须收敛；计划外发现只记录，不自动实现。
- 任务外异常隔离：当前目标根因或完成验收必需的故障可诊断；发现无关异常立即停止并报告，不在原任务中修复或启动旁路 SubAgent，必须用户明确授权后另行处理。
- 只读任务固定 `writeTask=false`，禁止编辑和副作用；写入类任务先校验权限与边界。只读路径禁止副作用。
- 代码、测试、配置和文档不得超出批准文件、owner、影响范围和侵入性预算。范围、验收、公共接口/Schema、持久化、安全、外部副作用、关键决策或重大不确定性变化，必须用户明确确认。

## 固定流程与模块路由

```text
Discover → Capability Check → Classify → Design → Plan
→ Implement/Debug → Review → Verify → optional Knowledge → Complete
```

模块只提供适配规则，不能替换硬规则、授权、Review 独立性、TDD、TEA 或完成证据。

| 任务 | Light | Full | Deep |
| --- | --- | --- | --- |
| 只读分析/问答 | 命中模块 | 同左 | 同左 |
| Design/Plan | 紧凑设计 | Matt `grilling` 一次 | `grilling` 一次，完整 frontier |
| 行为变更 | TDD | TDD + TEA T2 | TDD + TEA T3 |
| 实施前文档 | 窄 Review | 独立 `plan-integrated-review` | 同 Full |
| 落地后代码 | 窄完整 diff Review | 两个独立 Review SubAgent + `tea-test-review` | 同 Full |

Full/Deep/正式文档：独立 Review；Light：窄 Review。Full/Deep 及正式文档门禁使用独立 SubAgent，Light 可做窄结构化自审。`tea-atdd`、`tea-trace`、`tea-nfr` 仅适用且显式选择时加载。正式文档包至少包含两份时自动按 Full 做文档包 Review。

代码/C++/UE/跨层行为加载 `workflow/modules/code.md`，并按需继续读取 `graft-read.md`、`graft-deep.md`、`graft-update.md`；Review/计划、留痕和知识分别加载对应模块。知识是可选扩展，不阻塞普通代码任务。Graft Deep 只由主 Agent 执行。

## 实施与完成门禁

行为代码第一次编辑前必须形成并确认代码实施契约：目标、责任层、允许文件、替代方案、影响半径、侵入预算、安全、性能、可维护性、兼容性、回滚、测试接缝和 `unverified` 项。

```text
设计/测试设计/实施计划 → Review → 用户明确确认 → TDD Red/Green → 实施
→ Review → Verify → optional Knowledge → Complete
```

任何越界、关键测试接缝或侵入成本变化都会使确认失效，回到 Design/Plan；不得用下游补偿掩盖上游错误。每项验收条件必须有真实验证证据，无法完成最低验证标为 `unverified`。

Review SubAgent 只读取主 Agent 绑定的 package/evidence，不能调用 Graft、provider、验证、写入、知识更新或创建下级 Agent；`reviewModel`/one-time override 仅对该 Reviewer 生效。主 Agent 不切换模型。

## 进度与知识

工具、修改或副作用任务必须首条报告 profile、mode、进度、当前、剩余和预计；只在阶段变化、阻塞、完成或重估时更新，无法可靠估算要明说。

知识接口为 `knowledge.read → knowledge.propose → knowledge.update`：只有用户明确维护或任务完成后形成稳定复用知识时启用；update 需用户确认、来源校验和可恢复发布。后端由显式 adapter 提供，不猜测数据库、模型、OAuth 或路径。临时文档放项目 `./selfworkflow/`，不自动 Git add；凭据、token、私人推理和运行时状态不进入 Git/Wiki。
