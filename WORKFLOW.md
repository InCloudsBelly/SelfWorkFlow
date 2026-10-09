# SelfWorkFlow 启动入口

厂商无关、中文优先的轻量工作流。用户沟通和工程文档用中文；代码、路径、命令、错误、模型名、Skill 名和协议字段按事实保留。

## 启动

每个新任务只做一次：读取本入口和 runtime manifest，执行 `Discover → Capability Check → Classify`，报告：

```text
SelfWorkflow active: <profile>；mode: <Light|Full|Deep>
进度 <阶段>/<总阶段>（已完成主阶段/总主阶段，约 <区间>%）｜当前：<阶段>｜剩余：<阶段>｜预计：<时间或重估点>
```

分类后只读取一个 `workflow/modes/<mode>.md`，再读取命中的模块正文和必要引用。普通任务不创建 PlanGraph/RunLedger；只读任务也要分类，但不产生副作用。缺失或哈希漂移的必需模块标为 `unverified`，不得静默跳过。

## 固定流程

```text
Discover → Capability Check → Classify → Design → Plan
→ Implement/Debug → Review → Verify → optional Knowledge → Complete
```

按任务和模式按需加载：

- 代码/C++/UE/跨层行为：`modules/code.md`；C++/UE、Ponytail、项目 Review Skill 仅在命中时加载；非代码任务不自动加载，并按需读取 `graft-read.md`。
- Design/Plan：按 Light/Full/Deep 读取对应设计模块；Full/Deep 自动一次 `grilling`。
- 行为变更：TDD；Full/Deep 再加载 TEA。`tea-atdd`、`tea-trace`、`tea-nfr` 仅显式需要时加载。
- Review、知识、文档留痕：只加载各自模块；知识是可选扩展，不阻塞普通交付。
- Graft：已有可用且 fresh 的全局非 Deep Code Map 自动使用，无须显式启用或 Topic 绑定；stale 时询问更新，缺失不自动初始化；细则读取 `graft-read.md`。

## 两条 Graft 路径

1. **默认全局 Map**：读取阶段用 `graft-ensure` 只读检查；fresh 自动使用，stale 询问，同意后加 `--allow-update`。Agent 修改/撤回后合并调用一次 `graft-sync`；外部编辑/分支切换后重新检查，过期先询问。只维护全局非 Deep Code Map，不逐行重复构建。
2. **显式 Deep**：仅用户明确要求时恢复或选择 Topic，再使用/更新 Deep；绑定本身不触发 Deep 检查。明确禁用 Graft 时尊重禁用，继续原有 Light/Full/Deep 流程。

主 Agent 负责 Graft；Reviewer 不调用 Graft/provider。Graft 失败不得静默伪造 fresh 或无声降级。

## 质量门禁

Full/Deep 的正式设计、测试设计和实施计划由独立 SubAgent Review；至少两份正式文档时提交完整文档包和最终文档包 hash。按影响半径执行侵入性预算；测试覆盖不能反向驱动生产架构。代码实施契约要求第一次编辑测试或生产代码前形成明确实施确认，完成 `Review → 用户确认 → TDD` 后再实施；确认失效即回到设计。官方 Graft MCP 是代码阅读入口，SelfWorkFlow 只负责边界、路由、写后更新和显式 Deep 桥接。

## 硬规则

- 禁止虚构能力、Review、测试或 evidence；完成前必须有新鲜证据。
- Plan 是实施边界；计划外问题只记录。越界、侵入性、公共接口、持久化、安全或副作用变化时停止并重新确认。
- 代码首次编辑前形成实施契约；完成前执行适用的 Review、最窄充分验证和失败路径检查。
- 保护凭据、用户已有修改、不可逆操作和外部副作用。任务外异常隔离：任务外异常立即报告，不在当前任务旁路修复。
- 非当前目标根因或完成验收必需的故障，必须用户明确授权后另行处理。
- 工具、修改或副作用任务首条进度必须包含 profile、mode、进度、当前、剩余和预计；只在阶段变化、阻塞、重估或完成时更新。
- 知识遵循 `knowledge.read → knowledge.propose → knowledge.update`；update 需用户确认。临时记录放项目 `./selfworkflow/`，不自动 Git add。
