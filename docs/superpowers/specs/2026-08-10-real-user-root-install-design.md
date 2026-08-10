# SelfWorkFlow 真实用户目录安装兼容设计

- 日期：2026-08-10
- 状态：用户已批准实施
- 范围：Windows 一键安装器对真实 `.agents` / `.codex` 用户目录的兼容与回滚

## 问题

当前安装器把整个 `AgentsRoot` 和 `CodexRoot` 递归纳入 `doctor` 与 plan/apply
基线哈希。真实 Codex 根目录包含会话、SQLite、可执行文件、插件缓存和 junction，
因此会触发资源上限或 reparse 拒绝；这些内容既不是 SelfWorkFlow 的写入目标，也
不应被安装器读取或绑定。

此外，旧安装可能把 `AgentsRoot/skills/superpowers` 配置为指向用户选择的
Superpowers `skills` 目录的 junction。新安装要求把选定来源固化为版本化快照，
现有 staging 入口只接受不存在的目标，无法安全迁移该兼容 junction。

## 设计

### 1. 托管表面基线

安装 plan 只绑定本次可能写入的精确目标：

- `AgentsRoot/selfworkflow/versions/<version>/<artifact-hash>/**`；
- artifact 中映射到 `AgentsRoot/skills/**` 的 Skill 文件；
- `AgentsRoot/selfworkflow/current.json`；
- `CodexRoot/AGENTS.md`；
- `StateRoot/current-manifest.json`。

每个目标记录 regular-file hash 或 missing 状态。目标路径及其现存父链仍拒绝
reparse；现存目录、超大文件和非法类型仍失败关闭。无关 session、数据库、插件、
日志、缓存和可执行文件不被遍历，也不影响 plan/apply 漂移判断。

artifact、AgentsRoot、CodexRoot 和 StateRoot 必须两两不相等且互不包含；禁止把
状态、备份或 artifact 嵌入另一个受治理根。StateRoot 的当前 manifest 与另外两个
根的精确目标一起参与 plan/apply 及锁内二次基线校验。

`doctor` 同样只报告稳定托管表面：Codex `AGENTS.md`、SelfWorkFlow 版本/指针、
已安装的受管 Skill 和安装状态目录。根目录存在性继续报告，但不再把整个第三方
运行时树冒充成安装器所有权范围。

### 2. 兼容 Superpowers junction 迁移

`source stage` 新增显式迁移参数。只有同时满足以下条件才允许替换：

1. 调用方显式启用兼容 junction 迁移；
2. 目标是 reparse directory；
3. 其解析目标精确等于已检查来源的 `skills` 目录；
4. 备份目标为 StateRoot 下不存在的绝对路径，与目标同卷；其父链无 reparse，
   且不位于 AgentsRoot、CodexRoot、artifact 或选定 Superpowers 源码内。

staging 先把 junction 移到备份位置，再原子发布受信任 Git inventory 的快照。
移动前先在 `StateRoot/source-migrations/superpowers.json` 原子写入 intent，并在
每个阶段持久化状态。staging 自身失败时立即恢复 junction；一键安装后续失败时
只删除 hash 与 intent 匹配的本次快照并恢复 junction。新安装启动时先恢复任何
未 committed 的迁移，因此进程终止、stdout 丢失或 JSON 解析失败也可闭环。成功时
把 intent 标记 committed，并保留备份位置和来源/hash 记录，绝不修改 junction
指向的源码。
任意其他 reparse 或普通未托管目录继续返回 `target-conflict`。

### 3. 一键安装编排

一键安装器在选择并检查 Superpowers 来源后调用增强 staging；保留现有
plan → confirm → apply → verify → doctor 顺序以及 Provider 配置事务。迁移回执进入
日志与 summary，失败路径按相反顺序恢复 Provider、Superpowers 和核心安装事务。
恢复前必须先验证 journal 路径边界、backup junction 和 staged inventory，任何漂移
均停止而不删除目标。迁移 `committed` 是最后一个可能导致整体回滚的关键步骤；其后
Provider 回滚记录的删除只属于可重试清理，失败时保留记录并提示，不得把已经验证且
提交的安装重新带入不完整的跨事务回滚。

## 验证

- RED/GREEN：真实 Codex 根包含超过 8 MiB 的无关文件与无关 junction 时，doctor、
  plan、apply 和 verify 能完成，且无关内容 hash 不变。
- RED/GREEN：托管目标自身为 reparse、超大文件或在 plan 后漂移时仍拒绝。
- RED/GREEN：任意根目录父子嵌套被拒绝；StateRoot current manifest 漂移被拒绝。
- RED/GREEN：只允许指向已选择来源 `skills` 的 junction 迁移；错误目标拒绝。
- RED/GREEN：staging 失败、一键安装后续失败和模拟进程中断恢复原 junction；
  backup 位于源码、reparse 父链或不同卷时拒绝。
- 回归：installer、conformance 和 automated 验证通过。
- 本机验收：使用正式根完成一键安装，验证 manifest、doctor、Superpowers 快照、
  Grill-me 显式安装和 CodeGraph 本地覆盖；不读取或移动 Codex session/数据库。
