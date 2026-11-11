# 按需上下文压缩与恢复

日期：2026-11-11。任务沿原绑定 `758d7cd7a28a014e197fa1e0f508429454613bb9d2917e29afaec4428c8e35b7`；只维护仓库、来源与文档交付，不安装全局、不发布远端、不重启宿主。

## 接入与职责

- 维护来源采用 `dependencies/upstream/context-engineering` submodule，固定到原已核验的 `9ff0c99108b36d3b886defd825d8ac1f47dba374`；新增研究用锁，记录 tree、所选原文与许可的 UTF-8/LF SHA-256。此来源不进入 normal 初始化清单或生成复制路径，更新只提供待审候选方法。
- `WORKFLOW.md` 保留原交接字段与增量合并要求，用短路由替换原恢复细则。`workflow/modules/context.md` 按需负责安全压缩、原状态复用、缺能力处理、事实核对和恢复；未新增原生 Skill、常驻提示、hook 或第二套状态。
- `workflow/references/context-compaction-evaluation.md` 仅供维护调优/显式评估，区分静态结构、隔离样例与宿主真实压缩证据；对照整任务 token、恢复质量和遗忘代价，不将字符数或上游压缩率冒充收益。来源记录与 README 说明初始化、审查升级及自包含消费边界。

## 验证

来源身份已核对：gitlink、HEAD、tree、URL、干净工作树、三份选定文件 hash 与许可 hash 全部一致。同一独立 Reviewer 已完成源码、生成正文、紧凑性及最终验证证据覆盖，Critical/Important/Minor 均为 0，无必要待审项；本次文档与分发维护验收关闭。真实部署效果仍按下述缺口单独保留。

静态样例覆盖普通小修改/阶段切换不触发、有压力但在途写入先保存、无接口只准备、相同文件/决策增量合并、输入变化使原证据失效、截断输出局部恢复、交接不得新增授权，以及无进展停止重复压缩。它们是边界检查，不是宿主压缩实测。

生成与检查均退出 0：`skill sync` 为 `synchronized`，`skill check` 为 `verified`；新 revision 为 `d2575b9587aa691db3e396331c32e3e73a124b0ceaf7f68b784bc03ac9fd4f20`。两处新 release 各 441 文件且逐字节一致；原绑定两处各 439 文件，内容 hash 仍等于原 revision。未手改生成文件或旧 release。

既有回归执行 29 个测试方法，27 个通过；两个 Review 边界测试出现 6 处固定文案断言失败，整组退出 1，不记为通过。只读对照将这两个测试所读的三份文件替换为 `HEAD` 内容后，同样复现全部 6 处断言；依赖的 Review/CodeGraph 规则文件与 HEAD 字节一致。本次未修改这些规则或测试，不为断言追加重复措辞。失败分别为 `test_workflow_makes_primary_only_codegraph_and_reviewer_read_only` 与 `test_review_evidence_and_followup_preserve_existing_boundaries`，原始失败及对照保留。

回归覆盖自包含 clone、旧任务版本保留、无效更新不切入口、引用闭合、原生/文档路由以及按需可选能力边界；本轮未新增只匹配文案的测试。执行参数、退出码与完整输出在本地 `out/context-compaction-20261111/regression-result.json`、`regression.log`；归因证据在 `baseline-review-boundary-result.json` 与对应日志，生成/检查结果在 `skill-sync.json`、`skill-check.log`。

## 紧凑性与限制

按 Unicode 字符、LF 换行统计，每文件计一次：源码 `WORKFLOW.md` 1,335 → 1,335；根 Skill 1,776 → 1,776；消费者入口 1,736 → 1,736。普通 Full 维护规则组合（消费者入口、Full、维护、质量、Review）5,821 → 5,821，不含任务候选/证据输入。新增按需模块 759 字符，触发后入口加模块为 2,495；仅维护/显式效果评估再增加 1,157 字符参考，总计 3,652。来源说明均不在普通恢复中展开。

基线入口来自编辑前原字节，公共规则文件来自原绑定与新 release；逐文件路径/hash、组合与口径见本地 `out/context-compaction-20261111/metrics.json`。两处新/原 release 的文件数及重算内容 hash 在 `publication-integrity.json`。字符数是静态开销指标，不等于 tokenizer、缓存、费用或延迟实测。

当前会话未执行宿主历史替换或相同历史的 usage 对照；实际压缩保真、整任务 token/计费/耗时收益为 `not-run/unverified`。本次没有更改宿主机制来绕过此能力缺口。已有两份无关文件的哈希保持，visualizer 子模块状态未变；基线及核对见本地 `out/context-compaction-20261111/baseline.json`、`protection.json`。
