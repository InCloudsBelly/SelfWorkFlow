# 恢复与中止

只在诊断、恢复或已确认中止时加载。先读 `openwiki_status` 的 runtime/recovery；不因 `ready=false` 放弃诊断。adapter 的 `recovery_status` 与根定位只读状态，不要求发布 capability；中止和普通更新仍各自检查授权、能力、Review 与 CAS。

按结构化 error/recovery/nextAction 处理。能力未核实先验证，需重连时换连接后再继续。busy 待锁释放并核对既有进度。断连或结果未知先复读原请求。SDK 校验并接收同绑定的完整暂存响应。回执仍缺失时按操作恢复。

- 已知 run 先核对已接受动作和实际下一步，按原绑定的 failure/resume 接口恢复。
- `begin` 尚无 runId 时，确认已就绪且原 Wiki、修订、规则和来源绑定仍有效，以新请求文件原样重放，由后端恢复同绑定的 run。
- `prepare_sources` 尚无清单回执时，在原授权范围重备并重新核验清单。已接受的 run 继续使用原清单。

保留旧请求、回执和 journal，恢复以结构化结果为准。

写恢复要求实现至少 0.1.2。新版可接管尚未交换目录的同一 v4 发布，或恢复已绑定 v5 的部分文件更新；原候选、Review 和 CAS 继续有效。持久 `publish_pending` 时 `ready=false`，可用恢复接口继续同一事务，不能因此另建更新。保留日志交给工具校验，不手动迁移、删除或拼接文件；不能刷新旧连接时报告版本限制。显式旧 provider 的恢复继续使用原协议。

已有个人 run 的 `openwiki_finish` 可在 `ready=false` 时继续向后端请求恢复或完成重放；仍须完整个人/发布 capability，不能用来启动新 run。原 run、事务、回执、恢复状态和 CAS 由后端核验；全局未就绪不能成为无法调用恢复接口的循环前提。`openwiki_begin` 等普通更新要求发布就绪。SDK 发现未就绪或复读到待恢复状态时拦截普通更新，确认恢复后换会话继续。

只有用户明确确认放弃、且已取得现有 `transactionId`、`generation` 和 `bindingHash`，才通过 `abort_external_update` 转发冻结的 external finalize/abort 协议。只传实时 strict schema 存在的字段；不能为 abort 额外补传未定义的 generation 字段。成功中止后正式 Wiki 应保持原样，按实际结果报告。
