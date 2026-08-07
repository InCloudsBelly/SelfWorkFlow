# SelfWorkFlow v1 精确暂存命令

执行任一命令前先确认 index 为空；执行后用 `git diff --cached --name-only` 与该命令逐项比对。不得把后续任务提前产生的文件混入提交。

## 批准计划提交

```powershell
git add -- 'docs/superpowers/plans/2026-08-07-selfworkflow-v1.md' 'docs/superpowers/plans/2026-08-07-selfworkflow-v1-native-acceptance.md' 'docs/superpowers/plans/2026-08-07-selfworkflow-v1-agent-eval.md' 'docs/superpowers/plans/2026-08-07-selfworkflow-v1-staging.md' 'docs/superpowers/plans/2026-08-07-selfworkflow-v1-checklist.md'
git commit -m "docs: add SelfWorkFlow v1 implementation plan"
```

## Task 1

```powershell
git add -- '.gitignore' 'pyproject.toml' 'requirements-dev.lock.txt' 'src/selfworkflow/__init__.py' 'src/selfworkflow/cli.py' 'tests/__init__.py' 'tests/test_smoke.py' 'tests/test_bootstrap_cli.py' 'tests/fixtures/bootstrap/fake-npm-cli.js' 'scripts/test.ps1' 'scripts/verify.ps1' 'scripts/bootstrap-codex-cli.ps1' 'scripts/lib/bootstrap-execution.ps1' 'scripts/lib/bootstrap-manifest.ps1' 'schemas/bootstrap-tool-manifest.schema.json' 'README.md' 'docs/design/2026-08-07-selfworkflow-design.md' 'docs/superpowers/plans/2026-08-07-selfworkflow-v1.md' 'docs/superpowers/plans/2026-08-07-selfworkflow-v1-native-acceptance.md' 'docs/superpowers/plans/2026-08-07-selfworkflow-v1-staging.md'
```

## Task 2

```powershell
git add -- 'workflow/lifecycle.yaml' 'workflow/policies.yaml' 'workflow/evidence.yaml' 'schemas/lifecycle.schema.json' 'schemas/policies.schema.json' 'schemas/evidence.schema.json' 'src/selfworkflow/config.py' 'src/selfworkflow/model.py' 'src/selfworkflow/classifier.py' 'tests/unit/__init__.py' 'tests/unit/test_config.py' 'tests/unit/test_classifier.py' 'tests/unit/test_capability_gate.py'
```

## Task 3

```powershell
git add -- 'workflow/protected-rules.yaml' 'schemas/protected-rules.schema.json' 'src/selfworkflow/evidence.py' 'WORKFLOW.md' 'tests/unit/test_protected_rules.py' 'tests/unit/test_evidence.py' 'tests/fixtures/evidence/valid.json' 'tests/fixtures/evidence/stale.json'
```

## Task 4

```powershell
git add -- 'schemas/catalog.schema.json' 'catalog/index.yaml' 'catalog/domains/workflow.yaml' 'catalog/domains/code-quality.yaml' 'catalog/domains/knowledge.yaml' 'src/selfworkflow/catalog.py' 'tests/unit/test_catalog.py' 'tests/fixtures/catalog/valid.yaml' 'tests/fixtures/catalog/duplicate-id.yaml' 'tests/fixtures/catalog/cycle.yaml' 'tests/fixtures/catalog/conflict.yaml'
```

## Task 5

```powershell
git add -- 'src/selfworkflow/router.py' 'tests/unit/test_router.py' 'tests/fixtures/router/cases.yaml'
```

## Task 6

```powershell
git add -- 'tests/behavioral/__init__.py' 'tests/behavioral/scenarios/code-quality.yaml' 'tests/behavioral/rubrics/code-quality.yaml' 'tests/behavioral/test_code_quality_scenarios.py' 'tests/behavioral/test_agent_eval_runner.py' 'tests/fixtures/agent-eval/fake-agent.py' 'docs/provenance/code-quality-baseline.md' 'imports/source-registry.yaml' 'imports/extraction-records/code-quality-v1.yaml' 'scripts/import-agent-eval.ps1' 'scripts/run-agent-eval.ps1' 'schemas/agent-eval-result.schema.json'
```

## Task 7

```powershell
git add -- 'skills/code-quality/SKILL.md' 'skills/workflow-quality/SKILL.md' 'capabilities/code-quality/ownership-and-invalidation.md' 'capabilities/code-quality/change-safety.md' 'capabilities/workflow-quality/evidence-and-operations.md' 'docs/provenance/code-quality-v1.md' 'catalog/domains/code-quality.yaml' 'catalog/domains/workflow.yaml' 'imports/extraction-records/code-quality-v1.yaml' 'tests/behavioral/scenarios/code-quality-blind.yaml' 'tests/behavioral/test_code_quality_scenarios.py'
```

## Task 7A

```powershell
git add -- 'src/selfworkflow/imports.py' 'schemas/source-registry.schema.json' 'schemas/extraction-record.schema.json' 'tests/unit/test_imports.py' 'tests/fixtures/imports/clean-source.yaml' 'tests/fixtures/imports/dirty-source.yaml' 'tests/fixtures/imports/project-specific.yaml' 'imports/source-registry.yaml'
```

## Task 8

```powershell
git add -- 'dependencies/superpowers.lock.yaml' 'src/selfworkflow/sources.py' 'tests/unit/test_sources.py' 'tests/fixtures/sources/official.yaml' 'tests/fixtures/sources/local-clean.yaml' 'tests/fixtures/sources/local-dirty.yaml'
```

## Task 8A

```powershell
git add -- 'overlays/superpowers/stage-map.yaml' 'overlays/superpowers/policies.yaml' 'skills/grill-me/SKILL.md' 'src/selfworkflow/superpowers.py' 'tests/unit/test_superpowers_overlay.py' 'tests/behavioral/scenarios/superpowers-routing.yaml' 'catalog/domains/workflow.yaml' 'WORKFLOW.md'
```

## Task 9

```powershell
git add -- 'tests/installer/__init__.py' 'tests/installer/test_doctor.py' 'tests/installer/test_plan.py' 'tests/installer/test_apply.py' 'tests/installer/test_rollback.py' 'tests/installer/test_recovery.py' 'tests/installer/test_locking.py' 'tests/fixtures/installer/layouts.yaml'
```

## Task 10

```powershell
git add -- 'src/selfworkflow/installer.py' 'src/selfworkflow/transactions.py' 'src/selfworkflow/managed_blocks.py' 'installer/install.ps1' 'schemas/install-plan.schema.json' 'schemas/install-manifest.schema.json' 'schemas/rollback-plan.schema.json' 'src/selfworkflow/cli.py' 'tests/installer/test_doctor.py' 'tests/installer/test_plan.py' 'tests/installer/test_apply.py' 'tests/installer/test_rollback.py' 'tests/installer/test_recovery.py' 'tests/installer/test_locking.py'
```

## Task 11

```powershell
git add -- 'adapters/codex/adapter.yaml' 'adapters/codex/AGENTS.managed.md' 'adapters/claude-code/adapter.yaml' 'adapters/claude-code/CLAUDE.managed.md' 'adapters/cursor/adapter.yaml' 'adapters/opencode/adapter.yaml' 'adapters/copilot/copilot-instructions.md' 'adapters/unknown/BOOTSTRAP.md' 'schemas/adapter.schema.json' 'src/selfworkflow/adapters.py' 'tests/conformance/__init__.py' 'tests/conformance/test_adapters.py' 'tests/conformance/test_runtime_snapshot.py'
```

## Task 12

```powershell
git add -- 'extensions/knowledge/contract.yaml' 'schemas/knowledge-contract.schema.json' 'src/selfworkflow/knowledge.py' 'tests/unit/test_knowledge_contract.py'
```

## Task 13

```powershell
git add -- 'extensions/knowledge/c7-openwiki/adapter.yaml' 'extensions/knowledge/c7-openwiki/SKILL.md' 'extensions/knowledge/c7-openwiki/tool-contract.json' 'extensions/knowledge/c7-openwiki/provenance.yaml' 'src/selfworkflow/c7_openwiki.py' 'tests/conformance/test_c7_openwiki_adapter.py' 'tests/fixtures/c7-openwiki/tool-contract.json' 'tests/fixtures/c7-openwiki/native-errors.json'
```

## Task 14

```powershell
git add -- 'WORKFLOW.md' 'README.md' 'CHANGELOG.md' 'docs/decisions/0001-deterministic-core.md' 'docs/releases/release-manifest.schema.json' 'src/selfworkflow/release.py' 'tests/conformance/test_release_gate.py' 'tests/behavioral/test_workflow_matrix.py' 'scripts/verify.ps1'
```

## Task 15

```powershell
git add -- 'tests/acceptance/__init__.py' 'tests/acceptance/test_install_sandbox.py' 'docs/releases/0.1.0-acceptance.md' 'scripts/verify.ps1'
```

## Task 16

```powershell
git add -- 'tests/acceptance/codex-cli/c0-readonly.md' 'tests/acceptance/codex-cli/c1-change-paused.md' 'tests/acceptance/codex-cli/c2r2-design.md' 'tests/acceptance/codex-cli/grill-explicit.md' 'tests/acceptance/codex-cli/missing-superpowers.md' 'tests/acceptance/codex-cli/skill-minimality.md' 'tests/acceptance/codex-cli/write-tdd.md' 'tests/acceptance/codex-cli/review-write-result.md' 'tests/acceptance/codex-cli/result.schema.json' 'docs/releases/evidence/codex-cli.md'
```

## Task 17

```powershell
git add -- 'tests/acceptance/codex-desktop/prompt.md' 'tests/acceptance/codex-desktop/write-tdd.md' 'tests/acceptance/codex-desktop/review-write-result.md' 'tests/acceptance/codex-desktop/result.schema.json' 'tests/acceptance/c7-openwiki/native.json' 'scripts/c7-openwiki-acceptance.mjs' 'docs/releases/evidence/codex-desktop.md' 'docs/releases/evidence/c7-openwiki.md'
```

## Task 18

```powershell
git add -- 'src/selfworkflow/__init__.py' 'CHANGELOG.md' 'docs/releases/0.1.0.json'
```
