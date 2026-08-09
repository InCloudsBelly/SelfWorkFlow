# SelfWorkFlow V3 设计—实现一致性审计

- 日期：2026-08-09
- 审计范围：轻量核心、自适应质量 V3、C++/Provider V3、一键安装器及对应测试
- 基准：仓库实际文件和自动化测试是能力事实源；目标设计不自动等于已实现能力

## 结论

当前版本适合作为“轻量日常工作流 + 显式 V3 契约管理切片”，不适合作为已经完成全部自适应模块的
生产 Host。日常任务直接遵循 `WORKFLOW.md`，只按阶段加载命中的 Skill；PlanGraph/RunLedger 仅在用户明确
要求契约管理，或 conforming Host 能提供新鲜能力证据时创建。这样保留了 V3 的严格失败关闭边界，同时不会
让缺少 Host 证据的普通编码任务被错误暂停。

## 对照矩阵

| 设计能力 | 实际状态 | 证据与边界 |
| --- | --- | --- |
| 轻量代码主干 | 已实现 | `workflow/core.md` 与六个薄适配器；普通任务不创建 PlanGraph/RunLedger |
| 所有修改默认 Brainstorming | 已实现为 Agent 策略 | 核心文档、路由矩阵和行为测试一致；只读任务不触发 |
| V2/V3 显式分派 | 已实现并自动化验证 | V3 Schema、Catalog/Pipeline loader、Resolver、PlanGraph、RunLedger 与 V2 回归 |
| V3 默认生产执行 | 未启用 | checked-in 核心模块缺少真实 source/adapter/runtime/behavior 证据，解析保持 `paused` |
| 有界运行期选择 | 已实现契约内核 | 只能从静态 eligible 集合选择，结果绑定输入、策略和计划；不代表外部模块已可运行 |
| TEA | 部分实现 | 唯一锁定 Git submodule；五个候选模块可路由，但真实 runtime/behavior 保持 `unverified` |
| C++ 增强 | 已实现内置路由切片 | `cpp-core` 与九个专项能力内容寻址、正/误触发与组合测试；选中的能力必须进入 PlanGraph `designed/code.reasoning` eligible 集合；真实 Agent runtime 仍需原生验收 |
| Grill-me 后独立 Brainstorming | 契约与失败关闭已实现 | Host gate、摘要来源和 Fake dispatch port 已测试；生产 Agent 的原生调度仍为 `unverified` |
| Provider 本地覆写 | 已实现安全管理面 | 显式路径、无磁盘扫描、静态检查；一键安装传入 rollback token 时使用 write-ahead CAS 配置事务，并覆盖可捕获中断/冲突/回滚/幂等测试；独立 `provider configure` 是原子写但不创建 rollback transaction，强制进程或机器终止后的自动恢复仍未实现 |
| CodeGraph | 仅配置、静态检查和 plan-only | 不执行真实查询、索引或维护；非 plan-only 操作失败关闭 |
| OpenSpec | deferred | 没有 Catalog 模块、Adapter 或 Git submodule |
| 通用专项 Review 选择与聚合 | deferred | DiffSignalSet/ReviewAggregate Schema 和验证器已存在；没有完整 selector→specialists→aggregate Host 执行链 |
| Heavy/Forensic | deferred | 没有 Heavy submodule、Adapter 或执行入口；普通安装不会下载或运行 |
| C7OpenWiki | deferred | knowledge profile 只有通用契约，没有 MCP 执行适配 |
| 多 Agent 支持 | 薄策略入口 | Codex/Claude Code/Cursor/OpenCode 为 `experimental-unverified`，Copilot 为 instructions-only |
| Windows 一键安装 | 已实现并自动化验证 | 计划确认、隔离 Git 配置的来源锁定、冲突、幂等、日志、write-ahead 事务回滚与 Provider 配置回滚；Provider 管理入口保留在仓库而非不可执行的静态 runtime |

## 本次审计修正

1. 薄适配器不再要求每个普通任务调用 `selfworkflow resolve`；只有显式契约管理或 conforming Host 场景使用。
2. 如果显式使用 Resolver，`paused` 仍必须拒绝，不能以轻量化为由静默降级。
3. 未绑定真实来源的 V3 核心描述模块把 `sourceIntegrity` 从 `supported` 改为 `unverified`，避免占位 hash
   被误读为来源证明。
4. 轻量设计文档与既定策略对齐：所有修改默认 Brainstorming，复杂度只增加深度和可选模块。
5. README 将“契约存在”“Fake-port 自动化通过”“真实生产能力”分开陈述，并列出 deferred 范围。

## 独立终审修正

首轮独立 SubAgent 终审给出 `changes-required`。本轮没有淡化这些发现，而是逐项修正并补充回归：

1. 官方 Superpowers clone 与所有来源检查隔离继承的 Git URL rewrite、system/global config、hooks、
   system attributes 和 fsmonitor；测试替代传输只能在显式测试模式使用。
2. 工作流安装器及一键安装期间带 rollback token 的 Provider 配置都在正式写入前持久化 preimage、
   预期 postimage hash 与 `prepared` 状态；可捕获中断恢复原值。独立 `provider configure` 只保证原子写；
   突然进程/机器终止只保证已有 write-ahead 路径留下可诊断事务，本版不虚构自动 crash recovery。
3. Grill-me 后同 Agent 结构化 fallback 的授权在 dispatch 前消费；Review 返回 `changes-required` 后不能
   重放同一授权。
4. 跨 slot 显式模块只在所属 slot 验证；C++ 自动路由结果在创建 PlanGraph 前合入显式模块，并由结果
   合同再次验证其属于 `designed/code.reasoning` eligible 集合。
5. Provider BAT 修正 PowerShell 参数转发并通过任意工作目录调用测试；缺少 Python/package 的静态 Agent
   runtime 不再打包不可执行的管理脚本。
6. 日常轻量 Review 只保留迭代与最终 diff 证据；只有显式契约管理流程才创建 RunLedger attempt。

首轮修正后的独立复核又发现 3 项 Important：安装计划在锁外检查导致 TOCTOU、无 attestation 的独立
Review 在 `changes-required` 后可重放 fallback、自动 C++ route 改写 planning request 后无法用原始请求
构造 Host；同时指出 Provider write-ahead 文档表述过宽。最终修正为：

- 安装锁内重新验证 artifact 与目标基线，并以确定性交错测试证明漂移失败关闭；
- 在返回 `changes-required` 前消费匹配的独立 Review fallback，后续 approve 重放被拒绝；
- 新增 `ResolvedPlan.create_host()` typed Resolver→Host 接口，route 作为单独规划输入，`requestHash` 仍绑定
  原始规范化请求；
- Provider write-ahead 声明明确限定为一键安装携带 rollback token 的路径。

同一独立 Reviewer 对这些修正做聚焦 post-fix 复核，四项均判定 closed，最终结论为
**post-fix approved；无 Critical/Important**。Reviewer 未自行重跑长测试，测试结论以下述本地新鲜证据为准。

## 合理性判断

当前分层是合理的：`WORKFLOW.md` 负责低上下文成本的日常决策，确定性 V3 负责需要可审计证据的显式流程，
安装与 Provider 管理继续独立。下一步不应继续堆叠候选 Skill；应优先完成一个真实 Host 的能力采集、阶段调用和
原生 Review/测试回执，之后再逐个接入 OpenSpec、专项 Review 或 C7OpenWiki。每个新模块仍需独立价值、
正/误触发、冲突/组合、上下文成本和退出条件证据。

## 验证记录

- 首次全量门禁暴露一条仍要求普通安装入口默认调用 Resolver 的旧验收；修正为“轻量入口不强制
  Resolver、显式 CLI 请求仍可解析”后，聚焦测试与后续完整门禁通过。
- 独立复核的最后三项代码修正按 TDD 先得到 3 个预期 RED，再转为 GREEN；受影响的 PlanGraph、
  Resolver/C++ Host、Post-Grill gate/Host、installer apply/locking/sandbox 切片 **61/61 PASS**。
- 固定提交 `e7e6e03` 执行
  `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1 -Suite automated`：
  **424/424 PASS**，耗时 **700.085 秒**，退出码 0。
- post-fix 独立 SubAgent 结论：**approved，无 Critical/Important**；真实 Agent/Provider 能力仍按矩阵
  保持 `unverified` 或 deferred。
