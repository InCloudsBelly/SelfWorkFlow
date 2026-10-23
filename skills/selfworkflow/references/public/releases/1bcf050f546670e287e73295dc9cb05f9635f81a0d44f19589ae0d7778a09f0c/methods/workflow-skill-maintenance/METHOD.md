---
name: workflow-skill-maintenance
description: 维护 Skill/工作流的职责、触发和按需加载；仅新增、改造、集成时启用，纯审查或使用现有能力不触发。
---

# Skill 与工作流维护

在 SelfWorkflow 已选定的任务范围、阶段和授权内，为新的或已修改的 Skill 找到合适的责任层、触发边界和引用方式。只处理工作流本身的改造；用户使用某项能力时，直接进入那项能力。

## 来源与按需阅读

日常工作流规则、触发边界、路由与引用维护只读取本 Skill 和受影响文件，不预载整份上游创建指南。新增实质 Skill 或需要创建/评测方法时，才从 documentRoot 按需完整读取 `references/anthropic-skills/skill-creator/METHOD.md`；沿用本任务绑定的文档版本并核对引用完整性，不输出全清单、不猜旧路径。缺失或漂移标为 `unverified`。

显式维护 SelfWorkflow 仓库源码时，可以使用本任务批准的 repositoryRoot，从
`dependencies/locks/anthropic-skills.lock.yaml` 和固定 submodule 的
`skills/skill-creator` 读取对应材料；不要更新上游或修改其源码。

上游仅作方法引用；命中方法时正文首次读取并复用，grader/comparator/analyzer/schemas 只按具体评测需要加载。不因维护一个触发条件自动启动成对模型评测、额外审查 Agent 或整库读取。

## 融合与触发优化

1. 核对当前 Skill、现有职责、调用者和任务路由，只读本次新增或改造所需的范围。已有功能可复用时，优先修订当前入口。
2. 明确新 Skill 的输入、输出、owner、适用阶段、必要工具与权限。与 SelfWorkflow 和已有 Skill 重叠的流程职责交回现有 owner；专业 Skill 只提供方法，不重新 Discover、Grill、创建 Reviewer 或请求相同确认。
3. 让 description 描述用户的真实意图，加入能排除邻近误触发场景的边界。正文保留必要规则，较重且条件性内容放入 references；保留许可证与固定来源。
4. 建立少量正例、邻近负例和易混淆例：给出应加载的 Skill、原因和预期产物。尤其区分“创建这项能力”和“使用这项能力”，覆盖中文说法与已有同名 Skill。
5. 在已批准范围内修改；沿用当前任务的设计、Review、确认、TDD 和验证。宿主支持自动发现时保持窄意图触发；只有用户要求手动点名时才关闭 implicit invocation。
6. 有适配工具和授权时做修改前后对比：任务成功率、触发准确率、误触发、总 Token 和重复检索。没有真实执行证据时交付样例与验收方案，不把静态 frontmatter 检查称为模型触发或省 Token 的实测。

## 宿主适配与输出

上游 `claude` CLI、Claude 模型/API、`Task` 工具、评测脚本和插件命令不能直接假设在当前宿主可用。先检查对应能力；模型调用及并行评测需符合本任务授权与成本范围，外部安装、发布或消息发送分别检查授权。可移植的方法继续使用，特定工具不可用的执行项标为 `unverified`。

交付一份简短融合结果：固定来源、职责/阶段映射、重叠与复用决定、触发正负例、必要修改、验证证据及未验证项。是否创建说明文档取决于当前任务需要，不额外生成整套模板或把维护规则扩散到日常任务。

触发示例：“把新的科学绘图 Skill 接入个人工作流”“优化这个 Skill 的 description”“整理新增 Skill 的阶段与职责”。
不触发示例：“审查现在的工作流是否紧凑”“画一张性能曲线”“把报告导出为 PDF”“修复 C++ 崩溃”“使用现有 skill-creator 处理当前内容任务”。
