# 文档入口与新 Agent 接入验收（2026-10-20）

普通接入的源码、发布包与两种真实宿主冷启动已验证。默认 Adapter 仅保留加载要求和固定入口；规则更新由维护者发布文档，新任务重新读取同一入口，不要求逐宿主重装。

## 发布身份与复现

- 固定入口：[public/WORKFLOW.md](../../public/WORKFLOW.md)。
- 本次发布 revision：`635d1b4861672e1f59e73d40ff66c81cfca7b1e807b002d2b5f781567f3531e5`，418 份文档与静态资料。
- 验证功能候选 Git tree：`71af84ac5382185ac6cab945ce0121ac0ba08cd0`；本报告及设计文档中的验收状态说明随后补入，不改变功能输入。
- 从干净候选 checkout 校验发布目录的内容身份与引用闭包，再从固定来源重发布，得到完全相同的 revision；源码树未被发布器修改。
- 旧版本目录保留，入口最后切换；当前任务、子任务和独立 Reviewer 继续使用最初绑定版本。两个最终冷启动都只获知固定入口，没有预先提供目标 revision 或模板位置。

## 真实宿主结果

每次使用新的空白工作目录、独立会话及原有账户和模型配置，禁用额外 MCP；不向消费者安装 SelfWorkflow 或注册原生 Skill。任务仅要求读取文档、以文本生成最小 Adapter，并解释更新后的任务版本规则。宿主自身运行环境沿用既有部署。

| 宿主 | 结果 | 实际证据 |
| --- | --- | --- |
| MyFlicker 0.3.30 | 通过，74.19 秒 | 仅调用 6 次 `read`；读到固定入口、版本规则、文档约定、接入指南、模板和 Light；Adapter 仅含固定入口，未用能力标为未验证 |
| Codex CLI 0.163.0 | 通过，83.34 秒 | read-only、ephemeral 会话；7 次 `Get-Content` 全部退出 0，覆盖同版必读文档及 Review 模块；返回最小 Adapter 和正确任务绑定规则 |
| Claude Code 2.1.152 | 环境阻塞，未验证 | 读取文档前即 `Unable to connect to API (ConnectionRefused)`；未修改连接或账户配置 |
| DSH 0.2.1-rc.2 | 环境阻塞，未验证 | `MISSING_CREDENTIAL`，当前 `deepseek-official` 路由无凭据；未写入凭据或修改 profile |

最终两次通过均核对了工具轨迹与最终 JSON，不能只凭进程退出 0 判断。轨迹中没有写文件、安装、修改宿主配置或调用外部服务的工具动作；生成的 Adapter 未保存。二者均说明进行中的任务继续沿用原 revision/documentRoot，新顶层任务才选择入口指向的新版本。

这验证了普通文档接入与最小 Adapter，不证明任意模型均遵循规则，也不证明 Full/Deep 独立 Review、所有专业方法、远程 URL、离线重新分发或所有工具连接已在这些宿主实测。

## 实测发现与修复

1. Codex 首轮能读固定入口，却被目标版本的 Windows DACL 拒绝。原因是直接移动私有临时目录会保留私有 ACL。发布器改为在目标 `releases` 下创建临时公开目录，仅复制生成文档后原子改名，继承目标目录已有权限；不扩大父目录权限、不改旧版本。Windows 权限回归先失败，修复后通过；中断复制测试证明旧入口保持且本次残留被清理。
2. MyFlicker 中间轮次曾错拼模板路径、漏读模式，并把本次禁止操作列为可用。指南补充路径解析、模式实际读取和能力状态边界；默认模板缩为两行，额外工具接线按实际需要填写。保留失败记录，以最终同版重测作为通过依据。

个人 Codex 受管入口在连续发布后 SHA256 仍为 `af3324bc5d489c13d34dc0b254c0fdcb660378c5b8060fb94e18b7201157ff6c`，未因规则更新再次改写。

## 回归与审查

分批覆盖 **124 个独立用例**。兼容回归先运行 122 项，其中 121 项通过，1 项因隔离子模块的换行字节与既有 lock 不符失败；校准测试副本后，24 项受影响用例全部通过，覆盖原来的文档/迁移测试、两项新增发布回归及 Matt 来源锁定。其余 100 项已通过且相关源码/测试输入未变。未把失败的 122 项运行记为全绿。

隔离副本的全部子模块固定在候选 gitlink，不复用用户的 dirty 文件树。换行校准仅复制原干净子模块中与 lock hash 相符的字节，并验证子模块 Git tree 与 HEAD 一致；用户目录与 lock 未修改。最终候选与受影响测试通过时的 `src/`、`tests/` 完全一致，此后仅改接入文档并重新核验发布闭包和实际宿主。

覆盖模块：`test_documents`、`test_document_link`、`test_plan`、`test_apply`、`test_adapters`（unit/conformance）、`test_one_click`、`test_workflow_compression`、`test_matt_skills_foundation`、`v3.test_codegraph_lifecycle`。文档与迁移专项含更新传播、旧版保留、引用拒绝、发布锁、失败清理、权限继承、受管内容保护与回滚。

同一独立 Reviewer 增量复审源码、schema/catalog 绑定和最终两份接入文档，未遗留 Critical/Important；测试和工具执行由主 Agent 完成。

自有源码范围的 `git diff --check` 通过。全范围检查另有 148 处导出文档空白提示，分布于两个版本中的方法索引、TEA 许可与 Composio 来源正文；记为 Minor，保留来源文本与已验证的不可变版本字节，没有把该检查报告为全绿。

## 图状态与提交范围

主工作区本批增量 `provider sync` 仍返回 `codegraph-index-not-fresh`；保留旧库，未执行 rebuild/index --force 或删除缓存。Git worktree 的状态实际共享原库，因此没有借其缺少本地目录重新初始化。

另建具有独立 `.git` 的干净源码副本，官方 status 确认数据库确实缺失后初始化得到 fresh，再对最终功能候选执行一次官方增量 sync，结果仍为 fresh、`worktreeMismatch=false`。该证据绑定隔离候选，不宣称主工作区旧库已修好。临时 clone 的 Windows 长路径及子模块换行校准只用于完整还原固定输入。

提交包含工作流、兼容 Adapter、发布器/迁移与对应测试、导出方法的必要文档及公共版本；已有 Wiki Viewer 实现和个人配置修改留在本地。原始宿主日志、账户配置、临时索引、测试副本及 `.codegraph` 不进入提交。
