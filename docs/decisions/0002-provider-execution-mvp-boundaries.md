# ADR 0002：Provider 执行内核采用 fail-closed MVP

- 状态：Accepted
- 日期：2026-08-09

## 决策

Provider 执行内核首版只支持由内容寻址 `TrustedCommandRegistry` 产生的 `none` 或
`local-write` 计划。写计划只允许 `selfworkflow-managed` 的 managed-state 目标及显式
`initialize | sync | rebuild | upgrade | repair` 动作；`delete`、用户拥有内容的 mutation、
process/service mutation 和所有 network 计划均为 `unsupported`，不得生成可执行计划。

生产 local-write 必须由宿主注入以下权威能力，任一缺失即拒绝执行：

1. 每次执行重新解析当前状态的 `AuthorizationResolver`；Plan 中只保存 authorization hash，
   任何嵌入副本均不是权威状态。
2. 能证明跨进程原子 CAS 的外部 `HostAtomicLeasePort`，以及 Effect 执行期间实际调用的 live
   lease guard。本仓库不提供、也不声称提供安全的 Python 文件锁或生产 lease backend。
3. 密封的可信命令注册表和支持密封命令、live guard、真实观测证据的宿主 EffectPort。

Replay 采用 `reserve → commit/abort`：只有 EffectPort 明确抛出 `EffectNotStarted` 才可 abort
并重试；任何可能已经启动、返回失败或后置验证失败都提交 `terminal-failed`，禁止自动重放。

每个 `evidenceRequired` 目标必须恰有一条与 target/action/hash 和完整执行元组匹配的证据，
包括“执行成功但实际零 mutation”的情况。公共 receipt validator 必须通过 resolver 重新读取
证据；不能用序列化引用或冗余证据替代验证。

## 测试与支持状态

仓库内只提供 Fake CAS、Fake Effect 和 Fake evidence，用于机械验证互斥、失败路径和契约。
这些 Fake 证据不能把任何真实 Provider、lease backend 或 Effect backend 升级为
`supported`。真实 Provider 只有完成独立 native validation 后才能改变支持状态。
