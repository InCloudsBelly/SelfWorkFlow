# Matt Pocock Skills 基底迁移实施计划

**目标：** 将 SelfWorkflow 的默认工程能力基底从 Superpowers 切换到固定版本的 `mattpocock/skills`，同时保留现有 Light / Full / Deep 分级、模块路由、侵入性控制、TEA、代码增强、专项 Review 与知识沉淀能力。

**迁移边界：** SelfWorkflow 不再默认加载、要求或安装 Superpowers；只有用户明确指定时，外部 Agent 才可临时使用它。已有用户级 Superpowers 安装不删除、不覆盖。SelfWorkflow 自有的流程阶段、确认门禁和真实验证证据仍然保留。

## 基底映射

| SelfWorkflow 阶段 | Matt Skills 默认能力 | 既有可选增强 |
| --- | --- | --- |
| Design | Light 使用 SelfWorkflow 核心；Full 自动 `grilling`；Deep 自动 `grill-me`（内部运行更深的 `grilling`） | `codebase-design`、`grill-with-docs`、领域建模 |
| Plan | SelfWorkflow 中性 Plan 契约；按需使用 `to-spec`、`to-tickets` | 项目专项计划模块 |
| Implement | `implement`、`tdd` | C++/UE compact core、CodeGraph |
| Debug | `diagnosing-bugs` | C++ 调试、项目专项诊断 |
| Review | `code-review` | 任务语义命中的专项 Review |
| Verify | SelfWorkflow 真实命令与证据门禁 | TEA、项目测试工具 |
| Knowledge | SelfWorkflow 可选知识接口 | C7OpenWiki MCP |

## 固定决策

- 新增 `dependencies/upstream/matt-pocock-skills` Git Submodule，固定精确 commit，不自动跟随上游 main。
- 使用上游自带 `grill-me` / `grilling`，移除 SelfWorkflow 自有重复 Grill-me 的默认路由和安装管理。
- Light 保持精简；Full 和 Deep 必须加载 TEA。Light 仅在测试不确定性或用户要求时升级测试设计。
- C/C++/UE 任务默认加载 C++ compact core；其他语言不加载。
- 代码任务默认尝试使用已配置 CodeGraph。版本或索引不匹配时只能作为参考，并提示用户是否手动校正；不得把过期图谱当成事实。
- Caveman lite 继续常驻；它只影响对话表达，不改变持久文档、代码、命令或诊断文本。
- 旧 Superpowers 计划文档不迁移；新计划使用 `docs/plans/`。

## 实施任务

### 1. 建立上游来源与锁定信息

- 修改 `.gitmodules`。
- 新增 `dependencies/upstream/matt-pocock-skills`。
- 新增 `dependencies/locks/matt-pocock-skills.lock.yaml`，记录 URL、commit、选中 Skill 与内容 hash。

### 2. 先建立聚焦迁移测试

- 新增 `tests/conformance/test_matt_skills_foundation.py`。
- RED 必须覆盖：Submodule/锁文件缺失、默认目录仍引用 Superpowers、Matt 核心 Skill 未被打包、Light/Full/Deep 与 TEA 路由退化、CodeGraph 过期状态被当成可信。

### 3. 替换默认路由

- 更新 `workflow/core.md`、`WORKFLOW.md`、`catalog/modules.yaml` 和 V3 模块定义。
- Design、Implement、Debug、Review 改用 Matt Skill；Verify 保持 SelfWorkflow 原生真实证据门禁。
- 保留 TEA、C++、CodeGraph、知识和专项 Review 的现有选择策略。
- Superpowers 仅保留“用户显式指定的外部能力”说明，不进入默认依赖和 fallback。

### 4. 修改运行时与一键安装

- 运行时只打包被选中的 Matt Skill，不复制整个上游仓库。
- 一键安装从固定 Submodule 发布选中 Skill，不再询问 Superpowers 来源，也不单独安装重复 Grill-me。
- 已有 Superpowers 目录只报告为外部未管理内容；不得删除。
- Caveman lite 安装与全局常驻规则保持不变。

### 5. 文档和聚焦验证

- 更新 README 与安装说明中的默认基底、阶段映射和升级方式。
- 运行新增迁移测试、目录/Schema 测试、V3 路由测试和安装 dry-run。
- 搜索活跃目录，确认没有默认 `superpowers:` invocation；历史文档允许保留。
- 检查完整 diff，确保未修改 C7OpenWiki 行为、TEA 上游内容、用户已有无关改动或全局安装状态。

## 简化验收

1. Submodule URL 和 commit 可复现，选中 Skill 文件存在且 hash 与锁文件一致。
2. SelfWorkflow 默认流程不要求、不加载、不安装 Superpowers。
3. 显式请求 Superpowers 仍不被 SelfWorkflow 禁止，但不获得默认路由或 fallback。
4. Matt 基底覆盖 Design、Implement、Debug、Review；Plan、Verify 由中性 SelfWorkflow 契约承接。
5. Full/Deep 必须选择 TEA；C++ 与 CodeGraph 选择规则保持。
6. Matt 上游 Grill-me 取代 SelfWorkflow 重复副本。
7. Caveman lite 继续常驻。
8. 聚焦测试通过；未运行的全量 Review 和回归明确留给后续人工触发。

## 禁止边界

- 不删除用户机器现有 Superpowers。
- 不自动更新 Matt Submodule。
- 不把全部 Matt Skill 常驻加载进上下文。
- 不修改 C7OpenWiki MCP 行为。
- 不借迁移重构无关模块、Schema 或历史文档。
- 不声称本轮完成独立终审或全量回归。
