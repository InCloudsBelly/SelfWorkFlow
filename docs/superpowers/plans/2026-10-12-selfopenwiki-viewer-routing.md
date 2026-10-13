# SelfOpenWiki Viewer Default Routing Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the new SelfOpenWiki `zxh_wiki_viewer` the only default Wiki visualization route and route Wiki summary/update intents to the bound SelfWiki backend.

**Architecture:** SelfOpenWiki owns a live, versioned Viewer contract exposed by `openwiki_status`. Its `Visualize.bat` launcher accepts an explicit absolute `--wiki-root`, validates it, injects it into the Viewer, and remains loopback-only. SelfWorkflow validates that live contract, constructs the launcher command, and applies the `knowledge` profile’s SelfWiki default route without guessing paths or falling back to old OpenWiki/Agent Markdown content.

**Tech Stack:** Python 3.11+ (`unittest`, YAML/JSON contract tests), Node.js 22, TypeScript/Zod, Node test runner, pnpm 10.33.2, Windows batch launcher.

---

## Implementation Contract

- Scope is limited to SelfOpenWiki Viewer contract/launcher behavior, SelfWorkflow SelfOpenWiki adapter and knowledge routing rules, their tests, and directly associated documentation.
- The existing `upstream/openwiki` submodule is not modified.
- Existing user changes in both repositories are preserved; no reset, checkout, cleanup, commit, or push is performed for implementation files.
- The old `.work/openwiki/dist/cli/cli.js visualize` path is removed from the default adapter route and is not retained as an implicit fallback.
- Viewer startup must use the live `openwiki_status.paths.wikiRoot`; a missing or incompatible Viewer contract fails closed.
- `knowledge.read` remains fail-closed when SelfOpenWiki does not expose a verified safe query capability; it must not read Agent-local Markdown or silently select `legacy_provider`.

## File Map

### SelfOpenWiki

- Modify `scripts/visualize.mjs`: parse and validate `--wiki-root`, use it as the only explicit Viewer root override, and preserve loopback URL generation.
- Modify `self-openwiki/mcp-server/src/contracts.ts`: describe the optional live `visualizer` status contract.
- Modify `self-openwiki/mcp-server/src/runtime.ts`: include the validated Viewer contract in full and minimal status responses.
- Modify `self-openwiki/mcp-server/src/bootstrap.ts` and `self-openwiki/mcp-server/src/index.ts`: bind the host-owned `Visualize.bat` path and pass it through runtime construction without guessing from `openWikiRoot`.
- Modify `self-openwiki/mcp-server/test/contracts.c7.ts` and `self-openwiki/mcp-server/test/runtime.c7.ts`: test status schema and runtime binding/rejection behavior.
- Modify `test/visualize-script.test.mjs`: test explicit Wiki root parsing, validation, environment injection, and storage fallback.
- Modify `self-openwiki/agent-skills/self-openwiki/SKILL.md` and `self-openwiki/agent-skills/self-openwiki/references/mcp-contract.md`: document Viewer ownership, status-first routing, and no legacy fallback.

### SelfWorkflow

- Modify `src/selfworkflow/selfopenwiki.py`: validate the live Viewer contract and construct the `Visualize.bat` command with live Wiki root and loopback URL.
- Modify `tests/conformance/test_selfopenwiki_adapter.py`: replace the old OpenWiki CLI fixture and add contract rejection/root-binding tests.
- Modify `extensions/knowledge/selfopenwiki/adapter.yaml` and `extensions/knowledge/selfopenwiki/tool-contract.json`: describe the new Viewer contract and default routing boundary without machine-specific paths.
- Modify `skills/kg-selfopenwiki/SKILL.md` and `workflow/modules/knowledge.md`: route Wiki visualization/summary/update intents to SelfWiki and prohibit Agent-local Wiki/legacy fallback.
- Modify `extensions/knowledge/contract.yaml` and `schemas/knowledge-contract.schema.json`: make the `knowledge` profile’s default SelfWiki routing explicit and schema-validated.
- Modify `tests/unit/test_knowledge_contract.py`: verify the default routing contract and its no-fallback policy.
- Modify `tests/conformance/test_runtime_snapshot.py` only if the changed runtime artifact needs an additional stable-file assertion; do not add private paths or runtime evidence.

## Chunk 1: SelfOpenWiki Launcher Contract

### Task 1: Add red tests for explicit Wiki root injection

**Files:**
- Test: `D:\SelfOpenWiki\test\visualize-script.test.mjs`

- [ ] **Step 1: Extend the parser test with `--wiki-root` and invalid values.**

  Assert that `parseVisualizeArgs(["--wiki-root", "D:\\wiki_zxh", "--port", "3000"])` returns the normalized option, rejects a missing value, and rejects a relative root.

- [ ] **Step 2: Add a test proving an explicit root bypasses storage configuration.**

  Inject a fake `existsSync`/directory validator and a `readStorageConfig` that throws if called; assert `runVisualize(["--wiki-root", "D:\\wiki_zxh"])` starts with `SELFOPENWIKI_WIKI_ROOT=D:\\wiki_zxh` and returns the expected loopback URL.

- [ ] **Step 3: Run the focused test and verify it fails for the missing option/behavior.**

  Run from `D:\SelfOpenWiki`:

  ```text
  corepack pnpm@10.33.2 exec node --test test/visualize-script.test.mjs
  ```

  Expected: FAIL because the current parser rejects `--wiki-root` and always reads storage.

### Task 2: Implement the launcher override minimally

**Files:**
- Modify: `D:\SelfOpenWiki\scripts\visualize.mjs`
- Modify: `D:\SelfOpenWiki\Visualize.bat` only if help text or argument forwarding requires it.

- [ ] **Step 1: Add `wikiRoot` to parsed options and accept only `--wiki-root <absolute>`.**

  Keep `--production`, `--port`, and `--help` behavior unchanged. Reject empty, relative, or repeated values.

- [ ] **Step 2: Validate the override as an existing non-link directory before spawning.**

  Reuse the existing error boundary and return a safe diagnostic; never use an arbitrary path or infer a path from the process working directory.

- [ ] **Step 3: Select the explicit root when present, otherwise read configured storage.**

  Pass the selected root through `createVisualizeProcessSpec`, keep `SELFOPENWIKI_WIKI_ROOT`, `127.0.0.1`, and `/wiki/local` unchanged.

- [ ] **Step 4: Run the focused Node tests and verify they pass.**

  Expected: all visualization tests PASS.

## Chunk 2: SelfOpenWiki Live Status Contract

### Task 3: Add the Viewer status schema and red contract tests

**Files:**
- Modify: `D:\SelfOpenWiki\self-openwiki\mcp-server\src\contracts.ts`
- Modify: `D:\SelfOpenWiki\self-openwiki\mcp-server\test\contracts.c7.ts`

- [ ] **Step 1: Define a strict optional `visualizer` status object.**

  Require the fixed Viewer ID, contract schema `1`, absolute launcher path, `loopbackOnly=true`, `autoOpen=false`, `wikiRootInput.kind="argument"`, `wikiRootInput.flag="--wiki-root"`, and the URL template `http://127.0.0.1:{port}/wiki/local`.

- [ ] **Step 2: Add acceptance and rejection cases.**

  Accept the new contract and reject a non-loopback URL, wrong input flag, non-absolute launcher, old Viewer ID, and unknown fields. Keep the field optional so older status consumers remain parseable, while the host adapter will require it for visualization.

- [ ] **Step 3: Run the contract test before runtime changes.**

  Run from `D:\SelfOpenWiki`:

  ```text
  corepack pnpm@10.33.2 --dir self-openwiki/mcp-server exec vitest run test/contracts.c7.ts --maxWorkers=1
  ```

  Expected: the new schema cases fail until runtime fixtures are updated, while unrelated contract cases remain unchanged.

### Task 4: Bind the launcher from SelfOpenWiki runtime

**Files:**
- Modify: `D:\SelfOpenWiki\self-openwiki\mcp-server\src\runtime.ts`
- Modify: `D:\SelfOpenWiki\self-openwiki\mcp-server\src\bootstrap.ts`
- Modify: `D:\SelfOpenWiki\self-openwiki\mcp-server\src\index.ts`
- Modify: `D:\SelfOpenWiki\self-openwiki\mcp-server\test\runtime.c7.ts`

- [ ] **Step 1: Add a runtime option for the host-owned launcher path.**

  Require an absolute regular `Visualize.bat` path when constructing a full runtime; keep the field optional in test/minimal runtimes so unavailable Viewer state is represented by omission, not fabrication.

- [ ] **Step 2: Emit the strict Viewer contract from full status and minimal status when available.**

  `index.ts` passes `path.join(hostRoot, "Visualize.bat")` (or an explicit environment override used only for controlled installation/tests). `bootstrap.ts` verifies the path without deriving it from `paths.openWikiRoot`.

- [ ] **Step 3: Add runtime tests for live launcher binding and absent launcher behavior.**

  Assert status carries the expected absolute fixture path and that a missing launcher does not produce an invented path.

- [ ] **Step 4: Run SelfOpenWiki contract and runtime tests.**

  Expected: both suites PASS after updating the shared valid status fixture with the optional Viewer object.

## Chunk 3: SelfOpenWiki Documentation and Verification Surface

### Task 5: Document Viewer ownership and version boundary

**Files:**
- Modify: `D:\SelfOpenWiki\self-openwiki\agent-skills\self-openwiki\SKILL.md`
- Modify: `D:\SelfOpenWiki\self-openwiki\agent-skills\self-openwiki\references\mcp-contract.md`

- [ ] **Step 1: Add the Viewer status-first procedure.**

  Document that visualization uses the new `zxh_wiki_viewer` launcher, injects `paths.wikiRoot`, opens only the returned loopback URL, and never calls the legacy OpenWiki CLI by default.

- [ ] **Step 2: Document fail-closed behavior.**

  State that missing/old Viewer contracts are `unverified`; do not guess `SelfOpenWiki` root, read Agent Markdown, or fall back to `legacy_provider`.

- [ ] **Step 3: Run skill and repository contract tests.**

  Run from `D:\SelfOpenWiki`:

  ```text
  corepack pnpm@10.33.2 test
  ```

  If the capability fingerprint becomes stale, rebuild the MCP package and run the existing capability verification path; do not modify unrelated user files.

## Chunk 4: SelfWorkflow Adapter and Default Routing

### Task 6: Add red tests for live Viewer command construction

**Files:**
- Modify: `D:\SelfWorkFlow\tests\conformance\test_selfopenwiki_adapter.py`

- [ ] **Step 1: Extend the fake status with a valid live Viewer contract.**

  Use a temporary absolute launcher fixture and `paths.wikiRoot`; do not place machine-specific paths in checked-in contracts.

- [ ] **Step 2: Replace the old CLI expectation with the batch launcher command.**

  Assert the command passes the live root via `--wiki-root`, uses the requested port, and returns the loopback URL contract. Assert the repository-root/old `.work/openwiki` fixture is no longer consulted.

- [ ] **Step 3: Add fail-closed cases.**

  Cover missing Viewer, wrong ID, non-loopback URL, launcher path mismatch, root mismatch, and invalid port.

- [ ] **Step 4: Run the focused Python test and verify the new expectations fail first.**

  Run from `D:\SelfWorkFlow`:

  ```text
  py -m unittest tests.conformance.test_selfopenwiki_adapter -v
  ```

### Task 7: Implement the SelfWorkflow Viewer adapter

**Files:**
- Modify: `D:\SelfWorkFlow\src\selfworkflow\selfopenwiki.py`

- [ ] **Step 1: Add strict validation for the live Viewer contract.**

  Validate the fixed ID/schema, absolute existing launcher, loopback-only URL template, disabled auto-open, and exact `--wiki-root` injection descriptor.

- [ ] **Step 2: Make `visualizer_command` status-driven.**

  Call the live status boundary, take `paths.wikiRoot` as authoritative, reject a caller-supplied different root, validate the port, and construct `cmd.exe /d /s /c "<Visualize.bat> --wiki-root <root> --port <port>"` plus the returned loopback URL/spec. Do not accept or derive the old OpenWiki CLI path.

- [ ] **Step 3: Run the focused adapter tests to green.**

  Expected: all existing personal lifecycle tests and new Viewer tests PASS.

### Task 8: Make SelfWiki the default knowledge route

**Files:**
- Modify: `D:\SelfWorkFlow\extensions\knowledge\contract.yaml`
- Modify: `D:\SelfWorkFlow\schemas\knowledge-contract.schema.json`
- Modify: `D:\SelfWorkFlow\skills\kg-selfopenwiki\SKILL.md`
- Modify: `D:\SelfWorkFlow\workflow\modules\knowledge.md`
- Modify: `D:\SelfWorkFlow\extensions\knowledge\selfopenwiki\adapter.yaml`
- Modify: `D:\SelfWorkFlow\extensions\knowledge\selfopenwiki\tool-contract.json`
- Modify: `D:\SelfWorkFlow\tests\unit\test_knowledge_contract.py`

- [ ] **Step 1: Add a schema-validated default route declaration.**

  Declare that profile `knowledge` maps Wiki visualization, summary, organization, and update intents to `selfopenwiki`, with `fallback: forbidden`; keep explicit `legacy_provider` as an opt-in override only.

- [ ] **Step 2: Update the host Skill instructions.**

  Require `openwiki_status` before every route, use the live SelfWiki root, and state that a missing safe read capability reports `unverified` rather than reading Agent-owned Markdown.

- [ ] **Step 3: Update adapter contracts without private paths.**

  Replace the old OpenWiki CLI visualizer declaration with the status-driven SelfOpenWiki launcher contract and record the default route semantics.

- [ ] **Step 4: Add unit assertions for default backend and no fallback.**

  Validate the YAML against the schema and assert that the contract contains the SelfWiki default and forbidden fallback.

- [ ] **Step 5: Run focused SelfWorkflow tests.**

  ```text
  py -m unittest tests.unit.test_knowledge_contract tests.conformance.test_selfopenwiki_adapter -v
  ```

## Chunk 5: Full Verification and Review

### Task 9: Run targeted and integration checks

- [ ] **Step 1: Run SelfOpenWiki visualization and contract tests.**

  ```text
  corepack pnpm@10.33.2 exec node --test test/visualize-script.test.mjs test/repository-contract.test.mjs
  corepack pnpm@10.33.2 --dir self-openwiki/mcp-server exec vitest run test/contracts.c7.ts test/runtime.c7.ts --maxWorkers=1
  ```

- [ ] **Step 2: Run SelfWorkflow targeted suite.**

  ```text
  py -m unittest tests.unit.test_knowledge_contract tests.conformance.test_selfopenwiki_adapter tests.conformance.test_runtime_snapshot -v
  ```

- [ ] **Step 3: Run repository-wide checks proportionate to the changed surfaces.**

  Run `corepack pnpm@10.33.2 test` in `D:\SelfOpenWiki` and the SelfWorkflow test command used by the existing project (`py -m unittest discover -s tests -p "test*.py"`). Record any pre-existing failure separately; do not repair unrelated failures.

- [ ] **Step 4: Perform a diff and boundary review.**

  Confirm there is no `.work/openwiki/dist/cli.js visualize` default route, no private Wiki path, no credential/runtime evidence, no upstream submodule change, no hidden browser auto-open, and no changes outside the approved files.

- [ ] **Step 5: Verify installation artifact.**

  Rebuild the SelfWorkflow knowledge runtime with the existing installer path, verify the installed `kg-selfopenwiki` Skill and adapter contract contain the new route, and report the exact test counts and any `unverified` capability honestly.

## Completion Criteria

- New SelfOpenWiki status exposes the validated Viewer contract when `Visualize.bat` is available.
- `Visualize.bat --wiki-root <absolute>` starts the new Viewer with the exact bound Wiki root and loopback URL.
- SelfWorkflow’s default visualizer command consumes the live SelfOpenWiki status and never uses the old OpenWiki CLI fallback.
- `knowledge` profile routes Wiki visualization/summary/update intents to SelfWiki; no Agent-local Wiki or silent legacy fallback is used.
- Focused tests and repository-wide checks provide fresh evidence, and all unrelated existing worktree changes remain untouched.
