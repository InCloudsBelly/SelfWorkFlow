# 个人 Wiki 候选与发布

只在生成更新候选或已确认知识写入时加载。SelfWorkflow 已有的设计、实施授权和独立 Review 门禁复用；通用生命周期为 `knowledge.read → knowledge.propose → knowledge.update`，propose 不发布。

候选规划、写作与独立 Review 同时应用当前 runtime 的 `workflow/modules/knowledge.md`
“知识文章质量规范”。按完整问题合并零散页，解释关键接口/类，按需使用直观图例与短源码；
SHA、manifest 等精确维护身份移至文末，正文保留版本边界和未验证结论。主 Agent 将本次
适用要求写入有界的页面任务/审查指令，Writer 和 Reviewer 只读各自获授权的包；不要求它们
沿此路径访问未挂载的宿主目录。读取/打开 Wiki 不加载这份写作规范，不增加发布确认轮次。

默认协议为 `selfopenwiki:personal-openwiki-v1`，六工具是本模块的官方能力适配，不宣称与 upstream schema 字节一致。第一次 `openwiki_status` 必须确认 schema 2、external mode、OAuth-free、`externalAgent.ready=true`、恢复闭环、旧 external capability 对，以及下列个人能力全部 verified：

```text
update.external-agent.begin
update.external-agent.reviewed-finalize
personal.lifecycle.begin
personal.wiki-root.explicit
personal.skill-adaptation.bound
personal.lifecycle.plan
personal.page-job.queue
personal.lifecycle.next-page
personal.candidate.write-package
personal.claims.inspect
personal.claims.binding
personal.page.validate-assigned
personal.claims.sparse-decisions
personal.lifecycle.finish
personal.c7-review-cas-publish
```

用户确认本轮写入范围、来源和 revision 后才进入更新；已有同范围授权复用，冲突导致范围/revision 变化时重新形成可确认方案。本地来源先按实时协议 prepare 并确认 manifest，敏感、变化或拒绝的来源不旁路。基于返回的 Skill/work package 读取本阶段必要 Writer 规则和精确协议；这些技术材料不扩散到普通读取任务。

固定按以下顺序推进，每个 PageJob 循环步骤 3–5：

1. `openwiki_begin`：由 adapter 注入 status 已绑定的 `wikiRoot`，绑定 Wiki revision、Skill 和 upstream revision。传入不同根必须拒绝。
2. `openwiki_submit_plan`：只提交页面/删除计划，生成持久化队列。新增页面前先读取现有入口与主题导航，计划须包含把新页接入 `quickstart.md` 可达链路所需的导航页；可以更新已可达的主题索引，不要求每页直接链接到 quickstart。手工维护的导航 Markdown 需要显式 PageJob，不能误当成自动生成的索引而遗漏。
3. `openwiki_next_page`：一次一个 PageJob；Writer 只写返回的 candidate package 分配路径。
4. `openwiki_inspect_page_claims`：修改或撤回已有 Claim 前读取绑定页面的完整 Claim 集，不猜 Claim、证据或 hash。
5. `openwiki_submit_page`：提交候选页面与 sparse Claim decisions；不写正式 Wiki。不能覆盖已 accepted 的不同 payload。
6. `openwiki_finish`：按 candidate receipt → 独立 Review receipt → C7 CAS publish 推进；只接受真实绑定字段，不自行补算 C7-owned hash。

新页计划缺少可写的可达导航入口时，`submit_plan` 会在创建 C7 候选前拒绝并提示补充导航页；该次计划未接受，可在同一 run 更正后重交，无需 abort。此检查只判断范围是否允许接通，候选完成后仍检查实际链接与全页可达性。已接受的队列保持冻结，之后扩大范围仍走现有恢复与授权流程；导航页的 Claims 漂移不能通过直接修改正式文件绕过。

仅当 finish 返回结构化 `status: complete` 且 `published: true` 才报告正式 Wiki/Claims 更新完成。`review_required`、`publish_pending`、`repair_ready`、`needs_clarification` 都未完成；按返回 nextAction 处理，故障时加载 recovery 引用。

实现至少 0.1.2 才能发布。新版保留正式根与既有主题目录，逐个替换变更 Markdown；目录监听和只读预览可继续打开。所有 Wiki 写者必须使用同一 MCP 锁协议，提交期间外部工具不得同时改写正式文件。发布完成后不自动打开正式文件预览或切换工作目录；用户明确要浏览时再加载 visualize 引用。文件独占锁仍可能阻止单个文件替换，此时保留原回执和恢复义务，不强关其他进程。

官方 OpenWiki 和 Viewer 是 SelfWorkflow 根固定的 submodule，自有适配层不得修改或猜 upstream 未冻结接口。格式迁移只在候选包生成，展示 byte/hash/diff 后按确认、Review、CAS 发布；不直接重写原始 Wiki 或 `.git`。六阶段不执行个人 Wiki commit、push、fetch 或 ref 操作。
