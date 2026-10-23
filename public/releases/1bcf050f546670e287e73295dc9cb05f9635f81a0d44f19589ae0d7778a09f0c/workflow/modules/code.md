# 代码任务模块

- 准备对行为源码做结构化查询时，主 Agent 才读 [codegraph-read](codegraph-read.md)；精确路径阅读不因“读取阶段”启动图核对。实际纳入官方索引的源码批次后按 [codegraph-update](codegraph-update.md) 合并维护，再结构化读取或交付；生命周期、失败和漂移边界不变。
- 责任层与实施契约用 `code-quality`；按需加载 Ponytail、`cpp-core`。不得为小功能引入全局宏、公共枚举、非必要调用者或独立子系统。
- Review 到阶段再读 `review.md`；匹配且 hash 校验通过的项目 Review Skill 优先，只补通用检查缺项，不能覆盖硬规则。
