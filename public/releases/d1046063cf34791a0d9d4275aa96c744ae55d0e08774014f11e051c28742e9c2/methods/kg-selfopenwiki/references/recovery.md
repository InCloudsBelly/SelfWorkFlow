# 恢复与中止

诊断先读 `openwiki_status` 的 runtime/recovery。只读的 `recovery_status` 和根定位在 `ready=false` 时仍可用。中止与普通更新各守协议门禁。

按结构化 error/recovery/nextAction 行动。能力未核实先验证，需重连先换连接。busy 等锁释放并核既有进度。断连或结果未知时，SDK 先复读原请求并校验同绑定的完整暂存响应。回执仍缺失时按操作恢复。

- 已知 run 先核对已接受动作和实际下一步，按原绑定的 failure/resume 接口恢复。
- `begin` 无 runId 时，核对就绪及原 Wiki、修订、规则和来源绑定，用新请求文件原样重放，由后端恢复同绑定 run。
- `prepare_sources` 无清单回执时，在原授权内重备并核验清单。已接受的 run 沿用原清单。

保留旧请求、回执和 journal，恢复以结构化结果为准。

写恢复要求实现 ≥0.1.2。可接管尚未交换目录的同一 v4 发布，或恢复已绑定 v5 的部分更新。沿用原候选、Review 与 CAS。持久 `publish_pending` 时 `ready=false`，仅恢复同一事务。保留日志交给工具，勿手动迁移、删除或拼接文件。旧连接无法刷新时报版本限制，显式旧 provider 沿原协议。

已有个人 run 的 `openwiki_finish` 在 `ready=false` 时仍可请求恢复或完成重放。须完整个人/发布 capability，由后端核 run、事务、回执、恢复状态和 CAS。普通更新要求发布就绪，SDK 发现未就绪或复读到待恢复状态即拦截，确认恢复后换会话。

用户明确放弃且已有 `transactionId`、`generation` 和 `bindingHash` 时，才通过 `abort_external_update` 转发冻结的 external finalize/abort 协议。只传实时 strict schema 已定义字段，按实际结果核验正式 Wiki 原样。
