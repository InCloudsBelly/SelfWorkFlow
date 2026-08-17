# C7OpenWiki Runtime Adapter Design

> 状态：基于已批准的 `D:\openwikiC7\c7-openwiki\docs\superpowers\specs\2026-08-06-c7-openwiki-mcp-design.md` 和 SelfWorkFlow 总设计执行。本增量不重新打开已确认决策。

## 目标与边界

把已经存在的通用 `knowledge.read / propose / update` 插槽连接到真实的
C7OpenWiki stdio MCP，同时保持以下边界：

- SelfWorkFlow `core` 不依赖 C7OpenWiki；只有显式 `knowledge` profile 包含 C7 适配资产。
- `D:\openwikiC7` 是独立事实源，不复制 OpenWiki 源码、凭据、运行状态或 Wiki 到 SelfWorkFlow。
- 外部 Agent 仍是唯一用户界面；C7OpenWiki 模型负责读取、去重、组织、落库和强制复审。
- C7 MCP 实际 schema、`openwiki_status` 和能力证据优先于静态文档；不满足门禁时失败关闭。
- 正常代码任务不因知识后端不可用而失败，只产生明确的知识同步待办。

## 发现的事实缺口

C7 发布器内部已经以 Markdown tree root hash 做 CAS，但现有 MCP 没有：

1. 向调用方暴露查询所基于的 Wiki revision；
2. 让 update 绑定用户确认时看到的 expected revision；
3. 用结构化 conflict 返回实际 revision。

因此旧适配器只能标记 `unverified-contract-gap`，不能满足 SelfWorkFlow 已批准的
compare-and-swap 契约。本次先在最早拥有 Wiki 快照不变量的 C7 层修复，不在
SelfWorkFlow 下游猜测或补偿。

## 契约增量

C7 MCP 保持七个工具不变，只扩展 strict schema：

- `openwiki_status` 成功结果增加 `wikiRevision`。
- `openwiki_query` 成功结果增加本次隔离事务的 `wikiRevision`。
- `openwiki_update` 必须接收 `expectedWikiRevision`。
- update 在持有 Wiki lock 后、创建事务前捕获基线；所有业务终态返回非空
  `baseWikiRevision`。当 expected 与该基线不同时，模型和事务均不得启动、Wiki
  不得发布，返回 `status: conflict`、`published: false` 和结构化恢复信息。

revision 是 `snapshotMarkdownTree()` 的版本化 SHA-256 root hash，不是 Git commit，
也不宣称阻止绕过 C7 lock 的任意外部写入。发布器现有的逐步 CAS 仍是最终防线。

## SelfWorkFlow 映射

- `read` 调用 query，把回答、来源标识、`wikiRevision`、内容 hash 和
  `unverified` 语义验证状态映射到通用知识证据。
- `propose` 调用 query，不发布正式 Wiki，并把 query revision 作为
  `expectedBase`；同时保留提案正文及其内容 hash，避免通用层把模型产出的候选知识
  丢弃。OAuth refresh 和临时事务仍明确属于可能的运行态副作用。
- `update` 必须同时具有 `confirmedByUser: true` 和 `expectedBase`，并把后者原样
  传为 `expectedWikiRevision`。C7 返回的 `baseWikiRevision` 是 `actualBase`。
- C7 状态使用显式语义映射；`published_with_follow_up` 映射为独立的
  `published-with-follow-up`，不得折叠为普通发布。通用 update 结果保留一个只读
  `nativeResult` opaque 通道，供 Host 报告 follow-up、review issue 和 recovery；
  其中只允许 C7 MCP 已验证的结构化输出，不包含模型私有推理。

适配器不保存模型私有推理，不自行选择或降级 model/reasoning effort。
每次实际 read/propose/update 前都必须重新读取 status，验证 initialized、authorized、
恢复状态和 capability 证据；`ok: false` 的 error/recovery 必须原样保留为结构化失败，
不能压扁成无信息的 backend failure。适配器实例还必须绑定冻结工具契约、C7
`contracts.ts` 与 provenance；缺失绑定或 drift 时不得调用后端。

## 模块化装载

- `core` profile 继续不包含任何 C7 文件。
- `knowledge` 是唯一激活并安装 C7 Agent Skill 的运行 profile，增加冻结契约、适配说明和 `kg-c7-openwiki` Agent Skill；
  安装器只把该显式 profile 中的 Skill 暴露到 Agent Skill 目录。profile 切换时，
  只回收上一份安装 manifest 拥有、内容仍与 manifest 一致、且新 profile 不再包含
  的 Skill；用户修改过的文件必须失败关闭，回收也必须进入同一事务和回滚链。
- `maintainer` 的完整维护快照可保留 extension 源资产用于版本维护，但不生成或安装
  `skills/kg-c7-openwiki`，因此不会激活知识后端。
- V3 在 `discovered` 增加可选 `knowledge.read`，在 `completed` 增加可选
  `knowledge.propose` 与 `knowledge.update`。三个槽均为 explicit、最多一个，
  不在普通任务中自动加载。

## Grill-me 与确认

全局后续规则覆盖旧 C7 文案：Brainstorming 是默认设计能力；Grill-me 只有在
用户明确要求或 Agent 对复杂任务提出推荐并由用户选择后才使用。无论使用哪种
设计模块，`openwiki_update` 仍必须在最终写入摘要后获得本次明确“确认写入”。
Skill 的行为测试必须区分“设计模块选择”和“写入确认护栏”，不能把二者混为一谈。

## Codex 安装边界

Codex 使用官方支持的本地 stdio MCP 配置。配置目标只包含 C7 server 的绝对
`node`/`dist/index.js` 启动信息，不包含 OAuth token。配置前必须验证：

- server 路径和能力证据存在且匹配当前源码；
- 当前配置中不存在同名冲突；
- 修改前后保留可恢复备份并验证 TOML 可解析；
- MCP 原生 harness 能完成 initialize、tools/list 和 status。

该共享配置由 SelfWorkFlow 的 `codex-mcp configure` 边界负责：同名同配置幂等，
同名异配置失败关闭，原 TOML 非法时不写入；写入采用可恢复备份和原子替换，写后
再次解析并核对目标表。路径失效、写入/验证失败必须恢复原文件。成功新增后返回
`restartRequired: true`，不能宣称当前 Agent 已热加载。

配置器必须同时写入 `startup_timeout_sec = 120` 和
`tool_timeout_sec = 72000`。Codex 默认的 60 秒 MCP 工具期限短于 C7 单个
45 分钟模型阶段，会从错误责任层中断仍可恢复的更新。20 小时外层期限覆盖一次
完整更新在最保守瞬时重试与 result-finalizer 组合下的 18 小时理论界限；C7
仍拥有阶段超时、取消和清理。配置器只允许把自己带 managed marker 的精确旧
command/args block 原子升级到带期限的新 block；无 marker 的同名配置仍按冲突
失败关闭。

配置边界在任何写入（包括幂等返回）前验证 C7 capability evidence，并使用目标 Node
真实执行 initialize、tools/list、status smoke。配置修改由跨进程锁串行化，并在替换
前检查原始字节；失败回滚只允许覆盖本次写入的精确字节，发现并发修改时保留他人
内容并失败关闭。

当前 Codex 任务无法热加载新增 MCP 时，安装结果标记为 `restart-required`，不把
本会话未出现的工具伪称为已激活。

## 2026-08-11 稳定版维护增量

C7OpenWiki 已完成个人 MCP 稳定化并重新暴露真实状态。维护核对发现三个属于
SelfWorkFlow 的缺口：

1. V3 `knowledge-update` 把 `knowledge-propose` 声明为跨槽模块依赖，但 PlanGraph
   明确只允许槽内依赖；该静态目录错误会让不包含任何 Knowledge 模块的普通 C++
   计划也以 `v3-cross-slot-dependency` 暂停。
2. C7 当前 `contracts.ts` 已变化；本次冻结目标是
   `sha256:e412bff3f39cffce164559f28b85cefe77e34d53d45269000f4ce2b85d66d976`。
   旧 provenance 必须失败关闭，不能继续宣称绑定。
3. C7 现在为 `process_failure` 返回脱敏、限长的 `diagnostic` 和精确
   `failureStage`；通用 Knowledge 错误白名单尚未保留这两个字段。

采用最小责任层修复：

- 保留 PlanGraph 的跨槽依赖禁令，不放宽全局图不变量；移除
  `knowledge-update -> knowledge-propose` 的非法模块依赖。流程顺序仍由
  `knowledge.propose` 位于 `knowledge.update` 之前保证，而真实 update 继续由
  `confirmedByUser: true`、`expectedWikiRevision`、最终摘要和 C7 CAS 共同守护。
  两个槽仍为显式、可选，不能污染普通代码计划。
- 只刷新 SelfWorkFlow 保存的冻结工具契约、上述精确 C7 契约 hash、能力/Agent 契约
  provenance 和对应 V3 source hash；冻结工具契约 hash 必须由最终精确字节计算，
  provenance 中的 `frozen-tool-contract` 与 `knowledge-read/propose/update` 三个
  `sourceHash` 必须逐项等于它。不复制或修改 C7 源码、runtime、Wiki 或凭据。
- 通用层只新增 `diagnostic` 与四个公开 `failureStage` 值的封闭校验；diagnostic
  必须是非空字符串且不超过 4096 字符；合法阶段精确为 `result_missing`、
  `result_json_invalid`、`result_schema_invalid`、`result_binding_mismatch`。测试必须覆盖
  1/4096 字符接受、空值/错误类型/4097 字符拒绝，以及未知阶段、未知字段失败关闭。

本增量不新增 Knowledge 模块、不改变核心 profile、不自动启用知识写入，也不扩大
本次代码侵入性预算。

## 验收

1. C7 contract、runtime、query、update、server 和 Skill 测试覆盖 revision、冲突、
   未确认、失败路径与不启动模型不变量。
2. SelfWorkFlow 覆盖 read/propose/update 映射、冲突、失败隔离、profile 差异、
   V3 槽、Skill 正触发/误触发/冲突。
3. C7 `verify:capabilities` 重新生成与当前代码匹配的证据；真实 stdio harness
   列出精确七工具并调用 status。
4. SelfWorkFlow 完整自动化回归、安装 verify/doctor、配置幂等和最终 diff 检查通过。
5. 真实 ChatGPT OAuth、账户 model/effort 只有实际 smoke 成功后才标记通过；未执行
   时单独保持 unverified，不影响本地契约和 stdio 适配结论。
6. 公开 tools/list 的 update 业务结果 schema 对 `baseWikiRevision` 明确为非 null；
   仓库 Agent Skill/eval 明确执行 query/status revision 捕获、update 绑定及 conflict
   重新确认。
7. 普通 C++ V3 计划不再被可选 Knowledge 目录阻断；PlanGraph 的跨槽拒绝回归仍通过。
8. 通用 Knowledge 结果保留 C7 的安全 `failureStage`/`diagnostic`，并拒绝未知或超界值。
9. 当前 C7 contract 与冻结契约/provenance 重新绑定；真实 status 必须断言
   initialized、authorized、clean 和默认 `gpt-5.6-sol/xhigh`。真实 query 前后重读
   status，断言 `wikiRevision` 不变且没有正式 Wiki 发布。

## 2026-08-12 外部 Agent 执行模式增量

本节取代上文把 C7 provider/OAuth 作为默认知识执行路径的运行时描述，但保留旧路径
作为显式 legacy compatibility。目标是让当前宿主 Agent 与独立 SubAgent 执行知识
理解、候选编写和 Review；C7 只拥有来源与规则快照、事务绑定、确定性校验、恢复和
正式 Wiki 发布。外部模式不需要 C7 OAuth，也不得声称 C7 验证了宿主模型、
reasoning effort 或 SubAgent 身份。

默认 update 只使用冻结的两阶段接口：

1. `openwiki_status` 必须同时报告 `executionMode: external_agent`、
   `authRequired: false`、`externalAgent.ready: true`，并具有已验证 capability
   `update.external-agent.begin` 与 `update.external-agent.reviewed-finalize`。
2. `openwiki_begin_external_update` 在用户确认、精确 Wiki 路径、expected revision、
   可选来源和 Skill 顺序绑定后返回完整 work package。宿主把原样工作包交给编写
   SubAgent；它只写 C7 指定的私有候选目录。
3. `openwiki_finalize_external_update(prepare_review)` 冻结候选 hash 并返回只读 Review
   package；新的独立 Review SubAgent 返回 host-attested receipt。
4. `submit_review` 只有 `published`、`published_with_follow_up`、`repair_ready` 或
   `needs_clarification`。正式 Wiki 只能由 C7 原子发布；repair 按 `nextAction` 恢复，
   不假设尚未冻结的载荷形状。
5. Host 取消、超时、模型或进程故障使用 `report_host_failure` 保留候选；显式 abort
   需要用户确认。所有 revision、binding、candidate、规则和来源漂移均失败关闭。

默认 `read` / `propose` 不回退旧 provider。当前冻结契约没有外部只读 work package，
因此适配器明确报告 `external-agent-query-unavailable`；未来只有实时 schema 与 capability
公开该能力后才接入。`openwiki_query` / `openwiki_update` 仅能通过显式 legacy opt-in
调用，普通 Knowledge 路由不能触发。

SelfWorkFlow 侧可以先冻结路由、输入输出最小结构与 fail-closed 校验，但 C7 侧实现、
capability evidence、来源契约 provenance 和真实 stdio 场景全部通过前，支持状态保持
`experimental-unverified`，不得安装为已验证端到端能力。

### 外部执行契约修订：request package 与恢复分流

外部 `workPackage` 和 `reviewPackage` 都必须携带同一 C7 生成的
`requestPackage {path, packageHash}`。它绑定精确 instruction 和有序 materials，并进入
binding/review package hash；Host 只能把包原样交给 Writer/Reviewer，不得从对话摘要
重建 materials。

`begin(action: resume)` 按持久状态分流：可写候选和 repair successor 返回
`external_update_resumed + workPackage`；已冻结 Review 返回
`external_review_resumed + reviewPackage`；终态只做有界重放。`publish_pending` 先由 C7
恢复，否则返回 `restore_required`，不得暴露路径。Reviewer host failure 的
`retry_review` 必须恢复只读 Review 包，不能误开新一代候选。每次新的用户确认生成
fresh request ID；旧 ID 只用于当前事务幂等和 C7 的固定终态重放窗口。

## 双仓联合验收与安装门禁

C7 行为实现和 SelfWorkflow 适配实现分别完成后，仍不得单侧标记完成或安装新能力。
两个任务必须使用 C7 提供的 exact HEAD、built stdio、实时 schema、capability evidence
和各契约 hash，协同执行一次双仓整体 Review 与完整端到端流程测试。联合门禁至少覆盖：

- 默认 `external_agent` 无 OAuth，status 同时具有两项冻结 capability；
- begin → Writer 私有候选 → `prepare_review` → 独立 Reviewer → submit → 原子发布；
- host failure/resume，包括只读 Review 恢复和 repair successor 幂等恢复；
- `needs_clarification` 保持正式 Wiki 不变，随后执行 confirmed abort；
- 发布事务崩溃恢复与残留清理；
- legacy 显式 opt-in，默认路径绝不静默回退；
- 错误、revision、来源、规则、candidate、receipt、schema 和 hash 漂移全部 fail-closed；
- 两仓完整 diff、冻结契约、provenance、构建产物和安装态相互一致。

任一侧 Critical/Important 未清零，或任一联合场景缺少新鲜证据，都不得安装、发布或
宣称端到端完成。等待联合验收期间，provenance 必须保持 implementation pending；旧的
已安装历史适配器不构成本次外部 Agent 模式的成功证据。

仓库内的静态回归只证明上述要求被记录且 provenance 仍为 pending；它不是联合 E2E
或安装器行为已经通过的证据。只有 Task 10 真实执行并保存的双仓证据才能解除门禁。

### Task 10 实际状态（未安装态）

Task 10 已使用 C7 clean HEAD `73b8229ffb75bf4151ce019a95b3b23946202f84` 和 fresh
capability build `ca6f8f0c-2729-4d25-9e25-9d403ee03256` 完成真实 SubAgent Writer、独立
Reviewer、host failure/resume、原子发布以及 `needs_clarification` → confirmed abort。
C7 完整 verifier 为 612/612，快照路径绑定修复后的独立 SPEC/QUALITY Review 均为
0C/0I/0M。provenance 因而可从 implementation pending 提升为
`implementation-verified-install-pending`，同时用
`jointAcceptance.status=verified-uninstalled` 明确记录“协议与端到端行为已验证，但此
source 文件不是机器安装收据”。SelfWorkflow 最终联合 Review 达到 0C/0I 后才允许安装；
安装完成状态由外部 StateRoot manifest 证明，并必须核对当前 artifact、Skill bytes、
Codex MCP 配置和真实 stdio preflight，旧安装记录不能替代这些新鲜证据。
