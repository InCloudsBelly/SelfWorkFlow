# SelfWorkFlow 启动入口

厂商无关、中文优先的轻量工作流。用户沟通和工程文档用中文；代码、路径、命令、错误、模型名、Skill 名和协议字段按事实保留。

## 启动

每个新任务只做一次：读取本入口和 runtime manifest，执行 `Discover → Capability Check → Classify`，报告：

```text
SelfWorkflow active: <profile>；mode: <Light|Full|Deep>
进度 <阶段>/<总阶段>（约 <区间>%）｜当前：<阶段>｜剩余：<阶段>｜预计：<时间或重估点>
```

分类后只读取一个 `workflow/modes/<mode>.md`，再读取命中的模块正文和必要引用。普通任务不创建 PlanGraph/RunLedger；只读任务也要分类，但不产生副作用。缺失或哈希漂移的必需模块标为 `unverified`，不得静默跳过。

## 固定流程

```text
Discover → Capability Check → Classify → Design → Plan
→ Implement/Debug → Review → Verify → optional Knowledge → Complete
```

按任务和模式按需加载：

- 代码：`modules/code.md`；C++/UE、Ponytail、项目 Review Skill 仅在命中时加载。
- Design/Plan：按 Light/Full/Deep 读取对应设计模块；Full/Deep 自动一次 `grilling`。
- 行为变更：TDD；Full/Deep 再加载 TEA。`tea-atdd`、`tea-trace`、`tea-nfr` 仅显式需要时加载。
- Review、知识、文档留痕：只加载各自模块；知识是可选扩展，不阻塞普通交付。
- Graft：只由代码路由决定。已绑定 Deep Topic 才加载 Graft 模块；未绑定或 `no-deep-topic` 完全不调用 Graft。

## 两条 Graft 路径

1. **已绑定 Deep Topic**：首次只检查一次绑定；代码读取前调用一次 `graft-ensure`；代码修改后调用一次 `graft-sync`。两个入口负责 Topic Deep 与全局非 Deep Code Map，不检查全局 Deep manifest。
2. **未绑定/`no-deep-topic`**：不读取、不构建、不查询 Graft，继续原有 Light/Full/Deep 流程。绑定检查只用于决定分支，不是 Graft 查询。

主 Agent 负责 Graft；Reviewer 不调用 Graft/provider。Graft 失败不得静默伪造 fresh 或无声降级。

## 硬规则

- 禁止虚构能力、Review、测试或 evidence；完成前必须有新鲜证据。
- Plan 是实施边界；计划外问题只记录。越界、侵入性、公共接口、持久化、安全或副作用变化时停止并重新确认。
- 代码首次编辑前形成实施契约；完成前执行适用的 Review、最窄充分验证和失败路径检查。
- 保护凭据、用户已有修改、不可逆操作和外部副作用。任务外异常立即报告，不在当前任务旁路修复。
- 工具、修改或副作用任务首条进度必须包含 profile、mode、进度、当前、剩余和预计；只在阶段变化、阻塞、重估或完成时更新。
- 知识遵循 `knowledge.read → knowledge.propose → knowledge.update`；update 需用户确认。临时记录放项目 `./selfworkflow/`，不自动 Git add。
