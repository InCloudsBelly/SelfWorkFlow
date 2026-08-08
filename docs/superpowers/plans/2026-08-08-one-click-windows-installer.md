# Windows One-click Installer Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供带失败日志、Grill-me 可选安装和 Codex Superpowers 接入的一键 Windows 安装入口。

**Architecture:** 根目录 BAT 是薄入口；PowerShell 只做环境准备、交互、日志和流程编排；确定性运行时构建与事务发布继续由 Python 核心完成。Grill-me 作为构建特性开关进入 artifact manifest，跳过时同时移除 Skill 和 Catalog 元数据。

**Tech Stack:** Windows Batch、PowerShell 5.1+、Python 3.11+、`unittest`、现有 SelfWorkFlow CLI/事务安装器。

---

## Chunk 1: 可选 Grill-me 运行时

### Task 1: 让运行时真实支持包含或排除 Grill-me

**Files:**
- Modify: `src/selfworkflow/adapters.py`
- Modify: `src/selfworkflow/cli.py`
- Modify: `tests/conformance/test_runtime_snapshot.py`

- [x] 写失败测试：默认运行时包含 Grill-me；`include_grill_me=False` 和 CLI `--without-grill-me` 同时排除 Skill 目录及 Catalog 项，并在 artifact manifest 记录选择。
- [x] 运行 `./scripts/test.ps1 -Test tests.conformance.test_runtime_snapshot`，确认新测试先失败。
- [x] 为 `build_runtime` 增加布尔特性开关，并让 Catalog 过滤和复制清单使用同一选择。
- [x] 重跑定向测试，确认通过且默认行为不变。

## Chunk 2: 一键编排与诊断

### Task 2: 添加 BAT 薄入口

**Files:**
- Create: `Install_SelfWorkFlow.bat`
- Test: `tests/installer/test_one_click.py`

- [x] 写失败测试：BAT 从自身目录解析 PowerShell 脚本、转发参数并保留退出码，不在 BAT 内实现安装逻辑。
- [x] 实现最小 BAT 包装。
- [x] 运行定向测试并确认通过。

### Task 3: 添加可测试的 PowerShell 安装编排

**Files:**
- Create: `scripts/install-selfworkflow.ps1`
- Test: `tests/installer/test_one_click.py`

- [x] 写失败测试覆盖帮助、缺失 Grill-me 的 Install/Skip 非交互分支、日志文件、显式 APPLY、中文/空格路径、Superpowers 本地源检查和冲突停止。
- [x] 实现参数和稳定阶段退出码；所有控制台和详细输出写入当前安装日志。
- [x] 创建或验证 `.venv`，按锁文件准备依赖；任何外部安装都需要显式同意。
- [x] 调用 doctor、build、plan、apply、verify，并在应用后失败时使用现有 rollback-plan/rollback 恢复本次发布。
- [x] 仅从验证后的本地 Superpowers Git 源复制受跟踪的 Skill 文件并写来源锁；不使用会破坏 doctor 的 junction，不覆盖现有非匹配入口。
- [x] 重跑定向安装器测试。

## Chunk 3: 文档与闭环验证

### Task 4: 文档、回归和结构化 Review

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-08-one-click-windows-installer-design.md`
- Modify: `docs/superpowers/plans/2026-08-08-one-click-windows-installer.md`

- [x] 在 README 首屏加入 `Install_SelfWorkFlow.bat` 用法、默认选择、日志位置、原生验证边界和恢复说明。
- [x] 运行 `./scripts/verify.ps1 -Suite installer`。
- [x] 运行 `./scripts/verify.ps1 -Suite automated`。
- [x] 检查完整 diff、失败路径、安全、侵入性、无关修改和文档一致性；无法执行的原生 Agent 重启/触发测试标记为 `unverified`。
- [x] 根据真实实现和测试证据同步勾选本计划，不能用计划文字代替完成证据。

## Fresh verification evidence

- `./scripts/verify.ps1 -Suite installer`: 23 tests, exit 0.
- `./scripts/verify.ps1 -Suite automated`: 357 tests, exit 0.
- The official-clone branch was exercised without network by Git URL rewrite to a local committed mirror; the fixed production URL and the real `git clone` process were still used.
- Still `unverified`: a real fresh host with no Python, a real winget/PyPI/network transaction, Explorer double-click behavior, Codex restart/native Skill discovery, and native Grill-me/Brainstorming activation. These are not represented as automated success.
