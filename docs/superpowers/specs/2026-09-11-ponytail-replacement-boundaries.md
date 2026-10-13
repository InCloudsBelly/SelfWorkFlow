# Ponytail 替换 Caveman：实施边界

## 目标

将 SelfWorkFlow 自有的 Caveman 表达策略替换为 Ponytail 的代码任务增强能力，并保持工作流的中文输出、按需加载、最小侵入和现有 CodeGraph 绑定不变。

## 固定边界

- Ponytail 仅用于代码相关的设计、计划、实现、调试、验证和审查；非代码任务不自动加载。
- 运行时只发布 `ponytail`、`ponytail-review`、`ponytail-audit`、`ponytail-help` 四项 hash 绑定 Skill。
- `ponytail-review` 只能补充过度设计审查，不能替代 Standards/Spec Review；`ponytail-audit` 只响应显式审计请求。
- `ponytail-help` 只保留一次性使用说明；不发布上游 hooks、watcher、daemon、全局配置或 Node 运行时；不保留 SelfWorkFlow 管理的 Caveman Skill。
- Ponytail mode 只存在于当前任务路由结果，默认 `full`，不写全局配置。
- CodeGraph 已有 Provider 绑定默认保留；需要重绑时由用户单独执行显式 Provider 操作。

## 验收与证据

- 来源：Ponytail Git submodule、锁文件、commit/tree/license/Skill hash 校验，漂移和 reparse path fail-closed。
- 路由：代码任务正触发、非代码误触发、显式 review/audit、非法 mode/Skill 输入。
- 运行时：三项 Skill 存在，Caveman、上游源码目录、hooks 和插件元数据不存在；构建结果可重复。
- 安装器：三个正常 submodule 都按固定 gitlink 同步；Ponytail 校验失败有独立日志；已有 CodeGraph binding 不被替换。
- 范围：不修改 CodeGraph、TEA、Matt 上游内容，不改变 Review、TEA、知识库和项目级 Review Skill 语义。
