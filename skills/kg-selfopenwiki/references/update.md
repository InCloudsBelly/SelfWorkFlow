# 个人 Wiki 候选与发布

候选与已授权写入按本页。propose 止于候选。

写作流程与内容验收复用 [Wiki 工作流](../../wiki-workflow/SKILL.md)，本页只承接所选后端生命周期。在 `PagePlan.instructions` 留规则绑定及覆盖引用，按角色交接可达的同版规则、候选和证据。同专题跨 PageJob 复用，不可达时补一次必要正文。独立 Reviewer 复用有效证据，取得生命周期 binding 与 C7 reviewPackage，回执绑定实际发布候选。

默认使用 `selfopenwiki:personal-openwiki-v1` 的实时 schema。首次 `openwiki_status` 确认 schema 2、external mode、OAuth-free、`externalAgent.ready=true`、恢复闭环及以下能力均 verified。

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

沿用既有主题、目标与来源授权。读当前 revision，给出紧凑方案后继续，把必要来源页和导航纳入计划。跨主题重组、删除知识或来源许可/暴露范围变化须确认。

用已授权的绝对本机路径按实时协议 prepare，核实 manifest 的全部来源与版本。匹配时将授权映射到确认字段并留依据。超范围时列必要来源确认，拒绝或敏感来源不得绕过。

revision 冲突先刷新并比较受影响页面。主题、来源和结果未变且无语义冲突时自行重算绑定、候选并复核影响项，内容冲突或超范围才集中确认。冻结事务走协议恢复/重建，保留旧回执与并发修改。按返回的 Skill/work package 读取当前阶段所需规则及协议。

同一 Wiki 由主调度串行写入。沿用可用的原生 MCP，批量或需用 SDK 重连时读[SDK 调用](sdk.md)。

按以下顺序推进，每个 PageJob 循环步骤 3–5。

1. `openwiki_begin`：由 adapter 注入 status 已绑定的 `wikiRoot`，绑定 Wiki revision、Skill 和 upstream revision。传入不同根必须拒绝。
2. `openwiki_submit_plan`：只提交页面/删除计划，生成持久化队列。新增页先查入口和主题导航，规划从 `quickstart.md` 可达的链路，可经主题索引。手工导航页须列为 PageJob。
3. `openwiki_next_page`：一次一个 PageJob；Writer 只写返回的 candidate package 分配路径。
4. `openwiki_inspect_page_claims`：修改或撤回已有 Claim 前读取绑定页面的完整 Claim 集，不猜 Claim、证据或 hash。
5. `openwiki_submit_page`：提交候选页面与 sparse Claim decisions；不写正式 Wiki。不能覆盖已 accepted 的不同 payload。
6. `openwiki_finish`：按 candidate receipt → 独立 Review receipt → C7 CAS publish 推进；只接受真实绑定字段，不自行补算 C7-owned hash。

导航范围不足会在建 C7 候选前拒绝。未接受的计划可在同一 run 更正重交。候选完成后验证实际链接和页面可达性。已接受队列冻结，扩围走授权与恢复，导航 Claims 漂移也须经候选处理。

只凭结构化 `status: complete` 且 `published: true` 报 Wiki/Claims 更新完成。其他状态按 `nextAction` 处理，故障才读[恢复](recovery.md)。`needs_clarification` 时先修授权内的技术问题，非核心事实缺口按协议标 provisional，缺来源/语义/授权决策才提问。修复上限触达后保留候选与回执，报告具体未解项及允许的下一步。

发布要求实现 ≥0.1.2。保留正式根和既有主题目录，只替换变更 Markdown。所有写者用同一 MCP 锁协议。发布期间允许监听与只读预览，外部工具不得并发写。独占锁阻塞时保留回执，沿恢复流程，勿强关其他进程。按请求浏览或切换目录。

只用固定 OpenWiki、Viewer 和已核适配契约。格式迁移在候选包展示 byte/hash/diff，按确认、Review、CAS 发布。六阶段走 MCP，个人 Wiki 的 Git 操作另核授权。
