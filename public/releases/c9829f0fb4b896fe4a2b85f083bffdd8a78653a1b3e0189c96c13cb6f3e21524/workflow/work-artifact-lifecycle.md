# 项目本地工作文档生命周期

这是 SelfWorkflow 的可选项目级扩展，不新增 V3 生命周期阶段，也不修改
Pipeline、PlanGraph、RunLedger、Review dispatch、Provider 或知识后端。

## 适用条件

须显式启用本扩展，并满足以下任一条件：任务强度为 `Full`/`Deep`；或形成至少两份正式工作文档（设计、
测试设计、实施计划、整体 Review 摘要）时启用。`Light` 单份文档不创建正式
生命周期记录。

## 入口与存储

- 只通过 `selfworkflow artifact transition` 和 `selfworkflow artifact reconcile`
  访问；首版只接收有界内联 UTF-8 文档内容。
- 记录根为项目 `./selfworkflow/`，通过 Git common `info/exclude` 的精确
  `/selfworkflow/` 条目隔离；不改 `.gitignore`、Git index、commit 或 push。
- 已跟踪/已暂存、reparse/junction、路径逃逸、任意本地 source descriptor 和
  已知敏感内容必须 fail-closed。来源只保存有界 `sourceId`、`contentHash`、
  `verificationStatus` 元数据。

## 生命周期与证据

```text
documents-captured/revised
  -> review-recorded
  -> post-review-recorded
  -> verification-recorded
  -> local-final
  -> optional knowledge-published
  -> task-completed
```

每次写入绑定 content generation、state revision、Manifest hash 和 operation
nonce；同 nonce 同 payload 只重放原结果，payload 漂移拒绝。Review 的
Critical/Important finding 保持 candidate/current 并阻止 Verify；修订产生新
generation，旧 Review 失效。只有 fresh Verify 才能进入 `local-final`；知识后端
失败保持 `local-final`，不得伪造发布。

`reconcile --dry-run` 零写并返回 plan hash；`apply` 必须携带同一 plan hash，
平台能力不足时返回稳定失败，不静默降级。当前代和上一代正文保留；旧文档只
在满足引用、hash、Git 和文件身份条件后清理。知识包仅包含最终文档、必要来源
元数据、Manifest/hash 和残余风险，不包含废稿、凭据或私有推理。
