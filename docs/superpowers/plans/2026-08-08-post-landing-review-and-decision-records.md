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

- [ ] Write failing tests for a valid independent recommendation, valid structured self-review, unknown fields, oversize/bad counts, dangling recommendation/selection IDs, unequal recommendation/selection, and false mode/independence pairs.
- [ ] Also cover duplicate alternative IDs, input immutability/deep-copy output, and redacted errors that never echo `question` or summaries.
- [ ] Run `\.venv\Scripts\python.exe -m unittest tests.unit.test_contract_schemas -v` and confirm RED because the Schema/validator do not exist.
- [ ] Implement a closed Schema and `validate_decision_record(value)` that returns a normalized deep copy or raises a stable redacted `DecisionRecordError`.
- [ ] Require unique alternative IDs, both IDs to reference an alternative, `selectedId == recommendationId`, and the two fixed mode/independence combinations.
- [ ] Rerun the focused tests and confirm GREEN.
- [ ] Commit only Task 1 paths with `feat: validate minor decision records`.

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

- [ ] Add a failing resolver test for `operationType=document, writeTask=true`; require `implement-documentation`, `implement-result-gate`, `review-self`, and Verify modules in order with an active plan.
- [ ] Add a failing request test that rejects `operationType=document, writeTask=false`.
- [ ] Add a failing `route_skills(document)` test proving the vendor-neutral `workflow-core` entry is selected.
- [ ] Add a failing Pipeline test requiring `implement.method` to allow `agent-native` as well as `skill`.
- [ ] Run the focused tests and confirm RED because no document implementation module exists.
- [ ] Add supported `implement-documentation` to `implement.method`, default only for `document`, requiring `filesystem-write`, with local-write side effects and no invented external capability.
- [ ] Add `document` to `implement-result-gate` and to the `workflow-core` Catalog selectors/mandatory operation list.
- [ ] Allow `agent-native` in the implementation-method slot and rerun the focused tests.
- [ ] Commit Task 2 paths with `feat: route reviewed documentation changes`.

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

- [ ] Write failing policy/conformance assertions for post-landing Review, document Gate Review before continuing, pure-document Review/Verify, strict minor-decision criteria, `decision-record`, recommendation equality, and critical-decision escalation.
- [ ] Write failing Ledger tests for appending a unique attempt to an active Review stage while rejecting pending/terminal stages, duplicate attempt refs, stale capability snapshots, and plan mismatch.
- [ ] Require structured slot/Gate/skip records to bind the current attempt. After appending a Review attempt, prove old attempt results remain auditable but no longer satisfy stage completion until the new attempt records its own passing results.
- [ ] Write RunLedger v2 Schema tests for closed structured attempt/result records and explicit rejection of legacy v1, unknown attempt refs, cross-stage refs, duplicate global attempt refs, duplicate results, and broken ordinal/previous chains.
- [ ] Add a CLI test proving a v1 Ledger returns `ledger-schema-version-unsupported` without echoing its content.
- [ ] Run `\.venv\Scripts\python.exe -m unittest tests.conformance.test_adapters tests.behavioral.test_workflow_matrix -v` and confirm RED.
- [ ] Run `\.venv\Scripts\python.exe -m unittest tests.unit.test_ledger tests.unit.test_contract_schemas -v` and confirm RED because v2 structures and `record_stage_attempt` do not exist.
- [ ] Update the vendor-neutral core first, then keep adapters to one compact reminder that tells Hosts to read the core rather than copying all rules.
- [ ] State that implementation fixes stay in the active Review attempt; only static PlanGraph input changes re-plan. Review receipts bind final document or diff hashes.
- [ ] Implement `record_stage_attempt` as a fail-closed RunLedger helper that validates the current plan/snapshot, active stage, bounded unique ref, and appends without changing prior evidence.
- [ ] Upgrade RunLedger to schemaVersion 2. Store attempts as `{attemptRef,ordinal,previousAttemptRef}` and results as `{attemptRef,moduleId,resultRef}`, `{attemptRef,gateId,outcome,resultRef}`, and `{attemptRef,slotId,evidenceRef}`; make `_requirements_met` consider only the latest attempt.
- [ ] Validate ordinal continuity and exact previous links, plus global attemptRef uniqueness and same-stage result ownership.
- [ ] Reject legacy v1 with `ledger-schema-version-unsupported`; do not infer or migrate missing attempt ownership.
- [ ] Run adapter, Ledger, and contract-Schema tests GREEN. Run the existing `test_completion_subject_blocks_manifest_and_acceptance_graph_replay` to prove a final diff/hash change invalidates the old Review receipt.
- [ ] Run the Catalog/behavioral test once and confirm its only expected RED is `workflow/core.md` source-integrity drift.
- [ ] Commit Task 3 paths with `feat: bind review results to ledger attempts`.

### Task 4: Refresh the hash-bound Catalog source

**Files:**
- Modify: `catalog/domains/workflow.yaml`

- [ ] Read the Task 3 commit with `git rev-parse HEAD` and compute the committed blob hash without text decoding: `\.venv\Scripts\python.exe -c "import hashlib,subprocess; b=subprocess.check_output(['git','show','HEAD:workflow/core.md']); print('sha256:'+hashlib.sha256(b).hexdigest())"`.
- [ ] Update only the `workflow-core` revision and contentHash to those exact values.
- [ ] Run `\.venv\Scripts\python.exe -m unittest tests.unit.test_catalog tests.unit.test_router tests.unit.test_resolver tests.conformance.test_adapters tests.behavioral.test_workflow_matrix tests.unit.test_ledger tests.unit.test_contract_schemas -v` and confirm GREEN, closing both Task 3 policy tests and source-integrity RED.
- [ ] Commit the Catalog lock with `chore: refresh workflow core source lock`.

## Chunk 3: Review and verification

### Task 5: Independent Review and completion evidence

**Files:**
- Modify: `docs/superpowers/plans/2026-08-08-post-landing-review-and-decision-records.md`

- [ ] Run `git diff --check` and `\.venv\Scripts\python.exe -m selfworkflow.cli git-policy check --repo .`.
- [ ] Run focused contract, Pipeline, resolver, adapter, and behavioral tests.
- [ ] Run `.\scripts\verify.ps1 -Suite automated` and record exact count/exit code.
- [ ] Dispatch one independent reviewer over the complete feature diff. Fix Critical/Important findings and rerun affected tests; Review fixes themselves require another narrow Review.
- [ ] Confirm frozen C7 paths and `D:\openwikiC7` are unchanged, and no untracked runtime/credential artifacts exist.
- [ ] Record test evidence, native/unverified boundaries, reviewer verdict, and final commit IDs in this plan.
- [ ] Dispatch a final narrow document Review over the evidence update; if it finds Critical/Important issues, fix them and repeat Review until approved (maximum five iterations). At the limit, pause and request user direction.
- [ ] Rerun `git diff --check`, Git Policy, frozen-path and untracked-file audits after the evidence edit.
- [ ] Commit the reviewed evidence without pushing or opening a PR. Record implementation commit IDs in the document; report the evidence commit ID after creation because a commit cannot contain its own hash.
