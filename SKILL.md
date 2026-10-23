---
name: selfworkflow
description: 按 SelfWorkflow 执行工程任务的方案、实施、审查和验证；用户选择本工作流或已设为默认工程流程时使用，闲聊和仅讨论工作流概念不触发。
---

# SelfWorkflow

- 新顶层任务读取本 Skill 随包的[公共入口](skills/selfworkflow/references/public/WORKFLOW.md)，跟随入口绑定 revision/documentRoot。用户明确指定另一入口时服从该选择；宿主的默认安装路径不覆盖用户选定的这份 Skill。
- 子任务、Reviewer、阶段切换和续接继承已有绑定，不重选 latest；同版本完整正文复用。相对路径从声明文件解析，只读当前操作需要的模式和方法。
- 入口或必要资源不可读时报告具体缺口，仅继续独立且已授权的工作；不换旧安装冒充成功，不猜工具路径或自动安装外部服务。

本目录可直接作为 Skill 入口使用。自动发现与默认启用按宿主支持的全局/项目指令配置；进行中任务保留原版本。专业工具只在实际操作需要时核验。
