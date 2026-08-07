# SelfWorkFlow v1 执行清单

每项只有在对应 Red/Green、相关回归、规格 Review 和质量 Review 均有新鲜证据后才能勾选。

- [x] Task 1：开发与测试入口
- [x] Task 2：状态、C/R 与能力门禁
- [ ] Task 3：受保护不变量与证据门禁
- [ ] Task 4：Catalog 编译器
- [ ] Task 5：最小充分 Skill 路由
- [ ] Task 6：代码质量失败基线
- [ ] Task 7：内建代码与工作流质量 Skill
- [ ] Task 7A：外部 Skill 吸收机制
- [ ] Task 8：Superpowers 来源探测与锁定
- [ ] Task 8A：Superpowers 覆盖层与稳定 Skill
- [ ] Task 9：安装安全 fixture
- [ ] Task 10：事务安装器
- [ ] Task 11：厂商薄适配器
- [ ] Task 12：通用知识契约
- [ ] Task 13：C7OpenWiki MCP 适配器
- [ ] Task 14：自治理与发布清单
- [ ] Task 15：安装沙箱验收
- [ ] Task 16：Codex CLI 真实验收
- [ ] Task 17：Codex Desktop 与 C7OpenWiki 真实验收
- [ ] Task 18：最终验证与发布候选

原生发布子门禁：

- [ ] 需要 bootstrap 时已获确认，写入前 DACL/SDDL 验证通过，且正式 installer 已接管或专用目录已卸载
- [ ] Codex CLI 隔离写任务完成 Red/Green、独立 Review 与确定性最终验证
- [ ] Codex Desktop 隔离写任务完成 Red/Green、独立新任务 Review 与最终验证
- [ ] C7OpenWiki update 已获本次测试写入确认，且正式 Wiki tree hash 未变化
- [ ] 正式 `.agents/.codex` 安装计划已获确认并通过发现/rollback
- [ ] `0.1.0.dev0 -> 0.1.0 -> 0.1.0.dev0 -> 0.1.0` 四阶段 hash/SDDL 证据完整
