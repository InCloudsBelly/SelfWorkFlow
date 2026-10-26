---
name: tea-quality
description: Use only when the user explicitly requests TEA test design, ATDD, test review, traceability, NFR, framework or CI assessment. Full/Deep tasks, test levels, ordinary testing and workflow maintenance do not trigger TEA. Uses pinned references without a project _bmad directory.
---

# TEA Quality Adapter

Use this Skill only after an explicit user request selects the current TEA workflow. Mode, test level and project defaults are not authorization. Keep outputs inside approved paths; reuse the one existing Reviewer and never spawn another review team.

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

Before any upstream step, read [headless-contract.md](references/headless-contract.md). It alone owns bootstrap replacement, resolved paths, fixed defaults, workflow input mapping and the single approved output. Do not run project `_bmad`, greetings, menus, team orchestration, repeated confirmations or checkpoint writes; SelfWorkflow owns scheduling and authorization.
At Capability Check verify the selected entry, this contract and, except framework/ci, `references/bmod-tea/knowledge/tea-index.csv` and required fragments. Load the index once and only current-stage fragments. Missing/drifting references, capabilities, unresolved variables or unsafe paths are fail-closed `unverified`; never search another installation or improvise a replacement process.
Create new supplied output; Validate existing supplied output. Never search for unstated stories/specs or expand project inputs. Catalog support and structural validation prove only the local adapter/binding, not Host execution, upstream verification or real test results; the headless contract defines evidence limits.

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
