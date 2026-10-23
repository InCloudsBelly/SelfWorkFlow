# 代码任务模块

- 主 Agent 在结构化读取阶段按 `codegraph-read.md` 维护项目唯一 `.codegraph/`；实际代码批次后按 `codegraph-update.md` 合并维护，再读取或交付。生命周期、失败和漂移处理只在这两个模块定义。
- 责任层与实施契约用 `code-quality`；按需加载 Ponytail、`cpp-core`。不得为小功能引入全局宏、公共枚举、非必要调用者或独立子系统。
- Review 到阶段再读 `review.md`；匹配且 hash 校验通过的项目 Review Skill 优先，只补通用检查缺项，不能覆盖硬规则。
