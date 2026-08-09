# Windows 一键安装设计

## 目标

在仓库根目录提供 `Install_SelfWorkFlow.bat`，让 Windows 新机器在一次交互流程中完成 Codex 首批完整支持所需的环境检查、运行时构建、事务安装、Superpowers 接入和验证。安装必须可诊断、可重复执行、遇到冲突时停止，并保留已有用户内容。

## 范围

首版只完整配置 Codex；Claude Code、Cursor、OpenCode 和 Copilot 继续由已安装的薄适配器提供兼容入口，不伪称已完成原生安装。默认安装 `core` 运行时。知识扩展和 C7OpenWiki 不在一键安装的默认路径中。

BAT 只负责定位仓库并启动 PowerShell。`scripts/install-selfworkflow.ps1` 负责交互、日志和编排，实际工作流文件发布仍调用现有 Python 事务安装器，避免出现第二套覆盖与回滚逻辑。

## 安装流程

1. 建立 `%LOCALAPPDATA%\SelfWorkFlow\logs\install-<timestamp>` 日志目录，记录阶段、命令退出码和可公开诊断信息；不记录环境变量全集、凭据或 OAuth 数据。
2. 检查 Windows、PowerShell、Git 和 Python 3.11+。复用可用的仓库 `.venv`；否则创建并按锁文件安装依赖。缺少 Python 时说明用途、来源、安装位置和验证方法，获得同意后才可调用 `winget`，否则停止。
3. 检查 Superpowers 候选。优先展示用户显式传入的本地目录，其次检查 Codex 默认目录。展示来源路径、commit、dirty 状态和内容 hash；dirty 源必须获得单独授权。没有候选时询问是否安装官方版本；获准后的 clone 位于 `%LOCALAPPDATA%\SelfWorkFlow\dependencies`，不放进事务 installer 正在 hash 的 `.agents`、`.codex` 或 state 根目录。clone 完成后必须先检查真实 commit 和 inventory hash，再生成最终确认摘要并请求 `APPLY`。拒绝或失败时仅允许安装只读分析能力，任何写任务继续由工作流暂停，不能静默降级。
4. 检查目标位置的 Grill-me。SelfWorkFlow 仓库内置的 `skills/grill-me` 是自包含实现，但它的结束阶段依赖 Superpowers Brainstorming 做独立交叉复审。
5. 若 Grill-me 缺失，提供三种明确结果：安装内置版本（推荐）、选择并校验兼容本地版本、跳过。首版自动发布只支持“内置”或“跳过”；本地第三方版本只做冲突报告，不在未验证时接管。跳过会构建不含 Grill-me Skill 和 Catalog 项的运行时，并记录能力不可用。普通流程继续可用；将来显式请求 Grill-me 时必须暂停并提示安装。
6. 运行只读 doctor，构建确定性运行时，生成安装计划，并展示目标根目录、profile、artifact 文件数量、Grill-me 选择、Superpowers 来源/commit/dirty/inventory hash、冲突和 `planHash`。同样内容写入 `confirmation-summary.json`。
7. 只有用户输入 `APPLY` 后才调用现有 `install apply`。非交互模式必须通过参数显式给出等价确认，不能隐式确认。
8. 调用 `install verify`，随后从已确认且 hash 绑定的 Superpowers Git 源中，仅复制受跟踪的 `skills/**` 文件到临时目录，并在复制前后验证完整 tracked inventory、逐文件验证复制 hash，最后原子发布并写入来源锁。之所以不使用官方示例中的 junction，是因为事务 doctor 有意拒绝 reparse point；junction 会破坏后续 doctor、幂等安装和升级。Python apply 本身对中途异常执行持锁自动恢复；后续任一步失败也会删除本次新建的生成目录，并按事务记录回滚本次 SelfWorkFlow 发布；已有目录和文件不动。
9. 再次运行 doctor。若用户选择配置 CodeGraph，安装器先生成一次性 rollback token，再让 ProviderManager 在同一跨进程锁内原子写入配置及绑定 preimage/postimage 的事务记录。后续失败仅在当前配置仍匹配 postimage 时回滚；并发变化时失败关闭而不覆盖。全部步骤成功后提交并删除 token。最后输出摘要、日志目录、manifest 和必要的重启 Codex 提示。

## 冲突与幂等

- 已由同一 manifest 管理且验证通过的内容返回 `already-installed`。
- 未管理的同名 Skill、非预期的 Superpowers 链接、损坏的 managed block、目标漂移或不完整事务都暂停安装，不覆盖。
- 如果安装器发现已有 Grill-me，只报告其来源和状态；不能仅凭目录存在就把它标为兼容或受支持。
- Superpowers 生成目录只在目标缺失或来源锁与内容 hash 全部匹配时可继续。未管理目录或来源漂移属于冲突；更新源后必须重新执行后续升级流程，不能静默改变已安装技能。
- 安装状态与行为验证状态分开。文件复制成功不等于 Grill-me、Brainstorming 或原生 Agent 行为已经通过测试。

## 日志与退出码

日志至少包含 `install.log`、`doctor-before.json`、`runtime-manifest.json`、`install-plan.json`、`confirmation-summary.json`、`apply-result.json`、`verify-result.json` 和最终 `summary.json`。错误信息使用稳定阶段码：前置条件、环境准备、来源选择、计划冲突、用户取消、应用失败、验证失败和回滚失败分别可定位。控制台失败摘要必须给出日志绝对路径。

## 验收标准

- 双击 BAT 能进入同一 PowerShell 安装流程；带空格和中文的仓库路径可用。
- Grill-me 缺失时一定询问；选择安装后真实文件可发现，选择跳过后运行时和 Catalog 均不包含它。
- 选择跳过后，后续显式 Grill 请求返回 `paused/grill-me-unavailable`，不得注入不存在的 Skill。
- Superpowers 缺失、dirty、冲突和拒绝路径不会被误报为支持。
- 安装计划未确认时不发布工作流文件；失败验证会触发本次变更回滚；Python apply 中途写失败也不得留下部分正式文件。
- Provider 配置失败回滚必须恢复精确 preimage；并发修改后不得陈旧恢复；成功安装不得残留 rollback transaction。
- Superpowers 来源在检查与复制之间变化时不发布；官方 clone 失败的本次半成品可清理并重试。
- 干净安装、重复安装、冲突、跳过 Grill-me、日志生成和失败定位均有自动化测试；真实 Agent 重启和技能触发保留为原生验收，不虚构为自动通过。
