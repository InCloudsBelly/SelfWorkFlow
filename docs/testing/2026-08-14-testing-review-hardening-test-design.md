# 测试与 Review 强化 TEA 测试设计

## 风险分级

| 风险 | 等级 | 主要证据 |
| --- | --- | --- |
| 行为修改绕过 TDD | Critical | Resolver RED/GREEN；operation 或 archetype 任一行为信号均必选；冲突组合暂停；仅 mechanical/spec-document 明确豁免 |
| Full/Deep 静默跳过 TEA | Critical | Schema/PlanGraph 边界测试；缺失 Skill fail-closed |
| Review 漏掉未提交或未跟踪修改 | Critical | Review 契约与前向 SubAgent 场景测试 |
| 完成声明没有新鲜测试证据 | Critical | Verify Skill 契约、Runtime 产物和完成门禁测试 |
| Runtime 打包整个 TEA 或发生来源漂移 | Important | 固定 commit/树验证、允许清单和篡改失败测试 |
| 普通 Light 任务上下文膨胀 | Important | Runtime 清单与路由误触发测试 |
| Superpowers 残留进入默认流程 | Important | 活跃策略、Catalog invocation、post-Grill 搜索测试 |

## 测试接缝

- `build_runtime()`：验证固定来源、精选复制、篡改拒绝和制品边界。Matt 复制前必须同时匹配锁定 commit、完整 Git tree 且工作树无 dirty/untracked，辅助引用文件变化也拒绝。TEA 允许清单固定为 test-design、ATDD、test-review、trace、NFR 的完整目录闭包与 `LICENSE`；Catalog 只能引用 Runtime 内 `skills/tea-quality/references/...`。在没有项目 `_bmad` 的沙箱中，以五组固定 context/output 生成 invocation package，再把五份合法/非法结果送入输出契约校验；不得读取项目 `_bmad`、留下未解析变量或写越界产物。该 E2E 只证明 adapter/runtime 契约，不把模型语义质量标记为确定性证明。
- V3 `resolve` / PlanGraph：验证 operation、`max(complexity,risk,projectMinimums)` 推导的有效 strength、testLevelFloor 与静态模块选择；只读任务的实现编排槽必须不适用。
- Review builder：捕获批准路径的工作树与 index 字节、Git mode 及完整 dirty/untracked 指纹；最终包分别包含工作树和 staged 内容/mode/patch，覆盖 staged 新增后删除工作树文件及 mode-only 变化；批准路径外变化拒绝。
- Quality gate：验证 package 与收据绑定相同 `workflowMode`；Light 只接受一份结构化 `self_attested` 自审，Full/Deep 只接受同一 package hash 的 Standards/Spec `host_attested` 收据和不同 Host execution ID，跨模式证据拒绝。package 至少含一项用户确认的结构化 plan 和 `process-exit` 结果契约。Verify 执行前后重建 package，使用无 shell、无 stdin、仓库内 cwd、环境允许清单、超时与硬上限流式读取，超限终止进程树且必须确认终止，并生成 `runner_attested` 时间/argv/退出码/失败数/输出 hash/结构化消费者结果。Complete 从 baseline/spec/verification plans 自行重建当前包，拒绝外部 Verify 收据并自行重新执行全部绑定计划，不接受调用者声明的 current hash。
- Skill 文件：验证 frontmatter、阶段输入、双轴 Review、RED/GREEN 和 Verify 证据字段。
- 实施前前向 Review：一个新独立 SubAgent 只接收最终三文档包与 hash。实施后前向 Review：两个新的独立 SubAgent 分别执行 Standards/Spec，必须接收同一最终内容包并回传其 hash；不提供主 Agent 推理。

## RED/GREEN 用例

1. 旧 Runtime 缺少 TEA Skill；新增测试先失败，打包后通过。
2. Full/C2/R2+T1、Deep/C3/R3+T2 旧 Schema 接受；按最高要求增加约束后拒绝。
3. `implement.method` 旧路由允许空 TDD；新 `implement.tdd` 对写任务的任一行为 operation/archetype 强制选择且不与 diagnosing-bugs 冲突；`install+migration` 等写任务冲突组合暂停，`document+spec-document` 等真实非行为组合不误选；`review+bounded-feature` 等只读对象分类不得误入实现/TDD。
4. 旧 Review 只描述 `BASE..HEAD`；新 builder 必须输出包含实际 task delta 的完整内容包。
5. 旧 Complete 接受空计划及手工伪造/缺失/过期/失败证据；新 gate 拒绝空计划和任何外部 Verify 收据，自行运行计划，并分别拒绝 package 漂移、开放 Important、失败命令和 `unverified`。
6. 旧 Verify/Complete 指向占位 agent-native ref；V2/V3 新模块必须引用已安装、manifest/hash 绑定的 `testing-review-quality` Skill。
7. post-Grill 旧值为 `brainstorming-cross-review`；新值必须为 `independent-design-review`。
8. Matt/TEA 缺文件、commit 或完整 git tree 漂移、dirty 辅助文件、允许清单外复制和 Catalog 错误 Runtime 引用分别失败。
9. 无项目 `_bmad` 时五个 TEA 模式均可从本地入口解析；任何访问项目 `_bmad` 或未解析变量失败。
10. Review package 缺少需求、验收、设计、测试设计、计划或适用规则实际文本时失败。
11. 安装后验证故障注入及退休 Skill 删除后的故障注入触发既有 rollback；回读确认旧 `current`、manifest、bootstrap、已删除 Skill 和文件 hash 恢复。回滚失败阻止完成。
12. `core`、`knowledge`、`maintainer` 三个 Runtime profile 的根 `WORKFLOW.md` 必须与仓库根文件逐字节一致；V2 `design-grilling` 只能显式，默认 `design-core` 生效，V2 Review/Verify/Complete 不得保留 agent-native 占位。
13. `workflowMode` 缺失或跨模式重放、Full/Deep 中伪造 `host_attested` 之外的 Review receipt、相同 Host execution ID、Light 中非结构化自审、任何手工构造的 Verify receipt、完成前批准路径内外漂移均拒绝；Complete 必须自行实跑；Review 收据文档明确它不提供身份/模型认证。
14. V2 `implement/debug` 均静态选择 TDD；Full/Deep 静态选择 TEA design/review，诊断模块可与 TDD 组合。V2 与 V3 对同类请求不得产生质量等级倒挂。
15. 同一 baseline/spec/工作树/verification plans 连续构建两次，允许 `createdAt` 不同但 package hash 必须相同；绝对路径和临时目录不得进入语义 hash。
16. Verify runner 对未绑定 argv、shell、cwd 越界、环境注入、前后 package 漂移、超时和输出超限逐项拒绝；Windows Job / POSIX 进程组在父进程先退出时仍终止，先回收组长再确认子树；异常退出统一 finally 清空容器、等待 reader、关闭管道，清理失败覆盖原结果。
17. V2 Catalog 为 `testing-review-quality` 提供独立真实 revision/content hash；V3 source/index、Runtime manifest 与之同字节，任意篡改均构建失败。为建立及在 Review 修正后更新该 provenance，允许受控本地 commit：每次只包含该 Skill 路径，不 push、不暂存其他 dirty 内容；这是“不自动 commit”的唯一例外，提交前后都核对精确 staged set。
18. 五路 TEA 分别用表中最小 context 生成固定 invocation，验证 reference/input hash、相对输出和合法收据；context 与最终 Markdown 均扫描单段及复合未解析模板变量（包括 `{id}`、`{project-root}`），并逐项覆盖字段空缺、引用漂移、路径逃逸、Windows junction/reparse、输出缺失/过大/非 UTF-8、标题缺失和收据 hash 不匹配。

## 回归范围

- V3 catalog/pipeline/plan graph 与 quality gate 单元测试。
- Runtime snapshot、Matt foundation、安装 dry-run/幂等与安装后验证失败回滚测试。
- Skill 快速校验。
- 全量 Python 测试在聚焦测试通过后执行；与本任务无关的既有失败单独报告，不顺手修复。

## 不变量

- 不修改上游 Submodule 内容。
- 不覆盖现有未提交工作。
- 除为 `testing-review-quality` 建立或更新真实 Catalog provenance 的单一路径本地 commit 外，不自动 commit；不 push，不删除外部 Superpowers。每个该类 commit 只能暂存该 Skill 路径，若 staged set 不精确则停止。
- 不以文案存在代替 Runtime 文件、路由结果或真实命令证据。

## 完成门禁负向矩阵

- 模式字段缺失或不一致；Light 自审缺失；Full/Deep Standards 或 Spec 收据缺失、execution id 相同、package hash 不同：拒绝。
- 任一 `Critical`/`Important` 未清零：拒绝；Minor 必须有处置记录。
- Verify 命令未运行、非零退出、失败数大于零、时间早于最终 package、消费者结果缺失：拒绝。
- 任一必须项为 `unverified`、当前重建 package hash 变化或批准范围外内容变化：拒绝并要求重新 Review/Verify。
