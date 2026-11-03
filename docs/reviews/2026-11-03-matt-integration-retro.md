# Matt 接入与三会话复盘

日期：2026-11-03（Asia/Shanghai）。范围：仓库工作流接入与指定三会话的效率复盘，不重新审查 UE 业务代码，也不修改这些会话或其工作区。

## 接入结果与加载边界

已核对上游远端 HEAD：`4ae2317ddb22b046e26455e4f9c9b3aaaf62212d`，与现有 Matt 子模块/锁一致，不升级其他上游。命令及返回值留在 `out/matt-integration-retro-20261103/upstream-check.json`。原 `implement-spec` 已有 V2/V3 契约入口；本轮补齐日常文档路由、压缩适配器，并接入固定来源的 `pr`、`retro`。

- `implement-spec`：显式要求按 spec 与至少两张依赖 tickets 整体实施才触发；校验 DAG、授权、独立能力后推进 frontier。无冲突才并行，共享文件和集成串行；复用主协调者与最终一个 Reviewer，不逐票新增 merger/全套审查。
- `pr`：仅准备/更新 PR 正文或已请求创建 PR 时加载，复用已有 diff、验证、回滚和影响范围。模板优先；不为正文重跑构建、测试或审查，不强制图示。
- `retro`：只在用户请求会话复盘时加载，检查导航、规则、工具、审查、验证与确认往返；一次汇总有证据的改进。不会在每次交付后自动运行。

三个入口沿现有阶段/绑定；正文准备不自动授予远端副作用。普通文档模式由入口和方法索引路由；PR/retro 不增加 V2/V3 Host 调度器或契约 slot。自包含包同步不等于全局安装，在途任务继续沿旧 revision；所审历史分别引用 `0ad1061f3fa1…`、`0b34e4a4be96…`，不能把当前规则的修订追溯算成当时已生效。

## 证据与计量边界

通过 `codex.read_thread` 分页读完三个主会话的可用历史。证据保存在 `out/matt-integration-retro-20261103/<thread-id>.json`，统计在同目录 `metrics.json`；JSON 保留 turn/event ID、命令、必要输出和会话消息，便于复核。

| 会话 | 主会话轮次 | 命令事件 | 命令输出原始字符量 | 独立子会话数 |
| --- | ---: | ---: | ---: | ---: |
| [Locate 嵌套 ChildActor 碰撞预设检查](codex://threads/01a19ba0-ddbc-7050-84fd-f9fee4323ff2) | 35 | 908 | 4,207,248 | 1 |
| [审查运行时算法性能开销](codex://threads/01a19f81-5e56-7783-b2f5-97b3c77767f4) | 11 | 315 | 1,464,753 | 1 |
| [更新 CodeGraph](codex://threads/01a19f53-7b88-7732-a56a-ca072bed9333) | 13 | 345 | 1,470,232 | 3 |

以上是主会话返回的事件，未遍历子会话内部日志；子会话数按被引用的 thread ID 去重，不能把 wait/交互次数当成创建次数。第一、第三个会话首读时有在途轮，因此本报告覆盖已读取历史快照，不宣称业务任务完成。

输出字符量取 API 的 `originalChars`（无此字段时取返回文本长度），不是实际送入模型或计费 token。为节省本轮上下文，API 单项仅保留 1200/1600 字符；其 `truncated` 是本次取证裁剪，不能据此统计原会话溢出。完成轮累计时长含等待与用户回复，也不等于纯计算耗时。没有 usage、GPU/编译性能实测或模型 A/B，不报告精确 token、费用或提速比例。调用数大只说明候选开销，不能单独证明浪费。

## 发现与建议

### P1：审查覆盖过早宣布完成，导致追加审查与返工

ChildActor 会话在 turn `01a19f92-3ac9-7ed2-bd46-caa9f87c3daf` 报告“十个修改文件及对应 Builder 链路均已覆盖”；后续 `01a1a00a-9f58-7ab0-b72e-a88b184cc102` 又报告默认碰撞注册失败与诊断显示两项 P2。用户在 `01a1a013-ffa7-7981-88d3-1f7294b2b95e` 明确要求一次审完、不要持续追加。再后面的 `01a1a036-f34f-7252-9ea1-f3a9b3b8becc` 承认“上轮将这一项判为关闭过早”，指出复制后名称回退的遗漏分支。

这支持“存在覆盖/关闭判断失误”，但不证明所有晚发现都原先可见；有些来自中间修复。每项后续发现应区分原漏检、修复引入和新前提，不能把它们混作又一轮全审。最窄改进由既有 Reviewer 维护同一覆盖记录：围绕 Editor 检查→报告授权→复制/重建→Builder 消费者的不变量，先查同根失败分支，再关单。用户要求再审时继续履行，已经有效的覆盖只复核影响项。

当前 `workflow/modules/review.md` 已要求完整覆盖、相邻输入类别/消费者、同根合并及变化失效复核。本轮不再增加 Reviewer 或重复写一套规则。证据表明 ChildActor 和算法会话各只复用了一个独立 Reviewer，这部分设计应保留；不能把循环问题归咎于反复新建 Reviewer。

### P2：边界事实确认晚，审查投入到产品不使用的路径

算法会话 `01a19fd2-1327-7513-97cd-cfa51c4b4c9a` 报告两项多视图 P2；用户随后确认单主视角、两个 Actor 不重叠，`01a1a00b-5ded-7033-a5cf-90c4a10df0fa` 明确撤回为范围外。PC 仅 D3D12 也是后段才确认，影响 FP16 写入边界判断。

改进由审查 owner 在首次范围记录中合并目标平台/RHI、视图数量、Actor 覆盖等真正影响结论的产品事实。先查既有上下文；确实未知才一次问关键项，其他分支标条件风险，不先升级为确定缺陷。不能把用户新提供的边界倒推为 Agent 事先已知，也不应为排除场景增加生产状态。

CodeGraph 会话先围绕编译数据库、Build.cs、include 完整性展开，用户在 `01a1a00c-b00b-7cf2-b535-b2788ddac2ab`、`01a1a00e-da2b-7e93-be04-62415142b311` 澄清只要项目真实代码的静态关系、不需要过度索引标准库。这里应尽早区分静态项目关系与精确构建环境覆盖，避免为非目标补 UBT/UHT 链。

### P2：宽输出和重复规则加载增加上下文压力

算法首轮两个整段 diff 输出分别为 48,264 和 45,158 字符；ChildActor 单次混合规则搜索/整文件读取达到 54,926 字符，另一批 Builder 与规则读取达到 52,551 字符。CodeGraph 的 `codegraph_ue/AGENTS.md` 单次原始输出 38,235 字符，同一在途轮重复出现。可在证据 JSON 按命令与 `originalChars` 定位。

最窄改进由主 Agent 执行：先文件/符号/路径摘要，完整范围仍要审，但长 diff 分职责切片；规则正文完整且版本不变时复用，压缩后只补丢失段。并行独立查询要共享外层输出预算，不能每个子调用各给满预算。对必须阅读的项目规则保留完整覆盖，不能为省 token 漏掉强约束；长期可将大 AGENTS.md 留导航，专项内容放按需引用。

当前仓库入口已具备同版复用、源码/绑定版限定、工具内投影和总预算规则；本轮延续这些规则，不把同义提醒扩散到所有 Skill。CodeGraph 仓库正在其他会话中修改，本轮只给建议，不并发改其 AGENTS.md。

### P2：大范围索引与后台可见性形成等待瓶颈

CodeGraph 会话从写锁 busy、44 个新增文件，到 92,544 文件、6,917 条待处理引用，后续才到 fresh。用户在 `01a19f6a-0270-7fc2-a1b2-9b891792b8ce` 指出任务完全在后台、主对话没有持续关注；助手也承认过早结束。

改进由图谱 owner/主 Agent 分别承担：索引范围按已确认 UE 源码/插件策略收窄；已有后台任务用单一进度来源持续跟踪，有意义的阶段变化才汇报。锁占用不竞争维护，复用既有忙碌预算；显式更新任务继续跟踪至完成/明确阻塞，普通代码任务只标图证据缺口并继续独立工作。fresh 与覆盖分开，不能为了消除全局告警启动额外全量解析。

会话后期已经确认范围并开始修改 `codegraph_ue`，其业务完成/规模收益不在本轮可验证范围；不以本报告重复启动索引。当前 SelfWorkflow 的读取/写后模块已有共享忙碌预算和禁止自动重建边界。

### P3：访谈可以更早分组，但显式 grilling 不属于误触发

CodeGraph 中用户明确要求 grilling；历史含 35 个结构化回答条目（包括确认、补问等，并非 35 个独立问题编号），问题编号推进到 Q31。其范围确认有实际价值，不能因为次数多就判整个访谈浪费。

可优化的是：Q1 纳入 Client 时，项目事实与用户目标还没先确认；部分默认实现细节本可合并为带建议值的方案，只询问会改变结果/成本的选择。在现有 grilling 内按源码范围、插件扩张、查询语义、验收四组推进并复用答案，不为减少问数强制固定上限，也不重新发起另一套访谈。该改进属于使用方式，不新增默认 grilling 触发。

ChildActor 先约定不自动编译，后来只授权一次 Automation；为了验证新 C++，再明确最小编译授权属于必要边界，不能算重复索权或要求取消构建缓存保护。新增二进制未验证时保留 unverified，避免让更多静态审查冒充运行证据。

## 本轮紧凑性审查

字符数按 UTF-8 解码后计 Unicode 字符，统一 LF；不含模型 tokenizer 或缓存效果。

| 文本 | 改前/固定上游 | 本轮 | 变化 |
| --- | ---: | ---: | --- |
| 日常 `WORKFLOW.md` | 1,022 | 1,087 | +65，仅导航 |
| 本地 implement-spec | 4,744 | 2,605 | −2,139；省去默认再读上游与逐票 merger |
| pr | 上游 4,107 | 适配 872 | 省去整包图示示例 |
| retro | 上游 4,369 | 适配 794 | 省去额外写作 Skill 与无关环境调查 |

命中链：普通任务仍只读原入口/模式/实际职责；三个增强只增加相应交付路由与命中正文，不串读另外两项。`implement-spec` 的上游细节和 Matt TDD 改为缺口时补读，已加载的测试/Review 方法复用。PR 与 retro 的固定来源/许可仍在包中，来源完整性校验不省略。

按来源文本计入口→路由→命中正文，旧 implement-spec 常规链为 10,222 字符（1022 入口＋1621 可选模块＋4744 本地适配＋2835 原必读上游），本轮为 4,285（1087＋593 交付路由＋2605 本地适配）。新 pr 链为 2,552，retro 为 2,474；此前两项没有已接入的可达链，不能将其新增开销说成零成本。共用模式/职责两侧相同未重复计数，按需补缺和生成路径改写另计。可选模块自身为 1621→1594 字符。数值见 `compactness.json`，不代表整个任务的 token 降幅。

触发静态核对：整体实施已有 spec+多票→implement-spec；修单函数/单票→普通实现；写 PR 正文→pr；审查 PR 代码→review；明确会话复盘→retro；普通工作总结→原报告流程。这里只证明路由/正文约束与打包可达，不冒称真实模型触发率或 token 节省实测。

## 验证记录

- 仅来源文件建立本地提交 `1763733bd8b42eab31c8ad948b3b8edc5a7b6b72`，固定压缩后的 wrapper 与 Matt 选择锁；catalog 两项 revision/hash 对应该真实提交，V3 的 sourceHash 与索引 hash 同步，保留原 git show 字节核验。没有推送。
- 35 个不同的相关检查最终为 **34 通过、1 跳过**：主消费者组 18 项先有 17 项通过，补齐 V3 索引 hash 后仅重跑受影响项，并加跑 17 项 V3 catalog 检查。后组日志为 `OK (skipped=1)`；跳过项 `V3CatalogCompilerTests.test_rejects_traversal_and_reparse_source_refs` 在创建 symlink 发生 OSError 时跳过（本机符号链接能力不可用），该环境分支记 unverified，不计 passed；日志未保留具体 OS 错误文字，不推测错误码。成功且未受影响证据复用。记录见 `validation-summary.json`、`consumer-tests-final.log`、`v3-index-consumers.log`；不把前一次含失败的整组运行改写成当时通过。
- 额外执行 22 项压缩回归，出现 16 条旧文案断言失败（含子用例），没有运行错误；对失败方法仅替换本轮改前文档/配置输入后，同样 16 条失败复现、0 错误。属于既有断言与紧凑规则改写失配，本轮未扩成全套断言重写；也没有宣称完整旧代码回放或全部测试通过。见 `compression-summary.json` 与两份对应日志。
- 同一独立 Reviewer 已完成触发、授权、编排、打包与 retro 证据的完整覆盖及最终窄复核，无待审项、无未关闭 Critical/Important。加载链计数、成本比较用语两项 Minor 及测试跳过计数修订均已关闭；结论见 `independent-review-final.json`。
- 新完整 release 为 `0d1051f3069dec7d8f060a8066e49cc7f0f3a97e639195ad7a5cdca5a6801891`，431 份文档，在 `public/releases/` 和 `skills/selfworkflow/references/public/releases/` 均已生成；根入口及安装副本由生成器同步，保留旧 revision。按仓库要求实际执行 `.venv/Scripts/python.exe -m selfworkflow.cli skill sync --repository .` 和 `skill check --repository .`，均退出 0，check 为 verified；原始结果见 `skill-sync-cli.json`、`skill-check.json`。最终源文件格式及 diff 检查亦通过（`diff-check.json`）。
- 本仓库既有 CodeGraph 为 initialized/complete 但 stale，预存 1034 added、312 modified、26 removed 且建议重建；本轮仅取得状态，不启动全库恢复/重建。`src/selfworkflow/adapters.py` 的新图证据记 unverified，判断基于直接源码及消费者测试。见 `codegraph-status.log`。

没有额外安装全局工作流、发布远端 PR、push、修改其他会话或重建 UE/CodeGraph。

## 上游依据

[Matt implement-spec](https://github.com/mattpocock/skills/blob/4ae2317ddb22b046e26455e4f9c9b3aaaf62212d/skills/engineering/implement-spec/SKILL.md)、[PR](https://github.com/mattpocock/skills/blob/4ae2317ddb22b046e26455e4f9c9b3aaaf62212d/skills/engineering/pr/SKILL.md)、[retro](https://github.com/mattpocock/skills/blob/4ae2317ddb22b046e26455e4f9c9b3aaaf62212d/skills/engineering/retro/SKILL.md)。采用任务图/稀疏指针、正文证据/回滚、会话环境复盘方法，副作用与调度遵 SelfWorkflow 本地适配。
