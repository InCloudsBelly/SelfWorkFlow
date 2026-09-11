# SelfWorkFlow 工作流压缩设计

状态：用户已确认实施；Batch A 最小修复已写入，验证证据见本次任务；未提交、未安装、未推送。

## 目标与语言边界

在不改变核心行为的前提下，压缩每轮启动时加载的工作流上下文，并把大文档拆成按阶段、按任务匹配加载的模块。为兑现按需边界，仅收窄已有自动 Grill/TEA/代码 Review 的 operation predicate；显式模块选择仍须满足阶段、强度、operation/write selector、能力和安全门禁。

用户沟通、`WORKFLOW.md`、工作流文档、项目工程文档、决策记录、验证报告和知识落地正文全部使用中文。路径、代码、符号、命令、错误原文、模型名、Skill 名和协议字段可按事实原样保留；Skill 内部私有推理可以使用简洁英文，但不得把英文叙述泄漏到用户或项目文档。

本批次只实施工作流压缩。Graft Provider 仍是后续独立任务，不在本批次新增 Provider、Submodule、Installer、Worker、缓存或 Wiki Hook。

## 加载契约

`WORKFLOW.md` 只保留启动必需内容：

- 中文输出、文档语言和 Caveman-lite 规则；
- 完整硬约束：禁止虚构 capability/Review/test/evidence；禁止静默降级；保护凭据和敏感数据；禁止未授权副作用和不可逆操作；保护用户已有修改；完成前必须有新鲜证据；遵守 Scope/Plan 边界；关键决策必须确认；任务外异常立即停止并报告；
- 固定阶段：
  `discover → capability → classify → design → plan → implement/debug → review → verify → knowledge? → complete`；
- Light/Full/Deep 判断；
- 路由规则：先读取 `workflow/modes/<mode>.md`，再只读取命中的任务模块；
- 缺失、不可读、哈希漂移时标记 `unverified` 并停止受影响阶段，不回退读取旧的大文档。模块内容不新增独立信任根；Batch A 只复用现有 artifact/runtime manifest 校验，不宣称 manifest 与模块具备新的互相独立信任关系。

新增按需文件：

```text
workflow/modes/light.md
workflow/modes/full.md
workflow/modes/deep.md
workflow/modules/code.md
workflow/modules/review.md
workflow/modules/knowledge.md
workflow/modules/artifacts.md
```

`workflow/core.md`保留为 Host/实现参考，但不再复制长篇规范到启动入口；它不能替代启动硬约束，也不能让缺失模块静默通过。Graft 不在本批次模块清单中；Batch A 的显式 Graft 请求固定返回 `unsupported`。

## 保留的流程语义

- Light：紧凑设计、窄 Review、最小充分验证；不自动启动 Grill 或 TEA。
- Full：自动使用 Matt `grilling`，加载 TEA、TDD 和独立 Review。
- Deep：自动使用 Matt `grill-me` 及其上游 `grilling` frontier，加载 TEA T3 和独立 Review。
- Full/Deep 的代码 Review 使用独立、临时、按 Agent 配置模型的 SubAgent；匹配的项目 Review Skill 优先，通用 Review Skill 仅补充。
- 代码编辑前固定顺序：代码实施契约 → Plan → 独立 Review → 用户明确实施确认 → TDD。
- 侵入性、收敛、任务外异常、能力门禁、证据、进度、知识生命周期、WorkArtifact、受保护规则和失败关闭语义不得削弱；Light 允许如实的窄结构化自审，Full/Deep 与正式文档门禁才要求独立 Review。

## 闭合路由表

启动入口和 runtime manifest 始终加载；这里的 `core` 指压缩后的启动硬约束，不是重新加载完整 `workflow/core.md`。`writeTask=false`、禁止编辑、禁止副作用和能力/证据门禁始终有效。下表只决定额外模块，不决定是否允许写入。

| 任务/阶段 | Light | Full | Deep |
| --- | --- | --- | --- |
| 只读分析/问答 | 启动入口 + 命中能力模块 | 同 Light；不自动 Grill/TEA | 同 Light；不自动 Grill/TEA |
| 修改任务 Design/Plan | `modes/light.md` + `code.md`（命中时） | `modes/full.md` + `design-grilling` 一次 + Plan | `modes/deep.md` + `design-grill-me` 一次；其上游内部完成更深 frontier，不再独立加载 `design-grilling` |
| `implement`/`debug` 且改变行为 | `code.md` + TDD；无自动 Grill/TEA | `code.md` + TDD + `tea-test-design` + Full 设计路径 | `code.md` + TDD + `tea-test-design` + Deep 设计路径 |
| 实施前文档 Review | 窄 Review | `review.md` + `plan-integrated-review` | `review.md` + `plan-integrated-review` |
| Full/Deep 代码落地 Review | 窄 Review | `review.md` + `review-code-review` + `tea-test-review` | `review.md` + `review-code-review` + `tea-test-review` |
| `tea-atdd`/`tea-trace`/`tea-nfr` | 仅显式选择 | 仅显式选择 | 仅显式选择 |

显式模块只能在其适用任务/阶段中加入；冲突、越权或缺少能力时阻止路由。`graft` 不属于 Batch A 的活跃模块；显式要求 Graft 固定返回 `unsupported`，不得进入实现路径。

## 受保护规则归属

| 规则 | 启动入口 | 阶段模块 | 失败行为 |
| --- | --- | --- | --- |
| 不虚构能力、Review、测试、完成证据 | 必须保留 | 可补充 | 直接阻止声明成功 |
| 不静默降级；敏感信息和凭据保护 | 必须保留 | `code`/`knowledge` 可补充 | `unverified`并暂停 |
| 用户改动、不可逆副作用、关键决策确认 | 必须保留 | `artifacts`/`knowledge` 可补充 | 未确认不得执行 |
| Scope/Plan、侵入预算、发现问题不扩 scope | 必须保留 | `code`/`review` 可补充 | 停止并回到设计 |
| Review、TDD、TEA、完成证据 | 路由入口保留门禁 | `full`/`deep`/`review` | 缺证据不得完成 |
| 文档/知识中文落地 | 必须保留 | `knowledge`/`artifacts` | 不符合则不发布 |

“保留”必须由行为测试或明确的 fail-closed 测试证明，不能只用“仍然存在于某个文件”证明。

## Graft 后续交接

Graft 设计、测试和实现另行评审。当前仅保留未来适配位置，不新增 `code-graft` 活跃路由，也不宣称 Graft 已支持。后续 Graft 任务必须独立绑定其设计/TEA/Plan、owner、文件符号、侵入预算、原生能力证据和 CodeGraph 遗留迁移方案。CodeGraph 现有配置/缓存不在本批次删除。

## 禁止范围

本批次不改变 CodeGraph 默认入口、显式调用、安装提示、README、历史设计文档、机器配置或缓存；CodeGraph→Graft 迁移在 Batch B 另行处理。不得修改受保护 lifecycle/evidence Schema、Review 独立性、用户配置、凭据、Wiki 数据、无关模块、公共 API/ABI、持久化格式、全局宏、共享热路径或项目调用者。不得为了测试便利扩大生产架构。不得在没有真实 tokenizer 收据时声称 token 降幅。

## 验收

1. 先用固定脚本以严格 UTF-8 解码、拒绝 BOM、保留 CRLF、按 Unicode code point 计数，重新封存当前 `WORKFLOW.md` 基线；35,022 仅为预研基线。新启动入口不超过基线的 30% 且不超过 10,500 code points。
2. 使用临时、锁定版本 `tiktoken==0.11.0` 的 `o200k_base` 做分别绑定输入 hash 的 token 对比，`disallowed_special=()`；记录 tokenizer/version、encoding、基线/候选输入字节 hash、基线/候选 token 数和测量脚本 hash。该结果只称为 proxy，不冒充任意厂商模型 tokenizer；候选目标为不超过基线 70%。tokenizer 缺失、版本漂移或收据缺失时，不阻止核心压缩实施，但 token 优化只能报告 `unverified`，不得声称完成。
3. Light/Full/Deep 只加载选定模式和匹配模块；正触发、误触发、冲突、缺失、漂移均有测试。
4. Full 精确路由 `design-grilling`、`tea-test-design`、`plan-integrated-review`、`review-code-review`、`tea-test-review` 和行为变更 TDD；Deep 只路由一次 `design-grill-me`/frontier，不重复 `design-grilling`；`tea-atdd`、`tea-trace`、`tea-nfr`仍为显式可选。
5. Batch A 新增、修改或生成的用户可见工程文档和落地记录为中文；路径、代码、命令、错误原文等技术字段可原样保留；Skill 源文档可保留原语言。
6. 包构建和 Installer dry-run 能包含全部按需文件，并证明原有 CodeGraph 路由未被压缩批次意外破坏；真实安装是单独授权动作。
7. 最终完整 diff Review 和新鲜验证无 Critical/Important；每个 Minor 有处置记录。
