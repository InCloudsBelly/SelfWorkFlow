---
name: tea-framework-assessment
description: Explicit read-only assessment of the existing test framework and conventions during Plan.
---

# Framework assessment-only adapter

本地受限 TEA 入口；仅在显式选择 `tea-framework` 时于 Plan 使用。输入：projectManifest、testInventory、projectRules、acceptanceCriteria；提供内容的来源路径。缺少材料标为 unverified，不能猜测框架已安装或测试已执行。

读取项目明确提供的 manifest、现有测试入口、配置、fixture、测试命令与约定；接受已有完整框架，不把“未安装框架”作为前提。命令是待分析数据，不执行命令、不安装依赖、不运行测试、不创建或修改框架、配置、示例、CI 或项目 _bmad。未知技术栈（包括缺少项目证据的 UE/C++）标 unverified，不套用 Web 模板。

只读参考同目录 checklist.md 的现有配置、fixture、报告与命令检查项；其中 scaffold/create/install/write 要求不执行，标 N/A（本入口仅评估）。不加载上游 SKILL、steps-c、steps-e、BMAD resolver 或外部 knowledge 路径。

报告包含 ## Framework、## Conventions、## Commands、## Gaps。每项写出输入证据、现状、差距及 PASS/CONCERNS/FAIL/unverified；不使用模板标题作为测试通过证明。

默认在对话输出。仅当任务批准了报告文件时写唯一指定的 framework.md；既有文件不覆盖，路径不得是输入文件、越界、符号链接或 junction。Host 应在执行前限制写入目标并在执行后核对变更集；此 Skill 和输出验证器并非 OS sandbox。正式 V3 使用 build_packaged_invocation 和 validate_packaged_output 的 planned/plan.assessment/tea-framework receipt；validated 只证明报告格式与绑定，不能代替测试运行证据。
