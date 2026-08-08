# SelfWorkFlow Modular Workflow Orchestration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the V2 stateless modular workflow planner, explicit Host ledger contract, deterministic module slots, and Git repository boundary without implementing C7OpenWiki behavior.

**Architecture:** A checked-in Pipeline defines ordered slots and gates, Catalog V2 is the only runtime module registry, and the Resolver emits an immutable PlanGraph bound to request, policy, catalog, pipeline, and capability-evidence hashes. A separate RunLedger contract owns runtime results; thin Host adapters execute selected modules but cannot claim technical enforcement they do not provide.

**Tech Stack:** Python 3.11+, PyYAML, jsonschema Draft 2020-12, unittest, PowerShell verification scripts, JSON/YAML contracts.

**Spec:** `docs/superpowers/specs/2026-08-08-modular-workflow-orchestration-design.md`

**Working-tree constraint:** The branch already contains unrelated or earlier uncommitted installer/resolver work. Stage only paths listed by the current task, inspect every cached diff before committing, and never include frozen C7 paths.

**Frozen paths:**

```text
D:\openwikiC7\**
extensions/knowledge/c7-openwiki/**
src/selfworkflow/c7_openwiki.py
tests/conformance/test_c7_openwiki_adapter.py
tests/fixtures/c7-openwiki/**
```

---

## Preflight: Establish a clean first-version baseline

### Task 0: Verify and commit the already completed installer/Resolver work

This task does not add modular-orchestration behavior. It isolates the pre-existing dirty work
that belongs to the already approved one-click-installer and stateless-resolver specs, so later
tasks start from a reviewable baseline.

**Existing paths to audit and commit separately:**

```text
README.md
Install_SelfWorkFlow.bat
adapters/claude-code/CLAUDE.managed.md
adapters/codex/AGENTS.managed.md
adapters/copilot/copilot-instructions.md
adapters/cursor/CURSOR.managed.md
adapters/opencode/OPENCODE.managed.md
adapters/unknown/BOOTSTRAP.md
docs/superpowers/plans/2026-08-07-selfworkflow-v1-checklist.md
docs/superpowers/plans/2026-08-08-one-click-windows-installer.md
docs/superpowers/plans/2026-08-08-stateless-task-resolver.md
docs/superpowers/specs/2026-08-08-one-click-windows-installer-design.md
docs/superpowers/specs/2026-08-08-stateless-task-resolver-design.md
scripts/install-selfworkflow.ps1
src/selfworkflow/adapters.py
src/selfworkflow/cli.py
src/selfworkflow/installer.py
src/selfworkflow/resolver.py
src/selfworkflow/sources.py
src/selfworkflow/superpowers.py
tests/acceptance/test_workflow_resolution.py
tests/conformance/test_adapters.py
tests/conformance/test_runtime_snapshot.py
tests/installer/test_apply.py
tests/installer/test_one_click.py
tests/unit/__init__.py
tests/unit/test_resolver.py
tests/unit/test_sources.py
workflow/resolve-request.example.json
```

- [ ] **Step 1: Verify the existing scoped diff matches its two approved specs**

Inspect every listed path and confirm no frozen C7 path, credential, runtime artifact, or unrelated
feature is present. If the diff no longer matches its specs, repair and re-verify under those plans
before beginning Chunk 1.

- [ ] **Step 2: Run fresh prior-feature verification**

Run: `.\scripts\verify.ps1 -Suite installer`

Run: `.\.venv\Scripts\python.exe -m unittest tests.unit.test_resolver tests.acceptance.test_workflow_resolution tests.conformance.test_adapters tests.conformance.test_runtime_snapshot -v`

Run: `.\scripts\verify.ps1 -Suite automated`

Expected: all commands exit 0. A timeout or failure blocks the baseline commit.

- [ ] **Step 3: Stage only the explicit prior-feature paths**

Run these exact commands. Do not stage this modular plan or any new modular-orchestration file:

```powershell
git add -- README.md Install_SelfWorkFlow.bat
git add -- adapters/claude-code/CLAUDE.managed.md adapters/codex/AGENTS.managed.md adapters/copilot/copilot-instructions.md adapters/cursor/CURSOR.managed.md adapters/opencode/OPENCODE.managed.md adapters/unknown/BOOTSTRAP.md
git add -- docs/superpowers/plans/2026-08-07-selfworkflow-v1-checklist.md docs/superpowers/plans/2026-08-08-one-click-windows-installer.md docs/superpowers/plans/2026-08-08-stateless-task-resolver.md
git add -- docs/superpowers/specs/2026-08-08-one-click-windows-installer-design.md docs/superpowers/specs/2026-08-08-stateless-task-resolver-design.md
git add -- scripts/install-selfworkflow.ps1 workflow/resolve-request.example.json
git add -- src/selfworkflow/adapters.py src/selfworkflow/cli.py src/selfworkflow/installer.py src/selfworkflow/resolver.py src/selfworkflow/sources.py src/selfworkflow/superpowers.py
git add -- tests/acceptance/test_workflow_resolution.py tests/conformance/test_adapters.py tests/conformance/test_runtime_snapshot.py tests/installer/test_apply.py tests/installer/test_one_click.py tests/unit/__init__.py tests/unit/test_resolver.py tests/unit/test_sources.py
git diff --cached --check
git diff --cached --name-only
git diff --cached --stat
```

Expected: only the audited prior-feature paths are staged.

- [ ] **Step 4: Commit the prior work as its own first-version baseline**

Run: `git commit -m "feat: add first-version resolver and Windows setup"`

Expected: commit succeeds and `git status --short` contains only this modular plan before it is
committed separately.

## Chunk 1: Contract foundation and Catalog V2

### Task 1: Define Pipeline, Plan, StageResult, and RunLedger contracts

**Files:**
- Create: `workflow/pipeline.yaml`
- Create: `schemas/pipeline.schema.json`
- Create: `schemas/plan-graph.schema.json`
- Create: `schemas/stage-result.schema.json`
- Create: `schemas/run-ledger.schema.json`
- Create: `src/selfworkflow/pipeline.py`
- Create: `tests/unit/test_pipeline.py`
- Create: `tests/unit/test_contract_schemas.py`

- [ ] **Step 1: Write failing Pipeline and Schema tests**

Cover the fixed stage order, unique slot IDs, allowed cardinalities, closed condition operators, valid invocation kinds, PlanGraph hash fields, typed artifact/evidence references, and RunLedger state vocabulary. Add negative fixtures in the tests themselves for duplicate slots, unknown operators, arbitrary evidence paths, and two active stages.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.unit.test_pipeline tests.unit.test_contract_schemas -v`

Expected: FAIL because the schemas and `selfworkflow.pipeline` do not exist.

- [ ] **Step 3: Add the minimal contracts**

Define these stage IDs in order: `discovered`, `capability-checked`, `classified`, `designed`, `planned`, `implemented`, `reviewed`, `verified`, `completed`. Represent Knowledge read/propose/update as optional slots, not a new persisted lifecycle stage.

The condition AST must use only `all`, `any`, `not`, `eq`, `gte`, and `contains`, with operands restricted to normalized request fields declared by the spec. Implement a bounded YAML loader and deterministic canonical hash helper in `pipeline.py`; reuse existing bounded-value helpers where practical instead of duplicating security limits.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `.\.venv\Scripts\python.exe -m unittest tests.unit.test_pipeline tests.unit.test_contract_schemas -v`

Expected: PASS.

- [ ] **Step 5: Run contract-adjacent regression tests**

Run: `.\.venv\Scripts\python.exe -m unittest tests.unit.test_classifier tests.unit.test_capability_gate tests.unit.test_protected_rules tests.unit.test_evidence -v`

Expected: PASS.

- [ ] **Step 6: Commit only the contract foundation**

Run:

```powershell
git add -- workflow/pipeline.yaml schemas/pipeline.schema.json schemas/plan-graph.schema.json schemas/stage-result.schema.json schemas/run-ledger.schema.json src/selfworkflow/pipeline.py tests/unit/test_pipeline.py tests/unit/test_contract_schemas.py
git diff --cached --check
git diff --cached --name-only
git commit -m "feat: define modular workflow contracts"
```

Expected: only Task 1 paths are committed.

### Task 2: Upgrade Catalog to module-aware V2

**Files:**
- Modify: `schemas/catalog.schema.json`
- Modify: `catalog/index.yaml`
- Modify: `catalog/domains/workflow.yaml`
- Modify: `catalog/domains/code-quality.yaml`
- Modify: `catalog/domains/knowledge.yaml`
- Modify: `src/selfworkflow/catalog.py`
- Modify: `src/selfworkflow/router.py`
- Modify: `tests/unit/test_catalog.py`
- Modify: `tests/unit/test_router.py`
- Modify: `tests/unit/test_superpowers_overlay.py`

- [ ] **Step 1: Write failing Catalog V2 tests**

Test module slot references, activation enum, invocation kind/ref, closed side-effect declarations, four support-evidence layers, source integrity, duplicate module IDs, dangling slot IDs, incompatible cardinality, and the exact deterministic ordering `mandatory > explicit > repository default > deterministic > priority > stable ID`.

Assert semantic terms never select a Primary or Gate in V2.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.unit.test_catalog tests.unit.test_router tests.unit.test_superpowers_overlay -v`

Expected: FAIL on missing V2 module fields and pipeline-aware validation.

- [ ] **Step 3: Implement Catalog V2 and deterministic slot routing**

Keep non-executable content entries valid, but require the module block for executable entries. Validate every module slot against the compiled Pipeline. Keep Catalog source identity separate from external runtime evidence. Add Superpowers stage selection metadata to Catalog entries; keep the already committed `stage-map.yaml` unchanged as a source/compatibility declaration rather than a second runtime mapping.

Catalog source files referenced by new entries must already exist in a commit. Agent-native modules may bind to the Task 1 Pipeline commit; Superpowers modules may bind to the unchanged committed stage-map. If any referenced source must change, commit that source first and refresh revision/hash metadata in a separate follow-up commit. Never point Catalog at uncommitted bytes.

- [ ] **Step 4: Remove semantic auto-selection from V2 routing**

The router may report bounded semantic recommendations, but V2 `selectedModules` can contain only mandatory, explicit, default, and deterministic candidates. Unsupported optional modules are excluded with a typed reason; unsupported Primary/Gate candidates pause resolution.

- [ ] **Step 5: Run focused and conformance tests**

Run: `.\.venv\Scripts\python.exe -m unittest tests.unit.test_catalog tests.unit.test_router tests.unit.test_superpowers_overlay tests.conformance.test_runtime_snapshot -v`

Expected: PASS.

- [ ] **Step 6: Commit the Catalog migration**

Run:

```powershell
git add -- schemas/catalog.schema.json catalog/index.yaml catalog/domains/workflow.yaml catalog/domains/code-quality.yaml catalog/domains/knowledge.yaml src/selfworkflow/catalog.py src/selfworkflow/router.py tests/unit/test_catalog.py tests/unit/test_router.py tests/unit/test_superpowers_overlay.py
git diff --cached --check
git diff --cached --name-only
git commit -m "feat: register workflow modules in catalog v2"
```

Expected: no frozen C7 path is staged, and every Catalog revision/hash points to committed bytes.

## Chunk 2: PlanGraph Resolver and Host RunLedger

### Task 3: Implement the V2 request, capability snapshot, and PlanGraph

**Files:**
- Create: `schemas/resolve-request.schema.json`
- Create: `schemas/resolve-result.schema.json`
- Create: `src/selfworkflow/request_v2.py`
- Create: `src/selfworkflow/capability_snapshot.py`
- Create: `src/selfworkflow/plan_graph.py`
- Modify: `src/selfworkflow/resolver.py`
- Modify: `src/selfworkflow/classifier.py`
- Modify: `src/selfworkflow/cli.py`
- Modify: `workflow/resolve-request.example.json`
- Modify: `tests/unit/test_resolver.py`
- Modify: `tests/acceptance/test_workflow_resolution.py`

- [ ] **Step 1: Write failing 32-cell strength and ResolveResult tests**

Define the pure precedence: Deep when `C3`, `R3`, or `C2/R2`; Full when `C2` or `R2`; otherwise Light. Cross with `writeTask` true/false for 32 cases. For read-only plans, modification slots must be statically N/A while complex Design may remain applicable.

Test active, paused, and redacted-invalid paths; stable reason codes; capability snapshot canonicalization; plan hash stability; capability identity/freshness changes invalidating requestHash and planHash; and diagnostics that do not echo untrusted request text.

- [ ] **Step 2: Run resolver tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.unit.test_resolver tests.acceptance.test_workflow_resolution -v`

Expected: FAIL because the current resolver accepts only a single-stage V1 request.

- [ ] **Step 3: Implement V2 resolution**

Keep responsibilities separate: `request_v2.py` validates and migrates request shape;
`capability_snapshot.py` normalizes and hashes capability evidence; `plan_graph.py` builds and
hashes the immutable graph; `resolver.py` is a small facade that composes those units.

Return `ResolveResult {schemaVersion, status, reasonCodes, diagnostics, planGraph}`. PlanGraph contains only static conditions, selected modules, gates, failure owners, static N/A decisions, and bound hashes. Runtime skips, attempts, and gate outcomes must not appear.

Use stable reason codes from the spec. A well-formed but unsatisfied request returns paused; malformed input raises the existing redacted `ResolveError` pattern.

- [ ] **Step 4: Implement the explicit V1 request migrator**

Accept Schema V1 input through a named migration function. Preserve its task fields but mark declaration-only capability evidence as legacy/unverified unless the caller supplies V2 freshness evidence. Do not silently invent timestamps, provider receipts, or supported behavior. Record compatibility through a typed diagnostic using the existing ResolveResult fields; do not add an undeclared top-level field.

- [ ] **Step 5: Run resolver and CLI acceptance tests**

Run: `.\.venv\Scripts\python.exe -m unittest tests.unit.test_resolver tests.acceptance.test_workflow_resolution tests.test_smoke -v`

Expected: PASS.

- [ ] **Step 6: Commit V2 PlanGraph resolution**

Run:

```powershell
git add -- schemas/resolve-request.schema.json schemas/resolve-result.schema.json src/selfworkflow/request_v2.py src/selfworkflow/capability_snapshot.py src/selfworkflow/plan_graph.py src/selfworkflow/resolver.py src/selfworkflow/classifier.py src/selfworkflow/cli.py workflow/resolve-request.example.json tests/unit/test_resolver.py tests/acceptance/test_workflow_resolution.py
git diff --cached --check
git diff --cached --name-only
git commit -m "feat: resolve immutable modular workflow plans"
```

Expected: only Task 3 paths are committed from the clean Task 0 baseline.

### Task 4: Implement the explicit Host RunLedger contract

**Files:**
- Create: `src/selfworkflow/ledger.py`
- Create: `tests/unit/test_ledger.py`
- Modify: `src/selfworkflow/model.py`
- Modify: `src/selfworkflow/cli.py`

- [ ] **Step 1: Write failing ledger transition tests**

Cover planHash/requestHash binding, one active stage, pending-to-active-to-terminal transitions, immutable prior attempts, optional runtime skips with evidence, Gate result binding, failureOwner return, superseding on replan, and rejection of a changed/expired capability snapshot.

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.unit.test_ledger -v`

Expected: FAIL because `selfworkflow.ledger` does not exist.

- [ ] **Step 3: Implement minimal pure ledger operations**

Implement validation and transition functions only. Do not add a daemon, database, task scheduler, automatic retry engine, or persistence service. The Host may hold the ledger in conversation memory or its own storage.

- [ ] **Step 4: Add CLI validation without task execution**

Add a read-only command that validates a RunLedger against its PlanGraph and reports stable errors. It must not execute a Skill, MCP, command, or file mutation.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `.\.venv\Scripts\python.exe -m unittest tests.unit.test_ledger tests.unit.test_resolver tests.acceptance.test_workflow_resolution -v`

Expected: PASS.

- [ ] **Step 6: Commit the Host boundary**

Run:

```powershell
git add -- src/selfworkflow/ledger.py src/selfworkflow/model.py src/selfworkflow/cli.py tests/unit/test_ledger.py
git diff --cached --check
git diff --cached --name-only
git commit -m "feat: validate host workflow ledgers"
```

Expected: only Task 4 paths are committed.

### Task 5: Remove duplicate Superpowers runtime mapping and prove module order

**Files:**
- Modify: `src/selfworkflow/superpowers.py`
- Modify: `tests/behavioral/scenarios/superpowers-routing.yaml`
- Modify: `tests/behavioral/test_workflow_matrix.py`
- Modify: `tests/unit/test_superpowers_overlay.py`
- Modify: `tests/unit/test_resolver.py`

- [ ] **Step 1: Write failing tests for Catalog-only runtime selection**

Prove default Brainstorming, explicit Grill-me followed by independent Brainstorming cross-review, Writing Plans, TDD/Systematic Debugging, Review, and Verification are selected from Catalog/Pipeline data. Add an explicit failing source-structure test that the old Python runtime stage-map constant no longer exists; this remains RED after Task 2 even though V2 resolution already prefers Catalog.

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.unit.test_superpowers_overlay tests.unit.test_resolver tests.behavioral.test_workflow_matrix -v`

Expected: FAIL because the duplicate hard-coded mapping still exists.

- [ ] **Step 3: Reduce `superpowers.py` to source/support helpers**

Keep source selection, missing-source policy, dirty-state evidence, and compatibility helpers. Remove the duplicated stage-to-Skill runtime decision table. V1 compatibility may call the V2 resolver; it must not maintain a second mapping.

- [ ] **Step 4: Run routing and behavior tests**

Run: `.\.venv\Scripts\python.exe -m unittest tests.unit.test_superpowers_overlay tests.unit.test_resolver tests.behavioral.test_workflow_matrix tests.behavioral.test_code_quality_scenarios -v`

Expected: PASS.

- [ ] **Step 5: Commit the single-source selection change**

Run:

```powershell
git add -- src/selfworkflow/superpowers.py tests/behavioral/scenarios/superpowers-routing.yaml tests/behavioral/test_workflow_matrix.py tests/unit/test_superpowers_overlay.py tests/unit/test_resolver.py
git diff --cached --check
git diff --cached --name-only
git commit -m "refactor: make catalog authoritative for module order"
```

Expected: only Task 5 paths are committed.

## Chunk 3: Git boundary, Host adapters, and release verification

### Task 6: Implement deterministic Git index policy

**Files:**
- Create: `workflow/git-policy.yaml`
- Create: `schemas/git-policy.schema.json`
- Create: `src/selfworkflow/git_policy.py`
- Create: `tests/unit/test_git_policy.py`
- Modify: `.gitignore`
- Modify: `src/selfworkflow/cli.py`

- [ ] **Step 1: Write failing policy tests in temporary Git repositories**

Cover HEAD/index/staged blobs, case-normalized paths, symlink, submodule, binary, ignored runtime roots, allowed `.env.example`, forbidden `.env.local`, SQLite/WAL, known-secret heuristic redaction, 1 MiB warning, 5 MiB failure, and an allowlist entry requiring reason/hash/owner/expiry.

Add a negative acceptance assertion that the current feature diff contains no frozen C7 path.

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.unit.test_git_policy -v`

Expected: FAIL because the policy and scanner do not exist.

- [ ] **Step 3: Implement bounded index/blob inspection**

Inspect names, modes, and bounded blob metadata without printing secret content. Use exact runtime roots from the spec, not broad words such as `manifest`, `snapshot`, or `history`. The secret check reports only known patterns and never claims proof of absence.

- [ ] **Step 4: Add the read-only CLI check and extend `.gitignore`**

The command must return stable warning/failure codes and perform no staging or mutation. Keep `.env.example`, `.env.sample`, legitimate manifests, and redacted fixtures usable.

- [ ] **Step 5: Run focused tests and the policy against the repository**

Run: `.\.venv\Scripts\python.exe -m unittest tests.unit.test_git_policy -v`

Run: `.\.venv\Scripts\python.exe -m selfworkflow.cli git-policy check --repo .`

Expected: Tests PASS; repository scan reports no unallowlisted failure for tracked/staged first-party files.

- [ ] **Step 6: Commit Git hygiene**

Run:

```powershell
git add -- workflow/git-policy.yaml schemas/git-policy.schema.json src/selfworkflow/git_policy.py tests/unit/test_git_policy.py .gitignore src/selfworkflow/cli.py
git diff --cached --check
git diff --cached --name-only
git commit -m "feat: guard workflow repository boundaries"
```

Expected: only Task 6 paths are committed.

### Task 7: Update thin Host adapters and user documentation

**Files:**
- Modify: `adapters/codex/AGENTS.managed.md`
- Modify: `adapters/claude-code/CLAUDE.managed.md`
- Modify: `adapters/cursor/CURSOR.managed.md`
- Modify: `adapters/opencode/OPENCODE.managed.md`
- Modify: `adapters/copilot/copilot-instructions.md`
- Modify: `adapters/unknown/BOOTSTRAP.md`
- Modify: `src/selfworkflow/adapters.py`
- Modify: `README.md`
- Modify: `WORKFLOW.md`
- Modify: `tests/conformance/test_adapters.py`
- Modify: `tests/conformance/test_runtime_snapshot.py`

- [ ] **Step 1: Write failing adapter conformance tests**

Require thin adapters to identify the V2 resolve command, PlanGraph/RunLedger boundary, refusal of paused plans, selected-stage-only loading, critical-decision-only prompting, and truthful `conforming` versus `agent-policy` support. Require Knowledge wording to stay generic and C7 implementation to remain deferred.

- [ ] **Step 2: Run conformance tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.conformance.test_adapters tests.conformance.test_runtime_snapshot -v`

Expected: FAIL against the V1 managed blocks.

- [ ] **Step 3: Update adapters and concise documentation**

Keep managed blocks thin. Document the call sequence, module override semantics, Grill recommendation/confirmation, Review/Verify guarantees, Knowledge deferral, and extension recipe. Do not embed full schemas or every module body in Agent startup instructions.

- [ ] **Step 4: Run conformance and installer regression tests**

Run: `.\.venv\Scripts\python.exe -m unittest tests.conformance.test_adapters tests.conformance.test_runtime_snapshot tests.installer.test_apply tests.installer.test_one_click -v`

Expected: PASS.

- [ ] **Step 5: Commit adapters and docs**

Task 0 must have committed the earlier adapter/README work, so these paths start clean. Run:

```powershell
git add -- adapters/codex/AGENTS.managed.md adapters/claude-code/CLAUDE.managed.md adapters/cursor/CURSOR.managed.md adapters/opencode/OPENCODE.managed.md adapters/copilot/copilot-instructions.md adapters/unknown/BOOTSTRAP.md src/selfworkflow/adapters.py README.md WORKFLOW.md tests/conformance/test_adapters.py tests/conformance/test_runtime_snapshot.py
git diff --cached --check
git diff --cached --name-only
git commit -m "docs: expose modular workflow to host agents"
```

Expected: only Task 7 paths are committed. If Task 0 did not establish a clean baseline, stop rather than stage mixed changes.

### Task 8: Full verification, independent Review, and first-version commit audit

**Files:**
- Modify as needed: `docs/superpowers/plans/2026-08-08-modular-workflow-orchestration.md`
- Modify as needed: `docs/superpowers/specs/2026-08-08-modular-workflow-orchestration-design.md`
- Do not modify: frozen C7 paths

- [ ] **Step 1: Run format and diff checks**

Run: `git diff --check`

Run: `.\.venv\Scripts\python.exe -m selfworkflow.cli git-policy check --repo .`

Expected: no whitespace error and no unallowlisted Git policy failure.

- [ ] **Step 2: Run the focused modular workflow suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.unit.test_pipeline tests.unit.test_contract_schemas tests.unit.test_catalog tests.unit.test_router tests.unit.test_resolver tests.unit.test_ledger tests.unit.test_superpowers_overlay tests.unit.test_git_policy tests.behavioral.test_workflow_matrix tests.conformance.test_adapters tests.conformance.test_runtime_snapshot tests.acceptance.test_workflow_resolution -v
```

Expected: exit 0. Record the test count in the final verification evidence after execution; the plan does not invent a count in advance.

- [ ] **Step 3: Run the repository automated suite**

Run: `.\scripts\verify.ps1 -Suite automated`

Expected: exit 0. If it times out or fails, record the exact failing command and do not claim the full suite passed.

- [ ] **Step 4: Audit the complete diff and frozen scope**

Check correctness, full acceptance coverage, failure paths, security, invasiveness, unrelated changes, and generated files. Run all four path audits from the real design commit `3ff07d6`:

```powershell
git diff --name-only 3ff07d6..HEAD
git diff --cached --name-only
git diff --name-only
git ls-files --others --exclude-standard
```

Filter each result for the frozen C7 paths and confirm no match. Confirm no personal Wiki/runtime/credential file is tracked.

- [ ] **Step 5: Dispatch one independent final reviewer**

Provide only the approved spec, implementation diff, test evidence, skipped checks, and residual risks. Fix Critical/Important findings, rerun affected tests, and repeat Review once. Do not provide Grill-me transcripts or private reasoning.

- [ ] **Step 6: Run fresh verification after Review fixes**

Repeat targeted tests, Git policy, `git diff --check`, and the full automated suite when affected.

- [ ] **Step 7: Update the plan with exact evidence**

Record commands, exit codes, counts, skipped native Agent checks, and unverified boundaries. Keep raw logs out of Git.

- [ ] **Step 8: Audit staging for the first-version Git submission**

Use `git diff --cached --name-only` and `git diff --cached --check`. Installer and V1 Resolver work must already be isolated in Task 0 and must not be restaged here. Confirm only modular-orchestration sources, tests, approved specifications, and final plans are staged. Do not automatically push or open a PR.

Preferred final integration commit message: `feat: add modular self workflow orchestration`
