# SelfWorkflow 的 TEA headless 执行边界

此文件与 `../METHOD.md` 共同定义本地适配入口，优先于复制的上游引导、配置、菜单和输出规则。上游材料提供测试方法；不执行其项目 bootstrap。本契约变更使旧 referenceHash 和回执失效。

## 路径与输入

- `{skill-root}` 是本次选中的 `references/bmad-testarch-<workflow>`。
- `{tea-knowledge}` 是当前 `tea-quality` 目录下的 `references/bmod-tea/knowledge`；`knowledgeIndex` 是其 `tea-index.csv.md`。禁止从项目 `_bmad` 或别的安装版本补文件。
- `{project-root}` 只供读取用户批准的上下文。所有相对输入路径以此为基准；缺具体文件清单时不能猜测故事、PRD 或整个仓库的范围。
- 唯一报告输出为调用者指定的 `outputRelative`（项目内安全相对路径）。`output_file_override` 绑定此路径；`test_artifacts` 仅表示其父目录，不授权创建其他文件。
- 上游 checkpoint、progress、架构/QA/handoff 多报告以及 `run_key` 分支改为单份报告内的章节；不创建这些额外文件或目录。上游恢复只读取明确提供的旧报告。

## 固定配置

`headless=true`；`communication_language=中文`；`tea_use_playwright_utils=false`；`tea_use_pactjs_utils=false`；`tea_pact_mcp=none`；`tea_browser_automation=none`。`test_stack_type=auto` 只从已提供的上下文和批准读取的文件判断，无法判断则记录 unknown，不扫描无关范围。

这些值来自本地适配契约，不读取 `_bmad` config、用户覆盖或团队覆盖；不调用 `_bmad/scripts/resolve_config.py`。不启动交互菜单、浏览器/MCP、脚本、测试命令或依赖安装。上游命令只能作为建议写入报告。用户显式选择新的集成需先明确输入和权限，当前默认契约不能假装已启用。

## 按工作流映射

| 工作流 | 必需上下文 | 上游步骤的替代输入 |
| --- | --- | --- |
| test-design | requirements、acceptanceCriteria、design、risk | 以批准范围作为 system/epic scope；局部修复仅设计实际改动。无 epic 编号时使用任务范围，不虚构 epic；既有代码不等于整项目设计。 |
| atdd | requirements、acceptanceCriteria、implementationPlan、testDesign | 输入计划内的验收场景；报告记录 RED 方案或实际证据。写测试脚手架仅在用户已批准的测试路径和实施范围内进行，不由此报告入口新增写权限。 |
| test-review | acceptanceCriteria、implementationDelta、testDesign、verificationEvidence | `review_files` 来自 implementationDelta 中的批准文件清单，`context_files` 来自 testDesign/acceptanceCriteria 的明确引用；`headless=true`，输出覆盖为 outputRelative。缺文件清单而要求文件级结论时 unverified。 |
| trace | acceptanceCriteria、testInventory、verificationEvidence | 用给定测试清单与运行证据建立映射；没有运行结果时不得推断 PASS。 |
| nfr | design、nfrRequirements、verificationEvidence | 只审计输入中的 NFR 证据；缺阈值或测量值标 unverified，不生成测量。 |
| framework | projectManifest、testInventory、projectRules、acceptanceCriteria | 只读评估入口和 checklist；不创建框架，不依赖 knowledge。 |
| ci | pipelineFiles、verificationPlan、projectRules、runEvidence | 只读配置与门禁评估；配置存在不等于 CI 执行成功，不依赖 knowledge。 |

所有必需上下文必须非空且无未解析占位符。字符串完整不等于语义完整：需要但缺失的文件、阈值、配置或证据必须列明并保持 unverified；不得用任意文字满足要求。

## 预检与证据

打包与运行时预检检查知识索引、索引中每个片段、必需知识条目和安全路径；referenceHash 绑定本契约、适配入口、选中工作流及知识树。独立 framework/ci 只绑定实际消费的入口。

Catalog 的 supportEvidence 描述本地适配接口及测试，不是当前 Host 执行证明，也不覆盖上游 lock/adapter 中仍为 unverified 的运行证据。Python 校验器只验证文件、结构与绑定，不执行 Agent，不证明报告语义、知识片段已被阅读或测试已运行。正式结论需要真实上下文、独立 Review 和执行证据；缺失时保持 unverified。不得用标题齐全的空文档宣称质量门禁通过。
