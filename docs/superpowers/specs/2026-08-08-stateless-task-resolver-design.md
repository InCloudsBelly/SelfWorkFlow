# SelfWorkFlow 无状态任务解析器设计

## 背景与决策

轻量核心、分类器、Catalog 路由、Superpowers 阶段覆盖和安装器已经分别存在，但没有一个可执行入口把这些决策组合成同一份任务计划。只依赖静态 `WORKFLOW.md` 可以让能力较强的 Agent 人工遵循流程，却无法用确定性测试证明实际选择结果；引入长期任务编排器又会违背轻量核心目标。

本次选择无状态解析器：输入一份显式任务描述和编译后的 Catalog，输出一份只读、确定性、可审计的执行计划。解析器不执行代码、不调用模型、不写知识库、不保存任务状态，也不替代最终证据门禁。

对比方案：

- 重型编排器：可以管理完整生命周期，但默认成本、宿主耦合和维护复杂度过高，拒绝。
- 继续只依赖 Instructions：上下文最轻，但无法闭合实现与测试调用链，保持为宿主降级入口而非唯一实现。
- 无状态解析器：复用现有确定性模块，由外部 Agent 保留执行权，采用。

## 接口

CLI 增加：

```text
selfworkflow resolve --catalog <catalog.json> --request <request.json>
```

请求显式提供当前阶段、操作类型、C/R、是否修改、能力报告、Superpowers 来源状态和可选路由线索。首版只支持轻量代码流程的 `read-only`、`design`、`plan`、`implement`、`debug`、`review` 和 `verify`，不隐式进入安装、发布或知识流程。

`core` runtime 同时携带一份很小的请求示例，但默认不把它加入 Agent 上下文。安装后的薄入口只提示 Agent 在需要确定阶段能力时读取该示例并调用解析器；解析器不可用时继续遵循 `WORKFLOW.md`，并如实标记自动解析为 `unverified`。

解析顺序固定为：

```text
严格输入校验
-> C/R 分类
-> 基础能力门禁
-> Catalog 路由
-> 当前阶段 Superpowers 选择
-> Review/验证最低要求
-> 执行计划
```

只有能力门禁、Catalog 路由和 Superpowers 覆盖均为可执行状态时，结果才是 `active`；任一环节缺少证据或能力时返回 `paused`，不得静默降级。`selectedSkills` 保持 Catalog 顺序在前、阶段 Skill 在后并去重。

结果使用规范化请求的 `requestHash` 和编译 Catalog 的 `catalogHash` 绑定本次决策输入；同一输入产生相同 hash，能力、阶段、C/R 或路由线索变化后旧计划不得继续冒用。

## Review 与验证要求

- 只读任务不要求修改 Review 或修改验证。
- 普通修改最低为 `L0` 结构化自审。
- 需要完整设计的任务最低为 `L2`；进入 Review 阶段而缺少 `independent-context` 时暂停。
- 所有修改任务都输出 `verification.required: true` 和 `narrowest-sufficient` 策略；真实验证证据仍由现有完成门禁检查。
- `explicitGrill` 只影响设计阶段的阶段 Skill；结束后仍要求独立 Brainstorming 交叉 Review。

## 安全边界

- 请求中的能力和 Superpowers 状态是外部 Agent 提交的显式声明，不是身份验证；解析结果原样保留其状态并根据缺口暂停。
- 输入错误只返回稳定错误码，不回显不受信内容。
- 解析器不读取任意源码路径，不产生文件副作用，不修改运行时或正式安装。
- OpenWiki 和其他知识后端不在本次范围内。

## 验收

- 从构建后的 `core` runtime 和沙箱安装快照调用真实 CLI `resolve`。
- 安装后的 Codex 托管块能够发现解析命令和快照内请求示例。
- `implement`、`review`、`verify` 分别只追加对应阶段 Superpowers Skill。
- 缺少 Superpowers 或高等级 Review 能力时返回 `paused`。
- 无效输入失败关闭且不泄露输入。
- 现有分类、路由、运行时和安装测试保持通过。
