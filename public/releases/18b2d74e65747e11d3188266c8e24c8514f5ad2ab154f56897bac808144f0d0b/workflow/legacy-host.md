# 显式契约与旧安装 Host

仅显式 contract-managed task，或 conforming Host 已按契约承接当前任务时读取；普通通用 Skill/文档任务不使用本页启动。

- 旧安装兼容入口从 bootstrap snapshot 根在工具内解析 `artifact-manifest.json`，只回传 `version/profile/runtimeHash` 及所需 `path/sha256`，不先输出全清单再截断。缺失、不可读或 hash 漂移标 `unverified`，不找历史安装副本。
- 显式契约遵循 [core](core.md) 及任务实际要求的 package/receipt/runner，保留防伪与完成门禁；不能用普通 agent-policy 的等效方式冒充契约通过。
- 已有能力或 profile 名称不自动激活本模式。当前 Host 无法满足必要门禁时只阻塞该模式，如实报告缺口；不虚构独立上下文、工具执行或回执。
