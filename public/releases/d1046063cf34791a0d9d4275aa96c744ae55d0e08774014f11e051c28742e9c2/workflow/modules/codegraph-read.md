# CodeGraph 读取模块

适用入口选用图谱或任务要求图证据时，主 Agent 只查项目唯一图（默认 `.codegraph/`），排除 Topic、会话、Deep 和跨仓库图。按所需关系定向查图，再核源码。配置、文档、日志和精确源码路径直接读。

## 调用与复用

- 优先使用已绑定项目的官方 MCP，传绝对 `projectPath`、文件/符号与 `maxFiles`。已验证能在查询内同步并核验的 UE 入口只调用一次。其他 MCP 首次、换项目或证据失效先预检。有已验证且健康的 watcher 才复用无漂移核验，否则每次新查询先核对。换阶段沿用有效证据。
- MCP 未暴露时只用已安装的 `$env:LOCALAPPDATA\SelfWorkFlow\bin\selfworkflow.cmd`。每次 `provider query --provider-id codegraph --project-root <绝对repo> --query <text>` 自行维护并核验后查询，无需另跑 preflight。入口缺失报缺口，不另装工具或创建 watcher/supervisor。
- 同项目、同输入的成功查询直接复用。分支/HEAD、外部编辑、dirty/未跟踪变化或 stale/pending/degraded 使受影响证据失效，重查影响项，无需提交或暂存。宽查询收窄，输出截断只补缺。

## 核验门禁

- 仅对 `initialized=true`、`indexState=complete` 的已有库预检。执行官方增量 sync 后查状态，未变文件跳过解析。status 可能漏掉 clean checkout。确认 fresh 后仍须实际查询。
- 发布保护覆盖默认目录和 `CODEGRAPH_DIR`。相应 `<索引目录名>.publication.json` / `.publication.lock` 存在、不可读或异常，或文件跟踪表与节点表仅一侧非空，均停止普通访问。禁止自动初始化或重建。
- 新鲜度与覆盖分开。只有 `inputsVerified=true` 且无漂移时可带 `cpp-include-coverage-incomplete` 限制查询。未知旧 provider、输入不可读/未核验/变化均拒绝，UE Build.cs/include 覆盖另核。

遇入口缺失、调用失败、忙碌、发布保护、索引/绑定异常或疑似漏检时才读[异常与恢复](codegraph-recovery.md)。扫描范围、忽略和扩展名按官方配置。只读任务仅允许图索引维护副作用。
