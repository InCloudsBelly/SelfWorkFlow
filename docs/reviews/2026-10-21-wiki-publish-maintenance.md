# Wiki 发布流程维护（2026-10-21）

维护已完成，官方验证和新进程验收通过。依据为用户指定的“总结 e7fee894 提交到 Wiki”任务及其本地原始验证记录。共享对话链接当前不可访问，未以猜测补齐原始错误。维护未向正式 Wiki 发布测试文章。

## 故障与修正

1. **无关提交导致启动失败。** 原记录中的错误是 `Personal compatibility parent commit is stale.`。兼容校验改为依据完整受管模块源码清单，`parentCommit` 只记录生成清单时的来源。HEAD/index/worktree、Adapter、Skill、lockfile、物化标记和工具契约的内容绑定仍须全部有效。
2. **导航遗漏直到最终校验才暴露。** 原任务已完成两页候选，才因 `navigation_index` 不通过发现计划漏了入口；冻结队列只能经授权中止后重建。现在提交新页计划时，先判断范围能否从 `quickstart.md` 接通；没有可写的可达页面就提前拒绝，未创建 C7 候选，回退到同一 run 的 planning。可通过主题索引或已有链接接入，不强制每次修改 quickstart。已接受队列仍冻结，最终仍验证实际链接、Claims、Review 和 CAS。
3. **回归中另发现新主题目录误报 Claims 读取失败。** 允许尚无 Markdown 和 sidecar 的新路径返回无 Claims，不创建正式目录。已有 sidecar 没有当前 Markdown、版本漂移、链接或非目录路径仍拒绝。

导航预检只读取计划保留且不重写的页面正文，整个树的 revision 校验不变。这样删除或修复超大、非法 UTF-8 的旧页不会被新增门禁挡住；最终候选仍检查完整内容。Writer 与操作文档已明确手工导航需要显式 PageJob，自动生成的保留索引和运行元数据另由系统管理。

## 验证与审查

关键回归实际先失败后通过：无关父仓库提交；缺少导航后同 run 更正；新 namespace 只读 Claims 与孤立 sidecar 拒绝；删除或重写超限/非法编码旧页。隔离 Wiki 在未预建正式主题目录的情况下，完成主题、来源和入口三页的候选写作、Review、发布及逐字节回读。

其他边界覆盖主题索引、补齐已有链接、删除唯一导航桥接页、空 Wiki 初始化，以及内部读取额度与公开 256 KiB 读取上限的区别。测试类型检查、核心实现及新增回归的格式检查与 Skill 基础验证通过。独立 Reviewer 发现并推动修正待删/重写页的预检误阻断，复审后无遗留 Critical/Important；Reviewer 未代跑测试或索引。

首轮官方验证在测试阶段为审查修正主动停止，只停止经 PID、创建时间、父 PID 核对属于本 Agent 的验证进程树；不计为完整通过。大文件回归首轮遇到默认五秒超时，只为该组多次快照/复制的 IO 用例设置三十秒，未放宽全局测试或生产内容上限。

第一次完整运行为 **749/756**。其中六项因维护基础 Skill 文档后漏刷可信包哈希而失败；已用生产 `computeSkillPackage` 计算并更新可信清单及两个字面锁定向量，没有改成自动信任。另一项 Windows 来源快照清理用例连续复现五秒超时；生产清理重试窗口本身最高 5.25 秒，加上 prepare/verify 后超过默认测试时间，仅该用例调整为三十秒，断言和生产实现不变。原失败项已定向重测通过，基础 Skill 校验及全部 14 个 Skill eval 场景通过。独立 Reviewer 复审这些增量无 Critical/Important。

最终官方验证退出 0：**756/756 测试通过，97 个 suite，零失败、零跳过**；OpenWiki、MCP 和 Win32 helper 构建、两个 Skill 包校验、14 个 Skill eval 场景，以及 built stdio 的 external 与 personal 发布链路全部通过。能力证据由官方脚本在 smoke 成功后激活，buildId `6b8a6784-1201-4536-b66b-f42433a5af93`，verifiedAt `2026-10-21T03:28:22.459Z`。未手工生成或替换能力证据。

## 发布与运行状态

公共文档已发布并通过内容身份与引用闭包检查：revision `ac09c742ca29f74ae82a2620991b631ba69c93235a7645e5b73edd9324a31cb4`，418 份文档。固定入口仍为 [public/WORKFLOW.md](../../public/WORKFLOW.md)；本任务和独立 Reviewer 继续沿用开始时的 `635d1b…31e5`，新任务读取新入口。

新启动的构建产物使用现有存储配置通过真实 stdio 调用：schema 2、external mode、OAuth-free、39 项能力均绑定本轮 verifiedAt、ready=true、无活动事务、全部锁未持有、恢复状态 clean。`status` 与指定该 revision 的 `openwiki_read` 一致，安全索引读取成功。已经加载旧代码的 MCP 连接需重新连接一次；文档发布不等于该连接已热更新。

正式 Wiki 在维护期间有并行内容更新：已核对本任务最初 `status` 的实际工具记录时间与后续页修改时间。验收时当前版本与起始版本不同，因此不报告“Wiki 全程字节未变”。本任务未发布正式文章，保留当前 Wiki 内容，没有回滚他人的更新。

## 保护范围与限制

官方验证器取消删除两个 dist 目录的步骤，保留全部构建、测试、Skill、stdio smoke、产物 fingerprint 与证据撤销/激活门禁。沿用原有 Node、pnpm、.NET、Release/win-x64 环境；未执行 Clean/Rebuild、切换 Target 或清理编译缓存。构建输出目录身份与现有 bin/obj 保留。

个人兼容 JSON 的既有用户修改已备份；本次官方刷新仅改变 `build.adapterSetHash`、`build.parentSourceManifestHash` 与 `skill.packageHash`。Viewer 用户 diff 保持原 SHA256，未改正式 Wiki 内容、旧任务、Claims 数据或 Wiki Git。源码改动与新公共版本留在本地，未执行本任务的 commit/push。

主工作区 CodeGraph 增量维护先报 `codegraph-index-not-fresh`，最后两批为 `codegraph-project-busy`，保留原库，未重建、清锁或强制索引。独立 Git clone 在真正 missing 的数据库初始化后完成官方增量维护，最终 fresh；18 份受审源码与主工作区逐文件 SHA256 相同，完整验证后再次确认未变。该证据属于隔离源码候选，不代表主库已修复。CodeGraph MCP transport 不可用，结构查询使用 CLI。
