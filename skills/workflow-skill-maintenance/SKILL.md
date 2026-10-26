---
name: workflow-skill-maintenance
description: 仅新增、改造或集成 Skill/工作流时使用；纯审查及使用现有能力不触发。
---

# 工作流与 Skill 维护

沿 SelfWorkflow 的范围、授权、阶段和 Review，只改命中的职责/路由/引用，不另起流程。日常规则维护只读本方法及受影响文件，不预载上游创建指南。
新增实质 Skill 或确需创建/评测方法时，才按需读[创建指南](../../references/anthropic-skills/skill-creator/SKILL.md)；grader/comparator/analyzer/schemas 按具体评测再读。保持本任务版本，缺失/漂移 unverified，不找旧安装。明确维护源码时可从批准 repositoryRoot 的 `dependencies/locks/anthropic-skills.lock.yaml` 及固定 submodule `skills/skill-creator` 取对应材料，不更新/修改上游。

1. 复用已有最窄 owner；专业方法不重做 Discover/Grill、Review 调度或相同确认。
2. 定义意图、输入输出、职责/阶段、必要能力与排除场景；短 description 负责触发，条件细则放 references，保留许可与固定来源。
3. 少量正例、邻近负例、同名易混淆例覆盖“创建能力”与“使用能力”，含中文；不因改一条触发器自动做成对模型评测或额外 Agent。
4. 已批准范围内修改，沿现有设计/TDD/Review/验证。宿主支持时保留窄隐式触发，仅用户要求手动点名时关闭 implicit invocation。
5. 有真实能力/授权才做改前后成功率、误触发、重复检索与总token对比；静态格式/路由检查不称模型触发或省token实测。

厂商CLI/API、Task、评测命令和模型不能假设当前可用；只核对必要能力，安装/发布/消息发送分别核对授权，不重走全部接入。交付固定来源、职责/复用、触发样例、改动与已验证/缺口；不额外生成模板包或扩散维护规则到日常任务。
触发：优化Skill description、接入新方法；不触发：用现有能力写报告、画图、修复C++、只读审查工作流。
