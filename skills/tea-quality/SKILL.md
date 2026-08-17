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

Read the selected reference's `SKILL.md`, then only the checklist, instructions, step files, templates, and resources required for this invocation. Never load all five workflows.

## SelfWorkflow headless contract

- Treat the supplied requirements, rules, design, plan, test context, and output path as the resolved workflow context.
- Do not run the upstream greeting or interactive mode menu.
- Do not read or execute project `_bmad` scripts, configuration, team overrides, or user overrides. This adapter deliberately replaces that bootstrap.
- Resolve every upstream `{skill-root}` path from the selected reference directory. Resolve `{project-root}` only for read-only approved task inputs; writes remain limited to the supplied output path.
- Enter Create mode for new output and Validate mode for an existing supplied output. Never search for unstated stories, specs, or project files.
- Missing required reference files, unresolved variables, capability gaps, or unsafe paths are `unverified` and fail closed; do not substitute an improvised test process.

## Quality output

Preserve TEA's risk-based priorities and traceability. At minimum record scope, risks, acceptance criteria, test seams, direct and failure paths, state invariants, regression boundary, evidence gaps, and the applicable PASS / CONCERNS / FAIL result. Full uses test design and test review; Deep additionally uses trace and NFR when selected. ATDD creates RED acceptance scaffolding only after the implementation contract is confirmed.

For a V3 stage result, a Markdown file is not completion evidence by itself.
The host must pass the adapter-validated output through
`validate_packaged_output(..., binding=...)`; the resulting TEA receipt must
bind the current plan, attempt, stage, slot, selected module, and output hash.
`teaReceipts` are required for every selected TEA module when the stage is
marked `passed`; the host also supplies the current TEA runtime root so the
pinned reference hash is rechecked. A generic artifact hash, an unbound adapter
result, a stale receipt, or a missing runtime root is fail-closed and cannot
satisfy Full/Deep completion.
