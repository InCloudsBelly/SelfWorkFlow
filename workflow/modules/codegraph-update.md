# CodeGraph 更新模块

源码批次确有索引内变化时，主 Agent 汇总路径，在后续结构化读取或交付前调用一次 `provider sync --project-root <绝对repo> --changed-path <path>`。重命名传新旧路径，含部分失败、中止、回滚或撤回留下的变化。UE 后端以路径为提示，从已验证范围识别实际变更。

用该调用内置的发布保护、忙碌与库完整性门禁。仅对已初始化的完整库增量 sync，核验返回的 fresh。watcher 已处理的未变文件由 SDK 跳过，updated 只表示执行了维护。失败或仍 stale 按[异常与恢复](codegraph-recovery.md)，和读取共用重试预算。

计划、文档/日志、无变化或索引外文件跳过。用户编辑和 Git 操作由[读取](codegraph-read.md)核对漂移，fresh 后仅复查受影响结论。

`.codegraph/` 是再生缓存，勿 add/commit/push 或删库代替同步。旧 `<repo>\graft\` 仅按明确清理要求删除。进程、锁和并发沿官方 watcher/daemon。
