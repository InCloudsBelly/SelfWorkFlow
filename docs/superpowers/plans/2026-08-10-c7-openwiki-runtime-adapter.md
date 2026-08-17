# C7OpenWiki Runtime Adapter Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a truthful, optional SelfWorkFlow-to-C7OpenWiki knowledge path with revision-bound updates, real stdio verification, and a Codex installation entry.

**Architecture:** C7OpenWiki owns Wiki snapshots, CAS, models, sources, Skills, publication, and review. SelfWorkFlow owns vendor-neutral lifecycle mapping, explicit module routing, runtime packaging, and host guidance; the core profile remains independent.

**Tech Stack:** TypeScript/Zod/Vitest/MCP SDK, Python 3 standard library/unittest/jsonschema, PowerShell installer checks, Node.js stdio harness.

---

## Chunk 1: C7 revision contract and orchestration policy

### Task 1: Bind reads and updates to Wiki revisions

**Files:**
- Modify: `D:\openwikiC7\c7-openwiki\mcp-server\src\contracts.ts`
- Modify: `D:\openwikiC7\c7-openwiki\mcp-server\src\runtime.ts`
- Modify: `D:\openwikiC7\c7-openwiki\mcp-server\src\query.ts`
- Modify: `D:\openwikiC7\c7-openwiki\mcp-server\src\update.ts`
- Test: `D:\openwikiC7\c7-openwiki\mcp-server\test\contracts.c7.ts`
- Test: `D:\openwikiC7\c7-openwiki\mcp-server\test\runtime.c7.ts`
- Test: `D:\openwikiC7\c7-openwiki\mcp-server\test\query.c7.ts`
- Test: `D:\openwikiC7\c7-openwiki\mcp-server\test\update.c7.ts`
- Test: `D:\openwikiC7\c7-openwiki\mcp-server\test\server.c7.ts`

- [x] Add tests requiring `wikiRevision`, `expectedWikiRevision`, `baseWikiRevision`, and `conflict`.
- [x] Run the four focused test files and capture the expected Red failures.
- [x] Implement locked revision capture in the C7 owning layer; reject stale updates before
      transaction/model execution and keep a non-null revision on transaction failure.
- [x] Run focused tests, typecheck, and contract/server regression to Green.

### Task 2: Align the external Agent Skill with the global design policy

**Files:**
- Modify: `D:\openwikiC7\c7-openwiki\agent-skills\kg-c7-openwiki\SKILL.md`
- Modify: `D:\openwikiC7\c7-openwiki\agent-skills\kg-c7-openwiki\references\mcp-contract.md`
- Modify: `D:\openwikiC7\c7-openwiki\agent-skills\kg-c7-openwiki\evals\run-eval.mjs`

- [x] Add a failing eval proving ordinary updates use default Brainstorming and do not force Grill-me.
- [x] Keep explicit/accepted Grill-me and final `confirmedByUser` behavior distinct.
- [x] Update Skill/reference minimally and run Skill validation/eval to Green.

## Chunk 2: SelfWorkFlow knowledge adapter and modular runtime

### Task 3: Implement the generic lifecycle mapping

**Files:**
- Modify: `src/selfworkflow/c7_openwiki.py`
- Modify: `src/selfworkflow/knowledge.py`
- Modify: `src/selfworkflow/codex_mcp.py`
- Modify: `extensions/knowledge/c7-openwiki/tool-contract.json`
- Modify: `extensions/knowledge/c7-openwiki/adapter.yaml`
- Modify: `extensions/knowledge/c7-openwiki/SKILL.md`
- Test: `tests/conformance/test_c7_openwiki_adapter.py`
- Test: `tests/unit/test_knowledge_contract.py`

- [x] Add failing tests for execute(read/propose/update), revision mapping, conflict, and status spelling.
- [x] Implement an explicit status mapping and a bounded opaque `nativeResult` channel for Host reporting.
- [x] Run focused tests to Green and reject contract drift.

### Task 4: Package C7 only in the explicit Knowledge profile and V3 slots

**Files:**
- Modify: `src/selfworkflow/adapters.py`
- Modify: `src/selfworkflow/installer.py`
- Modify: `workflow/v3/pipeline.yaml`
- Modify: `catalog/modules.yaml`
- Modify: `tests/conformance/test_runtime_snapshot.py`
- Modify: `tests/unit/v3/test_pipeline.py`
- Modify: `tests/unit/test_catalog.py`
- Modify: `README.md`

- [x] Add failing tests proving core exclusion, knowledge inclusion, installed Skill presence, and explicit V3 slots.
- [x] Copy only the generic contract and C7 adapter assets into the knowledge snapshot.
- [x] Keep activation explicit and support evidence truthful until native verification completes.
- [x] Cover ownership-aware `knowledge -> core` Skill retirement, drift refusal, and rollback.
- [x] Run profile/catalog/pipeline tests to Green.

## Chunk 3: Native evidence, installation, and review

### Task 5: Refresh C7 capability evidence and exercise stdio

**Files:**
- Modify if required: `D:\openwikiC7\c7-openwiki\scripts\verify-capabilities.mts`
- Use: `D:\openwikiC7\c7-openwiki\mcp-server\scripts\smoke-mcp.mjs`

- [x] Run `pnpm verify:capabilities` from `D:\openwikiC7\c7-openwiki`.
- [x] Confirm no tracked user file outside the approved C7 source/test/docs scope was modified by this increment.
- [x] Run a fresh stdio initialize/tools-list/status harness and record exact evidence.

### Task 6: Regress, install, and review

**Files:**
- Modify: `src/selfworkflow/codex_mcp.py`
- Modify: `src/selfworkflow/cli.py`
- Test: `tests/unit/test_codex_mcp.py`
- Modify: runtime/installation state only after repository tests pass.

- [x] Run the narrow C7 and SelfWorkFlow suites, then each repository's full relevant verifier.
- [x] Build/install the SelfWorkFlow `knowledge` profile without changing the independent C7 source boundary.
- [x] Implement and test transactional Codex stdio configuration: exact idempotence, conflict,
      invalid TOML, missing paths, atomic failure recovery, backup, and restart-required.
- [x] Add the conflict-free Codex stdio MCP entry through that boundary, verify TOML and note restart requirement.
- [x] Put Codex outside the C7 operation bound with 120-second startup and 72,000-second tool timeouts; migrate only the exact legacy managed block and preserve unmanaged conflicts.
- [x] Compare design, plan, complete diff, failure paths, security, invasiveness, and unrelated changes.
- [ ] Dispatch one independent final reviewer; fix material findings and rerun affected tests.

### Task 7: Close independent-review gaps

- [x] Make the public update output schema structurally non-null for `baseWikiRevision`.
- [x] Add revision capture/binding/conflict behavior to the repository Agent Skill, reference and eval.
- [x] Preserve proposal content/hash and structured MCP error/recovery; fail closed on invalid runtime
      status, missing capability evidence, recovery blocks or contract/provenance drift.
- [x] Gate Codex configuration on current capability evidence plus real stdio smoke, and add
      cross-process locking, preimage checking and concurrent-safe rollback.
- [x] Re-run both repositories' full verification and refresh provenance/install state.
- [x] Conduct a fresh independent final review; apply its two P1 and bounded P2 findings,
      then run focused post-review verification.

### Task 8: Rebind the stabilized C7 backend and restore Knowledge composability

**Files:**
- Modify: `catalog/v3/modules/knowledge-update.yaml`
- Modify: `extensions/knowledge/c7-openwiki/tool-contract.json`
- Modify: `extensions/knowledge/c7-openwiki/provenance.yaml`
- Modify: `catalog/v3/modules/knowledge-read.yaml`
- Modify: `catalog/v3/modules/knowledge-propose.yaml`
- Modify: `src/selfworkflow/knowledge.py`
- Test: `tests/unit/test_knowledge_contract.py`
- Test: `tests/unit/v3/test_catalog.py`
- Test: `tests/unit/v3/test_plan_graph.py`
- Test: `tests/unit/v3/test_cpp_router.py`
- Test: `tests/conformance/test_c7_openwiki_adapter.py`

- [x] Reproduce the two ordinary C++ plan failures and locate the invalid cross-slot dependency.
- [x] Compare the frozen binding with current C7 status and `contracts.ts`; record contract drift and
      the new bounded `diagnostic` / `failureStage` fields.
- [x] Add Red tests for safe failure detail preservation, Knowledge module composability and current
      source-hash binding. Freeze C7 `contracts.ts` at
      `sha256:e412bff3f39cffce164559f28b85cefe77e34d53d45269000f4ce2b85d66d976`;
      require provenance/frozen-contract/three V3 source hashes to agree. Cover `diagnostic` at
      1/4096/4097 characters, empty/wrong types, all four public failure stages, unknown stage and
      unknown field.
- [x] Remove only the invalid cross-slot module dependency; retain pipeline order, explicit activation,
      confirmation and CAS guards.
- [x] Refresh the frozen contract/provenance hashes without modifying the independent C7 repository.
- [x] Run focused Green tests, including `test_plan_graph.py` cross-slot rejection and update
      confirmation/CAS regressions; assert `src/selfworkflow/v3/plan_graph.py` is unchanged. Then run
      the complete affected regression surface, a real status/query scenario that asserts
      initialized/authorized/clean, default `gpt-5.6-sol/xhigh`, unchanged `wikiRevision` and no Wiki
      publication, installer verification and an independent final Review.

## Execution evidence

- C7 MCP: the full MCP test suite passed; Prettier passed.
- C7 capability verifier: clean build, two Skill validations, scenario eval and stdio status passed; latest evidence ID `fc424e35-117d-4d12-a13e-a5c188c1d8d6`.
- SelfWorkFlow: final full run passed 457 tests after the independent-review repairs.
- Formal runtime: installed profile is `knowledge`; artifact hash is `sha256:9a12b0acc4601b5cc0d27650c18a5981b281e8e4940b069287c0ba102d1442ee`; manifest verify/doctor passed and installed Skill hash matched the repository source. Final install evidence is in `install-20260810-141143-238`.
- Codex config: first call returned `configured/restartRequired`, second call returned `already-configured`; TOML exact entry and single backup verified.
- Historical Task 1–7 C7 stdio snapshot: exact seven tools and 22 capabilities succeeded; that old
  snapshot reported `initialized:false` and `authentication:not_configured`. It is not the current
  runtime claim; Task 8 records fresh initialized/authenticated/model/query evidence separately.

### Task 8 execution evidence

- TDD Red: the new safe error-details test lost `error`, the stabilized-contract test saw the old
  `contracts.ts` hash, the Knowledge catalog retained a cross-slot dependency, and the two ordinary
  C++ plans failed before activation. After the minimal owner-layer changes, all five direct tests pass.
- Affected SelfWorkFlow regression: 104 tests pass, including Knowledge contract/adapter, runtime
  snapshot, Codex MCP configuration, V3 pipeline/catalog/PlanGraph/C++ routing. `git diff --check`
  passes and `src/selfworkflow/v3/plan_graph.py` has no diff.
- Current C7 source binding: `contracts.ts` is
  `sha256:e412bff3f39cffce164559f28b85cefe77e34d53d45269000f4ce2b85d66d976`;
  frozen tool contract and all three V3 Knowledge modules use
  `sha256:dfe403c151f45a9b98d7860e3f686b4b73ef6becd564c589e24c601d0518d105`.
- Fresh built stdio smoke reports MCP `0.1.1`, exact seven tools and candidate Review before
  publication. A real formal-runtime query reports initialized/authorized/clean, default
  `gpt-5.6-sol/xhigh`, `status: answered`, provider-accepted exact request/sent combination and
  identical before/query/after Wiki revision
  `sha256:b25bffb963347fac6ca8732e08db5f824efca266ee45196403f1639e9e507ec9`;
  no update was called and the query reported no publication.
- The already-running Codex MCP process in this task was still `0.1.0` and returned the historical
  generic `process_failure`; a separately launched current `0.1.1` process passed. Native Agent
  discovery therefore remains truthfully restart-bound.
- Knowledge profile reinstall succeeded with artifact
  `sha256:81892d78441f6bf6a9539caeaed616e4bb65a356555020780fa4b149e8ff7496`;
  manifest verify/doctor passed and installed catalog, frozen contract and provenance hashes were
  reread. Install evidence: `install-20260811-161943-993`.
- Independent final Review found that unhashable list/dict `failureStage` values could escape the
  generic failure-closed path and that whitespace-only diagnostic lacked direct coverage. Both were
  added to the boundary matrix; list/dict reproduced the expected Red while whitespace confirmed the
  existing rejection. The type guard was fixed minimally, the same 104-test suite passed again, and
  the same reviewer returned `Pass`. The idempotent reinstall/verify evidence is
  `install-20260811-162814-022`.

## Task 9: Route knowledge execution through host SubAgents

**SelfWorkFlow files:**
- Modify: `extensions/knowledge/c7-openwiki/SKILL.md`
- Modify: `extensions/knowledge/c7-openwiki/adapter.yaml`
- Modify: `extensions/knowledge/c7-openwiki/tool-contract.json`
- Modify: `extensions/knowledge/c7-openwiki/provenance.yaml`
- Modify: `src/selfworkflow/c7_openwiki.py`
- Test: `tests/conformance/test_c7_openwiki_adapter.py`

- [x] Freeze only the C7-owned minimum for `openwiki_begin_external_update` and
      `openwiki_finalize_external_update`; do not hard-code unfinished error enums, issue limits,
      rule filenames or `repair_ready` payload shape.
- [x] Require both external capability IDs and `externalAgent.ready`; ignore legacy OAuth/model
      readiness and fail closed without calling `openwiki_update`.
- [x] Route candidate writing and independent Review to host SubAgents while preserving the complete
      C7 work package, candidate-only permissions, hash/revision bindings and C7-only publication.
- [x] Put `openwiki_query` and `openwiki_update` behind explicit legacy-provider opt-in; default
      generic read/propose reports that the not-yet-frozen external query capability is unavailable.
- [x] Add TDD coverage for default routing, status/capability gates, complete work packages,
      source binding, review/failure/abort actions and forbidden model-evidence claims.
- [x] Require C7-generated `requestPackage` in writer/reviewer packages and route resume by persisted
      candidate/review/repair/terminal state without rebuilding materials or confusing a read-only
      Review package with a writable candidate.
- [x] Rebind `mcp-contracts`, capability evidence and native behavior only after the independent C7
      implementation publishes matching source bytes and real stdio evidence.
- [x] Reinstall the Knowledge profile only after both repositories pass focused regressions and an
      independent final Review. Until then the installed historical adapter is not the new mode.

## Task 10: Joint two-repository Review and end-to-end acceptance

- [x] Receive the final C7 exact HEAD, built stdio entry, live schemas, capability evidence and
      source/build/contract hashes; verify them before changing SelfWorkflow provenance.
- [x] Run one coordinated 双仓整体 Review over both complete diffs and the installation contract.
      Critical/Important findings must be zero on both sides; otherwise fix, retest and repeat.
- [x] Run a 完整端到端流程测试 for default `external_agent` 无 OAuth:
      status dual-capability gate → begin → Writer candidate → prepare_review → independent Reviewer
      → submit → atomic publication.
- [x] Exercise host failure/resume, `needs_clarification` → confirmed abort, crash recovery,
      legacy 显式 opt-in and every error/drift fail-closed boundary.
- [x] Verify the formal Wiki and runtime state after every failure path, then compare both repository
      diffs, provenance, frozen schemas/hashes, build evidence and proposed installation bytes.
- [x] Only after all evidence is current and both sides have no Critical/Important findings, update
      provenance from implementation-pending, install the Knowledge profile and verify the installed
      artifact. Before that point, 不得安装 or claim end-to-end completion.

Task 10 的未安装态联合验证绑定 C7 clean HEAD
`73b8229ffb75bf4151ce019a95b3b23946202f84` 与 capability build
`ca6f8f0c-2729-4d25-9e25-9d403ee03256`。真实 built-stdio 已覆盖默认 external status、
Writer failure/resume、Writer 候选、Review prepare、Reviewer failure/resume、独立 Reviewer
pass 与原子发布；另一事务覆盖 `needs_clarification` 后 confirmed abort，正式 Wiki revision
保持不变。C7 fresh verifier 为 612/612，快照 TOCTOU 修复后的两路独立 Review 均为
0 Critical / 0 Important / 0 Minor。SelfWorkflow 第一轮联合 Review 的剩余 findings 已按
TDD 收敛，最终独立 Review 与安装门禁仍在执行，因此当前 provenance 明确标记为
`verified-uninstalled`。该 source provenance 绑定的是安装候选字节，不把自身伪装成
机器安装收据；真正的安装完成状态只由 StateRoot current manifest、installed-byte verify
与 stdio preflight 证明。当前任务本身不会因安装态变化重新发现 MCP，新的 Codex 任务
需在重启后验证发现。
