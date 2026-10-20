# Light 模式

适用：低复杂度、低风险、范围清楚的只读或小修改任务。

- 只读直接分析；修改做紧凑 Design/Plan、适用的实施契约和最小充分验证。权限、证据复用与异常隔离遵循启动入口。
- 窄自审按 `workflow/modules/review.md`，不冒充独立 SubAgent Review；行为变更的 TDD 按 `testing-review-quality`。
- 不自动 Grill 或 TEA；只加载当前命中的能力，不重读已在上下文的启动入口。
