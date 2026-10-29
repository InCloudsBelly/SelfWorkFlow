---
name: knowledge-backend
description: 显式选定后端后的可选 knowledge.read/propose/update；不因普通代码、临时状态或泛化知识词触发。
---

# 通用知识后端

生命周期与默认选择归[知识模块](../../workflow/modules/knowledge.md)，已读不重入。只读当前操作与选定 adapter，实际 API/接线/失败语义由其契约提供，不猜模型、数据库、OAuth、工具或路径，不静默切换后端；缺能力/漂移 fail closed 标 unverified，代码交付继续并列 knowledge-sync-todo。
read 只读、propose 不发布；update 绑定有效授权、版本/来源与独立复审。直接更新要求即同范围授权，技术绑定刷新不重问；冲突/漂移/阻塞缺口/Review失败不发布。材料保留必要来源身份/hash/短摘录，不存私人推理或整份敏感原文。
SelfOpenWiki 是可选 adapter（extensions/knowledge/selfopenwiki；selfworkflow.selfopenwiki:SelfOpenWikiAdapter）：personal_call/personal_status 管更新，read 与 visualizer_spec 分别判能力。其他后端可实现相同生命周期和测试，不能改安全/授权/来源/失败关闭边界，不把 SelfWiki 变为通用接口硬依赖。
