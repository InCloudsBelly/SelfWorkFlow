# C++ Code Intelligence Providers V3 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不破坏 V2 兼容性的前提下，交付一个可运行、可测试的 V3 核心：按任务路由 C++ 增强能力，显式绑定本地 Provider 覆写，安全执行 Provider 查询与维护，并强制执行 Grill-me 后独立 Brainstorming Review。

**Architecture:** 先建立独立于 V2 的 V3 orchestration spine（Catalog、Pipeline、PlanGraph、Selection、Host、Ledger），再接入“稳定能力 ID → 静态 Provider 绑定 → 动态项目状态 → 查询/维护计划 → 收据”。路由器只选择能力，不直接依赖 CodeGraph、Serena 等品牌；真实副作用经过计划、授权、项目 lease 和证据校验。V2 文件、请求和解析行为保持原状，V3 通过显式 `schemaVersion: 3` 分派。

**Tech Stack:** Python 3.11、`unittest`、PyYAML、jsonschema Draft 2020-12、PowerShell、Windows batch、YAML/JSON Schema。

---

## 实施边界

本计划同时落实以下已批准设计：

- [V3 自适应质量模块设计](../specs/2026-08-09-adaptive-quality-modules-v3-design.md)
- [V3 C++ 代码智能与 Provider 设计](../specs/2026-08-09-cpp-code-intelligence-providers-v3-design.md)

首个可交付版本必须真正支持：

1. V3 请求、路由、Provider 绑定、查询计划与收据的闭环。
2. 内置 `cpp-core` 和按需 C++ 专项能力路由。
3. Fake Provider 的完整成功、失败、漂移、授权和并发测试。
4. 手工配置的本地 CodeGraph 覆写、只读检查、状态诊断和显式维护计划。
5. Grill-me 后独立、无继承上下文的 Brainstorming Review 强制门禁。
6. 一键安装和 Provider 管理入口；机器私有配置不进入 Git。

首版不虚构支持：Serena、DebugMCP、Joern、Trail of Bits 等仅进入 `candidate` 或 `unverified` 清单；在对应原生验收完成前不得路由为 `supported`。首版也不自动克隆、升级或修改用户拥有的本地 Provider 源码。

## 强制实施节奏

以下五个阶段可独立运行和提交：V3 主干、Provider 安全内核、C++ 路由、Post-Grill Host Gate、CodeGraph/安装器。每个阶段内对下列“测试项”逐项执行同一微循环，禁止先批量写完所有测试再实现：

1. 只新增一个行为测试并运行，确认它因计划指定的缺失行为和错误码失败；导入错误、路径错误不算有效 RED。
2. 只实现使该测试通过的最小代码。
3. 运行该聚焦测试，再运行本阶段已通过的全部测试。
4. 每完成一个完整契约切片，再运行 V2 相关回归并提交。

所有测试统一通过仓库入口执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test <dotted-module-or-test>
```

不得直接调用系统 `python`；当前仓库测试依赖 `.venv` 和脚本设置的 `PYTHONPATH`。

## Phase 1: 建立 V3 orchestration spine

**Files:**

- Create: `schemas/v3/resolve-request.schema.json`
- Create: `schemas/v3/resolve-result.schema.json`
- Create: `schemas/v3/plan-graph.schema.json`
- Create: `schemas/v3/run-ledger.schema.json`
- Create: `schemas/v3/pipeline.schema.json`
- Create: `schemas/v3/catalog.schema.json`
- Create: `schemas/v3/module.schema.json`
- Create: `schemas/v3/selection-receipt.schema.json`
- Create: `schemas/v3/diff-signal-set.schema.json`
- Create: `schemas/v3/review-finding.schema.json`
- Create: `schemas/v3/review-aggregate.schema.json`
- Create: `schemas/v3/test-strategy.schema.json`
- Create: `schemas/v3/coverage-result.schema.json`
- Create: `workflow/v3/pipeline.yaml`
- Create: `catalog/v3/index.yaml`
- Create: `src/selfworkflow/v3/__init__.py`
- Create: `tests/unit/v3/__init__.py`
- Create: `src/selfworkflow/v3/contracts.py`
- Create: `src/selfworkflow/v3/catalog.py`
- Create: `src/selfworkflow/v3/pipeline.py`
- Create: `src/selfworkflow/v3/plan_graph.py`
- Create: `src/selfworkflow/v3/selector.py`
- Create: `src/selfworkflow/v3/host.py`
- Create: `src/selfworkflow/v3/ledger.py`
- Create: `src/selfworkflow/v3/resolver.py`
- Modify: `src/selfworkflow/cli.py`
- Test: `tests/unit/v3/test_orchestration_schemas.py`
- Test: `tests/unit/v3/test_catalog.py`
- Test: `tests/unit/v3/test_pipeline.py`
- Test: `tests/unit/v3/test_plan_graph.py`
- Test: `tests/unit/v3/test_selector.py`
- Test: `tests/unit/v3/test_host_ledger.py`
- Test: `tests/unit/v3/test_version_dispatch.py`
- Test: `tests/unit/test_resolver.py`

- [ ] **Step 1: 逐个关闭 V3 orchestration Schema**

  按强制微循环依次实现上述 12 个 Schema。共同测试包括未知字段、重复 JSON key、版本不一致、非法 hash/UTC/attempt；每个 Schema 还需一个最小合法 fixture 和一个专属非法 fixture。第一个 RED 必须是 `test_v3_resolve_request_schema_is_available` 失败并报告 `v3-schema-not-found`。

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_orchestration_schemas
  ```

  Expected after all micro-loops: PASS。

- [ ] **Step 2: 实现独立 V3 Catalog 和 Pipeline loader**

  不修改或软链接 V2 Schema。V3 Catalog 编译器只读取 `catalog/v3/index.yaml` 并输出 V3 envelope；Pipeline loader 只读取 `workflow/v3/pipeline.yaml`。测试版本混用、未知模块、依赖环、hash 漂移和稳定排序。每项先 RED（例如 `v3-catalog-version-mismatch`）再最小 GREEN。

- [ ] **Step 3: 实现 PlanGraph、bounded selector 和 SelectionReceipt**

  selector 只能在 PlanGraph 给定的 eligible 子集中选择；输出包含 `selectionPolicyHash`、候选/选中模块、理由、上下文成本和 receipt hash。测试越权选择、重复模块、冲突、预算边界、静态/运行期选择和确定性。

- [ ] **Step 4: 实现 Host stage handoff、扩展请求和 RunLedger validator**

  Host 校验 stage result 与 PlanGraph 的 `planHash`、`attempt`、输入/输出 schema、SelectionReceipt 和 capability snapshot。当前 Gate 通过后，Host 在同一 immutable PlanGraph 和同一 Ledger 内推进正常下一阶段；只有请求 eligible 集合外能力时才产生 `nextStageRequest`，重新计算快照和 PlanGraph，并把旧 Ledger 标记为 `superseded`。测试必须证明正常推进不产生新计划，以及扩展请求产生新 planHash 并 supersede 旧 Ledger。Ledger 还应拒绝 receipt 版本混用、旧 attempt、hash 漂移、越过前驱阶段和非 eligible 模块。

- [ ] **Step 5: 实现显式 V2/V3 分派并回归**

  CLI/Resolver 仅根据请求 `schemaVersion` 进入 V3；V3 输出、PlanGraph、RunLedger 必须同版本。V1/V2 入口、错误文本和既有测试保持不变。

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_orchestration_schemas
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_catalog
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_pipeline
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_plan_graph
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_selector
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_host_ledger
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_version_dispatch
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.test_resolver
  ```

  Expected: PASS。

- [ ] **Step 6: 提交 V3 主干**

  ```powershell
  git add schemas/v3 workflow/v3 catalog/v3 src/selfworkflow/v3 src/selfworkflow/cli.py tests/unit/v3 tests/unit/test_resolver.py
  git commit -m "feat: add v3 orchestration spine"
  ```

## Phase 2A: 实现 Provider 关闭契约、显式配置和静态绑定

**Files:**

- Create: `providers/v3/catalog.yaml`
- Create: `providers/v3/codegraph-public.yaml`
- Create: `providers/v3/codegraph-local-template.yaml`
- Create: `providers/v3/candidates.yaml`
- Create: `schemas/v3/provider-descriptor.schema.json`
- Create: `schemas/v3/provider-local-config.schema.json`
- Create: `schemas/v3/provider-binding-snapshot.schema.json`
- Create: `schemas/v3/provider-support-matrix.schema.json`
- Create: `schemas/v3/provider-source-identity.schema.json`
- Create: `schemas/v3/provider-project-state-receipt.schema.json`
- Create: `schemas/v3/provider-operation-plan.schema.json`
- Create: `schemas/v3/provider-approval-receipt.schema.json`
- Create: `schemas/v3/provider-operation-receipt.schema.json`
- Create: `schemas/v3/provider-query-plan.schema.json`
- Create: `schemas/v3/provider-query-receipt.schema.json`
- Create: `schemas/v3/provider-mutation-evidence.schema.json`
- Create: `schemas/v3/workspace-fingerprint.schema.json`
- Create: `src/selfworkflow/v3/provider_config.py`
- Create: `src/selfworkflow/v3/provider_binding.py`
- Create: `src/selfworkflow/v3/support_matrix.py`
- Test: `tests/unit/v3/test_provider_schemas.py`
- Test: `tests/unit/v3/test_provider_config.py`
- Test: `tests/unit/v3/test_provider_binding.py`
- Test: `tests/unit/v3/test_support_matrix.py`

- [ ] **Step 1: 逐个关闭 Provider Schema**

  按强制微循环实现设计列出的 12 个 Provider Schema。`provider-source-identity` 必须是 `git-tree | binary-or-package-build | service | host-native` 判别联合；`provider-mutation-evidence` 必须是 `filesystem-manifest | managed-state-manifest | process-state-delta | service-state-delta` 判别联合。枚举回归测试必须拒绝旧拼写 `git`、`package-or-binary`、`filesystem-delta` 和 `managed-state-delta`。先运行 `test_provider_descriptor_schema_is_available`，Expected RED：`v3-schema-not-found`；最终：

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_provider_schemas
  ```

  Expected: PASS。

- [ ] **Step 2: 写优先级和误配置失败测试**

  固定优先级：`task explicit > project > user machine > pinned public > reportable builtin`。测试必须证明：

  - 本地目录不会被扫描或猜测。
  - 本地覆写只有显式写入机器配置后生效。
  - task 显式指定不存在、漂移或 unsupported 的 Provider 时必须失败，禁止 fallback。
  - 其他层失效时可选择下一层，但结果必须包含可见 fallback receipt。
  - 相同能力的冲突绑定稳定失败。
  - `candidate`、`unverified` 不得伪装为 `supported`。

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_provider_config
  ```

  Expected first RED: `test_local_override_is_never_discovered` 失败并报告 `provider-config-not-implemented`；完成该切片后 PASS。

- [ ] **Step 3: 实现机器私有配置读取与规范化**

  默认路径为 `%LOCALAPPDATA%\SelfWorkFlow\config\providers.local.yaml`，测试通过参数注入临时根目录。配置仅保存路径、provider ID、项目授权和用户选择；日志与收据必须脱敏。仓库内只提交 schema、模板和示例，不提交真实 `E:\kg-code-graph`。

- [ ] **Step 4: 实现静态 ProviderBindingSnapshot**

  绑定快照只描述能力、Provider、适配器、来源身份、配置层和绑定 hash；不得混入 freshness、索引状态或查询输出。git 来源身份包含 canonical remote、commit、dirty 标志和 dirty/untracked 内容 hash；package/binary/service/host-native 使用各自证据字段。

- [ ] **Step 5: 实现支持矩阵**

  `supported` 必须同时拥有 source、adapter、positive trigger、false trigger、conflict、failure、context-cost 和 native-validation 证据。Fake Provider 的 supported entry 只能存在于 `tests/fixtures`，禁止进入生产 Catalog。提交的 CodeGraph 条目默认 `unverified`；只有绑定精确 sourceIdentity、adapterHash、平台和 operation 的原生合成仓库验收，才能单项升级。其他研究候选保持 candidate/unverified。

- [ ] **Step 6: 运行测试并提交**

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_provider_schemas
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_provider_config
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_provider_binding
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_support_matrix
  git add providers/v3 schemas/v3 src/selfworkflow/v3 tests/unit/v3
  git commit -m "feat: add explicit provider binding"
  ```

  Expected: PASS；提交中不出现机器绝对路径或凭据。

## Phase 2B: 实现 Provider 安全内核、Fake Provider 和项目 lease

**Files:**

- Create: `src/selfworkflow/v3/hashing.py`
- Create: `src/selfworkflow/v3/approvals.py`
- Create: `src/selfworkflow/v3/project_state.py`
- Create: `src/selfworkflow/v3/plans.py`
- Create: `src/selfworkflow/v3/effects.py`
- Create: `src/selfworkflow/v3/runner.py`
- Create: `src/selfworkflow/v3/receipts.py`
- Create: `src/selfworkflow/v3/project_lease.py`
- Create: `tests/fixtures/providers/fake_provider.py`
- Create: `tests/unit/v3/test_plan_hashing.py`
- Create: `tests/unit/v3/test_provider_runner.py`
- Create: `tests/unit/v3/test_project_locking.py`
- Create: `tests/unit/v3/test_receipt_validation.py`
- Create: `tests/unit/v3/test_mutation_evidence.py`

- [ ] **Step 1: 分别实现三种 canonical approval subject**

  对 `operation-plan`、`query-plan`、`provider-selection-exception` 分别定义 builder，不共享可误用的泛型字典。固定顺序：canonical subject 排除 approval/final hash → 对应 subject hash → ProviderApprovalReceipt hash → 最终 operationPlan/queryPlan/request hash。逐项 RED/GREEN 覆盖 subject 交叉复用、循环 hash、过期/撤销、目标漂移、错误项目/Provider、nonce/attempt 重放。

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_plan_hashing
  ```

  Expected first RED: `test_query_approval_cannot_authorize_operation` 返回 `approval-subject-kind-mismatch`；完成切片后 PASS。

- [ ] **Step 2: 实现 FakeEffectPort 与测试专用 Fake Provider**

  测试中的文件、进程、环境、时间和 identity 操作必须经注入端口执行，能够记录 argv/env/cwd、触碰范围、退出码、stdout/stderr 摘要、开始/结束时间。Fake Provider 及其 supported 条目只能位于 `tests/fixtures`；生产 runner 不接受测试签发者或测试收据。测试固定命令模板拒绝参数、环境变量和 cwd 注入。

- [ ] **Step 3: 实现 ProviderProjectStateReceipt 和 QueryPlan**

  项目状态独立于静态绑定，包含 canonical project root、workspace fingerprint、source-content freshness、relationship freshness、Provider 状态和采样时间。dirty/untracked 文件以内容 hash 参与 fingerprint；依赖闭包不可证明时必须标记 `relationship-fresh: unknown`。

- [ ] **Step 4: 实现只读查询、可写查询和前后 workspace 证明**

  - 真正只读查询可标记 `automatic-readonly`。
  - 若 Provider 查询无法关闭自动 sync，则整个 QueryPlan 是 local-write，必须存在机器级 `(providerId, canonicalProjectRoot)` 授权。
  - project 配置只能提出建议，不能授予自动写权限。
  - 每次查询都生成新鲜 QueryReceipt，携带 binding/state/plan hash、pre/post workspace identity、pre/post fingerprint 和 freshness 结论。
  - query 前后 workspace identity 或非声明文件发生漂移时失败；无法观察 required mutation 时阻断，而不是写成 verified。

- [ ] **Step 5: 实现四类 MutationEvidence 的封闭验证**

  分别验证 filesystem、managed-state、process-state、service-state evidence。每条 evidence 绑定 plan hash、execution nonce、attempt、provider、project、时间窗和 mutationTargetHash；actual mutation 必须是声明目标和允许动作的子集。逐项测试越界副作用、跨执行复用、不可观察 required mutation 和冗余证据 unverified。

- [ ] **Step 6: 实现维护操作与 ProviderProjectLease**

  首版操作 ID 固定为 `inspect`、`initialize-index`、`sync-incremental`、`rebuild-index`、`upgrade-managed-adapter`、`repair-managed-state`。不提供含义模糊的 `remove`；用户拥有的 Provider 源码永不由 SelfWorkFlow 升级、修复或删除。

  写操作使用独立 `ProviderProjectLease`，字段至少包含 canonical project root hash、providerId、operationId、operation nonce、owner PID、process start time、user/session、host identity、boot identity、heartbeat、issued/expires time。Clock、ProcessIdentity 和 BootIdentity 都可注入。测试 live owner、PID 重用、主机重启后的旧 lease、heartbeat 漂移、nonce 不匹配、并发竞争和经显式授权的 stale unlock；不得直接复用只有 PID 的 installer lock。

  终审后的严格 MVP 边界见 [ADR 0002](../../decisions/0002-provider-execution-mvp-boundaries.md)：仓库不提供 Python 文件 lease backend；生产 local-write 必须注入外部 Host 原子 CAS、权威授权 resolver、可信命令 registry 和执行期 live guard。network、delete、user-owned mutation 均为 unsupported；Fake-only 验证不得升级真实 Provider 支持状态。

- [ ] **Step 7: 运行测试并提交**

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_plan_hashing
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_provider_runner
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_mutation_evidence
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_project_locking
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_receipt_validation
  git add src/selfworkflow/v3 tests/fixtures/providers tests/unit/v3
  git commit -m "feat: execute provider plans safely"
  ```

  Expected: PASS。

## Phase 3A: 以 Git submodule 接入 TEA 并建立分层测试设计

**Files:**

- Modify/Create: `.gitmodules`
- Add gitlink: `dependencies/upstream/tea`
- Create: `dependencies/locks/tea.lock.yaml`
- Create: `overlays/tea/adapter.yaml`
- Create: `overlays/tea/routing.yaml`
- Create: `catalog/v3/domains/test-quality.yaml`
- Modify: `catalog/v3/index.yaml`
- Modify: `catalog/v3/modules.yaml`
- Modify: `workflow/v3/pipeline.yaml`
- Create: `src/selfworkflow/v3/test_strategy.py`
- Create: `src/selfworkflow/v3/tea_adapter.py`
- Modify: `scripts/install-selfworkflow.ps1`
- Modify: `Install_SelfWorkFlow.bat`
- Create: `tests/fixtures/v3/test-strategy-routing.yaml`
- Create: `tests/unit/v3/test_test_strategy.py`
- Create: `tests/unit/v3/test_tea_adapter.py`
- Create: `tests/conformance/test_tea_source.py`
- Create: `tests/behavioral/test_v3_tea_workflow.py`
- Create: `tests/installer/test_submodule_profiles.py`

- [ ] **Step 1: 锁定 TEA 官方来源并验证身份**

  将 `https://github.com/bmad-code-org/bmad-method-test-architecture-enterprise.git` 作为 `dependencies/upstream/tea` Git submodule，固定到实施时明确记录的 commit。lock 文件保存 canonical URL、commit、tree/inventory hash、许可证/许可证文件 hash、Adapter hash 和验证状态；不得配置浮动 branch，也不得在普通安装时执行 `submodule update --remote`。先写 conformance RED，覆盖缺失 gitlink/lock、URL 漂移、非预期 branch 配置、commit/tree/inventory、dirty inventory、许可证/清单漂移；合法 detached HEAD 必须通过。任何身份缺口都返回 `tea-source-identity-invalid`，再添加 submodule 和 lock 使其 GREEN。

- [ ] **Step 2: 阅读锁定 TEA 的入口、test-design、ATDD、test-review、trace 工作流**

  读取锁定 submodule 内 agent 入口以及九个上游 workflow 的完整 `SKILL.md` 和 metadata，为每项建立候选条目；只有本轮实际适配的 test-design、ATDD、test-review、trace/NFR 再读取其步骤、checklist 和直接引用资源。逐项记录输入、输出、写入路径、按需加载、工具边界以及 `sourceIntegrity`、`adapterSupport`、`runtimeCapability`、`behaviorEvidence`。不得复制 TEA 正文到 SelfWorkFlow，也不得把 persona 菜单当成机器可验证能力。若许可证或入口与锁记录不符，暂停并保持 `unverified`。

- [ ] **Step 3: 先用 TEA test-design 产出本轮风险测试策略**

  对“V3 模块化主干 + Provider 安全内核 + C++ 路由 + Review Host Gate + 安装器”执行锁定 TEA 的 test-design 流程，形成内容寻址的 `TestStrategy`：风险、P0-P3 优先级、验收条件映射、直接/失败/边界/状态不变量、NFR、测试级别、授权需求和残余 `unverified`。每条风险义务必须绑定后续真实测试 invocation/result hash，并在 CoverageResult 中成为 `fulfilled | unverified | blocked`；未绑定真实结果或仍 unverified 的义务不能把对应行为证据升级为 `supported`。TEA 输出先作为设计工件，不能替代真实测试结果；设计工件经 Schema 与 test-review 校验后再驱动后续测试增补。

- [ ] **Step 4: 实现 T0-T3 路由和 TEA bounded module 适配**

  T0 只做格式/解析/链接/消费者；T1 覆盖直接、失败、状态不变量和最窄回归；T2 在 **Plan/Test Design 阶段**只把 TEA test-design 放入 eligible 集合，在 **Review/Test Review 阶段**只把 test-review 放入 eligible 集合；T3 的 Verify/Release Gate 再按信号选择 trace、NFR 和高级技法。ATDD 只在进入实现且需要验收测试 RED 时选择。Grill-me 后进入实现的任务最低 T2，但不自动加载所有 TEA workflow。适配器逐步、按需加载当前 workflow/step/resource，禁止把 TEA 全量上下文注入任务。

- [ ] **Step 5: 验证触发、误触发、冲突、组合和上下文成本**

  逐项 TDD 覆盖：T0/T1 不误加载 TEA；T2 按阶段严格分离 test-design/test-review；T3 trace/NFR；ATDD 的 RED 边界；显式选择；TEA 缺失/dirty/hash 漂移；九个 workflow 的候选条目和四层支持证据；与内置轻量测试策略的覆盖关系；非 Web/C++ 任务不加载 Playwright/Pact 专项资源；输出路径只能落入声明的测试工件目录。锁定来源、适配器、触发、失败、上下文成本和 CoverageResult 测试通过前，Catalog 状态保持 `unverified`。

- [ ] **Step 6: 实现按 Profile 初始化、pull 后同步和 Heavy 隔离**

  安装器执行 `git submodule sync -- dependencies/upstream/tea`，并只对用户选择的普通依赖使用 `git submodule update --init -- <allowed-paths>`；默认不得初始化 `dependencies/heavy/*`。父仓库 pull 更新 Gitlink 后，同一入口把 TEA 切换到父仓库锁定 commit，但绝不追踪远端最新分支。使用临时 bare remotes/fixtures 测试普通 clone、首次安装、重复安装、Gitlink 更新、离线失败和 rollback，机械证明 Heavy 未被初始化。

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_test_strategy
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_tea_adapter
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.conformance.test_tea_source
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.behavioral.test_v3_tea_workflow
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.installer.test_submodule_profiles
  ```

  Expected: PASS；只有完成真实行为验证的精确 TEA workflow 维度可升级为 `supported`，其他维度继续 `unverified`。

- [ ] **Step 7: 提交 TEA 来源与适配**

  ```powershell
  git add .gitmodules dependencies/upstream/tea dependencies/locks/tea.lock.yaml overlays/tea catalog/v3 workflow/v3 src/selfworkflow/v3 scripts/install-selfworkflow.ps1 Install_SelfWorkFlow.bat tests
  git commit -m "feat: integrate risk-based tea test design"
  ```

## Phase 3B: 落地 C++ 能力模块与任务路由

**Files:**

- Modify: `workflow/v3/pipeline.yaml`
- Modify: `catalog/v3/index.yaml`
- Create: `catalog/v3/domains/code.yaml`
- Create: `catalog/v3/modules.yaml`
- Create: `skills/cpp-core/SKILL.md`
- Create: `capabilities/cpp/core.yaml`
- Create: `capabilities/cpp/ownership.yaml`
- Create: `capabilities/cpp/type-system.yaml`
- Create: `capabilities/cpp/concurrency.yaml`
- Create: `capabilities/cpp/abi.yaml`
- Create: `capabilities/cpp/performance.yaml`
- Create: `capabilities/cpp/safety.yaml`
- Create: `capabilities/cpp/build.yaml`
- Create: `capabilities/cpp/debugging.yaml`
- Create: `capabilities/cpp/engine-unreal.yaml`
- Create: `src/selfworkflow/v3/classifier.py`
- Create: `src/selfworkflow/v3/router.py`
- Create: `src/selfworkflow/v3/resolver.py`
- Modify: `src/selfworkflow/cli.py`
- Create: `tests/fixtures/v3/cpp-routing.yaml`
- Create: `tests/unit/v3/test_cpp_router.py`
- Create: `tests/behavioral/test_v3_cpp_workflow.py`

- [ ] **Step 1: 写正触发、误触发、冲突和组合失败测试**

  至少覆盖：普通文档不加载 cpp-core；C++ 阅读/编写/维护加载 cpp-core；并发任务追加 `cpp.concurrency`；ABI 变更追加 `cpp.abi`；UE C++ 追加 `cpp.engine.unreal`；一般 debug 默认 `debug.reason`，真实调试器保持未授权；heavy audit 只在用户明确要求深审时出现。

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_cpp_router
  ```

  Expected first RED: `test_non_code_task_does_not_load_cpp_core` 失败并报告 `v3-cpp-router-not-implemented`；完成该切片后 PASS。

- [ ] **Step 2: 编写 vendor-neutral cpp-core**

  cpp-core 固化：所有权与生命周期、类型和边界、不变量、错误传播、并发、ABI/build、性能证据、debug failure envelope、最小侵入修复、共享路径回归。内容可吸收已研究 Skill 的正确规则，但正文不得依赖用户机器上的任何外部 Skill。

- [ ] **Step 3: 实现按需专项路由与上下文预算**

  路由先处理显式触发和硬规则，再做语义匹配；只加载命中的 Skill 正文和必要引用。正确性优先于上下文预算，但每个结果都报告加载理由、估计成本、冲突消解和未加载的 heavy 模块。

- [ ] **Step 4: 接入 V3 resolve 输出**

  V3 `resolve` 输出能力列表、模块顺序、Provider 选择或缺失、fallback receipt、风险等级和必要授权，不执行 Provider。V2 resolve 不受影响。

- [ ] **Step 5: 运行测试并提交**

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_cpp_router
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.behavioral.test_v3_cpp_workflow
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.test_resolver
  git add workflow/v3 catalog/v3 skills/cpp-core capabilities/cpp src/selfworkflow/v3 src/selfworkflow/cli.py tests/fixtures/v3 tests/unit/v3 tests/behavioral/test_v3_cpp_workflow.py
  git commit -m "feat: route modular cpp capabilities"
  ```

  Expected: PASS。

## Phase 4: 强制 Grill-me 后由 Host 调度独立 Brainstorming Review

**Files:**

- Modify: `workflow/protected-rules.yaml`
- Create: `workflow/v3/post-grill-review.yaml`
- Create: `schemas/v3/design-review-summary.schema.json`
- Create: `schemas/v3/review-fallback-authorization.schema.json`
- Create: `schemas/v3/review-independence-receipt.schema.json`
- Modify: `schemas/protected-rules.schema.json`
- Modify: `src/selfworkflow/evidence.py`
- Create: `src/selfworkflow/v3/review_gate.py`
- Create: `src/selfworkflow/v3/review_dispatch.py`
- Modify: `tests/unit/test_protected_rules.py`
- Create: `tests/unit/v3/test_post_grill_review_gate.py`
- Create: `tests/unit/v3/test_review_dispatch.py`
- Modify: `tests/behavioral/test_workflow_matrix.py`
- Create: `docs/decisions/2026-08-09-protected-rules-v2-owner-confirmation.md`
- Create: `docs/reviews/2026-08-09-protected-rules-v2-independent-review.md`
- Create: `tests/fixtures/protected-rules-v2/owner-confirmation.json`
- Create: `tests/fixtures/protected-rules-v2/owner-review.json`
- Create: `tests/fixtures/protected-rules-v2/behavioral-test.json`
- Create: `docs/releases/evidence/protected-rules-v2/owner-confirmation.json`
- Create: `docs/releases/evidence/protected-rules-v2/owner-review.json`
- Create: `docs/releases/evidence/protected-rules-v2/behavioral-test.json`

- [ ] **Step 1: 先扩展关闭 Schema 和现有语义 Gate**

  先为三个 Review Schema 和 protected-rules 2.0 形状写 RED；Expected 错误分别为 `v3-schema-not-found` 和 `protected-rule-set-invalid`。随后更新 Schema、`evidence.py` 和必要的 ArtifactCollector 语义，禁止只修改 YAML 绕过现有 Gate。

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.test_protected_rules
  ```

  Expected after this slice: PASS。

- [ ] **Step 2: 实现 ReviewDispatchPort 和 Host attestation collector**

  `ReviewDispatchPort` 接收规范化 `DesignReviewSummary`，Host 固定调度 `reviewMode=brainstorming-cross-review`、`forkContext=false`。Collector 从实际 dispatch 参数、实际发送 payload、Host agent/session identity 和返回值计算 receipt/hash；忽略 Review Agent 自报的 `agentInstanceId`、fork 模式和输入摘要。

  SpyPort 测试必须机械断言：`fork_context=False`；payload 只含 canonical summary、约束、替代方案、风险和验收条件；不含 Grill transcript 或推理过程；实现 Agent 和 Review Agent 的 Host identity 不同。第一个 RED 为 `test_dispatch_forces_fresh_context` 返回 `review-dispatch-port-not-implemented`。

- [ ] **Step 3: 实现 Review gate 五行真值表**

  覆盖：Host attestation 存在/缺失、独立调度能力存在/不存在、用户 fallback 授权存在/不存在、fallbackMode 不匹配、过期/撤销/hash 漂移。Review fallback 使用独立 `ReviewFallbackAuthorization`，禁止复用 `provider-selection-exception`。相同 Agent、继承上下文、summary-only 失败或结构化 fallback 未授权都阻断实现。

- [ ] **Step 4: 将策略版本提升到 2.0.0 并生成结构化 owner 工件**

  新增 `require-independent-post-grill-brainstorming-review`，强度为 `enforced`；枚举回归测试拒绝旧拼写 `require-independent-post-grill-brainstorm-review`。普通 Skill、项目规则和适配器不得覆盖。三类正式、内容寻址的结构化工件写入 `docs/releases/evidence/protected-rules-v2/`，并绑定 old/new policyVersion、base/proposed rules hash、proposal hash、实施 invocation hash、implementation actor/context：

  - `owner-confirmation`：记录用户在本任务中的明确批准；
  - `owner-review`：由独立 Review 产生，不能与实现 actor/context 相同；
  - `behavioral-test`：绑定真实测试 invocation 和输出 hash。

  `tests/fixtures/protected-rules-v2/` 只保存合成的伪造、重放和失败测试输入，绝不能充当正式授权。owner gate 以正式工件 hash 验证发布变更；Markdown 只引用并解释正式工件，不能替代它们。历史 Review 若不能由 Host 证明独立性，只记录 `independence=unverified`。

- [ ] **Step 5: 执行一次真实、全新无上下文的独立规则 Review**

  由宿主以 `fork_context=false` 启动全新 SubAgent，只传递 DesignReviewSummary、规则 diff、验收条件和测试证据；不传 Grill-me 推理过程。将 Host attestation 与结论写入正式 `docs/releases/evidence/protected-rules-v2/owner-review.json`，并让 gate 测试校验其 hash。若出现 Important/Critical，先修正规则、代码和测试后再启动新的独立 Review。

- [ ] **Step 6: 运行测试并提交**

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_review_dispatch
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_post_grill_review_gate
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.test_protected_rules
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.behavioral.test_workflow_matrix
  git add workflow schemas/protected-rules.schema.json schemas/v3 src/selfworkflow/evidence.py src/selfworkflow/v3 tests/unit tests/behavioral tests/fixtures/protected-rules-v2 docs/decisions docs/reviews docs/releases/evidence/protected-rules-v2
  git commit -m "feat: enforce independent post-grill review"
  ```

  Expected: PASS；review artifact 明确区分宿主证明与 Agent 自报。

## Phase 5: 接入 CodeGraph、Provider 管理器和一键安装

**Files:**

- Create: `src/selfworkflow/v3/providers/__init__.py`
- Create: `src/selfworkflow/v3/providers/codegraph.py`
- Create: `src/selfworkflow/v3/provider_manager.py`
- Modify: `src/selfworkflow/cli.py`
- Create: `scripts/manage-selfworkflow-providers.ps1`
- Create: `Manage_SelfWorkFlow_Providers.bat`
- Modify: `scripts/install-selfworkflow.ps1`
- Modify: `Install_SelfWorkFlow.bat`
- Modify: `src/selfworkflow/adapters.py`
- Modify: `README.md`
- Create: `docs/providers/codegraph.md`
- Create: `tests/unit/v3/test_codegraph_adapter.py`
- Create: `tests/unit/v3/test_provider_manager.py`
- Modify: `tests/installer/test_one_click.py`
- Modify: `tests/acceptance/test_install_sandbox.py`
- Create: `tests/acceptance/test_v3_provider_workflow.py`

- [ ] **Step 1: 写 CLI、安装、幂等和回滚失败测试**

  覆盖 `provider list`、`provider configure`、`provider doctor`、`provider status`、`provider maintain --plan-only`、确认 hash 后执行；首次安装询问是否配置本地覆写，空答即跳过；重复安装不重复写；配置冲突需用户决策；中途失败恢复旧配置；日志包含阶段和错误码但不包含敏感值。

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_codegraph_adapter
  ```

  Expected first RED: `test_query_never_initializes_index_implicitly` 失败并报告 `codegraph-adapter-not-implemented`；完成该切片后 PASS。

- [ ] **Step 2: 实现 CodeGraph 适配器**

  适配器通过注入的命令执行端口调用 CLI，解析 `status/sync/index` 的真实返回；默认查询不得偷偷初始化索引。无法禁止的自动写行为必须反映到 QueryPlan。对 `E:\kg-code-graph` 仅做本机原生验收示例，路径只能进入机器配置，绝不写入 Git。

- [ ] **Step 3: 实现 Provider CLI 与管理脚本**

  `Manage_SelfWorkFlow_Providers.bat` 只转发到 PowerShell，并把失败日志写到 `%LOCALAPPDATA%\SelfWorkFlow\logs`。管理器展示来源类型、commit/version、dirty、hash、项目授权和可用操作；修改配置使用临时文件、fsync/replace 和恢复副本。用户拥有的本地 Provider 只允许 inspect/status/query，不允许 SelfWorkFlow upgrade。

- [ ] **Step 4: 修改一键安装和 runtime 打包**

  安装器首次运行只询问一次是否显式配置覆写；不得扫描磁盘。runtime 的 core/maintainer profile 包含 V3 schema、pipeline、cpp-core、Provider descriptors 和管理入口；机器配置、日志、索引、缓存、测试临时文件不进入 artifact 或 Git。

- [ ] **Step 5: 执行本机 CodeGraph 分操作原生检查**

  仅执行只读 `doctor/status/help` 类检查，确认实际 CLI 入口、版本、能力和写边界；这些证据只允许把对应 inspect operation 标记为通过，不能证明 query、freshness、auto-sync 或维护。若要初始化或同步索引，先生成计划并获得显式授权。只有针对精确 sourceIdentity、adapterHash、Windows 平台和具体 operation 的原生合成 C++ 仓库测试，才能升级该 operation；其余保持 `unverified` 并报告人工验证命令。

- [ ] **Step 6: 运行测试并提交**

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_codegraph_adapter
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.unit.v3.test_provider_manager
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.installer.test_one_click
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.acceptance.test_install_sandbox
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.acceptance.test_v3_provider_workflow
  git add src/selfworkflow/v3 src/selfworkflow/cli.py scripts Manage_SelfWorkFlow_Providers.bat Install_SelfWorkFlow.bat src/selfworkflow/adapters.py README.md docs/providers tests
  git commit -m "feat: manage local code intelligence providers"
  ```

  Expected: PASS。

## Final Gate: 完整验证、文档对照和独立终审

**Files:**

- Modify: `docs/superpowers/specs/2026-08-09-adaptive-quality-modules-v3-design.md`
- Modify: `docs/superpowers/specs/2026-08-09-cpp-code-intelligence-providers-v3-design.md`
- Create: `docs/reviews/2026-08-09-cpp-code-intelligence-providers-v3-final-review.md`
- Modify: `scripts/verify.ps1`
- Modify: `tests/conformance/test_release_gate.py`

- [ ] **Step 1: 把验证命令纳入发布门禁**

  `scripts/verify.ps1` 增加 V3 schema、Fake Provider、C++ 路由、post-Grill gate、安装沙箱和 runtime snapshot；不把本机 CodeGraph 可用性变成通用仓库测试的硬依赖。

- [ ] **Step 2: 运行聚焦回归**

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1 -Suite unit
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.behavioral.test_v3_cpp_workflow
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.behavioral.test_workflow_matrix
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.installer.test_one_click
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -Test tests.acceptance.test_v3_provider_workflow
  ```

  Expected: PASS。

- [ ] **Step 3: 运行完整验证**

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1 -Suite automated
  git diff --check
  git status --short
  ```

  Expected: automated suite 和 `git diff --check` PASS；`git status` 只包含本任务预期文件。无参数 `verify.ps1` 的 `all` 模式继续诚实包含 native gate；若需要用户操作或真实 Provider 不可用，应保持非零/incomplete，不得为获得 PASS 改掉该语义。

- [ ] **Step 4: 对照设计更新真实支持状态**

  逐条检查验收条件与真实证据。只有通过 native-validation 的 Provider 才改为 supported；跳过或失败项标为 `unverified`，写明原因、风险和人工验证方法。不得把 Fake Provider 测试当作真实 CodeGraph 支持证据。

- [ ] **Step 5: 启动全新独立 SubAgent 终审**

  使用 `fork_context=false`，只提供最终设计、完整 diff、验收条件和新鲜测试输出。Review 覆盖逻辑闭环、失败路径、安全、侵入性、凭据、并发、升级边界、V2 回归和未验证声明。发现 Critical/Important 必须修复并重新运行受影响测试，直到批准或明确阻塞。

- [ ] **Step 6: 提交最终验证和文档**

  ```powershell
  git add docs scripts/verify.ps1 tests/conformance/test_release_gate.py
  git commit -m "test: verify v3 code intelligence workflow"
  ```

## 完成标准

- V2 全量测试保持通过，V3 仅由显式版本请求启用。
- C++ 任务可得到稳定、可解释、按需加载的能力路由；非代码任务不会误加载 cpp-core。
- Provider 的配置、选择、fallback、freshness、授权、查询、维护和收据形成可验证闭环。
- 本地覆写只能显式配置，机器路径不进入仓库；用户 Provider 源码不被 SelfWorkFlow 修改。
- Grill-me 后同一 Agent 自审无法通过门禁；全新无上下文 SubAgent Review 有结构化证据。
- 安装、冲突、幂等、失败回滚、升级边界和 runtime 打包均有真实测试。
- 所有“supported”声明都有对应 native validation；其余能力诚实标记为 candidate/unverified。
- 完整验证和独立终审通过，或明确列出未验证项与阻塞原因。
