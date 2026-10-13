---
name: tea-quality
description: Use for SelfWorkflow Full or Deep test design, ATDD planning, test-quality review, traceability, or NFR evidence review. Runs the pinned TEA workflows through a project-local-runtime-free adapter and must not require a project _bmad directory.
---

# TEA Quality Adapter

Use this Skill only for the SelfWorkflow stage that selected it. Keep all outputs inside the task's approved documentation or test paths.

## Required inputs

Require explicit `stage`, project root, approved requirements and acceptance criteria, final design/plan context, project rules, and output path. Reject missing values, path traversal, unresolved `{...}` variables, or output outside the approved paths.

Map stages to pinned references:

- `plan` → `references/bmad-testarch-test-design`
- `implementation` → `references/bmad-testarch-atdd`
- `review` → `references/bmad-testarch-test-review`
- `trace` → `references/bmad-testarch-trace`
- `nfr` → `references/bmad-testarch-nfr`
- 显式 `tea-framework` / Plan → `references/bmad-testarch-framework`（assessment-only）
- 显式 `tea-ci` / Verify 或发布前检查 → `references/bmad-testarch-ci`（assessment-only）

Read the selected reference's `SKILL.md`, then only the checklist, instructions, step files, templates, and resources required for this invocation. Never load all workflows.

For framework and ci, the packaged entry is the local assessment-only adapter.
Only its entry and checklist are available; never enter upstream Create/Edit,
scaffold a framework/pipeline, install dependencies, or execute input commands.
Existing frameworks are valid assessment targets. CI configuration findings and
actual CI run evidence are separate. Missing run evidence remains unverified.
These two optional modules supplement, and never replace, test-design or Verify.

## SelfWorkflow headless contract

- Before entering any upstream step, read [headless-contract.md](references/headless-contract.md). It owns the resolved paths, fixed defaults, per-workflow input mapping and single-output boundary. These overrides replace upstream bootstrap/configuration and multi-file progress writes.
- Preflight the selected reference, headless entry and (except framework/ci) `references/bmod-tea/knowledge/tea-index.csv` and its fragments at Capability Check. Do not wait until an upstream step tries to load a missing file. The packaged runtime validator binds these dependencies into `referenceHash`; missing or drifting files remain `unverified`.
- Treat the supplied requirements, rules, design, plan, test context, and output path as the resolved workflow context.
- Do not run the upstream greeting or interactive mode menu.
- Do not read or execute project `_bmad` scripts, configuration, team overrides, or user overrides. This adapter deliberately replaces that bootstrap.
- Resolve every upstream `{skill-root}` path from the selected reference directory. Resolve `{project-root}` only for read-only approved task inputs; writes remain limited to the supplied output path.
- Resolve `{tea-knowledge}` only to this adapter's `references/bmod-tea/knowledge`; `{knowledgeIndex}` is its `tea-index.csv`. Never search a project `_bmad` or another installation to repair a missing runtime dependency.
- `{tea-knowledge}` is `references/bmod-tea/knowledge` beside this adapter. Load its index once and only the fragments required by the current stage; do not enumerate or read the entire knowledge directory.
- SelfWorkflow alone schedules Review and authorization. Ignore upstream greeting, orchestration/team spawning, repeated confirmation, and checkpoint menus; reuse the task's single plan/test-design artifact and the existing independent reviewers. Upstream content supplies methods, not another workflow.
- Enter Create mode for new output and Validate mode for an existing supplied output. Never search for unstated stories, specs, or project files.
- Missing required reference files, unresolved variables, capability gaps, or unsafe paths are `unverified` and fail closed; do not substitute an improvised test process.

Catalog support describes the local adapter contract, not the current Host's execution. Upstream lock/adapter runtime and behavior evidence may remain `unverified`; a local `supported` entry does not promote them. Structural output validation proves binding and format only. Review still checks content and real evidence.

## Quality output

Preserve TEA's risk-based priorities and traceability. At minimum record scope, risks, acceptance criteria, test seams, direct and failure paths, state invariants, regression boundary, evidence gaps, and the applicable PASS / CONCERNS / FAIL result. Full uses test design and test review; Deep additionally uses trace and NFR when selected. ATDD creates RED acceptance scaffolding only after the implementation contract is confirmed.

Only for an explicit contract-managed V3 stage result, a Markdown file is not completion evidence by itself.
The host must pass the adapter-validated output through
`validate_packaged_output(..., binding=...)`; the resulting TEA receipt must
bind the current plan, attempt, stage, slot, selected module, and output hash.
`teaReceipts` are required for every selected TEA module when the stage is
marked `passed`; the host also supplies the current TEA runtime root so the
pinned reference hash is rechecked. A generic artifact hash, an unbound adapter
result, a stale receipt, or a missing runtime root is fail-closed and cannot
satisfy contract-mode Full/Deep completion. Ordinary agent-policy uses actual test-design/review findings and verification evidence without manufacturing a V3 receipt.
