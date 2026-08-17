# 通用 Skill 按需加载边界 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让通用能力 Skill 按任务相关性独立加载，同时避免把轻量只读任务膨胀成完整修改流程。

**Architecture:** 保留现有轻量工作流和 C++ 路由，仅补充一条“流程深度与能力选择正交”的核心规则，并在现有 Skill 中区分只读推理、修改规则和副作用边界。通用代码分析复用 `code-quality`，C/C++ 分析复用 `cpp-core`，不新增模块或路由器。

**Tech Stack:** Markdown Skill、YAML catalog、Python unittest。

---

## Chunk 1: 最小行为边界

### Task 1: 先用行为测试固定边界

**Files:**
- Modify: `tests/behavioral/test_workflow_matrix.py`
- Modify: `tests/behavioral/test_code_quality_scenarios.py`
- Modify: `tests/behavioral/test_v3_cpp_workflow.py`

- [ ] 在核心策略测试中要求出现“能力相关性不依赖流程深度”的稳定语义。
- [ ] 在 code-quality 测试中要求 description/body 覆盖只读代码理解，并要求 catalog selector 支持 `analyze`。
- [ ] 在 C++ 测试中新增 `analyze` 路由，证明只选择 `cpp-core`/`cpp.reasoning`，不选择执行能力。
- [ ] 运行三个目标测试文件，确认新增断言先失败。

### Task 2: 实现最小规则与 Skill 分层

**Files:**
- Modify: `workflow/core.md`
- Modify: `WORKFLOW.md`
- Modify: `skills/code-quality/SKILL.md`
- Modify: `skills/cpp-core/SKILL.md`
- Modify: `catalog/domains/code-quality.yaml`
- Modify: `catalog/v3/modules/cpp-core.yaml`

- [ ] 在核心规则中声明：流程深度由复杂度/风险/副作用决定，能力 Skill 由显式请求及语言、文件、语义相关性决定。
- [ ] 在 `code-quality` 增加精简的只读 reasoning core；现有 Required loop 明确为修改、Bug 与需要验证的分析路径。
- [ ] 在 `cpp-core` 明确只读任务只应用推理核心和命中参考，不自动进入修改、构建、调试器或完整流程。
- [ ] 把 `analyze` 加入现有 code-quality selector，并更新被文件内容绑定的 hash；不增加 catalog entry。
- [ ] 运行目标测试，确认通过。

### Task 3: 回归、Review 与安装

**Files:**
- Modify: `docs/superpowers/plans/2026-08-10-general-skill-activation-boundary.md`

- [ ] 运行 code-quality、C++ routing、catalog、runtime snapshot 与安装器相关最窄回归。
- [ ] 运行完整 SelfWorkFlow 测试和 `git diff --check`。
- [ ] Review 完整 diff，检查误触发、上下文膨胀、现有 C7OpenWiki 变更重叠和无关修改。
- [ ] 更新本计划的执行证据，然后用 `knowledge` profile 幂等重装并核对安装/source Skill hash。
- [ ] 不创建 Git commit；保留用户当前工作树状态。
