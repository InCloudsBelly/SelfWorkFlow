# 工作流整体审查与 README 更新

日期：2026-11-02。代码阶段已完成静态审查，README 内容与呈现检查在本报告末尾记录。

## 基线、范围与证据

- 已提交基线：`da26e5653dad91def347bd44c30a834ca747fe14`。另将开始时已有的个人 Wiki 运行时及质量文本修改纳入只读快照，区分草稿与已提交代码。
- 本次任务规则绑定：`e7e4a2b8cf271f8dddde77fb9383b3bd651d16e38e9058b3f5c2fe83542f475c`；用户要求整体审查并按 knowledge 标准更新 README。
- 审查单元是第一方组件、入口调用链及关键正常 / 失败 / 边界 / 恢复路径。76 个 Python 模块完成入口、调用与契约盘点及对应主链审读，不声称逐行穷举。第一方 TS 集成检查对应主链；第三方固定依赖只审来源锁、接口和命令边界。
- 本地证据位于 `out/workflow-overall-review-20261102/`：577 份输入快照、文件 hash、开始时 dirty 清单及最小观察记录。该目录包含任务材料，不随 README 提交。
- 官方已安装桥接实际执行 CodeGraph query，返回 `provider-operation-failed:codegraph-rebuild-required-preserving-existing-index`。原索引保留；没有初始化或重建。后续结论来自直接源码与手工调用追踪，图证据保持未核实。
- 一个独立 Reviewer 在相同材料上检查四个轴并补查相邻分支；未运行测试、provider 或修改文件。主 Agent 查询了真实 CLI 帮助，并在完全自有的临时目录中观察 junction 枚举行为；未执行清理删除或真实安装。

## 已确认问题

### P1：旧代次清理未阻止目录 junction 越界

定位：[work_artifacts.py:714–741](../../src/selfworkflow/work_artifacts.py#L714)。

有合法 Manifest 且 `contentGeneration >= 3` 时，旧 generation 会进入 `reconcile` 的清理范围。枚举只检查子目录 `is_dir()` 和叶子 `is_symlink()`；apply 同样只复核叶子和内容 hash，未执行完整祖先目录的 reparse 检查。

将符合年龄条件的 generation 目录或其子目录换成 junction 后，目标树的普通文件会被列入删除计划；后续 `path.unlink()` 将沿 junction 操作目标文件。Windows 安全样本已确认 `is_junction=true`、`is_symlink=false`，枚举路径与临时外部目标 `samefile=true`。两个树都由本任务创建，目标文件完好，**没有执行删除**。

建议：枚举与 apply 均核对真实祖先目录、文件身份、托管边界及 CAS / 锁状态；覆盖 generation 本身、嵌套 junction 和检查后替换的情况。修复前避免执行 `artifact reconcile` apply。

### P2：Review 严重级别别名绕过本地阻塞判断

定位：[严重级别标准化](../../src/selfworkflow/work_artifacts.py#L446)、[阻塞判断](../../src/selfworkflow/work_artifacts.py#L479)。

输入校验接受 `blocker/high/medium` 并标准化为 Critical / Important，但 transition 保存、判断的是原始 findings。`_review_has_blocking` 只识别 `critical/important`，因此这些合法别名的 open finding 可被误认为无阻塞，并继续到 `local-final`。

建议：判定和保存统一使用标准化 receipt / findings；补齐三种别名在普通 Review、post-Review 和验证入口中的一致性覆盖。这里影响的是可选本地工作产物状态，不等于默认 Skill 的所有审查都被绕过。

### P2：普通契约 Review 输入被强制绑定 Grill 完成凭据

定位：[review_inputs.py:86–143](../../src/selfworkflow/v3/review_inputs.py#L86)、[review_dispatch.py:352](../../src/selfworkflow/v3/review_dispatch.py#L352)。

普通契约代码 / 计划 Review 要求封闭的 `VerifiedReviewInput`，唯一公开发行入口却强制读取、验证 Grill completion attestation。未显式选择 Grill 的 Host 无法诚实构造普通 Review 输入，只能额外 Grill 或停住，与普通 Review 的按需规则不一致。

建议：分离通用已验证输入和 post-Grill 附加约束，并覆盖无 Grill 的正常 Review。默认 Skill 通过宿主原生 SubAgent 执行的独立审查不经过这条契约 API。

### P2：契约 runner 续期后没有交回可释放的最新租约

定位：[runner.py:248](../../src/selfworkflow/v3/runner.py#L248)、[project_lease.py:295–321](../../src/selfworkflow/v3/project_lease.py#L295)。

`guard.check()` 的 heartbeat 更新持久化 `leaseHash/storeVersion`，只将最新租约保存在 guard 内。runner 不释放或返回这个最新句柄。标准 `acquire → run → finally release(原 lease)` 在执行产生 heartbeat 后失败，后续同项目操作可能被遗留租约阻塞。

建议：明确租约归属，在 finally 释放当前租约，或公开返回 / 刷新可续接句柄。此问题针对显式契约 Host 使用公共 runner API 的路径；CLI ProviderManager 的 query / ensure 不调用该 runner。

### P2：损坏或空安装清单被报告为验证通过

定位：[installer.py:1117–1136](../../src/selfworkflow/installer.py#L1117)。

`verify_install` 对 JSON 解析后的对象不做必需字段、身份和结构校验，使用 `manifest.get('operations', [])`。`{}`、缺 operations 或空表可跳过逐文件核验，返回 `status=verified`，CLI 随之退出 0。

建议：先验证完整清单 schema、版本、安装身份与非空托管操作表，再做文件和解释器身份检查。本结论是可达分支的静态推导，未对真实安装运行损坏清单测试。

### P2：Python 版本声明与 Wiki API 使用不一致

定位：[pyproject.toml:10](../../pyproject.toml#L10)、[wiki_module.py:26](../../src/selfworkflow/wiki_module.py#L26)。

包声明支持 `Python >= 3.11`，安装器也保留 3.11 下限；Wiki 路径却无保护调用 `Path.is_junction()`。该 API [在 Python 3.12 加入](https://docs.python.org/3.12/library/pathlib.html#pathlib.Path.is_junction)，因此 3.11 的 Wiki inspect / register / doctor 会遇到 `AttributeError`。

建议：提供兼容的 reparse 检测，或统一包声明、安装器与文档的最低版本。本次没有切换全局 Python 或执行 3.11 环境测试；README 对当前可选 Wiki 路径明确要求 3.12 以上。

### P2：干净 clone 的固定依赖准备清单不闭合

定位：[submodule_profiles.py:17–20](../../src/selfworkflow/v3/submodule_profiles.py#L17)、[adapters.py:130](../../src/selfworkflow/adapters.py#L130)、[固定资源复制](../../src/selfworkflow/adapters.py#L482)。

普通依赖 profile 仅初始化 TEA、Matt、Ponytail、Anthropic、UI、Composio 和 Obsidian 来源，未列入 `scientific-agent-skills`。三个 Runtime profile 的构建却都会通过 `_copy_community_sources` 强制读取该来源的固定资源；安装脚本先执行同一准备清单，再进入 build。因此干净 clone 缺少数学来源时会构建失败，本机已有 submodule 会掩盖问题。

建议：将数学来源加入完整的固定依赖准备闭包，并检查三个 Runtime profile 与文档生成路径。本轮只改 README，提供 `git submodule update --init -- dependencies/upstream/scientific-agent-skills` 的固定版本绕行及首次维护准备步骤。本结论由调用链和来源锁确认，未运行联网安装或修改生产代码。

### P2：原生 helper 与 TS 桥接协议不兼容

定位：[TS 启动与解析](../../extensions/knowledge/selfopenwiki/self-openwiki/mcp-server/src/win32-helper.ts#L264)、[原生参数与协议](../../extensions/knowledge/selfopenwiki/self-openwiki/win32-helper/Program.cs#L33)。

TS 桥接以空参数启动同一路径的 exe，发送按行 JSON 的 `operation=inspect-path/inspect-copy/secure-path`，并期待含 `ok/version` 等字段的响应。构建脚本实际从该 C# 工程产出 exe；其入口要求 `--root`，使用四字节长度帧和 `op=handshake/read/write/...` 协议。缺少参数时先退出，即使仅补参数，两端的帧格式、操作与响应字段仍不一致。

可达条件是相关能力已验证后进入完整 bootstrap，调用 `securePrivatePath` 时无法完成。全未验证时的 `MinimalStatusRuntime`、Viewer 和普通 Skill 不走该完整初始化，不应外推为它们均不可用。该不兼容在已提交的 source 中已经存在，不能归因于开始时的 dirty 草稿。

建议：统一可执行协议及其契约，联测安全路径、来源检查和稳定复制能力，不只补启动参数。本次未构建、运行 helper，也未覆盖现有二进制；README 在完整 MCP 接入步骤之前披露该阻塞。

## 覆盖与未确认项

| 组件 | 覆盖的主要路径与结论 |
| --- | --- |
| 默认 Skill | 入口、绑定、Light/Full/Deep、按操作加载、同版复用、子任务和角色交接；与可选 Runtime 区分 |
| V2 / V3 | catalog / schema、请求归一化、选择、依赖与冲突、计划、账本重试和阶段约束 |
| 审批与证据 | provider 审批、来源与项目身份、execution / Review receipt、Host / completion 主链 |
| CodeGraph | lifecycle、静态绑定、query / maintain、锁 / publication 保护、固定 UE provider 命令边界；图实际查询未通过 |
| 安装与接入 | 根 bat → PowerShell、profile、计划 / CAS / 发布 / 回滚、managed surfaces、Host Python 身份及凭据配置边界 |
| 规则发布 | source collection、引用改写、不可变 release、Skill 入口生成与保留版本校验 |
| 可选能力 | TEA / Ponytail / C++ 等触发与适配、来源锁、固定来源准备闭包、Git policy / eval 边界 |
| 工作产物 | generation、Review / post-Review / Verify、知识包与 reconcile；已确认上面的两项状态 / 路径问题 |
| Wiki | Python 源区 / 注册与 TS 来源、敏感策略、动态 capability、权限、凭据 / OAuth、query / update / Review、Claims / 标记 / CAS 发布与恢复主链，以及 Win32 helper 协议 / 文件身份边界 |

未将以下候选写成缺陷：UE provider 的 `index` 实际拒绝覆盖已有索引，不能据 adapter 参数就断言会破坏旧库；统一 `explore` 入口不意味着回显 `query_kind` 一定违反接口；源码出现 `.env` 等敏感输入时硬拒绝是明确策略。独立审查同时证伪了弱引用缓存泄漏和拒绝 Review 被直接放行的猜测。

开始时已有的个人 Wiki 草稿增量未发现可确认回归；它们仍未经过本任务的运行验证。第三方源码、所有宿主与真实外部服务没有被整库 / 端到端验证。本次未编译 UE、清缓存、重建索引、运行真实安装或向 Wiki 写入。

Win32 helper 的路径段拒绝、逐级 reparse 检查、句柄和卷 / 文件身份检查等按静态实现核对；没有进行并发路径替换或完整 no-follow 安全证明。README 的 register / doctor 命令也核对了根 bat 到冻结 Host 的前置分派，不因底层 JS 缺分支误报。

## 按需加载与紧凑性

静态统计统一为 LF 下的 Unicode 字符数，按文件去重；不是模型 token，不含宿主注入、业务源码或工具输出：

| 路径 | 字符数 | 计入的规则 |
| --- | --- | --- |
| 自包含 Skill 冷入口 | 1,405 | `skills/selfworkflow/SKILL.md` |
| Deep 维护示例链 | 6,338 | 入口、Deep、维护方法、操作质量、Review |
| Deep 跨文件代码审查示例链 | 7,227 | 入口、Deep、代码方法、图谱读取、Review |

这些是命中条件后的示例，不要求每个任务加载所有文件。普通问答 / 精确配置查询不加载维护或知识评分链；Wiki 读取不默认加载 Writer、源码探索或评分；工作流文本变更才走维护紧凑性审查。普通 Skill 的 TEA / Grill 明确按需，契约 Review 的 Grill 耦合例外已列为缺陷。

本轮只修改 README、配图和本报告，没有修改 Skill 入口、模块路由或专业方法。README 从 41,031 字符重组为约一万字符；这是说明文档整理，不代表 token 或触发率实测。当前已有随包 Skill 的 `skill check` 实际返回 `verified`，revision 与任务绑定一致；没有为 README 重发其他对话的规则草稿。

## README 内容与呈现评价

候选主用途：帮助新用户完成安装、确认功能与边界，并定位可选部署和维护入口。采用绑定版本 v7 的十二项 H/V/A/E 标准及正文契约，不触发 Wiki 生命周期或 CAS 发布。

同一 Reviewer 已集中核对安装、更新、能力加载、版本 / 授权 / 交接、Runtime、CodeGraph、Wiki、维护验证及来源 / 限制。已接触源码与规范，不冒称盲评；与本页职责无关的数学推导、UE 渲染和内存布局检查点有据排除，没有豁免任何整项。

| 指标 | 分数 | 主要观察 |
| --- | --- | --- |
| H1 概念与范围 | 5 | 默认 Skill、可选 Runtime 与契约 Host 的用途和边界清楚 |
| H2 因果与取舍 | 5 | 解释绑定、按需加载、并行与正式队列、失败隔离的关系 |
| H3 阅读路径 | 5 | 新用户先安装 / 启用，再选功能；高级部署和历史材料后置 |
| V1 图型与覆盖 | 5 | 流程图解释默认推进，表格承担能力 / 前提对照 |
| V2 图文一致 | 5 | PNG、可编辑 SVG 与 Light / 知识可选条件一致 |
| V3 呈现 | null / unverified | 本地图文与宽度检查已有证据，GitHub 实际字体及最终呈现未核 |
| A1 契约 | 5 | 路径、版本身份、计划 hash、状态、产物和前置要求可定位 |
| A2 边界 | 5 | 普通 / 契约、源码构建 / 宿主注册 / 服务就绪，以及未修问题分开 |
| A3 实施与复现 | 4 | 完成静态搭建 / 失败 / 恢复走查，未进行真实安装、注册或完整 MCP 迁移复现 |
| A4 语义抽取 | 5 | 标题、条件、命令、占位输入和停止位置明确；代码块保持原文 |
| E1 来源 | 5 | 以本次代码 / 规则、锁和实际帮助为依据，区分静态、图和运行证据 |
| E2 组织与维护 | 5 | 当前规则优先；移除矛盾旧入口，链接与审查记录对应 |

维度结果：**H=100，A=94.285714，E=100；V=null，总分=null**。十二项全部适用，已评分 11/12（91.6667%），适用权重 100%、已评分权重 95%；维度分母仍为 30/20/35/15。不将未核的 V3 权重删除或重新归一化，**不报告达到个人 Wiki 的总分 95 门槛**。

主要证据共用六组：安装与更新 / 在途绑定；模式与按需边界；Runtime / Viewer / MCP 三类状态及已知阻塞；固定来源与维护闭包；流程图与无图说明；来源 / 链接 / 实际呈现。修订只复核影响项，复用既有代码审查和未变化的图证据。

本地预览采用 bundled marked 与 headless Chromium，检查 1000 / 390 两种宽度：无页面横向溢出，11 个代码块原文保持一致，3 张表格使用受控横向滚动。本地相对链接 / 锚点已逐个检查。图内 8 个文本节点均在边界内，实际字体为 FangSong 与 Times New Roman；PNG 和 SVG 的 hash 与记录绑定。GitHub 目标字体和最终页面仍未核实，本地预览不作为其通过证据。

本轮没有运行完整测试套件、真实安装、原生 helper 或 Wiki 发布；产品行为的发现保持静态审查性质。代码问题未修复，文档关键内容缺口已关闭；呈现未核项如上保留。
