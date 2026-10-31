# knowledge 写作与评分框架紧凑化

日期：2026-10-30。范围限于knowledge规则与SelfOpenWiki更新入口；运行时协议、发布门禁、全局安装及既有Wiki未改。

## 为什么会变慢

这是规则链的静态分析，不是线上耗时归因或模型效果实验。旧版已允许共享证据和增量复核，但仍有几个会放大工作量的默认要求：

- 默认追求每项5分。4分已经要求全部适用检查完成，5分再要独立补充问题/变式/抽取证据；十二项与逐页任务叠加，容易把95分达标任务执行成全项满分任务。
- 规划、覆盖清单、文档预问题/源码裁定、三类走查、作者/独立分和逐项记录表达大量相同事实。原规则要求无初稿时先造候选，再查文档可回答性；即使此前已看来源，也容易增加一次中间写作与重读。
- 必读质量标准与正文契约共26,638字节；细则引用还覆盖范围、质询、分档、链接、记录和图解。引用本身不是全部必读，但操作名称与常规必做事项重合，容易让执行者遍历细则。
- 每个指标要求锚点、方法、观察、理由、来源/版本和修订等信息；共用证据虽可复用，默认记录示例仍偏向展开全部字段，角色交接、逐页记录和修订容易重复输出。
- 图与实际字体/布局检查是有效质量成本。共享环境的字体证据可复用；每页布局、图文和内容仍需检查，不能靠省掉它们提速。PageJob串行和发布协议亦有固有成本，本次没有测定其占比。

## 已实施

保留十二项ID/权重、0–5分、每项至少4、各维度至少90、总分至少95及独立Review/来源/发布门禁。

一份范围/单元/条件清单贯穿取证、写作和审查，覆盖计数从同一清单派生；作者默认自检缺口，同一Reviewer集中独立评分。合并人类、图文和Agent走查，一次观察可对应多个指标，仍须逐项可追溯并覆盖全部关键机制。修订仅复核受影响证据及遗漏范围，达标后结束，不默认刷100分。

设计答案融入机制章节，章节锚点可充当问题ID；已看源码如实披露，不为模拟盲测重造初稿。细则改为具体范围/判分/路径问题需要时加载，结构化记录仅消费者确实要求时展开。相同渲染器/主题/字体环境可复用实际字体证据，每页布局仍核验；环境变化使相关证据失效。

humanizer-zh融入中文主线、节奏、去翻译腔和判断强度；technical-writing融入读者主用途、明确动作/条件、精确术语和消歧。技术解释仍可包含接口表/操作例，不机械拆页；不引入作者声音询问、额外润色轮次、英文词数限制或unslop依赖。两份固定commit、文件/许可SHA256和完整MIT声明在[来源记录](../../skills/knowledge-backend/references/writing-sources.md)，消费者可离线使用。

## 静态规模与验证边界

统计UTF-8文件字节数；后值包含新增来源/许可记录，diagram规范保持不变。字节/字符减少不等于token减少比例，更不等于生成耗时减少比例。

| 范围 | 改前字节 | 改后字节 | 减少 |
| --- | --- | --- | --- |
| 默认必读质量标准＋正文契约 | 26,638 | 17,461 | 34.45% |
| 全部knowledge-backend参考材料，含新增来源/许可 | 67,159 | 44,132 | 34.29% |

最小应用核对：读取Wiki不加载评分；措辞/链接修正仅查影响项；实质技术更新仍核对必要单元/条件、来源、图文/实际呈现及十二项；全库任务逐页覆盖，不能抽样外推。必需来源/渲染未核验仍为null且不能达标；不能借不适用缩分母。

数值边界：十二项均适用且仅A1=4，其余5时，总分98、Agent约94.286；仅E1=4时，可信约86.667，不达90；维度仅一项适用且为4时，维度80。精简没有改变这些结果。共享走查不是一个案例替代全部机制，来源核验仍由独立Reviewer承担。

验证收尾见下文。未采集真实写作/模型调用与耗时trace，实际延迟、token、成文质量及触发效果未验证；不能声称已实测提速。后续实测应固定主题/来源/模型/目标质量，比较总时长、调用/返工次数与最终独立评分。

## 验证记录

- 独立Reviewer完成上述规则/来源文件与本报告的全范围静态审查，未发现可行动缺陷；仅机械生成结果留主Agent校验，不把静态审查称为模型效果验证。
- `.venv/Scripts/python.exe -m unittest tests.unit.test_documents tests.unit.test_workflow_compression tests.conformance.test_wiki_module_runtime -q`：43个测试，首次有3个error（涉及2个测试方法）。其余41个测试通过，包含knowledge参考材料的实际打包及字节/manifest哈希检查。
- ACL测试在当前进程将PSModulePath限定到WindowsPowerShell模块目录后，仅重跑 `tests.unit.test_documents.DocumentPublicationTests.test_published_version_inherits_public_read_access_instead_of_private_staging_acl`：1个测试通过；没有修改系统环境、测试代码或产品代码。首次Get-Acl模块加载失败，进程内路径隔离后通过。
- 合计42个不同测试通过；maintainer全量打包1个仍未通过：既有 `extensions/codegraph/codegraph_ue/node_modules/@colbymchenry/codegraph-ui` junction触发 `runtime-source-link-rejected`。未删除/修改联接、node_modules或缓存，也未改打包保护；该profile的验证仍不通过，不外推为全部测试通过。
- 使用精确分数核对A1=4和E1=4的门槛算例；`git diff --check`退出0。未新增镜像规则文本的测试。
- `.venv/Scripts/python.exe -m selfworkflow.cli skill sync --repository .`：退出0，status=synchronized；新revision为 `5d197f67f2f3ac44e51e7e310cbb4876fe1853247bd23c2e21a6d7d6c67da996`，434份文档。根SKILL、生成副本和public指针已更新；旧revision保留，全局安装未改。
- 机械复读核对：9份knowledge参考正文在源码、两棵新release间一致；knowledge模块新路由已进入release。
- `.venv/Scripts/python.exe -m selfworkflow.cli skill check --repository .`：退出0，status=verified，revision与sync一致；包含生成副本、public指针、自包含引用及保留旧revision的完整性检查。
