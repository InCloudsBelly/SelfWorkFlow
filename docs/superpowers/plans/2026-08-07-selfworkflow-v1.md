# SelfWorkFlow v1 实施计划

> **执行要求：** 使用 `superpowers:subagent-driven-development` 逐任务执行；每个任务先做规格符合性 Review，再做实现质量 Review。任何功能或修复必须先看到对应测试失败，再写最小实现。

**目标：** 在 Windows 上交付一套不依赖维护者本地专项 Skill、可安全安装到 `.agents`、可由不同厂商 Agent 读取，并实际兼容 C7OpenWiki MCP 的 SelfWorkFlow v1。

**架构：** Python 提供确定性编译、路由、状态和事务安装核心；Git 内的 YAML、Markdown 与 Schema 是源，安装时生成规范化 JSON 和厂商薄入口。运行时安装为不可变版本快照，机器可变状态单独放在 `%LOCALAPPDATA%\SelfWorkFlow`。C7OpenWiki 通过可选契约适配器接入，不进入核心依赖。

**技术栈：** Python 3.11+、标准库 `unittest`、PyYAML、jsonschema、PowerShell 启动脚本、Markdown/YAML/JSON。

**设计依据：** `docs/design/2026-08-07-selfworkflow-design.md`

**进度清单：** `docs/superpowers/plans/2026-08-07-selfworkflow-v1-checklist.md`

**精确暂存：** `docs/superpowers/plans/2026-08-07-selfworkflow-v1-staging.md`；每个提交前执行其中对应 Task 的逐文件命令。

实施前先执行 staging 子计划的“批准计划提交”，确保所有计划文件进入 Git；然后才开始 Task 1。

**实施约束：**

- 当前功能分支为 `codex/selfworkflow-v1`，工作树为 `D:\SelfWorkFlow\.worktrees\selfworkflow-v1`。
- 不读取 `E:\kuaishou-misc-tools\skills` 作为运行时依赖；其通用经验只以带来源记录的 SelfWorkFlow 内建能力存在。
- 不修改 `D:\openwikiC7`；首版只读取其已存在的 MCP 契约并在 SelfWorkFlow 内实现适配。
- 不安装到正式 `C:\Users\Administrator\.agents`，直到安装沙箱、回滚、幂等与漂移测试通过，且用户确认安装计划。
- Codex Desktop、Codex CLI 和 C7OpenWiki 的真实测试必须与模拟/契约测试分开报告；未跑即 `unverified`。
- 每个提交前至少运行当前任务的最窄测试与 `git diff --check`。

### 全计划适用的原子 TDD 规则

下文每个“覆盖”列表不是一次批量实现清单。执行 Agent 必须把列表中的**每一个可观察行为**分别执行为一个 2–5 分钟微循环：

```text
只增加一个测试方法
-> 运行该测试并确认因目标行为缺失而失败
-> 写使该测试通过的最小实现
-> 运行该测试通过
-> 运行当前文件及相关既有回归
-> 才进入下一个行为
```

不得先写整批测试再一次实现整个模块。若测试因导入、fixture 或其他非目标原因失败，先修正测试基座并重新取得目标 Red。真实验收暴露实现缺陷时，停止验收，新增一个带 Red/Green/回归的明确修复子任务；禁止在 Task 16–18 中按失败临时修改未知文件。

所有 Python dotted tests 统一通过 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test <dotted-test>` 运行。脚本必须自行定位仓库 `.venv` 和 `src`，新终端不得依赖上一会话的 `PYTHONPATH`；跨进程/native 套件由 `verify.ps1` 编排。

### 全计划适用的工作树与提交规则

- 每个任务开始记录 `git status --porcelain=v2`，并保存为该任务 Review 的输入；
- 开始时 index 非空则暂停，不把既有 staged 变化视为本任务内容；
- 仅通过 `git add -- <本任务文件清单中的逐个精确路径>` 暂存，不使用目录级或通配 `git add`；
- 暂存后对比任务开始快照、`git diff --cached --name-only` 和文件清单；出现无关路径即取消本次暂存并调查；
- 每个 Task 的精确逐文件暂存命令已固化在 staging 子计划；执行 Agent 不得改成目录级、通配或 `git add .`。

---

## Chunk 1：确定性核心与证据模型

### Task 1：建立可复现的开发与测试入口

**文件：**

- 新建：`pyproject.toml`
- 新建：`requirements-dev.lock.txt`
- 新建：`src/selfworkflow/__init__.py`
- 新建：`src/selfworkflow/cli.py`
- 新建：`tests/__init__.py`
- 新建：`tests/test_smoke.py`
- 新建：`scripts/test.ps1`
- 新建：`scripts/verify.ps1`
- 新建：`scripts/bootstrap-codex-cli.ps1`、`scripts/lib/bootstrap-execution.ps1`、`scripts/lib/bootstrap-manifest.ps1`、`schemas/bootstrap-tool-manifest.schema.json`、`tests/test_bootstrap_cli.py`、`tests/fixtures/bootstrap/fake-npm-cli.js`
- 新建：`README.md`
- 修改：`.gitignore`

**步骤 1：写失败测试**

在 `tests/test_smoke.py` 中断言包暴露非空 `__version__`，且 `python -m selfworkflow.cli --version` 返回同一版本。

**步骤 2：确认失败**

运行：

```powershell
python -m unittest tests.test_smoke -v
```

预期：因 `selfworkflow` 包尚不存在而失败。

**步骤 3：写最小实现**

- 定义初始开发版本 `0.1.0.dev0`；
- CLI 只实现 `--version`；
- `scripts/test.ps1` 要求仓库 `.venv`，在子进程内将 `src` 加入 `PYTHONPATH`，支持 `-Test` 精确测试或默认全量发现，不污染全局环境；
- `scripts/verify.ps1 -Suite <unit|conformance|installer|behavioral|automated|native|all>` 是最终统一入口；Task 1 先实现 unit 包装，后续任务只通过测试扩展 suite。`automated` 排除交互式 native 验收；需要 OAuth/Desktop 时输出结构化 `requires-user-action` 并以专用非零退出码结束，禁止静默跳过；
- 锁定 PyYAML 与 jsonschema 的精确版本，README 写明 `python -m venv .venv` 和 `.venv\Scripts\python.exe -m pip install -r requirements-dev.lock.txt -e .`；
- `.gitignore` 加入 `.venv/`、`__pycache__/`、`*.pyc`、`build/`、测试原始输出和本机运行证据目录。
- 另按原子 TDD 实现 bootstrap 脚本。Discover 只接受位于预存
  `%LOCALAPPDATA%\SelfWorkFlow\bootstrap\toolchains` anchor 下的
  `ToolchainRoot`，验证完整目录链及 deterministic inventory 后，通过绝对
  `node.exe` 和绝对 `npm-cli.js` 执行一次隔离 metadata view，并输出
  `planSchemaVersion: 2` 完整计划。
- Apply 强制同时要求绝对 `ConfirmedPlanPath` 和 `ConfirmPlanHash`；先锁定
  计划文件，精确校验 shape、规范化 plan hash、内嵌 hash、参数 hash、
  静态 argv/env/cwd 及 node/npm/tree identity。任何 Add-Type、目录创建、
  ACL 修改或外部进程必须位于该门禁之后。旧 hash-only Apply、旧 plan v1、
  `NpmCommand` 和 `IcaclsCommand` 均 fail closed，不保留兼容别名。
- Apply 不重复 metadata view，只使用 confirmed version/integrity，并通过
  `ProcessStartInfo` 在固定 cwd、清空后精确白名单环境中执行 install。
  toolchain 与 install target/cache/trusted cwd 不得重叠；路径、owner、
  reparse、DACL 或 inventory 无法证明安全时拒绝。外部 `icacls` 完全移除，
  ACL 由 .NET 设置后从文件系统独立回读。
- Manifest 升级为 `schemaVersion: 2`，使用 `expectedCliVersion` 与
  `cliVersionVerification: "not-run"`，删除 `cliVersion`。Task 1 不执行新安装
  的 Codex Agent；真实启动与模型调用保留给 native acceptance。
- 测试使用系统真实 `node.exe` 和仓库 `fake-npm-cli.js`，在临时
  `%LOCALAPPDATA%` 中创建并保护 class-level toolchain。按全局原子 TDD 规则
  分别覆盖 confirmed-plan 前置门禁、旧接口拒绝、node/npm/tree 漂移、
  Apply 无 view、固定 cwd/环境、权限/reparse/owner/DACL、manifest v2 精确
  shape、不执行 fake Codex marker，以及无网络/无真实 npm/Codex。

**步骤 3A：创建可复现环境**

运行 `python -m venv .venv`，随后 `.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements-dev.lock.txt -e .`，再用 `.venv\Scripts\python.exe --version` 和 `.venv\Scripts\python.exe -m pip freeze` 验证解释器与锁定依赖；安装失败时 Task 1 保持 Red。

**步骤 4：确认通过**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.test_smoke
.venv\Scripts\python.exe -m selfworkflow.cli --version
git diff --check
```

预期：测试通过，CLI 输出 `0.1.0.dev0`，diff 无格式错误。

**步骤 5：提交**

```powershell
git commit -m "build: bootstrap SelfWorkFlow test harness"
```

### Task 2：实现核心状态、C/R 分类与能力门禁

**文件：**

- 新建：`workflow/lifecycle.yaml`
- 新建：`workflow/policies.yaml`
- 新建：`workflow/evidence.yaml`
- 新建：`schemas/lifecycle.schema.json`
- 新建：`schemas/policies.schema.json`
- 新建：`schemas/evidence.schema.json`
- 新建：`src/selfworkflow/config.py`
- 新建：`src/selfworkflow/model.py`
- 新建：`src/selfworkflow/classifier.py`
- 新建：`tests/unit/test_config.py`
- 新建：`tests/unit/__init__.py`
- 新建：`tests/unit/test_classifier.py`
- 新建：`tests/unit/test_capability_gate.py`

**步骤 1：按全局原子 TDD 规则逐项写失败测试**

覆盖：

- C0/R0 至 C3/R3 的合法值和非法值；
- 任一维度达到 2 时需要完整 Brainstorming/Plan；
- 任一维度达到 3 或 C2+R2 时建议 Grill-me；
- 边界不清时升级一级；
- 项目规则只能升级不能降低全局最低等级；
- 能力状态只能是 `supported|unsupported|unverified`；
- 缺少必需能力时返回结构化 pause，不允许静默降级；
- `unverified` 只由 `not-run|partial` 推导。

**步骤 2：确认失败**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.unit.test_config
```

预期：模块或配置不存在而失败。

**步骤 3：写最小实现**

- YAML 保存厂商无关状态和矩阵；
- `config.py` 负责 YAML 加载、JSON Schema 校验和规范化；
- `model.py` 使用不可变 dataclass 表达任务分类、能力报告、验证状态；
- `classifier.py` 只执行确定性升级和门禁，不加入模型语义判断。

**步骤 4：确认通过**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.unit.test_config
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.unit.test_classifier
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.unit.test_capability_gate
git diff --check
```

预期：全部通过。

**步骤 5：提交**

```powershell
git commit -m "feat: add workflow classification and capability gates"
```

### Task 3：固化受保护不变量与证据完成门禁

**文件：**

- 新建：`workflow/protected-rules.yaml`
- 新建：`schemas/protected-rules.schema.json`
- 新建：`src/selfworkflow/evidence.py`
- 新建：`WORKFLOW.md`
- 新建：`tests/unit/test_protected_rules.py`
- 新建：`tests/unit/test_evidence.py`
- 新建：`tests/fixtures/evidence/`

**步骤 1：按全局原子 TDD 规则逐项写失败测试**

覆盖：

- 普通 Skill、项目规则、覆盖层不能降低受保护不变量；
- 修改受保护不变量必须同时出现破坏性变更确认、主版本升级、独立 Review 和行为测试证据；
- 所有修改任务必须具有 classification、capabilities、selectedSkills、acceptanceCriteria、changes、review、verification、skipped、residualRisks；
- 失败、陈旧、hash 不匹配或仅 partial 的验证不能完成任务；
- 纯只读任务可用 `not-applicable` 完成；
- 不适用和跳过项必须带理由。

**步骤 2：确认失败**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.unit.test_protected_rules
```

预期：门禁实现缺失而失败。

**步骤 3：写最小实现**

实现规则合并、证据新鲜度检查和完成判定。错误必须返回机器可读 code 与人类可读说明。此任务同时创建首个可安装的厂商无关 `WORKFLOW.md`，只包含生命周期、阶段能力契约、规则优先级、证据要求和按需加载入口；后续任务只扩充其已测试章节，避免适配器引用尚不存在的核心。

**步骤 4：确认通过并回归 Chunk 1**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.unit
git diff --check
```

预期：Chunk 1 单元测试全部通过。

**步骤 5：提交**

```powershell
git commit -m "feat: enforce protected rules and evidence gates"
```

---

## Chunk 2：Skill Catalog、按需路由与内建代码质量

### Task 4：实现 Catalog 编译器

**文件：**

- 新建：`schemas/catalog.schema.json`
- 新建：`catalog/index.yaml`
- 新建：`catalog/domains/workflow.yaml`
- 新建：`catalog/domains/code-quality.yaml`
- 新建：`catalog/domains/knowledge.yaml`
- 新建：`src/selfworkflow/catalog.py`
- 新建：`tests/unit/test_catalog.py`
- 新建：`tests/fixtures/catalog/`

**步骤 1：写失败测试**

覆盖合法编译和以下拒绝项：重复稳定 ID、同名异内容、悬空依赖、依赖环、非法别名、互相冲突的必选项、未知能力、普通 Skill 覆盖受保护规则、来源 hash 缺失。

**步骤 2：确认失败**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.unit.test_catalog
```

预期：Catalog 编译器不存在而失败。

**步骤 3：写最小实现**

将分领域 YAML 编译为键稳定排序、换行稳定的规范化 JSON；生成内容 hash；错误按确定顺序报告。

**步骤 4：确认通过**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.unit.test_catalog
.venv\Scripts\python.exe -m selfworkflow.cli catalog compile --source catalog --output build/catalog.json
git diff --check
```

预期：测试通过，重复编译得到相同 hash。

**步骤 5：提交**

```powershell
git commit -m "feat: compile deterministic skill catalog"
```

### Task 5：实现最小充分 Skill 路由

**文件：**

- 新建：`src/selfworkflow/router.py`
- 新建：`tests/unit/test_router.py`
- 新建：`tests/fixtures/router/`

**步骤 1：写失败测试**

覆盖：

- 显式 Skill 优先；
- 安全和项目必选项不可被语义评分移除；
- 文件类型、阶段、操作类型确定性命中；
- 有界语义候选不能越权；
- 依赖闭包、禁止重复、冲突裁决；
- 能力不足时 pause；
- 上下文超预算时拆阶段，不能删除安全必选项；
- 正触发、误触发、冲突、组合与上下文成本。

**步骤 2：确认失败**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.unit.test_router
```

预期：路由模块不存在而失败。

**步骤 3：写最小实现**

路由器输出候选、命中原因、最终有序集合、排除原因、阶段拆分和 Catalog hash；不在确定性核心中调用 LLM。

**步骤 4：确认通过**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.unit.test_router
git diff --check
```

预期：全部通过。

**步骤 5：提交**

```powershell
git commit -m "feat: add bounded on-demand skill routing"
```

### Task 6：建立代码质量 Skill 的失败基线

**文件：**

- 新建：`tests/behavioral/scenarios/code-quality.yaml`
- 新建：`tests/behavioral/__init__.py`
- 新建：`tests/behavioral/rubrics/code-quality.yaml`
- 新建：`tests/behavioral/test_code_quality_scenarios.py`
- 新建：`scripts/import-agent-eval.ps1`
- 新建：`scripts/run-agent-eval.ps1`
- 新建：`schemas/agent-eval-result.schema.json`
- 新建：`tests/behavioral/test_agent_eval_runner.py`
- 新建：`tests/fixtures/agent-eval/fake-agent.py`
- 新建：`docs/provenance/code-quality-baseline.md`
- 新建：`imports/source-registry.yaml`
- 新建：`imports/extraction-records/code-quality-v1.yaml`

**步骤 1：只写场景和评分规则，不写 Skill 正文**

至少包含：

- detection point 下游补偿掩盖 owner 错误；
- 持久化成功与部分写入混淆；
- 缓存/恢复点导致修复后旧数据继续污染；
- 共享路径回归遗漏；
- dirty 工作树被覆盖；
- no-op 误报成功；
- 应用层需求错误侵入底层公共接口；
- 配置批量写入缺少 plan/review/confirm/reread。

Rubric 必须区分关键项、加分项和禁止项。

**步骤 2：执行无 Skill 基线**

先用 fake agent 逐项 Red/Green 验证各 Mode 参数、超时终止、非零退出、无效 JSONL、Schema、model/effort、Skill 范围、tree 漂移、InputRun hash 和脱敏边界。runner 接收 `-AgentCommand -Scenario -Schema -OutputRoot -TimeoutSeconds -Model -ReasoningEffort -Mode` 及按模式要求的 `-Skill|-InputRun`，创建独立临时 Git 仓库并调用 `<agent> exec --ephemeral --json --sandbox read-only --ask-for-approval never --output-schema <schema>`。原始输出进入被忽略 artifacts，import 只导入脱敏 hash 证据。

执行前先完成原生验收子计划 A1–A2 并取得用户对本地 CLI 工具安装的确认；随后运行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run-agent-eval.ps1 -AgentCommand <verified-codex.cmd> -Scenario tests/behavioral/scenarios/code-quality.yaml -Schema schemas/agent-eval-result.schema.json -OutputRoot artifacts/agent-evals -TimeoutSeconds 600 -Model gpt-5.6-sol -ReasoningEffort xhigh -Mode baseline`。无可验证 CLI 时 Task 6 暂停，不能跳过基线直接写 Skill。

**步骤 3：确认基线暴露至少一个真实缺口**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.behavioral.test_code_quality_scenarios
```

预期：场景与 rubric 格式通过；基线报告中的至少一个关键项失败。若基线全过，增强压力场景后重跑，不能伪造失败。

**步骤 4：提交基线，不提交 Skill 实现**

```powershell
git commit -m "test: capture code quality skill baseline"
```

### Task 7：实现独立内建代码质量与工作流质量 Skill

**文件：**

- 新建：`skills/code-quality/SKILL.md`
- 新建：`skills/workflow-quality/SKILL.md`
- 新建：`capabilities/code-quality/ownership-and-invalidation.md`
- 新建：`capabilities/code-quality/change-safety.md`
- 新建：`capabilities/workflow-quality/evidence-and-operations.md`
- 新建：`docs/provenance/code-quality-v1.md`
- 修改：`catalog/domains/code-quality.yaml`
- 修改：`catalog/domains/workflow.yaml`
- 修改：`imports/extraction-records/code-quality-v1.yaml`
- 修改：`tests/behavioral/test_code_quality_scenarios.py`
- 新建：`tests/behavioral/scenarios/code-quality-blind.yaml`

**步骤 1：实现满足基线缺口的最小 Skill**

Skill 必须固化：failure envelope、last-good/first-bad、owner/detection、最早责任层、禁止下游补偿、持久数据/缓存/恢复点/临时产物、下游失效与重建、直接和共享路径、no-op、边界与侵入性、dirty 保护、`plan -> review -> confirm -> apply -> reread`、证据缺口披露。

来源文档只记录通用原则来自哪些已跟踪文件、commit 和 hash；不复制公司路径、项目名、内部服务和一次性结论到运行时正文。

**步骤 2：运行确定性触发测试**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.unit.test_catalog
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.unit.test_router
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.behavioral.test_code_quality_scenarios
```

预期：Skill 独立价值、正触发、误触发、冲突、组合和成本测试通过。

**步骤 3：执行带 Skill 的独立压力测试**

先锁定 Skill 内容 hash；随后由未接收实现上下文的独立审查者新生成 blind 场景和 hash，此前该文件不存在。按 Agent-eval 子计划运行 skilled、blind、独立 review；若 Skill 再变化，旧 blind 证据失效并由新审查上下文重新生成场景。关键项必须全过。

**步骤 4：执行盲变体与独立 Review**

使用未在正文逐字出现的新场景验证泛化；审查通用性、过拟合、项目泄漏、冲突和 token 成本。

**步骤 5：提交**

```powershell
git commit -m "feat: add standalone code and workflow quality skills"
```

### Task 7A：实现可迭代的外部 Skill 吸收机制

**文件：**

- 新建：`src/selfworkflow/imports.py`
- 新建：`schemas/source-registry.schema.json`
- 新建：`schemas/extraction-record.schema.json`
- 新建：`tests/unit/test_imports.py`
- 新建：`tests/fixtures/imports/`
- 修改：`imports/source-registry.yaml`

**步骤 1：逐项 Red/Green**

分别验证：来源 commit/dirty/hash 记录；只读取用户指定 Skill 与必要 references；项目名、公司路径、内部系统和凭据模式进入候选隔离区而非运行时；重复/冲突检测；必须绑定失败基线、正负压力测试和独立 Review；来源更新只产生候选 diff；用户确认前不能发布。每项按全局原子 TDD 规则单独完成。

**步骤 2：独立性测试**

将 fixture 中外部源重命名或删除后，已发布 Skill 的构建、路由和行为静态测试仍通过；更新源 hash 后旧吸收证据必须失效。

**步骤 3：确认与提交**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.unit.test_imports
git diff --check
git commit -m "feat: add governed skill absorption pipeline"
```

---

## Chunk 3：Superpowers 来源、事务安装器与厂商适配

### Task 8：实现 Superpowers 来源探测与锁定

**文件：**

- 新建：`dependencies/superpowers.lock.yaml`
- 新建：`src/selfworkflow/sources.py`
- 新建：`tests/unit/test_sources.py`
- 新建：`tests/fixtures/sources/`

**步骤 1：写失败测试**

覆盖官方候选、本地 clean、本地 dirty、非 Git 来源、缺失来源、dirty 文件 hash、基础 commit、同一路径 hash 变化使证据失效、用户拒绝 dirty、用户拒绝安装后的只读限制。

**步骤 2：确认失败**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.unit.test_sources
```

预期：来源探测模块不存在而失败。

**步骤 3：写最小实现**

Doctor 只报告候选来源；选择必须显式写入安装计划。锁记录 source type、path/URL、commit、dirty files、每文件 hash、support status、reproducibility status。

**步骤 4：确认通过**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.unit.test_sources
git diff --check
```

**步骤 5：提交**

```powershell
git commit -m "feat: inspect and lock Superpowers sources"
```

### Task 8A：实现 Superpowers 覆盖层与稳定工作流 Skill

**文件：**

- 新建：`overlays/superpowers/stage-map.yaml`
- 新建：`overlays/superpowers/policies.yaml`
- 新建：`skills/grill-me/SKILL.md`
- 新建：`src/selfworkflow/superpowers.py`
- 新建：`tests/unit/test_superpowers_overlay.py`
- 新建：`tests/behavioral/scenarios/superpowers-routing.yaml`
- 修改：`catalog/domains/workflow.yaml`
- 修改：`WORKFLOW.md`

**步骤 1：逐项 Red/Green**

分别实现并验证：阶段到 `brainstorming/writing-plans/test-driven-development/systematic-debugging/requesting-code-review/receiving-code-review/verification-before-completion` 的映射；显式或阈值命中稳定 `grill-me` ID；Grill-me 后要求独立 Brainstorming 交叉 Review；写任务缺失 Superpowers 时 pause，只读分析可继续并披露；用户拒绝安装时不得静默降级；覆盖层不得写入或修改被选择的上游目录；仅将命中阶段正文装入 runtime。

**步骤 2：来源安装测试**

在 fixture 中分别使用官方快照、本地 clean、本地 dirty 和缺失来源。安装计划必须展示来源、commit、dirty 文件/hash、support 与 reproducibility；只有用户在计划中选择/确认后，才将所选快照或链接装入测试 runtime。hash 变化后行为证据失效。

**步骤 3：真实行为评测接口**

扩展 Task 6 的 Agent eval 格式，场景分别验证 Brainstorming、Plan、TDD、Debug、Review、Verification 与 Grill-me 交叉 Review；静态测试只允许标记 `static-conformance-passed`。

**步骤 4：确认与提交**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.unit.test_superpowers_overlay
git diff --check
git commit -m "feat: integrate governed Superpowers overlay"
```

### Task 9：建立安装安全 fixture 和测试切片清单

**文件：**

- 新建：`tests/installer/test_doctor.py`
- 新建：`tests/installer/__init__.py`
- 新建：`tests/installer/test_plan.py`
- 新建：`tests/installer/test_apply.py`
- 新建：`tests/installer/test_rollback.py`
- 新建：`tests/installer/test_recovery.py`
- 新建：`tests/installer/test_locking.py`
- 新建：`tests/fixtures/installer/`

**步骤 1：只建立 fixture，不预写整批测试**

用临时目录代替真实用户目录，准备全新、已有内容、冲突、漂移、链接和中断 fixture。只定义输入与预期，不创建会同时因实现缺失而失败的整批测试。

**步骤 2：确认失败**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.installer
```

预期：fixture 格式检查通过；安装行为测试尚不存在。

**步骤 3：提交测试边界**

```powershell
git commit -m "test: define transactional installer behavior"
```

### Task 10：按事务阶段实现 doctor、plan、apply、verify、rollback

**文件：**

- 新建：`src/selfworkflow/installer.py`
- 新建：`src/selfworkflow/transactions.py`
- 新建：`src/selfworkflow/managed_blocks.py`
- 新建：`installer/install.ps1`
- 新建：`schemas/install-plan.schema.json`
- 新建：`schemas/install-manifest.schema.json`
- 新建：`schemas/rollback-plan.schema.json`
- 修改：`src/selfworkflow/cli.py`
- 修改：`tests/installer/test_doctor.py`
- 修改：`tests/installer/test_plan.py`
- 修改：`tests/installer/test_apply.py`
- 修改：`tests/installer/test_rollback.py`
- 修改：`tests/installer/test_recovery.py`
- 修改：`tests/installer/test_locking.py`

**步骤 1：Doctor 微循环**

依次 Red/Green：只读输出环境、源、已安装 Agent、Superpowers、C7OpenWiki 和未完成事务；dry-run 前后 filesystem tree hash 相同。

**步骤 2：Plan 微循环**

依次 Red/Green：source/target hash、逐文件发现机制、冲突、备份、托管块和验证项；检测 AGENTS override 遮蔽并 pause；拒绝路径/链接越界与跨卷伪原子。另验证合法 bootstrap manifest 可按 hash 接管、路径/hash/SDDL 漂移则拒绝。

**步骤 3：Apply 微循环**

- 锁和事务状态放在显式传入的 state root；默认值才解析 `%LOCALAPPDATA%\SelfWorkFlow`；
- 重验 hash 后写精确备份；
- 临时文件与原子替换；
- 运行时写入版本化不可变快照；
- 只改托管标记块，不删除未知文件或 Skill；
- 托管块标记缺失、重复或损坏时 pause；
- 新建 state/backup/tool 根使用保护 DACL，仅当前用户 SID 与 SYSTEM 可访问；备份记录原目标 SDDL，rollback 原样恢复；`.agents` runtime 保留其父目录 DACL，不擅自收紧或扩大；
- 每个写入边界分别注入中断，按事务记录恢复。

每项必须独立 Red/Green，不能在一次实现中完成全部 apply 行为。

**步骤 4：Verify、幂等、恢复与 rollback 微循环**

Verify 检查 manifest、hash、非托管内容、快照/current 指针和幂等。Rollback 只恢复事务实际修改项；目标二次变化时拒绝覆盖。

逐项 Red/Green 实现 `install rollback-plan --transaction ... --output ...`：Schema、目标/当前 hash、原 SDDL、目标版本、plan hash 和漂移检查；`apply` 必须机器可读返回 manifest 路径与 transaction ID，供验收命令使用。

**步骤 5：运行安装器测试**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.installer
powershell -NoProfile -ExecutionPolicy Bypass -File installer/install.ps1 -Help
git diff --check
```

预期：所有安装器测试通过，PowerShell 入口可显示帮助。

**步骤 6：提交**

```powershell
git commit -m "feat: add transactional runtime installer"
```

### Task 11：生成 Codex 完整入口与其他厂商薄适配器

**文件：**

- 新建：`adapters/codex/adapter.yaml`
- 新建：`adapters/codex/AGENTS.managed.md`
- 新建：`adapters/claude-code/adapter.yaml`
- 新建：`adapters/claude-code/CLAUDE.managed.md`
- 新建：`adapters/cursor/adapter.yaml`
- 新建：`adapters/opencode/adapter.yaml`
- 新建：`adapters/copilot/copilot-instructions.md`
- 新建：`adapters/unknown/BOOTSTRAP.md`
- 新建：`schemas/adapter.schema.json`
- 新建：`src/selfworkflow/adapters.py`
- 新建：`tests/conformance/test_adapters.py`
- 新建：`tests/conformance/__init__.py`
- 新建：`tests/conformance/test_runtime_snapshot.py`

**步骤 1：按适配器逐项 Red/Green**

覆盖能力声明、支持状态、薄入口只引用已存在的 `WORKFLOW.md`、未知 Agent Bootstrap、厂商规则不能覆盖核心不变量、运行时快照可在无 E 盘/无 openwikiC7 仓库时读取、重复生成稳定。

**步骤 2：确认失败**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.conformance
```

预期：适配器编译不存在而失败。

**步骤 3：写最小实现**

Codex 声明目标状态但发布前仍为 `experimental-unverified`。安装计划必须逐项记录：默认将托管块合并到 `C:\Users\<user>\.codex\AGENTS.md`；若非空 `AGENTS.override.md` 遮蔽它，则 pause 并按用户选择改为合并 override；将版本化 Skill 快照链接或生成到 `C:\Users\<user>\.agents\skills\<stable-id>`；C7OpenWiki MCP 启用时才对 Codex MCP 配置生成单独、可确认的计划项。两种 AGENTS 目标都必须测试发现、漂移与 rollback。Claude/Cursor/OpenCode 同为 `experimental-unverified`，Copilot 为 `instructions-only`，Unknown 只提供 Bootstrap。

**步骤 4：确认通过**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.conformance
.venv\Scripts\python.exe -m selfworkflow.cli build --output build/runtime
git diff --check
```

预期：静态契约通过，构建结果不包含绝对维护者路径。

**步骤 5：提交**

```powershell
git commit -m "feat: generate cross-vendor workflow adapters"
```

---

## Chunk 4：可选知识扩展与 C7OpenWiki

### Task 12：定义厂商无关知识契约

**文件：**

- 新建：`extensions/knowledge/contract.yaml`
- 新建：`schemas/knowledge-contract.schema.json`
- 新建：`src/selfworkflow/knowledge.py`
- 新建：`tests/unit/test_knowledge_contract.py`

**步骤 1：写失败测试**

覆盖：`read` 有来源/revision/hash/验证状态；`propose` 不发布知识内容并返回 expected base，但允许后端声明 OAuth 刷新、临时事务等运行态副作用；`update` 必须明确确认并执行 CAS；后端缺失不阻塞代码任务；知识任务失败生成待办；不能存储模型私有推理过程。

**步骤 2：确认失败**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.unit.test_knowledge_contract
```

预期：知识契约模块不存在而失败。

**步骤 3：写最小实现**

实现协议类型、结果归一化和失败隔离；核心不导入任何 C7 模块。

**步骤 4：确认通过并提交**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.unit.test_knowledge_contract
git diff --check
git commit -m "feat: add optional knowledge backend contract"
```

### Task 13：实现 C7OpenWiki MCP 适配器

**文件：**

- 新建：`extensions/knowledge/c7-openwiki/adapter.yaml`
- 新建：`extensions/knowledge/c7-openwiki/SKILL.md`
- 新建：`extensions/knowledge/c7-openwiki/tool-contract.json`
- 新建：`extensions/knowledge/c7-openwiki/provenance.yaml`
- 新建：`src/selfworkflow/c7_openwiki.py`
- 新建：`tests/conformance/test_c7_openwiki_adapter.py`
- 新建：`tests/fixtures/c7-openwiki/`

**步骤 1：写失败契约测试**

先记录 `D:\openwikiC7` 的 HEAD、branch、tracked dirty 清单，以及未跟踪 `c7-openwiki` 排除 build/runtime/凭据后的确定性 tree hash；再根据该精确来源建立 fixture。provenance 必须绑定各契约文件 hash、能力证据 hash 和提取时间。覆盖：

- `openwiki_status`、`openwiki_setup`、`openwiki_prepare_sources`、`openwiki_list_skills`、`openwiki_query`、`openwiki_update`、`openwiki_set_default_model`；
- 本地文件先 prepare，再绑定 `sourceManifestId`；文件 hash 变化确认失效；
- update 只在外部 Agent 已获得明确确认时传 literal `confirmedByUser: true`；该字段不得描述成身份认证；
- base revision/CAS 冲突；
- 合法 update 状态白名单；
- review attention/clarification 优先自主闭环，严重信息缺失才恢复 Grill-me；
- 后端缺失与失败隔离。

**步骤 2：确认失败**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.conformance.test_c7_openwiki_adapter
```

预期：适配器不存在而失败。

**步骤 3：实现映射**

- `knowledge.read` 映射只读 query；
- `knowledge.propose` 不调用 update、不发布正式 Wiki；明确允许 query 刷新 OAuth token 和创建临时事务，不把它描述成绝对无副作用；
- `knowledge.update` 在确认、manifest 和 revision 均满足时调用 update；
- 模型及 reasoning effort 由 C7OpenWiki 配置管理，SelfWorkFlow 只报告实际选择；
- 不在运行时依赖 `D:\openwikiC7` 路径。

**步骤 4：契约漂移检查**

只读比较本地 C7OpenWiki 的工具 Schema 与适配器快照。差异导致 `contract-drift`，不得自动覆盖适配器。

**步骤 5：确认通过并提交**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.conformance.test_c7_openwiki_adapter
git diff --check
git commit -m "feat: add C7OpenWiki MCP knowledge adapter"
```

---

## Chunk 5：自举、真实宿主验收与发布门禁

### Task 14：实现自治理与发布清单

**文件：**

- 修改：`WORKFLOW.md`
- 修改：`README.md`
- 新建：`CHANGELOG.md`
- 新建：`docs/decisions/0001-deterministic-core.md`
- 新建：`docs/releases/release-manifest.schema.json`
- 新建：`src/selfworkflow/release.py`
- 新建：`tests/conformance/test_release_gate.py`
- 新建：`tests/behavioral/test_workflow_matrix.py`
- 修改：`scripts/verify.ps1`

**步骤 1：按发布行为逐项 Red/Green**

覆盖 C0-C3/R0-R3、Brainstorming、显式/阈值 Grill-me、独立 Brainstorming 交叉 Review、Review L0-L3、暂停/恢复、禁止静默降级、保护规则破坏性变更门禁、各适配器独立支持状态、缺失真实证据不能发布。

**步骤 2：确认失败**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.conformance.test_release_gate
```

预期：发布门禁不存在而失败。

**步骤 3：写最小实现**

Release manifest 记录源码 commit、dirty 状态、依赖锁 hash、runtime hash、测试命令/时间/结果/输出 hash、Review 身份与隔离级别、宿主证据、知识后端证据、跳过项和残余风险。README 同步写明安装、升级、回滚、支持矩阵和未知 Agent Bootstrap。

**步骤 4：确认通过并提交**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.conformance.test_release_gate
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.behavioral.test_workflow_matrix
git diff --check
git commit -m "feat: enforce SelfWorkFlow release governance"
```

### Task 15：完成安装沙箱与正式安装前演练

**文件：**

- 新建：`tests/acceptance/test_install_sandbox.py`
- 新建：`tests/acceptance/__init__.py`
- 新建：`docs/releases/0.1.0-acceptance.md`
- 修改：`scripts/verify.ps1`
- 若暴露缺陷：新增单独的 Red/Green 修复子任务后再恢复本任务

**步骤 1：构造带已有内容的沙箱**

模拟已有 `.agents`、已有 Codex AGENTS 内容、已有 Skill、dirty Superpowers、受管块漂移、未完成事务和并发锁。

**步骤 2：执行 dry-run -> plan -> confirm -> apply -> verify -> repeat -> rollback**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Test tests.acceptance.test_install_sandbox
```

预期：原始非托管内容逐字节保持；第二次 apply 为 no-op；rollback 精确恢复；冲突和漂移均暂停而不是覆盖。

**步骤 3：扩展统一验证入口并运行全量自动化回归**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify.ps1 -Suite automated
git diff --check
```

预期：全部自动化测试通过。

**步骤 4：独立 Review**

L2 审查者只接收已批准设计、完整 diff、验收条件和新鲜测试证据，审查逻辑闭环、失败路径、安全、侵入性和无关修改。Critical/Important 全部修复并重跑测试。

**步骤 5：提交**

```powershell
git commit -m "test: verify SelfWorkFlow installation lifecycle"
```

### Task 16：诊断并真实验证 Codex CLI

**文件：**

- 新建：`tests/acceptance/codex-cli/c0-readonly.md`、`c1-change-paused.md`、`c2r2-design.md`、`grill-explicit.md`、`missing-superpowers.md`、`skill-minimality.md`、`write-tdd.md`、`review-write-result.md`、`result.schema.json`
- 新建：`docs/releases/evidence/codex-cli.md`
- 依据：`docs/superpowers/plans/2026-08-07-selfworkflow-v1-native-acceptance.md` A 节

**步骤 1–4：严格执行原生验收 A1–A4**

先 systematic-debugging 固定 WindowsApps `Access is denied` 的 failure envelope；再使用记录 version/integrity 的官方 CLI 精确版本；随后执行 8 个独立 `codex exec --ephemeral --json --output-schema` 场景；正式安装后再验证全局 `~/.codex/AGENTS.md` 与 `$HOME/.agents/skills` 发现。每个输出记录版本、时间、输入/输出 hash 和退出码。发现实现缺陷时新增独立 Red/Green 子任务；失败状态保持 `unverified`。

**步骤 5：提交证据或阻塞记录**

```powershell
git commit -m "test: record Codex CLI acceptance evidence"
```

### Task 17：真实验证 Codex Desktop 与 C7OpenWiki

**文件：**

- 新建：`tests/acceptance/codex-desktop/prompt.md`、`write-tdd.md`、`review-write-result.md`、`result.schema.json`，以及 `tests/acceptance/c7-openwiki/native.json`
- 新建：`scripts/c7-openwiki-acceptance.mjs`
- 新建：`docs/releases/evidence/codex-desktop.md`
- 新建：`docs/releases/evidence/c7-openwiki.md`
- 依据：`docs/superpowers/plans/2026-08-07-selfworkflow-v1-native-acceptance.md` B、C 节

**步骤 1：正式安装计划与 Desktop 新任务**

展示所有目标、来源、dirty、备份、冲突和可选 C7 扩展；用户确认后 apply。Desktop 必须使用不继承本对话的新任务和 nonce 证明读取正式安装态；用户需自行新建，或明确授权 Agent 新建。

**步骤 2：隔离 C7OpenWiki 真实进程**

记录 C7 HEAD/dirty/完整能力 tree hash 和正式 Wiki tree hash；先运行 `pnpm verify:capabilities`；再在 C7 默认 runtime 根内建立独立 runtime，以 stdio JSON-RPC 真实调用七个工具。不得复制正式凭据或 Wiki；query/propose 只承诺不发布 Wiki，允许 OAuth 刷新和临时事务。

**步骤 3：明确确认后测试 update**

在独立 runtime 完成 OAuth 与选定模型/effort 验证，只对合成 Wiki 和无敏感临时源测试 prepare、hash 失效、CAS、`confirmedByUser: true`、复审与终态。未经用户对该测试写入的明确确认不调用 update；前后正式 Wiki tree hash 必须一致。

**步骤 4：更新独立支持状态**

只有 Codex Desktop 与 CLI 都真实通过，Codex 才能标记 `supported`。C7OpenWiki 单独记录 supported 或 unverified，不影响核心代码任务交付。

**步骤 5：提交证据**

```powershell
git commit -m "test: record native host and knowledge backend evidence"
```

### Task 18：最终验证与发布候选

**文件：**

- 修改：`src/selfworkflow/__init__.py`
- 修改：`CHANGELOG.md`
- 新建：`docs/releases/0.1.0.json`
- Review 暴露缺陷时：新增单独 Red/Green 修复子任务

**步骤 1：生成 release manifest 草案**

版本升级为 `0.1.0`，但在门禁通过前状态为 `candidate`。

**步骤 2：运行所有新鲜验证**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify.ps1 -Suite all -ReleaseManifest docs/releases/0.1.0.json -RuntimeOutput build/runtime-final
git diff --check
git status --short
```

预期：全部自动化测试通过；runtime hash 与 manifest 一致；无意外文件。

**步骤 3：最终独立双阶段 Review**

第一位审查需求/设计符合性，第二位审查代码质量、安全、安装侵入性、失败恢复和证据真实性。任何 Critical/Important 修复后重跑全套验证并重新 Review。

**步骤 4：执行回滚演练与安装态 smoke**

构建 `0.1.0.dev0` baseline artifact 与 manifest，先在沙箱执行 `install plan/apply/verify`；再构建 `0.1.0` candidate 并执行 upgrade；对 candidate upgrade transaction 生成 rollback plan、确认其 hash 后执行 rollback，比较托管 hash、非托管 tree hash 和 SDDL；最后重新 apply candidate。正式环境已有版本时改用其实际前一 manifest。精确命令见原生验收 E 节。

**步骤 5：只在全部硬门槛满足时标记 release**

若 Codex CLI 或 Desktop 未真实通过，保留 `candidate/unverified`，明确阻塞项，不发布为 supported。

**步骤 6：提交发布候选**

```powershell
git commit -m "release: prepare SelfWorkFlow 0.1.0"
```

---

## 每个 Chunk 的审查门禁

每个 Chunk 完成后必须：

1. 对照本计划逐项检查规格；
2. 审查完整 diff、失败路径、逻辑闭环、安全和侵入性；
3. 运行该 Chunk 全部测试及所有已实现相关回归；
4. 列出未执行项、原因、风险和人工验证方法；
5. Critical/Important 清零后才进入下一 Chunk；
6. 更新实施计划状态，但不得因接近结束而降低验证要求。

## 首版完成定义

- 核心、Catalog、路由、内建代码质量、安装器、适配器和 C7OpenWiki 契约均有 Red/Green 证据；
- 安装器 dry-run、冲突、幂等、回滚、恢复和并发锁全部通过；
- 运行时脱离 E 盘和 `D:\openwikiC7` 仍可运行核心；
- 正式 `.agents` 修改已经过用户确认且有可恢复备份；
- Codex Desktop 与 Codex CLI 真实通过后才称 Codex supported；
- C7OpenWiki 真实调用单独记录，失败不污染核心状态；
- 所有 Review 与测试都有新鲜、可追溯证据；
- 任何未满足硬门槛均明确为 `unverified` 或 blocked，不虚构“已完成”。
