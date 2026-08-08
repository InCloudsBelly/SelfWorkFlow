# SelfWorkFlow 执行清单

## 默认代码工作流

- [x] 精简、厂商无关的 `workflow/core.md`
- [x] 普通修改只路由 `workflow-core`
- [x] 无状态解析器组合 C/R、能力门禁、Catalog 和当前阶段 Superpowers 选择
- [x] Grill-me 仅由用户显式触发
- [x] 责任层优先、最小侵入、完整 diff Review 和最窄充分验证
- [x] `core` 为默认运行时，确定性排除安装、发布和知识扩展正文
- [x] `knowledge` 与 `maintainer` 必须显式选择
- [x] Catalog、路由和 profile 聚焦测试

解析器只生成执行计划，不伪称已经执行 Skill、Review 或测试。真实宿主是否按
计划发现并调用对应 Skill，仍由下方原生 Agent 验收确认。

默认代码工作流的可用性不再依赖原生 Agent 发布验收。未执行的宿主/模型测试
仍按事实标记 `unverified`，但不会让普通代码流程加载发布治理。

## 已实现的显式维护模块

- [x] 状态、C/R、能力与受保护不变量契约
- [x] Catalog 编译、最小路由和外部 Skill 吸收机制
- [x] Superpowers 来源探测、锁定和覆盖层
- [x] 事务安装、冲突、漂移、幂等、恢复和回滚
- [x] 厂商薄适配器
- [x] 可选知识契约与 C7OpenWiki MCP 契约适配器
- [x] 自治理与发布清单
- [x] 临时目录安装沙箱验收

这些模块存在于仓库或显式 profile 中，不进入普通任务默认上下文。自动化或
契约测试通过不等于对应外部宿主、账号、OAuth、模型和生产 ACL 已通过。

## 后续维护者验收（不阻塞默认 core）

- [ ] 完整质量 Skill 的真实 Agent 基线/启用后/盲测评估
- [ ] Codex CLI 原生启动、登录、模型与推理等级验收
- [ ] Codex Desktop 新任务发现、写任务和独立 Review 验收
- [ ] C7OpenWiki 真实只读事务与经确认写事务验收
- [ ] 正式 `.agents/.codex` 安装、发现、升级和回滚
- [ ] 生产目录 DACL/SDDL 与安全边界证据
- [ ] 版本发布候选和一次全局独立终审

任何未执行项都必须继续报告为 `unverified`，不得因默认 core 已可用而伪称整套
产品已经完成原生发布。
