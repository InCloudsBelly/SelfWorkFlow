# Post-Landing Review and Decision Records Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require Review after implementation or document landing, continue from reviewed intermediate documents into implementation, and permit only tightly bounded minor decisions to follow a recorded SubAgent recommendation.

**Architecture:** Keep the fixed Pipeline and Host-driven workflow. Add one closed `decision-record` contract plus semantic validator, make `document` a real write operation through an agent-native implementation module, and express Review/decision behavior in the vendor-neutral core with thin adapter reminders. Decision usage remains agent-policy; record validation is mechanical.

**Tech Stack:** Python 3.11+, JSON Schema Draft 2020-12, YAML Catalog/Pipeline, unittest, Markdown adapters.

**Spec:** `docs/superpowers/specs/2026-08-08-modular-workflow-orchestration-design.md`

---

## Chunk 1: Contracts and routing

### Task 1: Closed decision-record contract

**Files:**
- Create: `schemas/decision-record.schema.json`
- Create: `src/selfworkflow/decision_record.py`
- Modify: `tests/unit/test_contract_schemas.py`

- [x] Write failing tests for a valid independent recommendation, valid structured self-review, unknown fields, oversize/bad counts, dangling recommendation/selection IDs, unequal recommendation/selection, and false mode/independence pairs.
- [x] Also cover duplicate alternative IDs, input immutability/deep-copy output, and redacted errors that never echo `question` or summaries.
- [x] Run `\.venv\Scripts\python.exe -m unittest tests.unit.test_contract_schemas -v` and confirm RED because the Schema/validator do not exist.
- [x] Implement a closed Schema and `validate_decision_record(value)` that returns a normalized deep copy or raises a stable redacted `DecisionRecordError`.
- [x] Require unique alternative IDs, both IDs to reference an alternative, `selectedId == recommendationId`, and the two fixed mode/independence combinations.
- [x] Rerun the focused tests and confirm GREEN.
- [x] Commit only Task 1 paths with `feat: validate minor decision records`.

### Task 2: Make pure documentation a routable write operation

**Files:**
- Modify: `workflow/pipeline.yaml`
- Modify: `catalog/modules.yaml`
- Modify: `catalog/domains/workflow.yaml`
- Modify: `src/selfworkflow/request_v2.py`
- Modify: `tests/unit/test_pipeline.py`
- Modify: `tests/unit/test_resolver.py`
- Modify: `tests/unit/test_router.py`
- Modify: `tests/acceptance/test_workflow_resolution.py`

- [x] Add a failing resolver test for `operationType=document, writeTask=true`; require `implement-documentation`, `implement-result-gate`, `review-self`, and Verify modules in order with an active plan.
- [x] Add a failing request test that rejects `operationType=document, writeTask=false`.
- [x] Add a failing `route_skills(document)` test proving the vendor-neutral `workflow-core` entry is selected.
- [x] Add a failing Pipeline test requiring `implement.method` to allow `agent-native` as well as `skill`.
- [x] Run the focused tests and confirm RED because no document implementation module exists.
- [x] Add supported `implement-documentation` to `implement.method`, default only for `document`, requiring `filesystem-write`, with local-write side effects and no invented external capability.
- [x] Add `document` to `implement-result-gate` and to the `workflow-core` Catalog selectors/mandatory operation list.
- [x] Allow `agent-native` in the implementation-method slot and rerun the focused tests.
- [x] Commit Task 2 paths with `feat: route reviewed documentation changes`.

## Chunk 2: Cross-Agent policy and evidence

### Task 3: Land reviewed Host policy and thin adapters

**Files:**
- Modify: `WORKFLOW.md`
- Modify: `workflow/core.md`
- Modify: `README.md`
- Modify: `adapters/codex/AGENTS.managed.md`
- Modify: `adapters/claude-code/CLAUDE.managed.md`
- Modify: `adapters/cursor/CURSOR.managed.md`
- Modify: `adapters/opencode/OPENCODE.managed.md`
- Modify: `adapters/copilot/copilot-instructions.md`
- Modify: `adapters/unknown/BOOTSTRAP.md`
- Modify: `src/selfworkflow/ledger.py`
- Modify: `schemas/run-ledger.schema.json`
- Modify: `tests/conformance/test_adapters.py`
- Modify: `tests/behavioral/test_workflow_matrix.py`
- Modify: `tests/unit/test_ledger.py`
- Modify: `tests/unit/test_contract_schemas.py`
- Verify existing binding: `tests/unit/test_evidence.py`

- [x] Write failing policy/conformance assertions for post-landing Review, document Gate Review before continuing, pure-document Review/Verify, strict minor-decision criteria, `decision-record`, recommendation equality, and critical-decision escalation.
- [x] Write failing Ledger tests for appending a unique attempt to an active Review stage while rejecting pending/terminal stages, duplicate attempt refs, stale capability snapshots, and plan mismatch.
- [x] Require structured slot/Gate/skip records to bind the current attempt. After appending a Review attempt, prove old attempt results remain auditable but no longer satisfy stage completion until the new attempt records its own passing results.
- [x] Write RunLedger v2 Schema tests for closed structured attempt/result records and explicit rejection of legacy v1, unknown attempt refs, cross-stage refs, duplicate global attempt refs, duplicate results, and broken ordinal/previous chains.
- [x] Add a CLI test proving a v1 Ledger returns `ledger-schema-version-unsupported` without echoing its content.
- [x] Run `\.venv\Scripts\python.exe -m unittest tests.conformance.test_adapters tests.behavioral.test_workflow_matrix -v` and confirm RED.
- [x] Run `\.venv\Scripts\python.exe -m unittest tests.unit.test_ledger tests.unit.test_contract_schemas -v` and confirm RED because v2 structures and `record_stage_attempt` do not exist.
- [x] Update the vendor-neutral core first, then keep adapters to one compact reminder that tells Hosts to read the core rather than copying all rules.
- [x] State that implementation fixes stay in the active Review attempt; only static PlanGraph input changes re-plan. Review receipts bind final document or diff hashes.
- [x] Implement `record_stage_attempt` as a fail-closed RunLedger helper that validates the current plan/snapshot, active stage, bounded unique ref, and appends without changing prior evidence.
- [x] Upgrade RunLedger to schemaVersion 2. Store attempts as `{attemptRef,ordinal,previousAttemptRef}` and results as `{attemptRef,moduleId,resultRef}`, `{attemptRef,gateId,outcome,resultRef}`, and `{attemptRef,slotId,evidenceRef}`; make `_requirements_met` consider only the latest attempt.
- [x] Validate ordinal continuity and exact previous links, plus global attemptRef uniqueness and same-stage result ownership.
- [x] Reject slot/Gate `resultRef` replay across attempts, validate runtime-skip evidence against the current capability snapshot or same-attempt Gate result, and let a valid optional-slot skip waive only that slot's current-attempt module results.
- [x] Keep `runtimeSkip.evidenceRef` compatible with the capability contract (1–256 characters), align ordinary helper IDs with the Schema's colon-aware ID pattern, and test real colon, maximum-length, and same-attempt Gate references.
- [x] Reject attempt/result writes before they exceed RunLedger Schema collection limits.
- [x] Reject legacy v1 with `ledger-schema-version-unsupported`; do not infer or migrate missing attempt ownership.
- [x] Run adapter, Ledger, and contract-Schema tests GREEN. Run the existing `test_completion_subject_blocks_manifest_and_acceptance_graph_replay` to prove a final diff/hash change invalidates the old Review receipt.
- [x] Run the Catalog/behavioral test once and confirm its only expected RED is `workflow/core.md` source-integrity drift.
- [x] Commit Task 3 paths with `feat: bind review results to ledger attempts`.

### Task 4: Refresh the hash-bound Catalog source

**Files:**
- Modify: `catalog/domains/workflow.yaml`

- [x] Read the Task 3 commit with `git rev-parse HEAD` and compute the committed blob hash without text decoding: `\.venv\Scripts\python.exe -c "import hashlib,subprocess; b=subprocess.check_output(['git','show','HEAD:workflow/core.md']); print('sha256:'+hashlib.sha256(b).hexdigest())"`.
- [x] Update only the `workflow-core` revision and contentHash to those exact values.
- [x] Run `\.venv\Scripts\python.exe -m unittest tests.unit.test_catalog tests.unit.test_router tests.unit.test_resolver tests.conformance.test_adapters tests.behavioral.test_workflow_matrix tests.unit.test_ledger tests.unit.test_contract_schemas -v` and confirm GREEN, closing both Task 3 policy tests and source-integrity RED.
- [x] Commit the Catalog lock with `chore: refresh workflow core source lock`.

## Chunk 3: Review and verification

### Task 5: Independent Review and completion evidence

**Files:**
- Modify: `docs/superpowers/plans/2026-08-08-post-landing-review-and-decision-records.md`

- [x] Run `git diff --check` and `\.venv\Scripts\python.exe -m selfworkflow.cli git-policy check --repo .`.
- [x] Run focused contract, Pipeline, resolver, adapter, and behavioral tests.
- [x] Run `.\scripts\verify.ps1 -Suite automated` and record exact count/exit code.
- [x] Dispatch one independent reviewer over the complete feature diff. Fix Critical/Important findings and rerun affected tests; Review fixes themselves require another narrow Review.
- [x] Add a document-operation RunLedger lifecycle regression that advances the resolved PlanGraph through Implement, Review, Verify, and Completed.
- [x] Confirm frozen C7 paths are absent from the feature diff, `D:\openwikiC7` was read-only and retained its recorded HEAD/branch, and no untracked runtime/credential artifacts exist in SelfWorkFlow.
- [x] Record test evidence, native/unverified boundaries, reviewer verdict, and final commit IDs in this plan.
- [x] Dispatch a final narrow document Review over the evidence update; if it finds Critical/Important issues, fix them and repeat Review until approved (maximum five iterations). At the limit, pause and request user direction.
- [x] Rerun `git diff --check`, Git Policy, frozen-path and untracked-file audits after the evidence edit.
- [x] Commit the reviewed evidence without pushing or opening a PR. Record implementation commit IDs in the document; report the evidence commit ID after creation because a commit cannot contain its own hash.

## Completion evidence (2026-08-08)

### Commits

- Design/plan gates: `6d66402`, `da9653d`.
- Decision record: `d723d08`.
- Document routing: `310d7f6`.
- RunLedger v2 and policy: `e484c99`; source lock: `e54275e`.
- Compact-core regression fix and refreshed lock: `be973c6`, `c345014`.
- Independent-review fixes: `36153a6`, `fbe4985`.
- The evidence commit cannot contain its own hash and is reported in the final handoff.

### Test and policy evidence

- TDD RED was observed separately for the missing decision validator, document
  implementation route, RunLedger v2/attempt helper, old-result replay,
  runtime-skip semantics, and capability evidence-reference compatibility.
- Task 4 combined Catalog/router/resolver/adapter/behavior/Ledger contracts:
  `95/95`, exit `0`.
- Review-fix focused suites: `30/30`, exit `0`, followed by another `30/30`,
  exit `0` after evidence-reference alignment.
- Final fresh full run: `.\scripts\verify.ps1 -Suite automated` reported
  `387/387`, exit `0`, `874.135s`.
- An earlier full run correctly found the compact-core heading regression
  (`384/385`); it was fixed and rerun. A later parallel run timed out at
  `904s` without a test summary and was not counted as passing evidence.
- Final `git diff --check` passed. Final Git Policy returned `passed` with no
  findings. The feature diff from `46b14b7` contains zero frozen C7 paths, and
  the SelfWorkFlow worktree had no tracked or untracked changes before this
  evidence edit.

### Independent Review

- Reviewer: existing independent SubAgent `Erdos`.
- First implementation Review found two Important and two Minor issues:
  result-reference replay, optional runtime-skip semantics/evidence ownership,
  collection-limit enforcement, and missing document Ledger lifecycle coverage.
  Commit `36153a6` closed them.
- Second Review found one Important compatibility issue: capability
  `evidenceRef` allowed colon/256 characters while the helper did not. Commit
  `fbe4985` aligned Schema, helper, normalizer, and regression coverage.
- Final independent Review reported zero Critical, Important, and Minor
  findings: **approved for evidence closure**. Its own focused run was `52/52`,
  exit `0`.

### Deliberate unverified boundaries

- No real C7OpenWiki MCP transaction was executed and no C7 support status was
  upgraded. `D:\openwikiC7` remained a separate pre-existing dirty repository;
  this task only read its identity. Its HEAD/branch remained
  `5b7fc8cb959d3fa2342db96c346803435e2644c8` / `main`, matching checked-in
  provenance. Exact equality of its dirty tree is not claimed.
- Native execution in every advertised third-party Agent was not rerun; thin
  adapters remain `agent-policy` compatibility rather than conforming-Host
  proof.
- No push or pull request was performed.
