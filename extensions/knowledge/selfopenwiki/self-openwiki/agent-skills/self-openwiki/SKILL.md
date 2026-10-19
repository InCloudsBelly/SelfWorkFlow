---
name: self-openwiki
description: Use when an external Agent needs to query, organize, propose, or update local C7 project knowledge through the SelfOpenWiki MCP, especially from local code, technical documents, confirmed source manifests, ordered Skills, or reviewed Wiki candidates.
---

# SelfOpenWiki

## 核心原则

嵌入 SelfWorkflow 时，模式、Design/Plan、授权、Review 调度和验证由 SelfWorkflow 唯一管理；本 Skill 提供 Wiki 方法与发布检查项，复用已完成的同范围门禁。个人 Wiki 目录遵循模块根 `WIKI_LAYOUT.md`；长期正文、Claims 与可分享来源在 Wiki Git 内，事务运行状态不是分享或重新导入所需的知识。

SelfWorkflow 只发现根 `kg-selfopenwiki` 路由入口；本 Skill 随更新返回的 Writer/协议包按需读取。普通读取、Viewer 或安装不同时加载本正文和完整 MCP 契约。实现位于 SelfWorkflow Git 的 `extensions/knowledge/selfopenwiki/`，不依赖独立 SelfOpenWiki 源目录。

外部 Agent 是用户界面和默认知识 writer；C7 是来源、规则、候选、事务、正式发布、
恢复和审计权威。默认外部更新由两个隔离执行上下文完成编写与独立 Review，C7 不调用
内部模型，也不把宿主模型当作真源。每次工作以实时 MCP 工具 schema 和
`openwiki_status` 为准；在构造调用前先读取 [MCP 契约](references/mcp-contract.md)。

普通更新默认只用当前 Agent 的 Brainstorming/Design 能力，不强制 Grill-me。
只有用户明确要求 Grill-me，或 Agent 对复杂任务推荐且用户接受时才使用。
用户拒绝推荐时继续 Brainstorming/Design，不得暂停普通更新。
使用 Grill-me 后再以独立 Brainstorming/Design 上下文交叉 Review。

## v2 个人 Wiki 适配层

### 无模型的安全读取

在第一次 `openwiki_status` 后验证 `knowledge.read.safe`，使用 `openwiki_read {}` 获取目录
与 revision，再以 `paths` 和 `expectedWikiRevision` 读取选中 Markdown。最多 32 页，
每页 256 KiB、合计 1 MiB；返回 sourceId/revision/contentHash/verificationStatus，不
创建候选或调用 provider。语义 `unverified` 仍需保留；不得虚构 external query 或调用
显式 legacy query 来代替此读取。恢复诊断可以检查 `ready=false` 状态；已确认 abort
使用既有 external finalize 协议，正常发布门禁保持。

SelfOpenWiki v2 使用固定的 OpenWiki upstream Submodule 作为能力来源（official submodule），当前绑定的
revision 由实时 `openwiki_begin` 响应和兼容性清单共同确定。个人 Skill 是独立的
SelfOpenWiki-owned 适配层；它可以为官方能力增加本地规则、Claim 处理和 C7 发布约束，
但不修改或覆盖 `upstream/openwiki` 的文件。

适配后的官方六阶段工具按以下顺序使用：

1. `openwiki_begin`：传入明确的外部 Git 仓库根目录 `wikiRoot`，绑定 Wiki revision、
   upstream revision 和个人 Skill hash，并创建或恢复个人 Run。
2. `openwiki_submit_plan`：提交页面标题、目的、种子路径、关联页面和指令，生成持久化
   PageJob 队列。索引和运行元数据不作为 PageJob 内容。
3. `openwiki_next_page`：一次只取一个 PageJob，并只使用响应中 candidate package 的
   `rootPath/pagePath/permissions`。Writer 只能在候选目录写被分配的 Markdown 页面。
4. `openwiki_inspect_page_claims`：在修改或撤回已有 Claim 前读取绑定 Wiki 的
   `.claims/` sidecar 中、且与当前页面 revision 匹配的完整 Claim 集；不能从自由文本
   或客户端输入猜测 Claim、证据或 hash。
5. `openwiki_submit_page`：C7 读取并校验候选中的已分配页面，接收稀疏 Claim 决策；此
   调用不写正式 Wiki，也不执行个人 Wiki 的 Git commit、push、fetch 或 ref 操作。
6. `openwiki_finish`：按 candidate receipt → 独立 Review receipt → C7 CAS publication
   顺序推进；发布成功后，个人适配层还会把本轮稀疏决策重建为完整 `.claims/` sidecar，
   以当前正式 Markdown 字节写入 `pageVersion`。`review_required`、`publish_pending` 和
   `needs_clarification` 都是可恢复状态；只有结构化 `status: complete` 且 `published: true`
   才能报告正式 Wiki 和 Claims 已更新。

六工具是 SelfOpenWiki 的适配协议 `selfopenwiki:personal-openwiki-v1`，不宣称与官方
schema 字节一致。每轮仍先调用 `openwiki_status`；六工具或其绑定能力未 verified、
Wiki root 不是独立 Git 仓库、Skill/upstream 漂移、候选或恢复状态不可读时停止。

个人 Wiki 资源可以位于 SelfOpenWiki 之外。`wikiRoot` 必须是已存在的独立 Git 仓库根，
运行时目录固定为同级 `<wikiRoot>.selfopenwiki`。MCP 只读 Git 身份和内容；个人仓库的
commit、branch、remote、push 和回滚由用户明确执行。迁移或格式漂移先生成候选，不能
直接重写原始 Wiki 或其 `.git` 元数据。

## 不可绕过的护栏

- 第一次 MCP 调用永远是 `openwiki_status`；只传实时 strict schema 中存在的字段。
- 默认 status 必须返回 `executionMode: external_agent`、`authRequired: false`、
  schema 2，以及 verified 的 `update.external-agent.begin` 和
  `update.external-agent.reviewed-finalize` 完整 capability 对。
- 任一 capability 缺失、恢复未闭环或状态不可读时停止；不得单边调用 begin/finalize。
- writer 只能写 work package 指定的候选目录；Reviewer 只能读取候选；两者都不得直接写正式 Wiki。
- 不从自由文本推断成功，不自行补字段、路径、hash、receipt、模型证据或发布事实。
- 本地路径必须先 prepare 并由用户确认当前 manifest；敏感、变化或拒绝的来源不可旁路。
- 不声称 C7 验证了宿主模型、provider 或 reasoning effort；外部 receipt 只是
  `host_attested` 证据。
- `openwiki_setup`、`openwiki_query`、`openwiki_update` 和
  `openwiki_set_default_model` 仅属于用户显式选择的 `legacy_provider`；不得虚构 external query。

## 工作流

### 1. 读取实时状态

1. 检查当前会话实际暴露的工具及 schema。
2. 调用 `openwiki_status`，不附加未知字段。
3. 核对 schema 2、external mode、OAuth-free 状态、完整 capability 对、
   `runtime.recoveryState`、`externalAgent.ready`、活动事务和 `wikiRevision`。
4. `capability_unverified`、`restore_required`、`busy` 或其他失败只按结构化
   `ok`、`error` 与 `recovery` 处理。

### 2. 选择执行模式

默认选择 external-agent 更新，不询问 model/effort，不执行 OAuth。

只有用户明确要求兼容路径时才选择 `legacy_provider`。此时重新读取实时 schema，
`openwiki_setup` 负责首次 OAuth/精确模型组合验证；`openwiki_query`、旧
`openwiki_update` 和 `openwiki_set_default_model` 都必须携带 exact legacy
discriminator。验证失败不降级、不换 provider，也不把 legacy 能力冒充默认能力。

### 3. 准备任意本地来源

1. 任意本地绝对路径先调用 `openwiki_prepare_sources`。
2. 展示文件清单、大小、hash、风险、manifest 标识和确认文本，说明数据边界。
3. 等待用户明确确认绑定该清单。
4. start 只使用相互匹配且未变化的 manifest 标识与确认文本。
5. source changed/invalid/rejected 使旧确认失效；重新 prepare 并重新确认。

`materials` 只承载用户已脱敏的短文本，不能旁路来源或敏感文件规则。

### 4. 组合有序专项 Skill

需要专项规则时先调用 `openwiki_list_skills`，只选实时返回且 verified 的专项 Skill。

- `kg-c7-project-wiki` 永远第一且唯一，由个人适配层自动加入；`self-openwiki` 是其后的
  个人补丁 Skill，专项 Skill 再按请求顺序追加。
- 专项 Skill 有序、无重复；不得借提示词覆盖安全、来源、归档、Review 或发布硬规则。
- 以响应中的实际 selected Skills、package hash 和 aggregate hash 为准。

### 5. 查询 Wiki（显式 legacy 兼容路径）

旧有 C7 九工具契约没有 external-agent query。只有用户显式选择 `legacy_provider` 且 status
显示其初始化、认证和模型证据有效时，才按实时 schema 调用 `openwiki_query`。记录
响应中的 `wikiRevision`、来源、Skill 和模型边界；未出现的字段不补全。

若用户不接受 legacy provider，说明当前查询能力不可用并停止，不能用 begin/update
伪装查询，也不能直接读取 C7 私有运行目录。

### 6. Personal Wiki 六阶段更新

这是个人 Wiki 的默认沉淀路径。完成 Design 后，先用 `openwiki_begin` 绑定 `wikiRoot`
和当前摘要 revision，再按六阶段顺序推进。页面内容、OKF metadata、Claim 及证据只能
通过返回的 candidate package 和结构化 receipt 进入 C7；不要把个人 Wiki 根目录当成
候选目录。

`submit_page` 只提交当前 PageJob 的页面和 sparse Claim decision。重复提交同一绑定的
payload 必须得到相同接受结果；不同 payload 不能覆盖已经 accepted 的 PageJob。队列为空
后调用 `finish`，没有 candidate receipt 或 Review receipt 时按返回的 `nextAction` 继续；
`submit_plan` 至少需要一个页面或删除项，无工作更新应由 `begin` 返回 `noop`。候选
root 必须位于 `<wikiRoot>.selfopenwiki` 且没有链接或 junction 祖先；
不要把 `review_required` 解释成已发布。

检测到旧页面格式、frontmatter 或 Claim 结构需要迁移时，只在候选目录生成 migration
candidate。展示 byte/hash/diff 和影响范围，取得用户明确确认后仍按 Review 与 CAS 发布；
失败时保留原页面和 `.git` 状态。

### 7. 旧有 C7 external-agent 更新 Wiki

1. 用 Brainstorming/Design 收敛证据、页面范围、来源、Skill、未知项和排除项。将缺口
   分为 minor、provisional、blocking：minor 自主查证；provisional 允许保守落地并
   明示 follow-up；blocking 停止发布并恢复 Grill-me。
2. 展示最终摘要和记录 `wikiRevision`。用户明确“确认写入”后，按实时 schema 调用
   `openwiki_begin_external_update` 的 start；把该 revision 原样作为
   `expectedWikiRevision`。`conflict` 后刷新、重新形成摘要并重新确认写入。
3. 将完整 work package 交给隔离 writer。它只能写 package 的 candidate root，并以
   不透明字段原样绑定 transaction、generation、binding、request/rule/source/Skill/
   scope hashes。candidate receipt 的 `writerExecutionId`、classification、issues、
   questions 和 summary 必须真实、严格且有界。
4. writer 失败时调用 finalize 的 `report_host_failure`，不得丢弃候选；随后 begin/resume
   必须返回 `external_update_resumed` 和相同授权包，才可继续。
5. 调 finalize 的 prepare Review。blocking 结果是 `needs_clarification` 且未发布；
   否则只接受 hash-bound Review package。
6. 将 Review package 交给独立 Reviewer。Reviewer 只能读取候选，
   `reviewerExecutionId` 必须不同于已冻结的 `writerExecutionId`，并逐项检查证据、
   版本、作用域、链接和闭环。Reviewer 失败时使用 `report_host_failure`；恢复必须返回
   `external_review_resumed`。
7. 将严格 Review receipt 原样提交。它必须绑定返回的 review package、candidate root、
   candidate receipt、transaction、generation 和 binding hashes；不得自造或重算
   C7-owned hash。只有 C7 返回 published 布尔事实后才称落库成功。
8. `changes_requested` 只能通过 begin/resume 取得最多两代 successor，每代重新 writer、
   prepare、独立 Review；不得直接修改已冻结候选。

### 8. 处理结果与恢复

- `published`：报告 C7 已发布、正式 revision 和 host-attested Review 事实。
- `published_with_follow_up`：报告已发布并保留 provisional follow-up。
- `needs_clarification`：明确未发布、候选仍保留。取得关键决策后继续；若用户决定放弃，
  只调用 exact `abort` 并设置 `confirmedByUser: true`。成功 abort 后正式 Wiki 不变。
- `external_host_failure`：报告阶段和 next action，按返回 binding 执行 begin/resume。
- `repair_ready`：只由 resume 创建下一代；最多两次 repair successor。
- `conflict` 或其他失败：正式 Wiki 未变；按结构化 recovery 处理，不自动重放。

显式 legacy `openwiki_update` 仍可能返回 `review_requires_attention`。
先处理发布后的 finalization/cleanup，不要在没有语义 issue 时发起知识修正。
只有实时结果明确返回语义 issue，才把它作为新的更新重新走确认；
`review_requires_attention` 不是外部候选 Review receipt 的替代状态。

## SelfOpenWiki Viewer

当用户要求打开、查看或可视化个人 Wiki 时，Viewer 也属于 SelfOpenWiki 的默认能力边界：

1. 先调用 `openwiki_status`，只使用其中的 `visualizer` contract 和 `paths.wikiRoot`。
2. `visualizer.id` 必须是 `selfopenwiki.zxh_wiki_viewer`，且必须声明
   `loopbackOnly=true`、`autoOpen=false`、`wikiRootInput.flag=--wiki-root` 和
   `http://127.0.0.1:{port}/wiki/local` URL 模板。
3. 通过 SelfWorkflow 集成模块根目录的 `Visualize.bat --wiki-root <absolute-wiki-root>`
   启动 `visualizer/zxh_wiki_viewer`；启动器负责把同一路径注入 `SELFOPENWIKI_WIKI_ROOT`。
4. 只打开返回的 loopback URL。Viewer 不修改 Markdown taxonomy，也不执行 Git commit/push。
5. 缺少或不匹配的 Viewer contract 时标记 `unverified` 并停止；不猜测路径、不调用
   `.work/openwiki/dist/cli.js visualize`，也不切换到其他 Wiki。

当 `knowledge` profile 已加载且用户说“总结/整理 Wiki”时，默认目标同样是 SelfWiki。
必须先读 status，核对 `knowledge.read.safe` 后通过 `openwiki_read` 列目录和读取
正式 Wiki 页面。缺少该能力时报告 `unverified`；不能读取 Agent 自己的 Markdown
文档或静默使用 `legacy_provider`。内容的语义验证状态仍按读取证据报告。

## 快速自检

- [ ] 第一项调用是 status，且两个 external capability 都 verified。
- [ ] 没有把 setup/OAuth/model 作为默认 external 更新前置条件。
- [ ] 所有本地路径已 prepare，用户确认仍匹配。
- [ ] 基础 Skill 第一且唯一，专项 Skill 有序无重复。
- [ ] 用户看过最终范围与 revision 并明确确认写入。
- [ ] writer 只写候选，Reviewer 只读，execution ID 不同。
- [ ] 所有 package/hash 字段来自实时返回，没有重算或猜测。
- [ ] failure 走 report/resume；clarification 放弃走 confirmed abort。
- [ ] 只按结构化 published/recovery 报告，不虚构模型或正式 Wiki 变化。

## 红线

- 未调用 status、capability 只有一半或恢复未闭环就继续。
- 未确认来源或写入范围就 start。
- 未用 `wikiRoot` 绑定独立 Git Wiki，或把个人 Wiki 根目录当作 candidate root。
- 在 `submit_page` 或六阶段工具中执行个人仓库 commit、push、fetch、ref 修改。
- writer/Reviewer 写正式 Wiki、交换身份或绕过 receipt。
- 把 `legacy_provider` 静默当默认，或把 legacy query 宣称为 external query。
- 把宿主强模型当绝对真源，或说 C7 验证了宿主模型/effort。
