# SelfOpenWiki MCP 编排契约

## 事实来源

当前会话暴露的 MCP tool schema 是字段、必填项、枚举和 annotations 的唯一事实来源；
`openwiki_status` 是执行模式、认证、恢复、Wiki revision 和 verified capability 的唯一
运行时事实来源。所有输入都是 strict object。若本文、历史样例或缓存与实时结果不同，
立即采用实时结果；`ok: false` 只按 error/recovery 处理，`ok: true` 仍须按 status 与
published 字段判断事实。

新版本 status 可以带有 SelfOpenWiki-owned `visualizer` contract。它只用于默认 Viewer
路由，不改变个人 Wiki 六阶段协议：`id` 为 `selfopenwiki.zxh_wiki_viewer`，launcher
path 必须是绝对普通文件，`loopbackOnly=true`、`autoOpen=false`，Wiki root 通过
`--wiki-root` 参数注入，URL 模板固定为 `http://127.0.0.1:{port}/wiki/local`。缺失或
不匹配时必须报告 `unverified`，不能猜测 `SelfOpenWiki` 根目录或回退到旧 OpenWiki CLI。

每个请求的第一项 OpenWiki MCP 调用固定为 status。默认 external 更新还要求 status
返回 schema 2、`executionMode: external_agent`、`authRequired: false`，且同时包含
`update.external-agent.begin` 和 `update.external-agent.reviewed-finalize`。缺一项、状态
不可读或 recovery 未闭环都 fail closed。

## 十五工具契约

本节是 Personal Wiki（个人 Wiki）适配层的工具契约；Personal Wiki 的资源根目录由调用者显式传入。

### 个人 Wiki 适配的六阶段工具

| 工具 | 稳定用途 | 执行边界 |
| --- | --- | --- |
| `openwiki_begin` | 绑定外部 Git `wikiRoot`、Skill/upstream revision 并创建或恢复 Run | 只接受独立 Git 仓库根；运行目录是同级 `<wikiRoot>.selfopenwiki` |
| `openwiki_submit_plan` | 持久化页面 taxonomy 并生成有序 PageJob 队列 | 不把生成索引或运行元数据交给 PageJob |
| `openwiki_next_page` | 返回一个 PageJob、Claim issue 和候选写入包 | Writer 只写 `rootPath/pagePath`，权限严格为 read/list/write |
| `openwiki_inspect_page_claims` | 读取一个 PageJob 的完整当前 Claim 集 | 只读；从绑定 Wiki 的 `.claims/` sidecar 读取并校验页面 revision；修改或撤回 Claim 前必须调用 |
| `openwiki_submit_page` | 校验候选中的已分配页面并提交 sparse Claim decisions | 不写正式 Wiki，不执行个人 Git commit/push/fetch/ref 操作 |
| `openwiki_finish` | 驱动 candidate receipt、独立 Review、C7 CAS publication，并在发布成功后同步个人 Claims sidecar | `review_required`/`publish_pending` 可恢复；只有 `complete` 且 published 且 sidecar 同步成功才是个人 Wiki 落库事实 |

这六个名称吸收官方 OpenWiki lifecycle 的 Begin、SubmitPlan、NextPage、InspectPageClaims、
SubmitPage、Finish 能力，但 MCP schema 是 SelfOpenWiki 的适配协议
`selfopenwiki:personal-openwiki-v1`，不是官方 schema 的字节级复制。个人 Skill 可以在
这些能力上追加 Claim、迁移、来源和 C7 规则；补丁只放在个人 Skill/adapter 仓库，绝不
写入 `upstream/openwiki`。

`wikiRoot` 是用户的另一个 Git 仓库，不是 SelfOpenWiki 默认目录。MCP 只读取并绑定 Git
身份和 Wiki revision；用户仓库的 commit、branch、remote、push、fetch 和回滚必须由用户
在外部 Git 工作流中明确执行。

个人 Claim 的 authoritative source 是 `<wikiRoot>/.claims/<page>.json` sidecar，且
`pageVersion` 必须匹配页面内容 hash。客户端提交的 `claims`、确认 ID 和撤回 ID 只能
表达对这份快照的决策，不能替换 authoritative Claim 集；sidecar 缺失表示无 Claim，
sidecar 格式错误或版本过期则 fail closed。

### 诊断、读取与 C7 兼容工具

| 工具                                | 稳定用途                       | 执行边界                                          |
| ----------------------------------- | ------------------------------ | ------------------------------------------------- |
| `openwiki_status`                   | 最小诊断、revision、恢复和能力 | 永远先调用                                        |
| `openwiki_read`                     | 正式目录或所选 Markdown 证据  | 需 `knowledge.read.safe`；不启动 provider 或事务    |
| `openwiki_setup`                    | OAuth 与模型组合验证           | 仅显式 `legacy_provider`                          |
| `openwiki_prepare_sources`          | 绑定本地文本/源码 manifest     | 展示清单/hash/风险后等用户确认                    |
| `openwiki_list_skills`              | 列出受信任基础/专项 Skill      | 基础 Skill 自动第一且唯一                         |
| `openwiki_query`                    | provider 驱动的 Wiki 查询      | 仅显式 `legacy_provider`；不得虚构 external query |
| `openwiki_update`                   | 内部模型生成/复审兼容更新      | 仅显式 `legacy_provider`                          |
| `openwiki_begin_external_update`    | start/resume 外部候选事务      | 只返回 hash-bound work/Review package             |
| `openwiki_finalize_external_update` | failure/prepare/submit/abort   | C7 校验 receipt 并独占正式发布                    |
| `openwiki_set_default_model`        | 验证并修改默认模型             | 仅显式 `legacy_provider`                          |

工具缺失、capability 未验证、schema 不兼容或返回
`capability_unverified` 时，不得宣称可用。外部模式不调用 setup，不要求 OAuth，不选择
model/effort；legacy 模式必须按每个工具实时输入明确携带 exact discriminator，不能回退
或静默切 provider。

## 共同输入不变量

1. 任意本地路径先经 prepare；manifest ID、hash、确认文本和文件 bytes 任一变化都使
   旧确认失效。
2. `materials` 只包含用户已脱敏的短文本，不能旁路敏感文件或来源准备。
3. `kg-c7-project-wiki` 由个人适配层自动且唯一放在第一位，`self-openwiki` 作为个人补丁
   Skill 紧随其后；专项 Skill 有序、无重复且不可覆盖硬规则。
4. status/query 返回的 `wikiRevision` 是用户摘要基线；外部 start 或 legacy update 的
   `expectedWikiRevision` 必须原样绑定。`conflict` 返回的 `baseWikiRevision` 只用于
   刷新、重做摘要和重新确认，不能自动重放。
5. `confirmedByUser: true` 是本次明确确认的防误操作字段，不是身份认证。
6. `openwiki_submit_plan` 至少包含一个页面或删除项；无工作更新由
   `openwiki_begin` 返回 `status: noop` 表示，不通过空计划伪装更新。

## External-agent 状态机

### Start 与 writer

用户确认最终范围后，调用 begin/start。C7 返回 work package，其中 transaction、
generation、binding、before revision、request/source/Skill/rule/scope hashes 以及候选
路径都是不透明权威。writer 只可写候选，不得直接写正式 Wiki；候选路径之外的写入、
link、范围、版本或证据漂移必须失败。

writer receipt 必须使用真实且有界的 `writerExecutionId`，并按实时 schema 返回
classification、issues、questions 和 summary。外部 Agent 不计算 candidate root hash；
C7 在 prepare 时重读、确定性校验并冻结候选。

writer 进程失败时，finalize 的 `report_host_failure` 只记录有界阶段信息，不推进语义
状态、不删除候选。随后 begin/resume 必须返回 `external_update_resumed` 及同一绑定包。

### Review 与 publication

prepare 成功返回只读 Review package。独立 Reviewer 只能读取候选；它必须重新检查
原始证据、版本、作用域、规则、链接和闭环。`reviewerExecutionId` 必须不同于冻结的
writer ID。Reviewer 失败同样先 report，再 resume；合法恢复状态是
`external_review_resumed`。

Review receipt 只能使用返回的 transaction/generation/binding、review package、
candidate root 和 candidate receipt hashes，verdict 与 issue relation 必须符合 strict
schema。不得添加 model/provider verification。C7 重新计算全部绑定；只有 pass 或合法
follow-up 可进入一次原子发布。结果中的 Review 证据只能是 `host_attested`。

- pass + minor → `published`；
- pass + provisional 且无 blocking → `published_with_follow_up`；
- changes requested 且 generation 尚未耗尽 → repair-ready，begin/resume 创建 successor；
- requires-user、矛盾或耗尽 → `needs_clarification`，未发布并保留候选。

最多两代 repair successor；每代有新 candidate/binding/receipts 并重新独立 Review。
`report_host_failure` 不能被用作绕过 Review 或改变 verdict 的工具。

### Clarification 与 abort

`needs_clarification` 保留唯一活动候选。补齐 blocking 决策后按实时 next action 继续；
若用户决定放弃，只能调用 exact `abort` 且使用 `confirmedByUser: true`。成功返回
external aborted terminal，正式 Wiki 不变。不得把普通 failure、provisional 或
Reviewer 不确定性擅自解释为用户已同意 abort。

## Legacy provider

`openwiki_setup`、`openwiki_query`、`openwiki_update` 和
`openwiki_set_default_model` 保留旧 OAuth/model 行为，但只在用户明确 opt in
`legacy_provider` 后使用。setup 成功不证明 provider 内部真实采用某个 reasoning
effort；只报告 requested/sent/providerAccepted/providerReportedModel 等实时证据。

legacy update 可能返回 `published_with_follow_up`、`needs_clarification`、
`review_requires_attention`、`conflict` 或失败。attention 是发布后
finalization/cleanup 恢复，不是 external Review receipt；不得由此伪造外部 repair。

## 安全与扩展

- 不主动读取 `.env`、私钥、浏览器/OAuth/云凭据或拒绝的二进制。
- Host 执行 ID、receipt、package 和路径均为不可信输入，必须原样受 C7 strict schema、
  hash、scope、CAS 和 tree validation 约束。
- C7 不验证宿主模型或 reasoning effort；强模型也可能产生幻觉。
- 新工具或字段必须先进入实时 schema、能力矩阵、失败 eval 和 built-stdio 验证；本文
  不能授权任意 Shell、HTTP、自动 Git、隐藏回滚、Skill 自修改或模型降级。
