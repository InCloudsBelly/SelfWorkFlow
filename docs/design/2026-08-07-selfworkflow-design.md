# SelfWorkFlow 跨厂商个人开发工作流设计

日期：2026-08-07
状态：已由用户批准
首版平台：Windows
首版完整支持目标：Codex Desktop 与 Codex CLI

## 0. 2026-08-08 轻量核心修订

日常任务运行面已收缩为“轻核心、显式扩展”。默认 Agent 入口只读取
`workflow/core.md`，执行范围判断、责任层定位、必要设计/计划、最小实现、完整
diff Review 和最窄充分验证。普通代码任务不会加载本设计后续章节描述的安装
事务、证据 Schema、发布门禁、原生验收或知识后端实现。

仓库仍保留这些治理能力，供显式的 `knowledge` 或 `maintainer` profile 使用；
保留源码不代表进入默认上下文。若本设计后续章节与轻量默认运行面发生歧义，
以 [轻量代码优先核心设计](../superpowers/specs/2026-08-08-lightweight-code-first-core-design.md)
为准。完整质量 Skill 的模型行为在真实 Agent 评测前继续标记 `unverified`，默认
核心只吸收其已经过静态测试的通用原则，不虚构真实模型效果。

## 1. 目标

SelfWorkFlow 是一套独立、可版本管理、可测试、可扩展的个人开发工作流。它应当：

- 不依赖维护者机器上的其他 Skill 或仓库即可独立运行；
- 使用同一套厂商无关核心规范服务不同 Agent；
- 通过薄适配器接入 Codex、Claude Code、Cursor、OpenCode、Copilot 等宿主；
- 默认使用 Superpowers 的 Brainstorming、Plan、TDD、Debug、Review 和 Verification 方法；
- 允许用户显式启用 Grill-me，对复杂设计进行多轮压力测试；
- 根据任务复杂度和风险选择流程强度，但所有修改都必须 Review 和验证；
- 按需加载最小充分 Skill 集，避免上下文膨胀；
- 从用户指定的外部 Skill 中吸收经过审查的通用优势能力，并固化为自身能力；
- 通过可选知识后端沉淀知识，首版兼容 C7OpenWiki MCP；
- 不虚构 Agent、工具、Review、测试或知识后端能力。

## 2. 非目标

首版不承诺：

- 跨操作系统支持；
- Claude Code、Cursor、OpenCode 或 Copilot 的完整真实宿主支持；
- 自动支持未知 Agent；
- 通用数据库 MCP 生成器；
- 常驻本地守护进程或中央 MCP 控制平面；
- 自动吸收扫描到的所有外部 Skill；
- 用提示词规则冒充技术上不可绕过的安全沙箱。

## 3. 总体架构

采用“确定性核心 + 编译式薄适配器”，静态 Instructions 是不支持完整运行时的宿主所使用的降级输出模式。

```text
D:\SelfWorkFlow                 Git 唯一版本化事实源
        |
        v
编译、校验与安装计划
        |
        v
C:\Users\<user>\.agents\selfworkflow
        |
        +--> Codex 薄适配器
        +--> 按需 Skill 入口
        +--> 未来厂商适配器

%LOCALAPPDATA%\SelfWorkFlow
        +--> 安装锁、事务、备份、缓存和任务账本

可选 Knowledge Backend
        +--> C7OpenWiki MCP
```

### 3.1 三类状态边界

1. `D:\SelfWorkFlow`
   - 唯一版本化期望状态；
   - 保存工作流、Schema、Catalog、内建能力、覆盖层、适配器源、依赖锁和测试；
   - 不保存凭据、安装事务、缓存或普通任务运行状态。

2. `C:\Users\<user>\.agents`
   - 安装生成的运行时快照；
   - 不允许反向成为开发源；
   - 每个托管文件必须能追溯到 SelfWorkFlow 版本和内容 hash。

3. `%LOCALAPPDATA%\SelfWorkFlow`
   - 保存安装锁、事务日志、备份、任务账本和缓存；
   - 不进入 Git；
   - 不保存明文凭据。

项目级 `AGENTS.md`、`CLAUDE.md` 和项目 Skill 是任务输入及项目事实，不是 SelfWorkFlow 产品代码的第二事实源。

## 4. 仓库职责布局

```text
D:\SelfWorkFlow\
├── README.md
├── WORKFLOW.md
├── workflow\
│   ├── lifecycle.yaml
│   ├── policies.yaml
│   ├── protected-rules.yaml
│   └── evidence.yaml
├── schemas\
├── catalog\
│   ├── index.yaml
│   └── domains\
├── capabilities\
│   ├── code-quality\
│   ├── workflow-quality\
│   ├── documentation-quality\
│   └── knowledge-maintenance\
├── skills\
├── overlays\
│   └── superpowers\
├── adapters\
│   ├── codex\
│   ├── claude-code\
│   ├── cursor\
│   ├── opencode\
│   └── copilot\
├── dependencies\
│   └── superpowers.lock.yaml
├── extensions\
│   └── knowledge\
├── imports\
│   ├── source-registry.yaml
│   ├── extraction-records\
│   └── provenance\
├── src\selfworkflow\
├── installer\
├── tests\
│   ├── unit\
│   ├── conformance\
│   ├── installer\
│   ├── behavioral\
│   └── fixtures\
└── docs\
    ├── design\
    ├── decisions\
    ├── provenance\
    └── releases\
```

首版只创建实际实现需要的目录，不预先生成空壳。

## 5. 核心任务契约

### 5.1 正交状态

主阶段：

```text
discovered
-> capability-checked
-> classified
-> designed
-> planned
-> implemented
-> reviewed
-> verified
-> completed
```

执行状态：

```text
active | paused | blocked | failed | completed
```

验证状态：

```text
not-applicable | not-run | partial | passed | failed
```

- `paused` 表示具备明确恢复条件；
- `blocked` 表示当前环境无法继续；
- `partial` 表示仅取得部分适用验证；
- `unverified` 是由 `not-run` 或 `partial` 推导的用户可见结论；
- 只有验证通过，或纯只读任务为 `not-applicable`，才允许正常完成。

### 5.2 能力声明

适配器必须如实声明：

```text
skill-discovery
independent-context
command-execution
filesystem-read
filesystem-write
test-execution
user-confirmation
task-resume
knowledge-read
knowledge-write
```

状态只能是：

```text
supported | unsupported | unverified
```

缺少本任务必需能力时，任务暂停并报告缺失能力、用途、补齐方法、允许的单次替代及不可豁免边界。

### 5.3 最小证据

每个产生修改的任务必须能够给出：

```text
classification
capabilities
selectedSkills
acceptanceCriteria
changes
review
verification
skipped
residualRisks
```

轻量任务可以只在最终报告中呈现；暂停恢复、高风险操作、安装事务或跨 Agent 接续才写入任务账本。

## 6. 复杂度与风险

复杂度：

- `C0`：纯问答、只读查询；
- `C1`：明确的小型或机械修改；
- `C2`：多文件功能、局部重构或存在设计选择；
- `C3`：架构、迁移、跨系统或大量未知项。

风险：

- `R0`：无状态变化；
- `R1`：容易撤销的本地变化；
- `R2`：公共接口、持久数据、兼容性、性能或安全边界；
- `R3`：不可逆操作、生产发布、凭据或重大数据风险。

流程规则：

- 任一维度达到 2：完整 Brainstorming 和 Plan；
- 任一维度达到 3：提示是否使用 Grill-me；
- `C2 + R2`：提示 Grill-me；
- 用户可以升级等级；
- 降级必须记录理由，且不能越过安全规则；
- 任何修改都必须执行适用 Review 和验证。

## 7. Superpowers 与 Grill-me

Superpowers 是默认且原则上必需的工作流依赖，但正文按阶段加载：

```text
设计：brainstorming
计划：writing-plans
实现：test-driven-development / systematic-debugging
执行：executing-plans / subagent-driven-development
审查：requesting-code-review / receiving-code-review
完成：verification-before-completion
```

首次安装检测官方源和已有本地源，展示来源、路径、基础 commit、dirty 文件和内容 hash，由用户选择并写入锁文件。

Dirty 本地 Superpowers 可以在用户确认后直接使用：

- 不要求必须提交；
- 不清理、不提交、不伪装成干净版本；
- 标记为 `local-dirty/local-only`；
- 支持状态和可复现状态分开记录；
- hash 变化后旧验证证据失效并重新测试。

采用三层治理：

```text
固定或已记录来源的上游 Superpowers
-> SelfWorkFlow 个人覆盖层
-> 厂商和项目适配层
```

普通本地化修改进入覆盖层，不继续侵入上游安装目录。对外只暴露一个稳定 Grill-me ID，底层 grilling 实现作为内部依赖。

## 8. Brainstorming、Grill-me、Review 与验证

- `C0/R0`：不进入设计流程；
- `C1/R1`：简短设计检查；
- `C2/R2`：完整 Brainstorming 和 Plan；
- `C3/R3`、`C2+R2`、不可逆多方案或关键矛盾未解决：提示 Grill-me；
- 用户显式要求 Grill-me 时立即启用；
- Grill-me 清空设计前沿并获用户确认后，执行独立 Brainstorming 交叉 Review。

Review 隔离级别：

```text
L0：同一 Agent 结构化自审
L1：同一宿主的新上下文
L2：独立子 Agent，只接收验收条件、diff 和验证证据
L3：不同宿主或模型交叉验证
```

- `C1/R1` 最低 L0；
- `C2/R2` 最低 L2，不可用时询问是否接受 L1；
- `C3/R3` 最低 L2，并按需执行盲前向演练；
- Review 先检查需求符合性，再检查实现质量；
- Critical/Important 必须修正并重新 Review。

验证按产物类型定义最低套件：行为代码、Bug、配置、文档、安装器、Skill 和路由各有真实证据要求。无法执行时标记 `unverified`，不能称为通过。

## 9. 规则强度

规则分为：

- `enforced`：可以通过 Schema、安装器、hash、事务或确定性代码执行；
- `agent-policy`：依赖模型遵循并通过行为测试约束，不能声称绝对技术强制。

受保护不变量包括：

- 禁止虚构能力、Review 和测试结果；
- 禁止静默降级；
- 凭据和敏感信息保护；
- 副作用及不可逆操作授权；
- 用户已有修改保护；
- 完成前必须有新鲜验证证据。

仓库所有者可以修改受保护不变量，但必须作为破坏性工作流变更，经过明确确认、版本升级、独立 Review 和行为测试。普通 Skill、项目规则和厂商适配器不得覆盖。

## 10. Skill Catalog 与按需路由

Catalog 使用分领域 YAML 作为 Git 源，安装时编译为规范化 JSON。条目记录：

- 稳定 ID 和显示名称；
- 来源、revision 和内容 hash；
- 触发、排除和适用阶段；
- 能力要求；
- 依赖、冲突和组合规则；
- 强制条件和优先级；
- 上下文成本等级；
- 支持状态。

编译时检查 Schema、来源、同名异内容、别名、依赖环、冲突、受保护规则和厂商能力。

路由顺序：

```text
用户显式指定
-> 项目和安全强制规则
-> 文件类型、阶段和操作类型确定性匹配
-> 有界语义评分
-> 依赖闭包
-> 冲突裁决
-> 最小充分集合
```

语义阶段不能移除确定性必选 Skill。路由结果记录候选、原因、最终集合和 hash。

不设置固定 Skill 数量或字数上限；根据 C/R 等级按阶段加载。超过预算时拆分阶段，不能删除安全必选项。

## 11. 独立内建能力与外部 Skill 吸收

SelfWorkFlow 安装后不得依赖维护者本地其他 Skill。能力分为：

1. 内建通用能力：吸收、去项目化并验证后归 SelfWorkFlow 所有；
2. 可选外部 Skill：依赖特定项目或工具，存在时按需路由；
3. 维护期来源：只用于继续提炼和升级，不是运行时依赖。

首版内建代码质量原则：

```text
固定 failure envelope
-> 找到 last-good / first-bad
-> 区分 root-cause owner 与 detection point
-> 在最早拥有数据和不变量的责任层修复
-> 禁止用下游补偿掩盖上游错误
-> 检查持久数据、缓存、恢复点和临时产物
-> 计算下游失效与重建范围
-> 验证直接路径和受影响共享路径
```

并固化：证据优先、no-op 检查、所有权边界、成功与完整持久化分离、平台隔离、`plan -> review -> confirm -> apply -> reread`、dirty 改动保护、独立 Review、盲演练和证据缺口披露。

能力吸收流程：

```text
用户指定源 Skill 和目标能力
-> 锁定来源、revision、dirty 状态和 hash
-> 完整阅读相关 Skill 与必要 references
-> 提取候选原则
-> 区分通用与项目专属内容
-> 检查重复、冲突、安全和适用边界
-> 编写失败行为用例
-> 写入内建能力
-> 正向、负向、压力和冲突测试
-> 独立 Review
-> 用户确认后发布
```

来源更新只生成候选差异，不自动修改已发布能力。

`E:\kuaishou-misc-tools\skills` 是首版只读经验源。只从已跟踪、可定位 commit 的内容自动提炼；dirty 内容只能在人工确认后作为候选证据。项目名称、公司路径、内部系统和一次性结论不进入通用运行时。

## 12. 安装、合并与恢复

安装流程：

```text
doctor -> plan -> confirm -> apply -> verify
```

Doctor 只读检查环境、源状态、现有 Agent、Superpowers、C7OpenWiki 和历史事务。

Plan 生成包含源/目标 hash、变更分类、冲突、备份和测试的不可变计划。

Confirm 处理 Superpowers 选择、dirty 来源、非托管冲突、受管块漂移、C7OpenWiki 启用和单次降级。非交互环境生成计划并暂停。

Apply：

- 获取全局安装锁；
- 重新验证目标 hash；
- 写入事务日志；
- 创建精确备份；
- 使用临时文件和原子替换；
- 安装版本化快照和薄入口；
- 不修改受管标记外内容；
- 不删除未知文件或已有 Skill。

### 12.1 Task 1 Codex CLI 安全自举

Task 1 的 Windows-only bootstrap 使用完整、可保存和审阅的 Discover plan，
而不是只把 hash 当作授权内容：

```text
Discover
-> 验证受保护 portable Node/npm toolchain
-> 执行一次隔离的 metadata view
-> 输出 planSchemaVersion 2 完整计划和 planHash
-> 用户保存并确认计划
-> Apply 锁定并读取 confirmed plan
-> 精确校验 shape、三方 hash、静态 argv/env/cwd 与全部 identity
-> 创建 bootstrap root、写入精确 DACL
-> 只执行 confirmed install
-> 回读 package/lock/ACL 并写 manifest v2
```

Apply 强制同时接收绝对 `ConfirmedPlanPath` 和 `ConfirmPlanHash`。在计划
校验及 toolchain identity 复核完成前，不编译 Win32 helper、不创建目录、
不修改 ACL，也不启动外部进程。旧 hash-only Apply 和旧 plan v1 均
fail closed；Apply 不重复 metadata view。

toolchain 只能位于
`%LOCALAPPDATA%\SelfWorkFlow\bootstrap\toolchains` 的预存 anchor 下。
从 `%LOCALAPPDATA%` 到 toolchain 的目录链以及 deterministic tree inventory
必须无 reparse/escape，owner 和 DACL 不得把写入、删除或改权限能力授予
当前 SID、SYSTEM 之外的主体。计划绑定 `node.exe`、`npm-cli.js`、完整
inventory/tree hash、固定 cwd、精确环境白名单、显式 npm 配置、目标和
卸载边界。Apply 使用绝对 `node.exe` 通过 `ProcessStartInfo` 直接运行绝对
`npm-cli.js`，清空继承环境后只加入计划允许项；不通过 `npm.cmd`、PATH、
项目 `.npmrc` 或外部 `icacls`。

toolchain 与安装包树共用 canonical snapshot：按 path 排序完整
`path/type/sha256` inventory，canonical JSON 后计算 SHA-256；snapshot 在接受
结果前拒绝 reparse、越界路径和读取期间的文件漂移。

bootstrap manifest 使用 `schemaVersion: 2`，记录 `expectedCliVersion` 和
`cliVersionVerification: "not-run"`。Task 1 不执行新安装的 Codex Agent；
真实 CLI 启动、登录和模型调用仅由原生验收执行。即使持有目录、计划、
node 和 npm 入口句柄，当前 SID、SYSTEM 或 OS 特权主体对未逐文件锁定的
toolchain/安装树进行最终复核后的原地修改仍必须报告为 `unverified`，
不能宣称绝对同 SID 隔离。

Verify 检查 manifest、hash、非托管内容、幂等、Codex 发现、Superpowers 和真实行为。

事务记录 source version、apply plan hash、托管文件、前后 hash、备份、步骤和完成状态。恢复只处理该事务实际修改的文件；安装后文件再次变化时停止并询问。

## 13. 知识后端扩展

知识落地是可选能力，核心定义：

```text
knowledge.read
knowledge.propose
knowledge.update
```

首版实际实现和测试 C7OpenWiki MCP 适配器，但核心不依赖它：

- MCP 不存在时开发工作流正常运行；
- `read` 返回来源、revision/hash 和验证状态；
- `propose` 无副作用，返回预期 base revision 和 diff；
- `update` 需要明确确认并使用 compare-and-swap；
- C7OpenWiki 失败只产生知识同步待办，不使代码任务失败；
- 模型、推理等级和内部归档策略由 C7OpenWiki 管理；
- Wiki 保存模型无关的稳定知识、来源、hash、冲突和验证状态，不保存模型私有推理过程。

未来其他用户需要其他数据库时，工作流提示使用 Grill-me 设计新的 MCP 适配器，再由 Brainstorming 交叉 Review 和契约测试。首版不实现通用适配器生成器。

## 14. 厂商支持状态

支持状态使用：

```text
designed
-> static-conformance-passed
-> experimental-unverified
-> native-behavior-tested
-> supported
```

首版：

- Codex Desktop：必须真实通过；
- Codex CLI：必须解决当前 `Access is denied` 并真实通过；
- 只有两者都通过，首版才能发布并称 Codex supported；
- Claude Code、Cursor、OpenCode：experimental-unverified；
- Copilot：instructions-only；
- Unknown Agent：只输出 Bootstrap 和能力报告，不宣称支持。

首版明确 Windows-only。跨厂商不等于跨平台。

## 15. 测试策略

测试层级：

```text
单元测试
-> Schema/Catalog 契约测试
-> 安装沙箱测试
-> 工作流行为测试
-> Codex CLI 真实测试
-> Codex Desktop 新会话测试
-> C7OpenWiki 真实适配器测试
-> 独立 Review
```

测试必须覆盖：

- 核心状态和 C/R 矩阵；
- Catalog 显式触发、确定性必选、语义候选、依赖、冲突和成本；
- 外部 Skill 缺失时独立运行；
- 能力吸收的通用化、冲突、来源和基线对比；
- 代码质量的 owner/detection、持久化、下游失效和侵入性场景；
- 安装的全新、合并、冲突、漂移、幂等、升级、回滚、崩溃恢复和并发锁；
- C0 至 C3、R0 至 R3、Brainstorming、Grill-me、暂停和禁止静默降级；
- Review 隔离等级；
- C7OpenWiki 缺失、只读、无副作用提议、确认写入、revision 冲突和失败隔离；
- 正式运行时与 Git 事实源一致。

未实际运行的项目必须标记 `not-run` 或 `unverified`。

## 16. 发布与自举治理

SelfWorkFlow 的修改必须遵循自身工作流：

- 更新版本、Changelog、必要 ADR 和 release manifest；
- 核心与 Skill 行为先建立失败测试；
- 运行 Schema、路由、安装、冲突、幂等、回滚和行为测试；
- 核心阶段和安全变化执行 Brainstorming，按等级提示 Grill-me；
- 独立 Review；
- 安装态烟雾测试；
- 验证失败时不得发布到正式 `.agents`；
- 保留旧运行时和经过测试的回滚路径；
- 适配器变化只更新对应厂商状态；
- 不因一个入口通过而宣称其他入口通过。

## 17. 首版交付边界

首版发布门槛包括：

1. 厂商无关核心契约、状态机和规则优先级；
2. 分层 Catalog 和确定性路由；
3. 内建代码质量能力及外部 Skill 吸收机制；
4. 安全 `.agents` 安装、冲突、幂等、恢复和回滚；
5. Superpowers 官方、本地和 dirty 来源选择；
6. Codex Desktop 与 CLI 适配及真实验收；
7. SelfWorkFlow 自身 Review、测试和发布门禁；
8. 可选但真实兼容的 C7OpenWiki MCP 适配器。

其他厂商的完整行为支持和通用知识数据库适配器生成器后续迭代。

## 18. 验收原则

- SelfWorkFlow 在没有维护者本地专项 Skill 时独立运行；
- 所有宣称能力都有真实测试证据；
- 所有未验证能力明确标记；
- 所有修改经过适用 Review 和验证；
- 安装不覆盖用户非托管内容；
- 不允许静默降级；
- 不把提示词规则虚构成技术强制；
- 运行时不依赖 E 盘经验源；
- C7OpenWiki 缺失不阻塞核心任务；
- Codex Desktop 与 CLI 未全部通过前不发布首版。
