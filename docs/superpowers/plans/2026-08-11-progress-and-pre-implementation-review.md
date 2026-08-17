# SelfWorkFlow Progress, Code Implementation Contract, and Pre-implementation Review Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在既有进度、整体 Review 和侵入性预算基线上，为所有代码修改增加实施前代码契约与最终用户确认门禁。

**Architecture:** 进度反馈和代码实施契约保持为嵌入用户指令的厂商无关 Agent Policy；实施前整体 Review 复用 planned/`plan.gate`，不新增生命周期或持久状态。Light 使用对话内紧凑契约，Full/Deep 在设计、TEA 与实施计划中分别记录代码边界并经独立 Review 后由用户确认。侵入性预算加入现有 `code-quality` 和 Review 契约，不新增专用模块；按影响半径约束公共契约、全局宏/Build 变体、跨层基础设施和测试来源的生产改动。V2 按 Light 与 Full/Deep 分流 gate，V3 保持现有 `plan.integrated-review` 插槽。安装器沿用现有 hash-bound runtime 传播规则。

**Tech Stack:** Markdown/YAML、Python unittest、现有 SelfWorkFlow Catalog/Pipeline/installer。

---

**Current delta:** 当前 HEAD 及进入本任务前的脏工作树已经包含进度反馈、整体 Review 和侵入性预算。本计划本轮只新增代码实施契约、相应测试、两个既有 source-lock 更新和 knowledge profile 重装；不回滚或重复实现既有能力。

## Chunk 0: 脏工作区基线

### Task 0: 在当前增量的任何实现或测试修改前保存受保护基线

**Files:**
- Inspect: all dirty/untracked files
- Create after final confirmation: `build/audit/code-contract-before.patch`

- [x] 当前 HEAD 为 `08640be26b051354615941a11a65342a9a953297`；staged diff 为空。进入本增量前已经存在其他任务的 tracked/untracked 修改，全部视为用户已有修改，不回滚、不覆盖。
- [x] 全部受保护 dirty/untracked 路径、状态和完整 SHA-256 固化在 `docs/reviews/2026-08-11-code-contract-baseline.md`；计划文档包本身单独以整体 Review hash 绑定。
- [ ] 用户最终确认后、第一次测试编辑前执行 `New-Item -ItemType Directory -Force build\audit`，再执行 `git diff --binary --output=build/audit/code-contract-before.patch 08640be26b051354615941a11a65342a9a953297 -- .`；记录该 patch 的 SHA-256。最终比较始终使用固定原始提交，不使用届时 HEAD。
- [ ] 最终同时检查 baseline manifest、before patch、`08640be...`→最终总 diff、允许列表内的任务增量和 staged diff；对原有 hunk 逐项确认仍存在。

### Gate 0.5: 独立 Review 与用户实施确认

- [ ] 对设计、TEA、实施计划和 dirty-baseline 审计清单四文件包运行新的独立只读 SubAgent Review，并绑定四个 SHA-256。
- [ ] 修正所有 Critical/Important，处置每个 Minor；任一包内文件变化后重新整体 Review。
- [ ] Review `pass` 后向用户呈现设计 §6.1 的最终代码实施契约及四个最终文件 hash，并取得明确的“确认实施”。此前的方案选择不替代本门禁。
- [ ] 只有以上三项全部满足才进入 Task 1；否则不得编辑任何测试或生产策略文件。（对应 AC-13/14/15）

## Chunk 1: 契约与测试

### Task 1: 写入失败的行为与安装传播测试

**Files:**
- Modify: `tests/behavioral/test_workflow_matrix.py`
- Modify: `tests/behavioral/test_code_quality_scenarios.py`
- Modify: `tests/behavioral/scenarios/code-quality.yaml`
- Modify: `tests/conformance/test_runtime_snapshot.py`
- Modify: `tests/installer/test_apply.py`

- [ ] 在 workflow matrix 中断言 core/WORKFLOW 包含确认前允许/禁止行为、正式文档分工、Review→用户确认→TDD 顺序、契约失效和 Light 紧凑边界。
- [ ] 在 runtime snapshot 与 installer apply 测试中断言 knowledge profile `WORKFLOW.md` 和安装后 `AGENTS.md` 传播同一组关键词。
- [ ] 增加“已确认局部实现后发现公共枚举/全局宏捷径”的契约失效压力场景，以及“同一责任层私有辅助函数调整”的预算内反例。
- [ ] 增加代码实施契约断言：第一次编辑测试/生产代码前必须覆盖修改预期、影响半径、安全、性能、可维护性/回滚并取得用户明确实施确认；旧规则应先 Red。
- [ ] 增加 Full/Deep 文档分工、Review→用户确认→TDD 顺序、越界确认失效，以及 Light 紧凑内联契约的正反场景。
- [ ] 运行 Red：`.venv\Scripts\python.exe -m unittest tests.behavioral.test_workflow_matrix.LightweightPolicyTextTests.test_code_implementation_contract_precedes_all_code_edits tests.behavioral.test_code_quality_scenarios.CodeQualityScenarioTests.test_skills_are_standalone_generic_and_contain_core_invariants tests.conformance.test_runtime_snapshot.RuntimeSnapshotTests.test_default_runtime_is_deterministic_lightweight_core tests.installer.test_apply.InstallApplyTests.test_real_knowledge_runtime_installs_progress_and_integrated_review_policy -v`。预期仅因 core/WORKFLOW/Skill/安装产物缺少代码实施契约关键词而失败，不得是导入或 fixture 错误。

## Chunk 2: 最小实现

### Task 2: 更新轻量与完整工作流文本

**Files:**
- Modify: `workflow/core.md`
- Modify: `WORKFLOW.md`
- Modify: `skills/code-quality/SKILL.md`
- Modify: `catalog/domains/workflow.yaml`
- Modify: `catalog/domains/code-quality.yaml`

- [ ] 增加统一代码实施契约：确认前只允许只读分析和文档修订；测试代码也不得提前写；Full/Deep Review 通过并修正后，用户明确确认最终摘要才允许进入 TDD。
- [ ] 明确设计、TEA、实施计划各自的代码相关必填内容；Light 只使用对话内紧凑摘要，不强制正式文档或 SubAgent。
- [ ] 明确越过责任层、公共契约、侵入性、安全、性能、维护或测试接缝预算时停止并重新 Review/确认；预算内局部细节不重复询问。
- [ ] 提交 core 前执行 `git diff --cached --quiet`；`git add -- workflow/core.md` 后要求 `git diff --cached --name-only` 恰为 `workflow/core.md`，执行 `git commit -m "feat: require code implementation contract" -- workflow/core.md`，将 `git rev-parse HEAD` 保存为 workflow revision，并以 `Get-FileHash workflow/core.md -Algorithm SHA256` 保存完整 contentHash。
- [ ] 再次要求 staged diff 为空；对 `skills/code-quality/SKILL.md` 重复限路径 add/name-only 检查，执行 `git commit -m "feat: gate code changes on approved contract" -- skills/code-quality/SKILL.md`，单独保存 code-quality revision/contentHash。两次提交均不 push、不夹带测试、Catalog 或其他脏文件。
- [ ] 使用保存的两个 revision/contentHash 精确 patch 对应 Catalog；提交后再次确认 staged diff 为空。

### Task 3: 证明 V2/V3 路由未受当前增量影响

**Files:**
- Verify only: `catalog/modules.yaml`
- Verify only: `workflow/v3/pipeline.yaml`
- Verify only: `catalog/v3/**`

- [x] 这些路由属于进入当前任务前的受保护基线，不是本轮代码实施契约增量。
- [ ] 本轮不得修改 `catalog/modules.yaml`、`workflow/v3/pipeline.yaml` 或 `catalog/v3/**`；只运行现有 PlanGraph 回归证明没有路由变化。（对应 AC-2/3/9）

### Task 4: 运行 Green 与最窄回归

**Files:**
- Verify only

- [ ] 运行目标 Green：与 Task 1 的 Red 命令相同，预期全部通过。
- [ ] 运行最窄回归：`.venv\Scripts\python.exe -m unittest tests.behavioral.test_workflow_matrix tests.behavioral.test_code_quality_scenarios tests.conformance.test_runtime_snapshot tests.installer.test_apply tests.unit.v3.test_plan_graph -v`，预期 exit 0。
- [ ] 运行 Catalog source-lock 校验：`.venv\Scripts\python.exe -m unittest tests.unit.test_catalog tests.unit.v3.test_catalog -v`，预期 exit 0；使用 `Get-FileHash -Algorithm SHA256` 重算 core/Skill hash，revision 只取各自限路径本地提交的 `git rev-parse HEAD`。
- [ ] 使用 Task 0 基线执行 `git diff --check`，并审计基线→最终任务增量和重叠 hunk，不覆盖已有 C7OpenWiki 修改。

## Chunk 3: 发布与验收

### Task 5: post-landing Review

**Files:**
- Review complete diff

- [ ] 对最终完整 diff 检查验收覆盖、逻辑闭环、失败路径、安全、侵入性和无关修改；单列公共头文件、Build/宏、公共契约、跨层依赖、测试来源的生产改动和编译变体形成 `intrusion delta`。
- [ ] 核对最终 policy 与 Skill 没有新增阶段、Schema、默认模块或长期状态；确认代码实施契约只是复用现有门禁。
- [ ] 报告 `workflow/core.md` 与 `skills/code-quality/SKILL.md` 相对 Task 0 的行数/词数增量，检查没有长篇重复、没有强制 Light 生成文档/SubAgent；不设脆弱的固定 token 阈值，但任何可合并的重复说明都应压缩。
- [ ] 修正任何有效发现后，重新执行受影响测试；旧证据失效。

### Task 6: 构建、安装和核验 knowledge profile

**Files:**
- Runtime output under the configured user SelfWorkflow installation only

- [ ] 构建：`.venv\Scripts\python.exe -m selfworkflow.cli build --repository . --output build\code-contract-runtime --version 0.1.0.dev0 --profile knowledge`，预期 exit 0 且产生 `artifact-manifest.json`。
- [ ] 生成计划：先执行 `$artifactPath = (Resolve-Path -LiteralPath build\code-contract-runtime).Path`，再执行 `.venv\Scripts\python.exe -m selfworkflow.cli install plan --artifact $artifactPath --agents-root "$env:USERPROFILE\.agents" --codex-root "$env:USERPROFILE\.codex" --state-root "$env:LOCALAPPDATA\SelfWorkFlow\state" --version 0.1.0.dev0 --output build\code-contract-install-plan.json`；读取并检查 `status=ready`、目标清单和 `planHash`。安装器继续拒绝未解析的相对 artifact root。
- [ ] 应用、验证和失败回滚使用下面的完整 PowerShell 块；保存原 artifact、`transactionPath`、rollback plan hash 和最终 artifact：

```powershell
$oldCurrent = Get-Content -LiteralPath "$env:USERPROFILE\.agents\selfworkflow\current.json" -Raw | ConvertFrom-Json
$oldArtifactHash = $oldCurrent.artifactHash
$plan = Get-Content -LiteralPath build\code-contract-install-plan.json -Raw | ConvertFrom-Json
$applyJson = & .venv\Scripts\python.exe -m selfworkflow.cli install apply --plan build\code-contract-install-plan.json --confirm-plan-hash $plan.planHash
if ($LASTEXITCODE -ne 0) { throw "install apply failed" }
$apply = $applyJson | ConvertFrom-Json
try {
    $verifyJson = & .venv\Scripts\python.exe -m selfworkflow.cli install verify --manifest $apply.manifestPath
    if ($LASTEXITCODE -ne 0) { throw "install verify failed" }
    $verify = $verifyJson | ConvertFrom-Json
    if ($verify.status -ne "verified") { throw "install status was not verified" }
} catch {
    $verifyError = $_
    .venv\Scripts\python.exe -m selfworkflow.cli install rollback-plan --transaction $apply.transactionPath --output build\code-contract-rollback-plan.json
    if ($LASTEXITCODE -ne 0) { throw "verify failed and rollback-plan failed: $($verifyError.Exception.Message)" }
    $rollbackPlan = Get-Content -LiteralPath build\code-contract-rollback-plan.json -Raw | ConvertFrom-Json
    $rollbackPlanHash = $rollbackPlan.planHash
    $rollbackJson = & .venv\Scripts\python.exe -m selfworkflow.cli install rollback --plan build\code-contract-rollback-plan.json --confirm-plan-hash $rollbackPlanHash
    if ($LASTEXITCODE -ne 0) { throw "verify failed and rollback execution failed: $($verifyError.Exception.Message)" }
    $rollback = $rollbackJson | ConvertFrom-Json
    if ($rollback.status -ne "rolled-back") { throw "rollback status was not rolled-back" }
    $restored = Get-Content -LiteralPath "$env:USERPROFILE\.agents\selfworkflow\current.json" -Raw | ConvertFrom-Json
    if ($restored.artifactHash -ne $oldArtifactHash) { throw "rollback did not restore the prior artifact" }
    throw $verifyError
}
$newCurrent = Get-Content -LiteralPath "$env:USERPROFILE\.agents\selfworkflow\current.json" -Raw | ConvertFrom-Json
.venv\Scripts\python.exe -m selfworkflow.cli install rollback-plan --transaction $apply.transactionPath --output build\code-contract-rollback-plan.json
if ($LASTEXITCODE -ne 0) { throw "post-install rollback plan generation failed" }
$rollbackPlan = Get-Content -LiteralPath build\code-contract-rollback-plan.json -Raw | ConvertFrom-Json
$rollbackPlanHash = $rollbackPlan.planHash
```
- [ ] 检查 `C:\Users\Administrator\.agents\selfworkflow\current.json`、snapshot `WORKFLOW.md` 和 `C:\Users\Administrator\.codex\AGENTS.md` managed block 都绑定新 artifact hash 且包含新规则。
- [ ] 汇报实际测试证据、未验证能力、残余风险、新 artifact hash，以及为 Git source-lock 创建的单文件本地技术 commit；不得 push。
