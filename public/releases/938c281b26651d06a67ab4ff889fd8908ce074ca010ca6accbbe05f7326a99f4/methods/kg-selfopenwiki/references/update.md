# 个人 Wiki 候选与发布

只在生成更新候选或已确认知识写入时加载。SelfWorkflow 已有的设计、实施授权和独立 Review 门禁复用；通用生命周期为 `knowledge.read → knowledge.propose → knowledge.update`，propose 不发布。

写作与内容Review统一按[质量标准](../../knowledge-backend/references/wiki-quality.md)与[正文契约](../../knowledge-backend/references/article-contract.md)，不回读知识模块。PageJob复用一份适用项、单元/条件、正文锚点和来源/缺口清单；Writer自检，同一Reviewer合并人类、图文/实际呈现、Agent实施/依赖走查，独立核来源后集中评分。共享观察跨指标复用，修订只查影响项，达标即结束，不默认全项满分；专题/全库仍覆盖全部授权页面和关键机制。L1必要契约/用途/版本与选读/证据随包传递，不递归展开所有相关页。细则仅具体问题需要时读，数值阈值不复制；发布成功不等于质量达标，不增加MCP字段、确认、润色轮次或Reviewer。

角色间传可达同版规范及其绑定、适用项、范围/单元/条件清单、来源和页面增量，并确认Writer/Reviewer实际取得。在既有PagePlan.instructions留质量版本、适用项与覆盖引用；Host把对应必要正文一次传入获授权的隔离包/交接材料，Review同时接收个人生命周期binding及C7 reviewPackage。只给不可达路径或后端发布回执都不能证明质量标准已执行。同版正文跨PageJob复用，不每页粘贴；修复重用的页面作业只表示内容/Claim未变，独立Review仍核对原范围及受影响依赖。

涉及数学表达时，Host把已绑定的[数学方法](../../sympy/METHOD.md)与[公式约定](../../sympy/references/wiki-math.md)必要正文一并交接，复用计算证据。公式解释/参数并入人类理解走查，正确性与目标Viewer显示分别核验；不额外建评分轮次，纯浏览/无数学内容不加载。

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

用户直接要求总结到 Wiki、更新或发布，即授权对应主题、目标和明确来源；已有同范围授权复用。先读当前 revision、展示紧凑方案并继续，不让用户手工批准 Agent 选择的每个页面或 hash。必要来源页和导航纳入计划；跨主题重组、删除知识、来源许可或数据暴露范围变化才重新确认。

本地来源先按实时协议 prepare，核对 manifest 完全落在已批准的来源/版本内；符合时把既有授权映射到协议确认字段，记录依据，不重复询问。未授权的新路径、敏感/拒绝来源或超出批准版本的变化不能旁路；缺失授权才展示有界清单并确认。协议字段与精确绑定仍必须真实，不把 Agent 自己选择的任意来源说成用户已批准。

revision 冲突先刷新并比较受影响页面：授权主题、来源和结果未变且无语义冲突时，自行重算绑定、候选及受影响 Review；不因 revision/hash 变化重问写入授权。真正内容冲突或超范围才合并提问。已冻结事务只使用协议支持的恢复/重建路径，不改旧 receipt，不覆盖并发修改。基于返回的 Skill/work package 读取本阶段必要 Writer 规则和精确协议；这些材料不扩散到普通读取。

固定按以下顺序推进，每个 PageJob 循环步骤 3–5：

1. `openwiki_begin`：由 adapter 注入 status 已绑定的 `wikiRoot`，绑定 Wiki revision、Skill 和 upstream revision。传入不同根必须拒绝。
2. `openwiki_submit_plan`：只提交页面/删除计划，生成持久化队列。新增页面前先读取现有入口与主题导航，计划须包含把新页接入 `quickstart.md` 可达链路所需的导航页；可以更新已可达的主题索引，不要求每页直接链接到 quickstart。手工维护的导航 Markdown 需要显式 PageJob，不能误当成自动生成的索引而遗漏。
3. `openwiki_next_page`：一次一个 PageJob；Writer 只写返回的 candidate package 分配路径。
4. `openwiki_inspect_page_claims`：修改或撤回已有 Claim 前读取绑定页面的完整 Claim 集，不猜 Claim、证据或 hash。
5. `openwiki_submit_page`：提交候选页面与 sparse Claim decisions；不写正式 Wiki。不能覆盖已 accepted 的不同 payload。
6. `openwiki_finish`：按 candidate receipt → 独立 Review receipt → C7 CAS publish 推进；只接受真实绑定字段，不自行补算 C7-owned hash。

新页计划缺少可写的可达导航入口时，`submit_plan` 会在创建 C7 候选前拒绝并提示补充导航页；该次计划未接受，可在同一 run 更正后重交，无需 abort。此检查只判断范围是否允许接通，候选完成后仍检查实际链接与全页可达性。已接受的队列保持冻结，之后扩大范围仍走现有恢复与授权流程；导航页的 Claims 漂移不能通过直接修改正式文件绕过。

仅当 finish 返回结构化 `status: complete` 且 `published: true` 才报告正式 Wiki/Claims 更新完成。`review_required`、`publish_pending`、`repair_ready`、`needs_clarification` 都未完成；按返回 nextAction 处理，故障时加载 recovery 引用。

`needs_clarification` 先区分来源/语义/授权决策与技术故障。链接、格式、证据引用等能在批准范围内修复的先自主修复；不影响核心事实的缺口按协议标 provisional。只有确实缺用户决策才集中提问，不自动启动 Grill-me。修复次数上限不是“用户必须作决定”的证据；触达后保留候选和回执，说明具体未解决问题及协议允许的下一步，不盲目重试、不冒充完成。

实现至少 0.1.2 才能发布。新版保留正式根与既有主题目录，逐个替换变更 Markdown；目录监听和只读预览可继续打开。所有 Wiki 写者必须使用同一 MCP 锁协议，提交期间外部工具不得同时改写正式文件。发布完成后不自动打开正式文件预览或切换工作目录；用户明确要浏览时再加载 visualize 引用。文件独占锁仍可能阻止单个文件替换，此时保留原回执和恢复义务，不强关其他进程。

官方 OpenWiki 和 Viewer 是 SelfWorkflow 根固定的 submodule，自有适配层不得修改或猜 upstream 未冻结接口。格式迁移只在候选包生成，展示 byte/hash/diff 后按确认、Review、CAS 发布；不直接重写原始 Wiki 或 `.git`。六阶段不执行个人 Wiki commit、push、fetch 或 ref 操作。
