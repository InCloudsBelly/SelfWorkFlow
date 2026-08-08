# Stateless Task Resolver Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one stateless CLI entry that composes classification, capability gating, Catalog routing, stage-specific Superpowers selection, and minimum Review/verification requirements.

**Architecture:** A focused `resolver.py` owns strict request parsing and deterministic composition. `cli.py` only loads bounded JSON/Catalog files, delegates to the resolver, and serializes the result. External Agents still execute the plan; no task ledger, model call, knowledge write, or global installation is added.

**Tech Stack:** Python 3.11, `unittest`, existing SelfWorkFlow classifier/router/Superpowers modules.

---

## Chunk 1: Resolver contract and CLI integration

### Task 1: Prove the missing composition path

**Files:**
- Create: `tests/unit/test_resolver.py`
- Create: `tests/acceptance/test_workflow_resolution.py`

- [x] Add unit tests for active implement, L2 Review capability pause, missing Superpowers pause, explicit Grill, strict input rejection, and deterministic selected-Skill ordering.
- [x] Add a sandbox test that builds and installs `core`, reads the active snapshot, and invokes CLI `resolve` for implement, review, and verify stages.
- [x] Assert the installed Codex managed block points to the resolver and the snapshot contains a bounded request example.
- [x] Run both modules and confirm RED because `selfworkflow.resolver` and CLI `resolve` do not exist.

### Task 2: Implement the minimum resolver

**Files:**
- Create: `src/selfworkflow/resolver.py`
- Modify: `src/selfworkflow/cli.py`
- Create: `workflow/resolve-request.example.json`
- Modify: `src/selfworkflow/adapters.py`
- Modify: `src/selfworkflow/installer.py`

- [x] Parse an exact versioned request shape with bounded collections and stable `resolve-input-invalid` failures.
- [x] Compose `classify_task`, `check_capabilities`, `route_skills`, and `decide_overlay` without side effects.
- [x] Emit classification, capability gate, Catalog route, Superpowers overlay, ordered Skills, Review/verification requirements, issues, and final status.
- [x] Add `selfworkflow resolve --catalog ... --request ...`; return a stable nonzero code and redacted message on failure.
- [x] Package the request example in `core` and make the Codex managed block reference the command without preloading the example body.
- [x] Run resolver unit and acceptance tests and confirm GREEN.

## Chunk 2: Documentation and regression closure

### Task 3: Keep user-facing status truthful

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-07-selfworkflow-v1-checklist.md`

- [x] Document the stateless resolver command and distinguish deterministic task planning from native Agent execution.
- [x] Change the stage-loading checklist claim to state that the resolver now composes the stage selection, while native host behavior remains `unverified`.

### Task 4: Verify and Review

- [x] Run resolver unit and acceptance tests.
- [x] Run classifier, router, Superpowers, runtime, adapter, and install-sandbox focused regression tests.
- [x] Review the complete diff for strict input handling, failure closure, determinism, safety, scope, and unrelated changes.
- [x] Attempt the full suite with a bounded timeout; report timeout or skipped native/OpenWiki checks as `unverified`.

## Verification Record

- TDD RED: missing resolver/CLI produced 8 expected errors; runtime discovery assertion then failed before adapter wiring; duplicate-key and Grill capability tests produced 2 expected failures; request identity assertions then failed on missing fields.
- TDD GREEN: resolver and acceptance modules passed 10/10 after the final request-hash change.
- Final focused regression: 64/64 passed in 13.092 seconds.
- `git diff --check`: passed.
- Full `scripts/test.ps1`: exceeded the 304-second outer limit; the two exact residual `unittest discover` processes were terminated. Full-suite result remains `unverified`.
- Native Codex CLI/Desktop, formal global install, and real C7OpenWiki calls were not run and remain `unverified`.
