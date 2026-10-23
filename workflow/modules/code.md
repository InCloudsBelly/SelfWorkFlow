# 代码与测试

- 行为源码分析/变更读[责任层方法](../../skills/code-quality/SKILL.md)；准备验证故障或编辑前按其变更规则给出实施契约，Plan 是实施边界。精确配置/文档/日志查询不触发。
- 行为变更 TDD、测试设计或实际测试执行证据核验读[测试方法](../../skills/testing-review-quality/SKILL.md)；普通 Review、纯分析和机械文档不触发测试方法。
- 准备对行为源码做结构化查询时才读 [codegraph-read](codegraph-read.md)；精确路径读取不启动图核对。实际纳入索引的源码批次后按 [codegraph-update](codegraph-update.md) 合并维护，再结构化读取或交付；生命周期与失败边界不变。
- Ponytail、C++、项目 Review 仅按实际需要加载；不得为小功能引入全局宏、公共枚举、非必要调用者或独立子系统。Review 调度沿当前模式，不重复创建审查。
