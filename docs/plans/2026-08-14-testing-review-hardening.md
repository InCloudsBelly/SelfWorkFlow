# 测试与 Review 强化实施计划

## 批准范围

1. 强化生效的根 `WORKFLOW.md`；Runtime builder 的 `core`/`knowledge`/`maintainer` profile 统一从该文件生成制品策略。新增 `testing-review-quality` Skill 承载 TDD、双轴 Review、完整 diff 和新鲜 Verify 契约；既有 revision/hash 绑定的 `workflow/core.md` 与 `workflow-quality` 保持原字节。
2. 新增轻量 `tea-quality` 适配 Skill；Runtime builder 从锁定 TEA Submodule 只复制 test-design、ATDD、test-review、trace、NFR 五个完整目录闭包及许可证，并拒绝来源漂移或越界文件。本地入口只接受显式 stage/context/output，禁止依赖项目 `_bmad`。
3. 同步调整 V2/V3 Pipeline：独立 `implement.tdd` 槽在写任务的 operation（V2）或 operation/archetype 任一行为信号（V3）命中时强制 TDD；只读 Review/Verify 不反向进入实现或 post-landing Review 阶段。诊断模块不再与 TDD 冲突，V3 写任务分类冲突暂停；Full/Deep 强制 TEA 设计与测试 Review；Full/Deep 到 T2/T3 fail-closed。
4. 新增最小本地 quality helper：捕获批准路径的工作树/index 字节与 Git mode 及完整 dirty/untracked 起点，生成包含实际工作树/staged delta、mode-only 变化、`workflowMode` 和确认后验证计划的确定性 Review package。Light 使用一份绑定模式的结构化自审，Full/Deep 使用两份绑定模式的独立双轴 Review；模式证据不可跨级复用。runner 绑定计划、重建 package、硬限制输出，并以 Windows Job / POSIX 进程组覆盖父进程先退出的子树；所有启动后退出统一 finally 清理，先回收组长再确认容器为空。Complete 不接收外部 Verify JSON，自行实跑全部计划后判定。
5. 将 V2/V3 Review/Verify/Complete 的占位能力替换为已安装 `testing-review-quality` Skill 与 quality helper 契约；V2/V3 按 Light/Full/Deep 路由 Grill，Deep 不重复加载其内部的 `grilling`；修正 post-Grill 的 Brainstorming 残留。
6. 增加聚焦测试、Runtime 测试和前向独立 Review，验证后按现有安装事务重建当前用户 Runtime。

## 预计修改位置

- 策略：`WORKFLOW.md`、`skills/testing-review-quality/SKILL.md`、`capabilities/workflow-quality/evidence-and-operations.md`；新 Skill 及 Review 后的同路径修正分别形成只包含该路径的受控本地 provenance commit（本次实施授权下“不自动 commit”的唯一例外，不 push），再由专属 V2 source entry、V3 source/index 与 Runtime manifest 绑定最终 revision/hash。每次提交前后核对 staged set，发现任何用户无关 dirty/staged 文件即停止。
- TEA/Matt 来源：`skills/tea-quality/**`、`src/selfworkflow/adapters.py`、`src/selfworkflow/v3/tea_adapter.py`、TEA Catalog modules；按设计表实现五路固定 context、invocation hash、Markdown 标题与 receipt 校验，增加沙箱 E2E 和全部失败条件；Matt Runtime 复制前核对锁定 commit、完整 tree 和 dirty 状态。
- 路由：`catalog/modules.yaml`、`workflow/pipeline.yaml`、`workflow/v3/pipeline.yaml`、V3 request schema、相关 modules/index、post-Grill policy/schema。
- Review/完成门禁：`src/selfworkflow/quality.py`、最小 CLI 接线与对应 Schema/测试；Review 收据只声明 host-attested，Verify 由 runner 执行；不新增后台状态、信任数据库或服务。
- 测试：新增聚焦 conformance/quality 测试；更新 V3 pipeline/plan graph、Runtime snapshot 与 Matt foundation 测试。
- 安装：只使用现有安装事务。安装前记录 `current.json`、artifact hash 与回滚快照；成功后逐文件回读 manifest 和全局 AGENTS bootstrap。增加安装后验证失败与“退休 Skill 已删除后失败”注入：必须调用既有 rollback，并逐文件验证旧指针、manifest、bootstrap、被删 Skill 和文件 hash 恢复；回滚失败阻止完成。用户本轮实施授权包含该工作流升级，不改变外部 Skill 目录所有权。

## TDD 顺序

1. 写入 Runtime 策略来源错误、TEA 缺失、TDD 可跳过、有效强度/测试等级不闭合、只读任务误入实现、空验证可完成、runner 漂移/输出边界、TEA 模板/reparse、完整 Review package/Complete 负向条件、V2/V3 Review/Verify 占位和 post-Grill 残留的失败断言。
2. 运行聚焦 RED，确认失败原因对应旧行为。
3. 按 owner 层最小修改：策略 → Runtime 打包 → Pipeline/Schema → Catalog metadata。
4. 重跑同一聚焦集合至 GREEN，再运行最窄相关回归。
5. 对最终完整 diff 启动 Standards/Spec 两路独立 Review；修复 C/I，处置 Minor。
6. 重建 Runtime、执行安装验证和新的原生 Agent 前向检查。

## 禁止边界与回滚

- 禁止修改 Matt/TEA Submodule、C7OpenWiki 行为、知识库数据、凭据和无关迁移代码。
- 禁止新增公共网络接口、持久 Schema、后台服务或项目级 BMAD 目录。
- 禁止把测试便利变成新的生产架构。
- 回滚按本任务精确文件 diff 反向恢复；不使用 `reset --hard`，不清理其他未提交内容。

## 验证命令

- `python -m unittest tests.conformance.test_testing_review_hardening`
- `python -m unittest tests.unit.test_quality_gate`
- `python -m unittest tests.behavioral.test_v3_tea_workflow tests.unit.v3.test_pipeline tests.unit.v3.test_plan_graph`
- `python -m unittest tests.conformance.test_runtime_snapshot tests.conformance.test_matt_skills_foundation`
- `python -m unittest discover -s tests`
- Skill quick validation、`git diff --check`、完整任务 diff Review。

使用当前会话 `python` 对应的绝对解释器，并在证据中记录 `sys.executable` 与版本。聚焦命令最长 120 秒，全量测试最长 10 分钟；成功标准为退出码 0、所选测试 0 failure/0 error，实际测试数由命令输出记录，不预填可能过期的数字。
