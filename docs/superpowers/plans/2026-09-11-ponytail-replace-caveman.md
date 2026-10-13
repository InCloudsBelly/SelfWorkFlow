# Ponytail 替换 Caveman 实施计划

> **For agentic workers:** REQUIRED: 使用 superpowers:subagent-driven-development（存在 SubAgent 时）或 superpowers:executing-plans 执行本计划。所有步骤使用 checkbox（- [ ]）跟踪。

**目标：** 在 CodeGraph 稳定版本之上，彻底移除 SelfWorkFlow 中 Caveman 的所有活动功能，由 Ponytail 按官方推荐范围仅服务 coding/engineering task，并同步提供 Codex、Claude、Cursor、OpenCode、Copilot 等宿主的通用薄适配。

**架构：** 将 Ponytail 作为锁定的只读 Git submodule 纳入 source governance，由 runtime builder 只复制官方选定的 Skill 文件；SelfWorkFlow 保留自己的流程、证据、Review、TDD、验证、安全和中文文档约束。Ponytail 不作为所有回复的常驻表达策略，不启用上游 Node hooks、插件生命周期或全局状态。

**技术栈：** Git submodule、YAML lock/source registry、Python runtime builder/Installer、PowerShell one-click installer、JSON Schema、unittest、现有 adapter/catalog/runtime manifest。

---

## 状态与执行门槛

- 设计来源：用户已通过 Grill-me 和后续确认冻结方案。
- 本文是实施方案文档，不代表本轮开始删除或安装；当前只落地文档。
- CodeGraph 是硬前置条件。必须等待 CodeGraph 当前工作完成，取得最终提交后，重新创建独立 codex/ponytail-* worktree；禁止在现有 D:\SelfWorkFlow\.worktrees\selfworkflow-v1 脏 worktree 中实施。
- 实施代码前仍须经过 plan.gate、Full 文档集成 Review、用户明确实施确认，然后才能进入 TDD Red → Green。
- 任何新增公共 API/Schema、持久化格式、宿主原生 Hook、全局配置或超出本计划的安装面都会使本计划失效，必须回到设计阶段。

## 已冻结的范围

| 范围 | 决定 | 明确不做 |
| --- | --- | --- |
| Caveman | 完全删除 SelfWorkFlow 管理的 Caveman 源文件、runtime 文件、激活逻辑、规则、测试和活动文档引用；删除已确认的用户级安装 Skill | 不保留 fallback、别名、兼容层、双模式或 Caveman 表达功能 |
| Ponytail 主 Skill | 只在官方定义的 coding/engineering task 中应用；默认 full | 不把 Ponytail 变成所有回复的常驻行为；非编码任务不自动加载 |
| Ponytail 辅助 Skill | ponytail-review 只用于代码 Review，ponytail-audit 只用于代码审计，ponytail-help 只用于 Ponytail 使用说明 | 当前不纳入 ponytail-debt、ponytail-gain |
| 宿主 | Codex、Claude、Cursor、OpenCode、Copilot、unknown 全部同步分发同一行为契约 | 不声称所有宿主具备相同的原生 Hook、命令或状态能力 |
| 上游 | 只读、锁 commit/tree/hash/license；runtime 只选择性复制 Skill | 不修改 Ponytail upstream，不复制官方 Hooks、Node 脚本、.codex-plugin 配置到 runtime |
| 模式 | full 为 coding task 默认；保留官方支持的 lite/full/ultra/off 会话切换 | 不写 %APPDATA%\ponytail\config.json、PONYTAIL_DEFAULT_MODE、PLUGIN_DATA 或其他全局持久状态 |
| 平台 | Windows 首先验证；路径和规则保持可移植 | 不宣称 Linux/macOS 原生安装已验证 |
| 指标 | 不复制 upstream 的 token、成本、时间或代码行数宣传；如需指标另做独立实验 | 不在本次迁移中发布未经 SelfWorkFlow 收据支持的性能结论 |

## 官方应用范围契约

Ponytail 的触发条件必须由 SelfWorkFlow classifier/router 明确表达，而不是通过“每轮必读”或宿主全局表达规则间接触发：

1. coding/engineering task：加载 ponytail 主 Skill；包括实现、修复、重构、工程配置消费者、构建相关代码工作和代码 Review 前的工程决策。
2. 代码 Review：仅按 Review 任务加载 ponytail-review，不因普通对话自动加载。
3. 代码审计：仅按明确的 audit 任务加载 ponytail-audit。
4. Ponytail 使用说明、模式或安装问题：仅按明确的帮助请求加载 ponytail-help。
5. 一般问答、翻译、普通写作、非工程资料整理和不涉及代码行为的文档任务：不得自动触发 Ponytail。
6. SelfWorkFlow 的硬规则始终优先。Ponytail 的“最小实现”判断不能跳过 Scope/Plan、用户确认、Review、TDD、验证、安全检查、CodeGraph freshness 或失败关闭门禁。

## 运行时关系

~~~text
Ponytail upstream（锁定 commit）
        │ 只读校验 selected skills
        ▼
SelfWorkFlow runtime builder
        │ 选择性复制 ponytail / review / audit / help
        ▼
runtime artifact + manifest
        │ 通过已有 Installer 的 managed surfaces / backup / rollback
        ▼
Codex / Claude / Cursor / OpenCode / Copilot / unknown
        │ 宿主薄适配；保持同一触发范围和 SelfWorkFlow 优先级
        ▼
仅 coding/engineering task 激活 Ponytail
~~~

## 文件结构与责任边界

以下路径均相对于 CodeGraph 完成后新建的 Ponytail 实施 worktree；主工作区当前只新增本文。

### Source governance 与构建

- Modify: .gitmodules — 增加 dependencies/upstream/ponytail submodule。
- Create: dependencies/locks/ponytail.lock.yaml — 保存 canonical URL、submodule gitlink commit、tree、upstream version（若存在）、LICENSE SPDX/hash 和四个 selected Skill 的路径/hash。
- Modify: imports/source-registry.yaml — 注册 Ponytail 官方 source、锁定身份和支持状态。
- Modify: src/selfworkflow/v3/submodule_profiles.py — 将 Ponytail 加入 normal profile 的路径白名单；保持不使用 --remote，失败恢复各 submodule 原 HEAD。
- Modify: scripts/install-selfworkflow.ps1 — 对 Ponytail lock、gitlink、submodule HEAD/tree/dirty 状态做 fail-closed 校验，并把 source report 写入安装日志；不执行 upstream install command。
- Modify: src/selfworkflow/adapters.py — 增加 Ponytail lock/source 校验和选择性复制；移除 skills/caveman runtime source。
- Create: src/selfworkflow/ponytail_scope.py — 维护 coding-only route 判断和会话级 Ponytail mode；不写全局配置、不改变 SelfWorkFlow mode。

### SelfWorkFlow 规则与目录

- Modify: WORKFLOW.md — 删除 Caveman-lite 常驻条款；加入“Ponytail 只用于 coding/engineering task”的简短触发契约，不添加全局表达风格。
- Modify: workflow/core.md — 删除 Caveman 表达、默认模式和 Skill 常驻安装规则；保留 SelfWorkFlow 自己的中文、进度、Review、验证和安全要求，并记录 Ponytail 优先级边界。
- Modify: catalog/domains/workflow.yaml — 删除活动 Caveman entry；增加范围受限的 Ponytail foundation entry。
- Modify: catalog/modules.yaml — 增加 Ponytail coding/review/audit/help 的 v2 route metadata，明确 operation、scope、exclusion、supportStatus 和依赖。
- Modify: catalog/index.yaml — 更新生成索引 hash。
- Modify: catalog/v3/domains/workflow.yaml — 增加 Ponytail 相关 module id，保留现有 CodeGraph/TEA/Review 流程。
- Create: catalog/v3/modules/ponytail-coding.yaml — coding/engineering task 的主 Skill route。
- Create: catalog/v3/modules/ponytail-review.yaml — 明确代码 Review 才能触发的辅助 route。
- Create: catalog/v3/modules/ponytail-audit.yaml — 明确代码审计才触发的辅助 route。
- Create: catalog/v3/modules/ponytail-help.yaml — 明确帮助请求才触发的辅助 route。
- Modify: catalog/v3/index.yaml — 更新新增 module 文件的 hash。
- Delete: skills/caveman/SKILL.md 和 skills/caveman/README.md — 不保留 Caveman 源 Skill。

### 宿主适配

所有 adapter 必须表达同一个范围契约，具体宿主只负责文件名、加载入口和能力状态：

- Modify: adapters/claude-code/adapter.yaml
- Modify: adapters/claude-code/CLAUDE.managed.md
- Modify: adapters/codex/adapter.yaml
- Modify: adapters/codex/AGENTS.managed.md
- Modify: adapters/cursor/adapter.yaml
- Modify: adapters/cursor/CURSOR.managed.md
- Modify: adapters/opencode/adapter.yaml
- Modify: adapters/opencode/OPENCODE.managed.md
- Modify: adapters/copilot/adapter.yaml
- Modify: adapters/copilot/copilot-instructions.md
- Modify: adapters/unknown/adapter.yaml
- Modify: adapters/unknown/BOOTSTRAP.md

适配器必须继续满足：coreOverride: forbidden；保留现有 experimental-unverified、instructions-only、bootstrap-only 的诚实状态；不把 Ponytail upstream Hook 的存在当作宿主原生能力证据。

### 测试与文档

- Modify: tests/conformance/test_runtime_snapshot.py — runtime 必须包含 Ponytail 四个选定 Skill，且不存在 Caveman、upstream hooks、Node runtime 和 .codex-plugin 文件。
- Modify: tests/conformance/test_matt_skills_foundation.py — 删除 Caveman 相关断言；保留 Matt Pocock source foundation 的独立覆盖。
- Create: tests/conformance/test_ponytail_source.py — lock、gitlink、tree、license、selected Skill hash、source dirty/drift 和 upstream path rejection。
- Modify: tests/conformance/test_adapters.py — 验证所有宿主的 Ponytail scope contract、能力状态和 coreOverride 不可覆盖。
- Modify: tests/behavioral/test_workflow_matrix.py — 删除 Caveman 常驻行为测试；增加非编码不触发、编码触发、SelfWorkFlow hard rules 优先测试。
- Create: tests/behavioral/test_host_ponytail_matrix.py — 对 Codex、Claude、Cursor、OpenCode、Copilot、unknown 做统一范围和薄适配矩阵测试。
- Modify: tests/installer/test_one_click.py — 验证 Ponytail source report、Caveman managed retirement、显式确认门禁和安装后 doctor。
- Modify: tests/installer/test_plan.py — 验证旧 artifact 中由 SelfWorkFlow 管理的 skills/caveman/** 只在 hash 未漂移时进入 retired skill list。
- Modify: tests/installer/test_submodule_profiles.py — 验证 normal profile 只新增 Ponytail 路径，不引入 remote update，并继续覆盖离线失败回滚。
- Create: tests/unit/test_ponytail_source.py — 覆盖 lock 结构、selected path 白名单和复制拒绝条件。
- Modify: README.md — 说明 Ponytail 的官方应用范围、宿主支持状态、Windows 首验证边界和不启用 upstream hooks；删除活动 Caveman 安装说明。

历史设计/计划文档只作为历史记录，不重新恢复 Caveman 功能；如需说明迁移关系，只能写“已被 Ponytail 迁移计划取代”，不能作为 runtime source 或 activation evidence。

---

## Chunk 1：建立 Ponytail source lock 与 submodule 边界

### Task 1: 等待 CodeGraph 完成并创建隔离 worktree

**Files:**

- Read-only: D:\SelfWorkFlow\.worktrees\selfworkflow-v1
- Create: 新的 codex/ponytail-* worktree（目录由 using-git-worktrees 规则选择）

- [ ] **Step 1: 确认 CodeGraph 前置状态**

运行：

~~~powershell
git -C D:\SelfWorkFlow\.worktrees\selfworkflow-v1 status --short --branch
git -C D:\SelfWorkFlow\.worktrees\selfworkflow-v1 log -1 --oneline
~~~

预期：CodeGraph 相关修改已形成最终可用提交；若 worktree 仍有未提交 CodeGraph 修改，停止本计划实施并等待用户确认最终提交。

- [ ] **Step 2: 从最终 CodeGraph 提交创建新 worktree**

运行：

~~~powershell
$NewWorktreePath = 'D:\SelfWorkFlow\.worktrees\selfworkflow-ponytail'
$FinalCodeGraphCommit = (git -C D:\SelfWorkFlow\.worktrees\selfworkflow-v1 rev-parse HEAD)
git -C D:\SelfWorkFlow worktree add -b codex/ponytail-foundation $NewWorktreePath $FinalCodeGraphCommit
~~~

预期：只有在上一步确认 CodeGraph 已最终提交后，才使用解析出的 $FinalCodeGraphCommit；新 worktree 从该提交创建；原 selfworkflow-v1 worktree 状态逐字保持不变。

- [ ] **Step 3: 记录基线并确认没有 Ponytail 实施改动**

运行：

~~~powershell
git -C $NewWorktreePath status --short --branch
rg -n -i "caveman|ponytail" $NewWorktreePath -g '!dependencies/upstream/**'
~~~

预期：只看到迁移前的 Caveman 活动引用；没有 Ponytail 实施文件被提前写入。

- [ ] **Step 4: Commit**

本 Task 只建立 worktree，不单独提交业务变更。

### Task 2: 锁定官方 Ponytail source

**Files:**

- Modify: .gitmodules
- Create: dependencies/locks/ponytail.lock.yaml
- Modify: imports/source-registry.yaml
- Modify: src/selfworkflow/v3/submodule_profiles.py
- Modify: scripts/install-selfworkflow.ps1
- Test: tests/conformance/test_ponytail_source.py
- Test: tests/installer/test_submodule_profiles.py

- [ ] **Step 1: 写 lock/source/profile 的 RED 测试**

测试必须证明：缺 lock、canonical URL 错误、gitlink 不匹配、submodule dirty、selected Skill 缺失、symlink、tree/hash 漂移时均 fail closed；normal profile 只能操作固定白名单路径。

- [ ] **Step 2: 运行 RED 测试**

~~~powershell
.\scripts\verify.ps1 -Suite conformance -Test tests.conformance.test_ponytail_source
.\scripts\verify.ps1 -Suite installer -Test tests.installer.test_submodule_profiles
~~~

预期：新增 Ponytail 断言失败，失败原因必须是明确的 lock/source/profile 缺失，而不是测试导入异常。

- [ ] **Step 3: 添加 submodule 并重新读取官方身份**

运行：

~~~powershell
git -C $NewWorktreePath submodule add https://github.com/DietrichGebert/ponytail.git dependencies/upstream/ponytail
$PonytailPath = Join-Path $NewWorktreePath 'dependencies\upstream\ponytail'
git -C $PonytailPath status --porcelain=v1 --untracked-files=all
git -C $PonytailPath rev-parse HEAD
git -C $PonytailPath rev-parse 'HEAD^{tree}'
git -C $PonytailPath ls-tree -r --name-only HEAD -- skills/ hooks/ .codex-plugin/
~~~

实现要求：重新读取当时官方 main 的确切 commit，不使用可变 branch 作为 lock；把实际读取结果写入 lock。预研曾观察到一个 main commit，但不得直接把预研值当作最终 pin。

- [ ] **Step 4: 写完整 lock**

写入 dependencies/locks/ponytail.lock.yaml。lock 至少包含以下字段；动态值必须由实现时的 source 计算，不得手填或使用可变 branch：

- schemaVersion: 1
- sourceId: ponytail
- canonicalUrl: https://github.com/DietrichGebert/ponytail.git
- path: dependencies/upstream/ponytail
- gitlinkCommit：来自 submodule HEAD 的 40 位 commit
- gitTree：来自 submodule HEAD^{tree} 的 tree
- upstreamVersion：来自 upstream manifest 的版本；不存在时省略
- license.path、license.spdx、license.hash：来自实际 LICENSE 文件
- selectedSkills：依次锁定 skills/ponytail、skills/ponytail-review、skills/ponytail-audit、skills/ponytail-help 及各自递归内容 hash

- [ ] **Step 5: 实现 profile/Installer lock 校验**

只将 dependencies/upstream/ponytail 加入 _NORMAL_PATHS；保留现有 path-limited、无 --remote、失败恢复和 postcondition 检查。Installer 在 submodule 阶段同时验证 Ponytail lock/gitlink/source dirty 状态，并把 commit/tree/lock hash 写入安装日志。

- [ ] **Step 6: 运行 GREEN 测试并提交**

~~~powershell
.\scripts\verify.ps1 -Suite conformance -Test tests.conformance.test_ponytail_source
.\scripts\verify.ps1 -Suite installer -Test tests.installer.test_submodule_profiles
git add .gitmodules dependencies/locks/ponytail.lock.yaml imports/source-registry.yaml src/selfworkflow/v3/submodule_profiles.py scripts/install-selfworkflow.ps1 tests/conformance/test_ponytail_source.py tests/installer/test_submodule_profiles.py
git commit -m "build: lock ponytail upstream source"
~~~

预期：新增测试通过，source drift 和 dirty source 均 fail closed。

## Chunk 2：选择性打包 Ponytail，删除 Caveman runtime

### Task 3: 为 runtime builder 增加 Ponytail selected-skill 复制

**Files:**

- Modify: src/selfworkflow/adapters.py
- Modify: tests/conformance/test_runtime_snapshot.py
- Create: tests/unit/test_ponytail_source.py（如 Task 2 已创建则合并，不重复建文件）

- [ ] **Step 1: 写 runtime RED 测试**

测试要求：

- core、knowledge、maintainer 的既有 profile 行为保持不变。
- runtime 包含 skills/ponytail/SKILL.md、skills/ponytail-review/SKILL.md、skills/ponytail-audit/SKILL.md、skills/ponytail-help/SKILL.md。
- runtime 不包含 skills/caveman。
- runtime 不包含 Ponytail hooks、.codex-plugin、Node scripts 或 global config。
- selected Skill 的源路径必须是普通文件目录，不接受 symlink、路径穿越或 lock 外路径。

- [ ] **Step 2: 运行 RED 测试**

~~~powershell
.\scripts\verify.ps1 -Suite conformance -Test tests.conformance.test_runtime_snapshot
.\scripts\verify.ps1 -Suite unit -Test tests.unit.test_ponytail_source
~~~

预期：旧 runtime 仍找到 Caveman，且找不到 Ponytail，测试失败于预期断言。

- [ ] **Step 3: 实现最小复制路径**

在 src/selfworkflow/adapters.py 增加与现有 Matt/TEA source 校验同等级别的 Ponytail helper：读取 lock，验证 canonical URL/path、gitlink commit、tree、license 和 selected Skill hash，然后将四个 Skill 分别复制到 runtime 顶层对应的 skill id 目录。从 _CORE_PATHS 移除 skills/caveman；不复制整个 upstream tree。

- [ ] **Step 4: 运行 GREEN 测试**

~~~powershell
.\scripts\verify.ps1 -Suite conformance -Test tests.conformance.test_runtime_snapshot
.\scripts\verify.ps1 -Suite unit -Test tests.unit.test_ponytail_source
~~~

预期：runtime manifest 稳定、四个 Ponytail Skill 存在、Caveman 和 upstream runtime extras 不存在。

- [ ] **Step 5: Commit**

~~~powershell
git add src/selfworkflow/adapters.py tests/conformance/test_runtime_snapshot.py tests/unit/test_ponytail_source.py
git commit -m "feat: package ponytail coding skills"
~~~

### Task 4: 删除 Caveman 活动规则与旧断言

**Files:**

- Modify: WORKFLOW.md
- Modify: workflow/core.md
- Modify: tests/conformance/test_matt_skills_foundation.py
- Modify: tests/behavioral/test_workflow_matrix.py
- Delete: skills/caveman/SKILL.md
- Delete: skills/caveman/README.md

- [ ] **Step 1: 写删除行为 RED 测试**

测试必须证明：

- WORKFLOW.md 和 workflow/core.md 不再出现 Caveman active/default/mode 规则。
- 不存在 skills/caveman。
- 原有 SelfWorkFlow 的硬规则、进度、Review、验证和安全语义仍存在。
- 不编码任务不加载 Ponytail；编码任务才允许加载 Ponytail。

- [ ] **Step 2: 运行 RED 测试**

~~~powershell
.\scripts\verify.ps1 -Suite behavioral -Test tests.behavioral.test_workflow_matrix
.\scripts\verify.ps1 -Suite conformance -Test tests.conformance.test_matt_skills_foundation
~~~

预期：旧 Caveman 断言或缺少 Ponytail scope 断言导致失败；不得通过删除 SelfWorkFlow 硬规则来消除失败。

- [ ] **Step 3: 修改入口和核心规则**

删除 Caveman-lite 常驻、默认 lite、full/ultra/wenyan 切换和“官方 Caveman Skill 常驻安装”描述。加入紧凑但明确的条件：Ponytail 仅用于 coding/engineering task，非编码任务不得自动加载；SelfWorkFlow hard rules 高于 Ponytail。

- [ ] **Step 4: 删除源 Skill 并更新测试**

删除 skills/caveman 目录，删除旧的常驻行为测试，新增范围正/负路径测试。历史文档不作为 runtime source，不恢复任何 Caveman 命令或表达能力。

- [ ] **Step 5: 运行 GREEN 测试并提交**

~~~powershell
.\scripts\verify.ps1 -Suite behavioral -Test tests.behavioral.test_workflow_matrix
.\scripts\verify.ps1 -Suite conformance -Test tests.conformance.test_matt_skills_foundation
git add WORKFLOW.md workflow/core.md tests/conformance/test_matt_skills_foundation.py tests/behavioral/test_workflow_matrix.py
git rm -r skills/caveman
git commit -m "refactor: remove caveman workflow behavior"
~~~

预期：SelfWorkFlow 规则仍完整，Caveman 不再是可发现、可加载或可切换的 Skill。

## Chunk 3：路由 Ponytail 官方范围与多宿主适配

### Task 5: 增加 catalog route 和官方范围判断

**Files:**

- Modify: catalog/domains/workflow.yaml
- Modify: catalog/modules.yaml
- Modify: catalog/index.yaml
- Modify: catalog/v3/domains/workflow.yaml
- Create: catalog/v3/modules/ponytail-coding.yaml
- Create: catalog/v3/modules/ponytail-review.yaml
- Create: catalog/v3/modules/ponytail-audit.yaml
- Create: catalog/v3/modules/ponytail-help.yaml
- Modify: catalog/v3/index.yaml
- Test: tests/behavioral/test_workflow_matrix.py

- [ ] **Step 1: 写 catalog/router RED 测试**

覆盖以下矩阵：

| 请求 | 预期 |
| --- | --- |
| implement / debug / engineering code | 选择 ponytail-coding |
| review 且目标为代码 | 选择 ponytail-review 或既有 Review route 的受限组合 |
| 明确 code audit | 选择 ponytail-audit |
| 明确 Ponytail help | 选择 ponytail-help |
| 普通问答/翻译/普通写作 | 排除所有 Ponytail route |
| Ponytail 与 SelfWorkFlow hard rule 冲突 | 保留 SelfWorkFlow route，拒绝 Ponytail 覆盖 |
| 缺 Skill capability/source integrity | unverified 并按现有 fail-closed 规则暂停受影响阶段 |

- [ ] **Step 2: 运行 RED 测试**

~~~powershell
.\scripts\verify.ps1 -Suite behavioral -Test tests.behavioral.test_workflow_matrix
.\scripts\verify.ps1 -Suite unit -Test tests.unit.test_router
~~~

- [ ] **Step 3: 写 v2/v3 catalog metadata**

新增 entry/module 时复用现有 schema 和 route 语义：ponytail-coding 的 exclusions 明确非编码任务；辅助 Skill 使用 explicit/deterministic activation；supportStatus 在 native capability 未验证时保持 unverified 或由宿主 adapter 的现有状态表达，不提高为 native supported。

- [ ] **Step 4: 重新生成并校验 index hash**

使用仓库既有 catalog 编译入口生成 catalog/index.yaml、catalog/v3/index.yaml 对应 hash；禁止手工保留过期 hash。

- [ ] **Step 5: 运行 GREEN 测试并提交**

~~~powershell
.\scripts\verify.ps1 -Suite unit -Test tests.unit.test_router
.\scripts\verify.ps1 -Suite behavioral -Test tests.behavioral.test_workflow_matrix
git add catalog tests/unit/test_router.py tests/behavioral/test_workflow_matrix.py
git commit -m "feat: route ponytail only for coding tasks"
~~~

### Task 6: 同步所有宿主的薄适配

**Files:**

- Modify: adapters/claude-code/adapter.yaml
- Modify: adapters/claude-code/CLAUDE.managed.md
- Modify: adapters/codex/adapter.yaml
- Modify: adapters/codex/AGENTS.managed.md
- Modify: adapters/cursor/adapter.yaml
- Modify: adapters/cursor/CURSOR.managed.md
- Modify: adapters/opencode/adapter.yaml
- Modify: adapters/opencode/OPENCODE.managed.md
- Modify: adapters/copilot/adapter.yaml
- Modify: adapters/copilot/copilot-instructions.md
- Modify: adapters/unknown/adapter.yaml
- Modify: adapters/unknown/BOOTSTRAP.md
- Test: tests/conformance/test_adapters.py
- Test: tests/behavioral/test_host_ponytail_matrix.py

- [ ] **Step 1: 写宿主矩阵 RED 测试**

对每个 adapter 检查：存在 Ponytail 条件触发契约；非编码任务不激活；SelfWorkFlow hard rules 优先；不声明上游原生 Hook 已支持；保留当前能力状态和 coreOverride: forbidden。

- [ ] **Step 2: 运行 RED 测试**

~~~powershell
.\scripts\verify.ps1 -Suite conformance -Test tests.conformance.test_adapters
.\scripts\verify.ps1 -Suite behavioral -Test tests.behavioral.test_host_ponytail_matrix
~~~

- [ ] **Step 3: 修改各 adapter 的 managed instructions**

每个宿主只增加相同的三项语义：

1. coding/engineering task 才加载 Ponytail；
2. non-coding task 不加载；
3. SelfWorkFlow hard rules、Review、验证和用户确认优先。

宿主差异只保留入口文件名、能力声明和 instructions-only/experimental-unverified/bootstrap-only 状态；不复制 upstream hooks/claude-codex-hooks.json。

- [ ] **Step 4: 运行 GREEN 测试并提交**

~~~powershell
.\scripts\verify.ps1 -Suite conformance -Test tests.conformance.test_adapters
.\scripts\verify.ps1 -Suite behavioral -Test tests.behavioral.test_host_ponytail_matrix
git add adapters tests/conformance/test_adapters.py tests/behavioral/test_host_ponytail_matrix.py
git commit -m "feat: distribute ponytail across host adapters"
~~~

## Chunk 4：Installer 安全迁移、模式会话和文档

### Task 7: 复用 Installer 做 Caveman managed retirement 与回滚

**Files:**

- Modify: tests/installer/test_plan.py
- Modify: tests/installer/test_one_click.py
- Modify: tests/installer/test_rollback.py（仅在现有测试不能覆盖退休删除原子性时）
- Modify: src/selfworkflow/installer.py（仅在 RED 证明既有 managed retirement 不足时；否则不改）
- Modify: scripts/install-selfworkflow.ps1

- [ ] **Step 1: 写迁移 RED 测试**

测试旧 artifact manifest 含 skills/caveman/**、新 artifact 不含 Caveman 时：

- 只有当前 manifest 明确管理的路径才进入 retiredSkillFiles；
- 目标 hash 未漂移时删除并创建 backup；
- 目标 hash 漂移时返回 managed-skill-drift 并停止，不删除；
- 安装中途失败时恢复旧文件和 manifest；
- 用户自定义的非 manifest 文件不被删除；
- 二次安装幂等，doctor 与最终 manifest 一致。

- [ ] **Step 2: 运行 RED 测试**

~~~powershell
.\scripts\verify.ps1 -Suite installer -Test tests.installer.test_plan
.\scripts\verify.ps1 -Suite installer -Test tests.installer.test_one_click
.\scripts\verify.ps1 -Suite installer -Test tests.installer.test_rollback
~~~

- [ ] **Step 3: 优先只调整 artifact 内容和安装日志**

现有 _retired_skill_files、write-ahead transaction、backup、rollback、doctor 机制优先复用。只有测试证明无法表达 Caveman 退休删除时，才在 src/selfworkflow/installer.py 增加最小私有局部逻辑；不得新增独立删除器或绕过 manifest。

- [ ] **Step 4: 处理已知用户级 Caveman 安装**

安装 preflight 必须区分：

- SelfWorkFlow manifest 管理的 agentsRoot/skills/caveman/**：按现有事务删除；
- 已确认且路径由 $env:USERPROFILE\.agents\skills\caveman 解析得到的用户级 Skill（当前环境为 C:\Users\Administrator\.agents\skills\caveman）：先验证目录名、SKILL.md frontmatter name: caveman、hash 和备份，再纳入同一删除报告；
- 其他插件缓存、其他用户目录或非 Skill 文件：不猜测、不递归删除，报告为人工处理项。

删除操作必须保留 backup 和 rollback token；失败或 drift 时 fail closed。

- [ ] **Step 5: 运行 GREEN 测试并提交**

~~~powershell
.\scripts\verify.ps1 -Suite installer -Test tests.installer.test_plan
.\scripts\verify.ps1 -Suite installer -Test tests.installer.test_one_click
.\scripts\verify.ps1 -Suite installer -Test tests.installer.test_rollback
git add src/selfworkflow/installer.py scripts/install-selfworkflow.ps1 tests/installer
git commit -m "feat: retire managed caveman files safely"
~~~

### Task 8: 实现会话级 Ponytail mode，不引入全局状态

**Files:**

- Modify: WORKFLOW.md
- Modify: workflow/core.md
- Create: src/selfworkflow/ponytail_scope.py
- Modify: tests/behavioral/test_workflow_matrix.py
- Create: tests/unit/test_ponytail_scope.py

- [ ] **Step 1: 写 mode RED 测试**

覆盖：coding task 默认 full；显式 ponytail lite、ponytail full、ponytail ultra、ponytail off、stop ponytail、normal mode 只影响当前会话；非编码任务即使存在旧 mode 也不加载 Ponytail；进程结束后不产生配置文件或环境变量持久化。

- [ ] **Step 2: 运行 RED 测试**

~~~powershell
.\scripts\verify.ps1 -Suite behavioral -Test tests.behavioral.test_workflow_matrix
.\scripts\verify.ps1 -Suite unit -Test tests.unit.test_ponytail_scope
~~~

- [ ] **Step 3: 复用现有 session/request context**

在 src/selfworkflow/ponytail_scope.py 中集中保存当前 request/session 的 Ponytail scope 和 mode。不创建 %APPDATA%\ponytail\config.json、PONYTAIL_DEFAULT_MODE、PLUGIN_DATA、daemon、watcher 或 global hook。该模块不能改变 SelfWorkFlow 的 mode、Review、证据和确认门禁。

- [ ] **Step 4: 运行 GREEN 测试并提交**

~~~powershell
.\scripts\verify.ps1 -Suite behavioral -Test tests.behavioral.test_workflow_matrix
.\scripts\verify.ps1 -Suite unit -Test tests.unit.test_ponytail_scope
git add WORKFLOW.md workflow/core.md src/selfworkflow/ponytail_scope.py tests/behavioral/test_workflow_matrix.py tests/unit/test_ponytail_scope.py
git commit -m "feat: keep ponytail mode session-scoped"
~~~

### Task 9: 更新 README 与迁移说明

**Files:**

- Modify: README.md
- Create: docs/design/2026-09-11-ponytail-foundation-design.md（若实施 Review 要求把设计决策从本计划中拆出）

- [ ] **Step 1: 写文档 RED 检查**

检查 README 不再提供 Caveman 的安装、常驻或命令用法；Ponytail 文档明确 coding-only 范围、四个 Skill、所有宿主的诚实支持状态、无 upstream Hook 和 Windows 首验证边界。

- [ ] **Step 2: 修改文档**

保持 upstream Skill 原文语言不改；SelfWorkFlow 自有文档使用中文；不复制 upstream benchmark、token/cost/time/code-line claims。

- [ ] **Step 3: 文档检查并提交**

~~~powershell
rg -n -i "caveman|ponytail|hook|benchmark|token|cost" README.md docs/design
git diff --check
git add README.md docs/design
git commit -m "docs: document ponytail coding-only foundation"
~~~

预期：活动文档不再指导使用 Caveman；历史文档若提及 Caveman，只表达已移除/已取代，不提供可执行入口。

---

## Chunk 5：独立 Review、完整验证与完成门禁

### Task 10: 实施前 Plan Review

**Files:**

- Read: 本文
- Read: docs/design/2026-08-07-selfworkflow-design.md
- Read: CodeGraph 最终提交对应的 WORKFLOW.md、workflow/core.md、runtime/Installer/adapter/test 入口

- [ ] **Step 1: 由独立 Plan reviewer 审查**

审查目标：文件清单是否准确、Caveman 是否真正删除、Ponytail 是否严格 coding-only、CodeGraph 边界是否未越界、删除/回滚是否可证、测试是否覆盖正负路径、是否无隐式 upstream Hook 或全局状态。

- [ ] **Step 2: 处理 Critical/Important**

Critical/Important 必须清零；Minor 必须在文档中记录处置。若审查发现新增责任层、公共 Schema、全局配置或不可逆删除面，停止并修订计划。

- [ ] **Step 3: 形成用户实施确认**

只有 Plan Review 通过且最终文档 hash 固定后，才能请求用户确认实施；用户确认前不得编辑测试或生产代码。

### Task 11: 全量 TDD、Review、验证

**Files:**

- All files listed in Tasks 1–9
- Read-only: final Git diff, generated artifact manifest, installer log, backup/rollback receipt

- [ ] **Step 1: 逐 Task 保持 RED → GREEN**

每个行为变更都必须保存真实失败和同一路径通过证据；不能只运行最终全量测试来替代 RED。

- [ ] **Step 2: 运行最窄验证**

~~~powershell
.\scripts\verify.ps1 -Suite unit
.\scripts\verify.ps1 -Suite conformance
.\scripts\verify.ps1 -Suite installer
.\scripts\verify.ps1 -Suite behavioral
~~~

- [ ] **Step 3: 构建三类 runtime snapshot**

验证 core、knowledge、maintainer 的 artifact manifest、catalog hash、Ponytail selected Skill hash、Caveman 缺失和 upstream extra 缺失。若运行 native：

~~~powershell
.\scripts\verify.ps1 -Suite native
~~~

当前预期是 requires-user-action；没有真实宿主证据时，adapter native 能力必须保持 unverified，不得改写为 supported。

- [ ] **Step 4: 执行安装 dry-run 与失败回滚测试**

使用临时 AgentsRoot、CodexRoot、StateRoot 和临时 source fixture，验证：

- 未提供 -ConfirmApply 时不发布；
- Caveman managed file retirement 有 backup；
- drift、缺 source、lock mismatch、失败注入均停止并恢复；
- doctor 前后状态与 manifest 一致；
- 未跟踪/用户自定义文件不受影响。

- [ ] **Step 5: Full 独立代码 Review**

按 SelfWorkFlow Full 规则使用两个身份独立的临时 Review SubAgent，分别做 Standards/Spec review，并运行 tea-test-review。Review 输入必须绑定最终完整 diff，包括已提交、暂存、未暂存、未跟踪、删除和文件模式。

- [ ] **Step 6: 修复 Review 发现并重跑验证**

任何修复都使旧验证收据失效；必须重新运行受影响 suite 和最终完整 diff Review。

- [ ] **Step 7: Commit 与交付**

只有当所有 Critical/Important 为零、Minor 有处置、验证收据新鲜、Caveman 删除和 Ponytail coding-only 证据齐全时，才允许提交最终实现分支。

---

## 验收清单

- [ ] .gitmodules、Ponytail lock、source registry、submodule profile 和 Installer 身份完全一致。
- [ ] lock 包含实际 commit/tree/license/selected Skill hash；source dirty、lock drift、gitlink mismatch 均 fail closed。
- [ ] runtime 包含四个官方选定 Ponytail Skill，不包含 skills/caveman、Ponytail hooks、Node scripts、.codex-plugin 或 global config。
- [ ] SelfWorkFlow 入口和核心规则完全删除 Caveman 功能，但保留自身硬规则、进度、Review、验证和安全语义。
- [ ] coding/engineering task 触发 Ponytail；非编码任务不触发；review/audit/help 辅助 Skill 只在对应官方范围触发。
- [ ] Codex、Claude、Cursor、OpenCode、Copilot、unknown 的 adapter 具有一致行为契约，且支持状态诚实。
- [ ] Ponytail mode 只存在于会话 context，不写全局配置、不启用 upstream hooks。
- [ ] Installer 只退休 manifest 管理的 Caveman 文件；hash 漂移停止；备份、回滚、doctor 和幂等证据通过。
- [ ] 已知用户级 Caveman Skill 删除前完成精确路径/frontmatter/hash 校验并保留备份；其他外部文件不递归删除。
- [ ] CodeGraph 相关代码、Provider、Worker、配置和当前 CodeGraph worktree 未被本批次修改。
- [ ] 不复制 upstream benchmark 或未经验证的成本/token/时间/代码行数结论。

## 回滚方案

1. 实施始终在独立 codex/ponytail-* worktree 和独立提交中进行，不改 CodeGraph worktree。
2. 源码层回滚使用 Git revert 或删除实施提交，不回退用户后续提交。
3. 安装层回滚使用已有 transaction backup/rollback token；任何 target drift、backup hash mismatch 或 transaction mismatch 都停止并要求人工处理。
4. Caveman 文件只有在 manifest/hash/路径检查通过时才删除；删除前保留 backup。若外部用户级 Skill 不是精确确认的 Caveman 目录，不自动处理。
5. 若 Ponytail native capability 无法验证，保留 instructions-only/experimental-unverified 状态；不通过静默降级或启用 upstream hooks“补齐”能力。

## 相关 Skill

- @superpowers:writing-plans：本计划的分步结构、TDD、验证和提交边界。
- @superpowers:using-git-worktrees：CodeGraph 完成后建立隔离实施 worktree。
- @superpowers:test-driven-development：行为变更的 RED → GREEN → refactor 顺序。
- @testing-review-quality：Full 模式下的测试质量、实施前/落地后 Review 和完成门禁。
- @workflow-quality：文件变更、删除、回滚、证据和用户已有修改保护。
