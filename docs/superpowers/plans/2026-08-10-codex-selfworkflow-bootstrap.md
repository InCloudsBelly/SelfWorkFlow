# Codex SelfWorkflow Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Codex 每个新任务直接获得 SelfWorkflow 轻量核心，而不依赖 Agent 主动展开外部文件引用。

**Architecture:** 复用现有事务安装器和 managed block；安装计划从 artifact 读取已验证的 `WORKFLOW.md`，生成含元数据和内联核心的文本。高级模式继续使用 snapshot，不引入新运行时组件。

**Tech Stack:** Python 3、`unittest`、PowerShell 一键安装器。

---

## Chunk 1: 安装入口最小修复

### Task 1: 固定缺陷行为

**Files:**
- Modify: `tests/installer/test_apply.py`

- [x] 添加测试：安装后的 managed block 包含 artifact `WORKFLOW.md` 的唯一规则、artifact hash/profile/snapshot 元数据，并保留用户文本。
- [x] 添加测试：修改 artifact 工作流后，升级会刷新 managed block，且用户文本保持不变。
- [x] 运行定向测试，确认测试因当前只写外部引用而失败。

### Task 2: 内联轻量核心

**Files:**
- Modify: `src/selfworkflow/installer.py`

- [x] 让 `_managed_instruction` 接收 artifact 工作流正文及安装元数据。
- [x] 生成简短 bootstrap 头、内联正文和仅供高级模式使用的 snapshot 提示。
- [x] 保持 managed block 替换、事务回滚和路径校验不变。
- [x] 运行定向测试并确认通过。

### Task 3: 安装与验证

**Files:**
- Modify only if evidence requires: `tests/acceptance/test_install_sandbox.py`
- Modify only if evidence requires: `tests/installer/test_one_click.py`

- [x] 运行安装器、适配器、运行时快照和一键安装回归。
- [x] 使用当前 knowledge profile 重装到真实用户目录。
- [x] 重新读取 `C:\Users\Administrator\.codex\AGENTS.md`，验证用户内容、managed block、artifact hash 和内联核心。
- [x] 执行安装 verify/doctor，并记录新任务才能重新构建 Codex 指令链的限制。

## 验证证据

- TDD Red：两个定向测试均因旧 managed block 只有外部文件引用而失败。
- TDD Green：两个定向测试通过。
- 相关回归：installer、adapter、runtime snapshot 和 install sandbox 共 48 项测试通过。
- 真实安装：knowledge profile 安装、`install verify` 和 `doctor` 成功；用户原有 managed block 外文本保持不变。
- 结构验证：内联正文与当前 hash-bound snapshot 的 `WORKFLOW.md` 完全一致；`AGENTS.md` 仅有一个 managed block，且总大小低于 Codex 默认 32 KiB 上限。
- 原生新任务烟测：当前 WindowsApps 中的 Codex 可执行文件由 shell 调用时返回 `Access is denied`，因此该项标记为 `unverified`；必须通过重启 Codex 或新建任务确认新指令链。
