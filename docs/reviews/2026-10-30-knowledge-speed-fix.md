# knowledge 速度与恢复修复验证

日期：2026-10-30。范围为knowledge规则、SelfOpenWiki模块校验/快照、PageJob修复与Claims恢复。保留用户既有修改，以本轮开始时的精确文件副本为比较基线；正式Wiki只做摘要快照微测，写入/发布测试全部在临时Wiki中进行。

## 修复

- 模块身份校验改为最多4个并发的独立Git观察，仍逐次读取真实文件字节；保留原同步实现与相同manifest/hash格式，未加入TTL或mtime缓存。模块内容身份不使用的dirty查询不再执行。
- 快照文件读取共享8路限流，保留目录链、路径/句柄身份、文件变动检查和最终排序；异常立即接收，返回前等所有已开始的读取结束。重复accepted提交核对真实页面/Claim/marker后直接返回，最终候选全量校验保持。
- 有明确页面的修复只重开目标与双向relatedPages闭包；未定位/未知范围全重开。未改页必须有持久accepted作业、真实候选内容、原marker及可重建的Claim摘要；缺决定记录则重开，篡改失败关闭。稳定jobId与历史marker支持连续两代冷恢复；历史凭证不能自动接受pending/assigned工作。
- 普通修复与中断恢复共用真实C7 successor核对、精确清理未发布prepared义务、原子切个人state的入口。修复中断只使用C7已有predecessor重放返回的新绑定，无法证明修复范围时全重开。
- 负verdict不创建Claims发布日志。旧prepared日志在恢复前先取C7证明；正文hash相同不能证明发布，尤其仅Claim变化时。foreign、published、applying义务不被修复清理；真实已发布但个人state未提交的恢复仍可完成。
- 字体证据仅复用已覆盖字符/样式，新增字符/字重/代码和图内样式窄查；Host实际交接同版正文、版本、适用项及覆盖记录，有界摘要不代替全部关键机制检查。

## 数学可读性增量

承接SymPy接入对话的用户要求，复用其固定submodule、来源锁和随包数学方法；不重复接入或宣称本轮重新执行了SymPy验证。rubric升为`personal-wiki-deep-clarity-v7`，十二项ID/权重/门槛不变，旧v6记录与revision保留，不重贴标签；升级仅补适用数学增量及其影响项。

数学公式/参数说明归H1–H3：帮助理解时使用LaTeX和自然中文，解释机制步骤、成立条件、假设/近似、边界与退化。首次符号说明含义、输入输出角色、必要类型/矩阵形状、单位/维度、域和索引/积分范围。正确性/来源仍核A2/E1，显示仍查V3；非数学页不强造公式，同一Reviewer/共享观察完成集中评分。正文契约、分档样例、记录示例及Host/有界Writer交接已同步。

当前Viewer的`package.json`未配置remark-math/rehype-katex/MathJax，`src/components/MarkdownContent.tsx`只注册remarkGfm；这是配置静态观察，未完成目标页面的数学渲染验收。LaTeX生成、数学/工具执行正确、TeX可编译均不等于实际显示通过。规则区分未知/未预览的unverified与已知不支持/显示错误的缺口；本轮未修改已有脏Viewer子模块，数学显示能力仍待补齐并实际验证。

加上数学增量和字体范围补充后，默认必读质量标准＋正文契约为19,861字节，比原26,638少25.44%；全部knowledge-backend参考材料含来源/许可为47,593字节，比原67,159少29.13%。这是UTF-8静态字节数，不是token或生成耗时比例；先前v6压缩记录保留其当时快照，不外推到v7。

十二项评分、权重、每项至少4、各维度至少90、总分至少95、来源核验、独立Review及最终CAS保持。公开MCP字段和v1持久格式未改变；重新绑定源码/基础Skill的真实hash，不颁发或伪造新运行能力证据。

## 本机同数据对照

各3对；比较完整manifest/snapshot对象逐次相等。模块使用原同步实现与新异步实现；快照原实现由修复前保存源码转译，避免把可变的现有dist当作旧基线。快照样本交替先后顺序；小样本不代表稳定分布。

| 项目 | 原中位数 | 新中位数 | 时长减少 |
| --- | --- | --- | --- |
| 模块身份helper | 2135 ms | 866 ms | 59.4% |
| 当前70页、6,769,928字节Wiki快照 | 233 ms | 57 ms | 75.5% |
| 合成250页、37,500,000字节分层树快照 | 672 ms | 142 ms | 78.9% |

这是helper耗时，模块数值不含每次Node启动；正式Wiki快照不等于候选/修复/发布耗时。不能外推整篇生成提速，更不能据此宣称模型产文质量实测不降。真实写作A/B仍须固定任务、来源、模型及质量门槛，比较总时长、返工、覆盖和最终独立评价。

## 验证与生效边界

- 先观察异步校验缺失、全重排/Claim篡改、链接marker及跨层恢复的实际RED，再最小修复到GREEN。fixture准备错误不计作行为RED。
- 定向回归覆盖未变hash、嵌套新增/删除/暂存、两代冷恢复、缺失/篡改Claim、历史/未来marker、关联闭包、非法树最终拒绝，以及真实C7+ClaimsResolver+临时发布的11个恢复/保留窗口。
- TypeScript noEmit与隔离outDir编译通过；没有执行npm/pnpm pretest、依赖重装或Win32 helper重建。
- 独立Reviewer已核对本轮完整增量，并复核、关闭同一跨层恢复Finding；最终自动化结果见下方收尾。
- 现有CodeGraph增量维护返回rebuild-required；保留原索引，未初始化/重建。相关结论以直接源码与回归取证，图谱新鲜度仍未核实。
- 全局工作流安装、能力证据重新颁发、MCP执行构建切换和宿主重启不属于本次仓库维护默认授权。当前在途事务、旧revision和已有缓存保留；源码/文档就绪与运行中服务已切换分别判断。

## 自动化收尾

- 完整MCP回归：`node node_modules/vitest/vitest.mjs run --maxWorkers=1`，49个文件、868项；867通过，唯一失败为基础Skill内容更新后两处旧hash金值。按真实包重算并保留固定字面量断言，失败文件2/2定向重测通过。其后只增加数学规则/有界摘要，运行时代码未变；最终受影响契约/compatibility复跑另列。
- 模块身份helper：`node --test test/parent-source-manifest.v2.test.mjs`，3/3通过；完整MCP回归包含新增11个真实C7/Claims恢复发布场景，全部通过。TypeScript noEmit及隔离outDir编译通过。
- 最终源码兼容性按真实文件重算并校验：baseSkill=`sha256:47f2c3b99da439d40c7f4062eb17b8c802403fd19dd1ca7c87455aa9c715df3b`，aggregate=`sha256:60bc4644623b373155ecc53086ef6b00249b8d5f25f690a9070ce56c7df52b26`。adapterSet不变；公开tool bindings严格相等，来源兼容校验通过。未颁发新的live能力证据。
- 数学增量定稿后，`test/skill-contract.c7.ts`和`test/personal-compatibility.v2.ts`定向复跑：2文件、8/8通过。按当前源码再次计算module manifest并执行`assertPersonalCompatibility`通过，未写live运行证据。
- `.venv/Scripts/python.exe -m unittest tests.conformance.test_wiki_module_runtime.WikiModuleRuntimeTests.test_knowledge_artifact_packages_backend_reference_bytes -q`：1/1通过，核对knowledge参考材料实际打包字节；测试临时文件已恢复。`git diff --check`通过。
- 同一独立Reviewer复核数学增量、版本/渲染状态、报告和真实hash金值，无新增可行动问题；原运行时Finding闭环结论复用。此结论是静态审查，测试结果由主Agent执行取得。
- `.venv/Scripts/python.exe -m selfworkflow.cli skill sync --repository .`：退出0，`status=synchronized`；完整新release含445份文档，revision=`106a8a850dd867c911d5c3ff98a1a6a3c2187d06de4b1dd24478ab9e5398dffb`。根入口、生成副本、两棵release及公共指针已同步；旧revision保留。
- 机械复读：9份knowledge参考正文与两棵新release逐字节一致；后端update正文除已声明的数学入口`SKILL.md→METHOD.md`发布路由转换外相同，目标方法实际存在。根/生成入口与两份公共指针同revision。
- `.venv/Scripts/python.exe -m selfworkflow.cli skill check --repository .`：退出0，`status=verified`，revision与sync一致。源码、根入口、生成副本及完整新release可一并交付；没有更新全局安装、推送远端或重启宿主。
