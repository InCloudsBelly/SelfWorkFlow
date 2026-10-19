# Review 模块

本模块唯一管理 Review 调度、材料、隔离和复审；专业 Skill 只提供检查项，不另建 Reviewer。阶段变化本身不触发重复审查。

## 调度

- Light 窄结构化自审并如实标记。Full/Deep 交付前一个独立 SubAgent 同时检查 Standards/Spec、行为与测试证据；所有模式取消双 Reviewer，两个轴不是两个上下文。
- 普通设计/计划/测试设计合并为紧凑实施方案，由主 Agent 自审。重大架构、安全、持久化、不可逆风险或显式请求才前置独立 Review；尽量复用同一 Reviewer。机械文档同步用窄自审/脚本校验，不单开审查；实质设计按风险处理。
- Full/Deep 纯分析一次独立 Review，Light 结构化自审；发现本身是结果，不要求当场修复被审查系统，不套落地代码/TDD/TEA。
- 同范围已有明确授权复用；关键决策、越界或实质风险变化才重问。Critical/Important 必须解决，Minor 有处置；修复后只复核未关闭问题及影响项，持续到验收，不设“超预算中止”。

## 输入、模型与复用

- Review 默认继承主 Agent 模型/推理配置，不读取机器本地 Review 模型配置，不传 model/reasoning_effort 覆盖；没有实际模型回执不虚构型号或缓存命中。独立上下文不是不同模型，不为缓存导入作者推理/完整历史。
- 主 Agent 一次提供请求、验收、适用规则、最终方案/实际任务增量与必要证据，绑定内容/hash。独立 Reviewer 只能读取该包及其中绑定的必要代码来验证反例；不接收完整主历史、Wiki 或无关材料，不重走主流程。
- Reviewer 不得调用 CodeGraph/provider、运行验证、写工作区、更新知识或创建下级 Agent。主 Agent 负责 CodeGraph evidence；缺少 CodeGraph evidence 且结论依赖它时返回该项 unverified，不能用猜测替代。
- 匹配项目 .selfworkflow/review.yaml 的 Skill 优先，通用 Skill 仅补充。复用相同输入、规则、Skill hash 的有效结论；相关变化只失效受影响项。必要反例检查不能被“禁止重复”压掉。
- 优先复用原 Reviewer，通过 send_input 补充变化；仅上下文不可用/污染/版本不兼容时替换，不并行追加重复 Reviewer。TEA 仅显式启用，复用此证据，不新增另一批审查者。
- 宿主真实完成状态是普通审查证据。独立能力不可用标 unverified；无清理回执不声称已销毁，也不因契约专用清理回执缺失阻塞普通任务。

## 显式契约模式

首次构造门禁前读 testing-review-quality/references/contract-host.md。保留真实 hash-bound package、receipt、runner、隔离与 created → executed → cleaned 证据；单 Reviewer 仍须真实独立。历史 reviewModel 字段仅保留 null 用于回执格式兼容，任何专属模型覆盖拒绝执行。普通任务不创建 PlanGraph/RunLedger，不伪造契约回执；契约能力不足不降级冒充通过。
