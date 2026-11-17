---
name: pr
description: 撰写或更新 PR 正文时使用，包括已请求创建 PR 时准备正文；仅审查 PR 代码、普通交付、出现 PR 链接不触发。
metadata:
  upstream: mattpocock/skills@4ae2317ddb22b046e26455e4f9c9b3aaaf62212d
  credits:
    skill: show-me
    author: Dex Horthy
    organisation: Humanlayer
    url: https://github.com/humanlayer/skills/blob/main/plugins/show-me/skills/show-me/SKILL.md
---

# PR 正文

沿 SelfWorkflow 当前阶段，仅组织已有证据；不新启 Reviewer、构建、测试或全面探索。复用当前 diff/基线、验收、验证结果与未关闭风险；缺什么只补必要信息。仓库模板和用户格式优先，术语沿既有项目文档，不为写正文另找词汇表。

无模板时写三项：Summary 说明具体问题与改后行为；Evidence 列已有 before/after、命令与结果，未执行标 not-run/unverified；Merge Danger 说明回滚难度、影响范围与必要风险。简单变更用短段落，关系复杂时只加一幅有助评审的小图或 diff，不强制截图、全套图或新跑测试。证据不得从“代码看起来正确”推断。

正文随最终增量改写，删除对话过程和废弃方案。撰写正文不含 commit/push/创建或更新远端 PR/标 ready/merge/关闭任务权限；用户已明确请求的动作在其授权范围内直接完成，复用现有批准。默认仅返回正文，不自动落盘或发送消息。

来源与 MIT 许可由同包 Matt 锁及 LICENSE 保留；本入口适配其 Summary / Evidence / Merge Danger 方法，不加载整包示例。
