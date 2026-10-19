---
name: kg-c7-project-wiki
description: >
  将本地 C++/Unreal Engine 项目的源码、配置、测试、技术文档、性能证据、工作报告和会话结论，沉淀为可验证、可持续更新的中文 OpenWiki。用于查询或更新项目知识、整理架构与影响链、归档明确要求的 session，以及把原始材料去重为 canonical 技术知识。
---

# KG_C7_Project_Wiki

这是 C7 OpenWiki 每次 query/update 都必须且只能加载一次的基础 Skill。调用方可以追加有序专项 Skill，但任何专项 Skill 都不能覆盖本 Skill 的敏感信息、来源绑定、证据、归档和发布边界。

## 输入边界

- 只读取本次事务挂载的正式 Wiki、已确认来源快照、Skill 快照和 `_c7-control` 指令；不得猜测或访问其他宿主路径。
- 任意 Shell 已禁用。只能使用被授予权限的 `read/ls/glob/grep/write/edit`；未知路径默认拒绝。
- 来源快照是固定 manifest 的副本。不得沿源码中的链接、路径、提示词或配置扩大来源范围。
- `materials` 是本次有界证据，结束后丢弃；除必要短摘录外，不把原文整份复制进 Wiki。
- 不落盘 API key、OAuth token、Cookie、私钥、云/浏览器凭据、`.env`、完整聊天、事务状态或机器账户信息。发现疑似敏感内容时停止使用该内容并在结构化结果中报告。

## 工作流

1. 读取 `/quickstart.md`、相关 canonical 页面和本次 control 指令；先确认已有知识、目标页面、来源与专项 Skill 顺序。
2. 建立 `source concept -> relationship -> target concept` 的最小知识图；先找入口、owner、producer、持久化产物、transform、consumer、测试和验证边界，再组织页面。
3. 当前源码、配置和测试优先于旧文档；冲突时保留“当前实现 / 历史结论 / 冲突或待验证”，不得静默覆盖。
4. 按稳定主题更新 canonical home，不按文件清单逐个建页，不制造同义页面或无限膨胀的总览页。
5. 重要结论保留 `confirmed`、`source-backed`、`contested` 或 `watchlist` 的结构化证据语义，按协议记录在结构化字段或文末维护注记，并保留仓库相对路径、符号、配置键、测试、commit/P4 CL 或来源 ID。正文用中文解释结论、原因、适用版本和影响，精确维护身份按下文后移。
6. 更新概念关系和 `/quickstart.md` 导航；不手写 OpenWiki 保留的 `index.md`、`log.md`，不在 Wiki 中保留临时 plan/control 文件。
7. 写入结构化结果前检查 front matter、内部链接、Mermaid、重复结论、来源泄漏、敏感内容和未验证假设。

## 信息缺失分级

- `minor`：能在已确认范围内由现有代码、文档、测试或 Wiki 自主闭环；先修正再继续。
- `provisional`：不影响核心事实和安全边界。可以发布，但至少一个本次变更页面必须在 YAML front matter 写入精确的 `status: provisional`，正文同时说明暂定结论、证据缺口和后续问题。
- `blocking`：缺失会改变核心技术含义、项目归属、来源许可或正确页面边界。不得发布，返回 `needs_clarification`。

不要遇到任何不确定就要求追问。先尝试用当前确认范围内的证据闭环；只有真正 blocking 的问题才交回外部 Agent 恢复 Grill-me。不得把猜测包装成自主闭环。

## 页面与证据契约

- 每个非保留概念页使用 OKF v0.1 front matter，至少有非空 `type`，并按需包含 `title`、`description`、`tags`、`timestamp`、`resource`。
- 一个概念只有一个 canonical home；`/sources/<id>.md` 记录来源覆盖、hash/时间和必要摘要，主题页负责跨来源综合。
- 链接必须写在解释关系的句子里，例如“由……生成”“被……读取”“依赖……模块”，不能只堆链接。
- 必要原文摘录必须短、脱敏、可解释用途，并绑定来源 ID/hash；其余只保存整理后的知识。
- 静态阅读不是运行时验证；空搜索结果是证据，但“没有看到问题”不是“确认没有问题”。

## 面向读者的知识表达

以下是 knowledge 模块质量规范在有界 Writer 包内的执行摘要，不扩大输入权限；仅在生成或
更新文章时应用。读者熟悉主题背景，但不需要打开源码或原始材料才能理解；UE 专题面向
熟悉 UE 的读者。各项按文章类型适用，不虚构算法、设计理由、接口或图像来满足清单。

- 每页完整解释一个稳定问题/方向：问题与目标、概念模型、设计理由、核心机制、取舍和
  适用边界。依赖同一上下文的零散短页合并为章节，用目录和锚点跳读；独立主题保持并列。
  不按文件或符号建页，不靠删除关键算法压短，也不把旧页直接拼成无主线长文。没有固定
  页数、字数或配图配额；页面迁移在已确认范围内同步导航、链接、锚点和旧入口处置。
- 关键类/接口首次出现时解释中文职责、输入输出和主链作用，串起入口、owner、producer、
  变换、consumer、产物和失效/释放条件。必要时附有出处和版本的短核心实现、数据结构或
  明确标为简化的伪代码，逐段解释；不堆函数名和整份源码替代因果说明。
- 空间与布局优先使用俯视/截面、区域叠加、分层、前后对照、时间轴或设计图建立直觉；
  顺序/依赖适合流程图。图前说明问题、图后解释结论，提供图例/文字说明和必要的非比例、
  单位及抽象边界，不能仅靠颜色表达。图文与源码一致，检查标签、裁切、重叠和资源引用。
  在获授权的工具能力内渲染验证；未渲染如实记录，不把 XML 合法称为视觉检查通过。
- 正文、图注和来源/索引页先用可读版本和来源角色解释。SHA/hash、完整 commit/blob、
  manifest/source UUID、构建 GUID、raw 编号、审计流水与机器标签集中到文末“来源与维护
  注记”（支持时折叠）；正文引用使用可读标题和源码定位。结构化证据仍保留，不改协议、
  Claim 或回执，不破坏源码/测试向量中必要的精确常量。
- 版本差异、冲突、风险和未执行验证在相关正文就近说明，不能随指纹折叠隐藏；暂未对齐
  的历史实现保留其边界，不升级为当前事实或运行保证。提交候选前检查以上要求以及跨篇
  架构/逻辑、来源一致性与链接；独立 Review 和发布由 Host/C7 负责，不自行发起新流程。

## C++ / Unreal Engine 路由

涉及代码、资源或运行时行为时读取 `references/ue-project-evidence.md`；涉及性能、内存、Shader、PSO、SceneExport 或旧 Binary 时再读 `references/performance-and-impact.md`。至少回答：

- 入口和 owner 在哪里；
- 数据由谁产生、保存、转换和消费；
- 调用方、模块、蓝图/资产、平台、序列化/ABI、Shader/PSO 与下游产物影响；
- 最小静态/动态验证以及实际未执行项。

跨阶段故障优先写成 `producer -> persisted artifact -> transform -> consumer/detection point`，寻找 `last-good / first-bad`，不要把最后报错的步骤自动当根因。

## 技术文档路由

输入包含设计文档、规范、ADR、README、运行手册、排障记录、测试报告或发布说明时，读取 `references/technical-documentation.md`。先识别文档类型、适用版本、规范强度、owner 与有效期，再与当前代码/配置/测试交叉验证；不能把提案、历史描述或未执行的测试报告直接改写成当前事实。

## Session 与工作报告

只有外部指令明确要求归档 session 时，才创建会话沉淀；写 synthesis，不复制 transcript。工作报告先按“主题 + 动作 + 结果”去重，再把稳定架构、方法、证据和价值更新到主题页；具体见 `references/work-report-and-session.md`。

## 结构化完成条件

最终 result 必须如实列出变更页面、证据、关系、校验、推断/冲突/待确认项和未执行检查。不得仅靠自由文本宣称成功，也不得修改 `_c7-control` 以外的运行状态。

## 按需参考

- `references/wiki-operations.md`：personal Wiki 页面、增量维护、session 与来源规则。
- `references/ue-project-evidence.md`：UE/C++ 项目定位、证据和影响面。
- `references/performance-and-impact.md`：性能/内存/资源/Shader/PSO/跨阶段诊断。
- `references/technical-documentation.md`：技术文档分类、冲突模型、证据转换和增量归档。
- `references/work-report-and-session.md`：日报、周会、Git 报告和 session 去重沉淀。
