# 恢复与中止

只在诊断、恢复或已确认中止时加载。先读 `openwiki_status` 的 runtime/recovery；不因 `ready=false` 放弃诊断。adapter 的 `recovery_status` 与根定位只读状态，不要求发布 capability；中止和普通更新仍各自检查授权、能力、Review 与 CAS。

按结构化 error/recovery/nextAction 处理，不从自由文本推断成功、不猜 transaction 或删锁/journal。恢复写入时按已选协议加载 update 或 compatibility 引用，并仅使用既有绑定的 failure/resume 接口。

写恢复要求实现至少 0.1.2。新版可接管尚未交换目录的同一 v4 发布，或恢复已绑定 v5 的部分文件更新；原候选、Review 和 CAS 继续有效。持久 `publish_pending` 时 `ready=false`，可用恢复接口继续同一事务，不能因此另建更新。保留日志交给工具校验，不手动迁移、删除或拼接文件；不能刷新旧连接时报告版本限制。显式旧 provider 的恢复继续使用原协议。

已有个人 run 的 `openwiki_finish` 可在 `ready=false` 时继续向后端请求恢复或完成重放；仍须完整个人/发布 capability，不能用来启动新 run。原 run、事务、回执、恢复状态和 CAS 由后端核验；全局未就绪不能成为无法调用恢复接口的循环前提。`openwiki_begin` 等普通更新仍要求发布就绪。

只有用户明确确认放弃、且已取得现有 `transactionId`、`generation` 和 `bindingHash`，才通过 `abort_external_update` 转发冻结的 external finalize/abort 协议。只传实时 strict schema 存在的字段；不能为 abort 额外补传未定义的 generation 字段。成功中止后正式 Wiki 应保持原样，按实际结果报告。
