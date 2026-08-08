---
schemaVersion: 3
artifactKind: tea-risk-test-design
status: design-only
testLevel: T3
source: locked-tea-test-design
---

# Phase 3A TEA 风险测试设计

## 依据与边界

本工件依据以下已批准设计与实施计划，使用锁定 TEA 的风险分级、P×I 和最低有效测试层级原则整理：

- `docs/superpowers/specs/2026-08-09-adaptive-quality-modules-v3-design.md`
- `docs/superpowers/specs/2026-08-09-cpp-code-intelligence-providers-v3-design.md`
- `docs/superpowers/plans/2026-08-09-cpp-code-intelligence-providers-v3.md`

它只设计测试，不证明 TEA workflow 已被 Agent 原生执行，也不替代测试 invocation/result receipt。

## 风险与验收映射

| 风险 | 类别 | P | I | 分数/优先级 | 验收条件 | 最低证据 |
|---|---:|---:|---:|---:|---|---|
| R-01 伪造 `supported` | TECH | 3 | 3 | 9 / P0 | 九个候选逐维记录支持证据；未验证 runtime/behavior 不得升级 | registry 单测、source conformance、最终 diff |
| R-02 TEA 全量上下文被注入 | PERF | 2 | 3 | 6 / P1 | T0/T1 零加载；每次 JIT 只读取一个当前 workflow 的 skill/workflow/step/resource 文件 | 路由单测、路径逃逸与目录读取失败测试 |
| R-03 设计输出伪装执行证据 | SEC | 3 | 3 | 9 / P0 | `fulfilled` 必须解析 Host collector receipt，并绑定 invocation/result/strategy/diff | CoverageResult 直接路径与失败路径单测 |
| R-04 submodule URL、gitlink、tree、inventory、license、adapter 或 dirty 漂移 | DATA | 2 | 3 | 6 / P1 | 任一漂移统一失败为 `tea-source-identity-invalid`；合法固定 HEAD 通过 | 真实仓库 conformance 与漂移注入测试 |
| R-05 安装器初始化 Heavy 或离线失败污染旧状态 | OPS | 2 | 3 | 6 / P1 | normal profile 仅允许 TEA；无 `--remote`；失败恢复旧 HEAD | 临时 bare remote 的 clone、幂等、更新、离线回滚测试 |

## 覆盖义务

- Direct：固定来源通过；T2 plan/review 与 T3 verify/release 命中预期 workflow；有效 collector receipt 可形成通过的 CoverageResult。
- Failure：未知字段、重复候选、非法等级/阶段、缺失 receipt、URL/branch/dirty/hash 漂移、离线缺失 commit 均 fail closed。
- Boundary：T1→T2、T2→T3、acceptance RED false→true、单文件→目录、子模块 allowlist→Heavy。
- State invariants：父仓库 gitlink 是目标版本；重复执行幂等；失败后已初始化 TEA 回到 last-good commit；用户 dirty submodule 不被覆盖。
- Authorization：本阶段没有外部发布、网络服务写入或用户数据删除；安装器仍由既有显式 APPLY 门控制。

## NFR 计划与残余未验证

本阶段只对以下可观察属性提供证据：确定性路由、内容 hash、路径隔离、失败回滚和上下文切片。性能时延、最大仓库规模、并发安装、跨平台行为和第三方 Agent 的原生 TEA 执行阈值均没有已批准的量化要求，状态保持 `UNKNOWN / unverified`，不得推断为 PASS。Windows 一键安装是当前唯一安装目标。

TEA 的 `runtimeCapability` 与九个 workflow 的真实 Agent 执行效果均保持 `unverified`；未来只有在记录真实 invocation/result、输入工件和独立复审后才能逐项升级。
