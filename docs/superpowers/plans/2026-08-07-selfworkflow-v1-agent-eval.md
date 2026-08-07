# SelfWorkFlow v1 Agent Eval 子计划

前置：原生验收 A1 已验证现有 CLI，或 A2 的独立 bootstrap 已获用户确认并完成。`<verified-codex.cmd>`、`<baseline-run>`、`<skilled-run>` 和 `<blind-run>` 必须替换为本次实际绝对路径；runner 将它们写入证据并拒绝不存在或 hash 不符的路径。

## Baseline

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run-agent-eval.ps1 -AgentCommand <verified-codex.cmd> -Scenario tests/behavioral/scenarios/code-quality.yaml -Schema schemas/agent-eval-result.schema.json -OutputRoot artifacts/agent-evals -TimeoutSeconds 600 -Model gpt-5.6-sol -ReasoningEffort xhigh -Mode baseline
```

预期 runner 退出 0、输出符合 Schema，且 rubric 至少一个关键项未命中；若全部命中，增强场景后重新建立真实 baseline，不能伪造失败。

## Skilled

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run-agent-eval.ps1 -AgentCommand <verified-codex.cmd> -Scenario tests/behavioral/scenarios/code-quality.yaml -Schema schemas/agent-eval-result.schema.json -OutputRoot artifacts/agent-evals -TimeoutSeconds 600 -Model gpt-5.6-sol -ReasoningEffort xhigh -Mode skilled -Skill skills/code-quality/SKILL.md
```

预期 runner 退出 0，隔离仓库只安装目标 Skill，所有关键项命中，禁止项为零。

## Blind（Skill hash 锁定后生成）

先固定 skilled run 所用的 `skills/code-quality/SKILL.md` hash。然后启动一个未接收实现上下文的独立审查者，要求它新生成 blind 场景到实现工作树之外的受控临时目录；场景在此刻以前不存在。审查者只返回文件路径和 hash，不返回答案给实现上下文。Skill hash 此后若变化，本轮 blind 立即失效。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run-agent-eval.ps1 -AgentCommand <verified-codex.cmd> -Scenario <reviewer-generated-blind-scenario> -Schema schemas/agent-eval-result.schema.json -OutputRoot artifacts/agent-evals -TimeoutSeconds 600 -Model gpt-5.6-sol -ReasoningEffort xhigh -Mode blind -Skill skills/code-quality/SKILL.md
```

预期 runner 退出 0；证据记录生成时间晚于 Skill hash 锁定时间，且 runner 输入 hash 与审查者返回值一致。评分完成后才把该场景复制为 `tests/behavioral/scenarios/code-quality-blind.yaml` 并提交，用于未来回归；它不再被描述成后续版本的盲测。

## Independent Review

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run-agent-eval.ps1 -AgentCommand <verified-codex.cmd> -Scenario tests/behavioral/rubrics/code-quality.yaml -Schema schemas/agent-eval-result.schema.json -OutputRoot artifacts/agent-evals -TimeoutSeconds 600 -Model gpt-5.6-sol -ReasoningEffort xhigh -Mode review -InputRun <blind-run>
```

预期新的只读进程只收到 rubric、脱敏输出和证据，不收到 Grill-me/实现推理；Critical/Important 为零。任一调用超时、模型/effort 降级、Schema 失败、隔离 tree 漂移或退出码非零，均使 eval 失败并禁止发布 Skill。
