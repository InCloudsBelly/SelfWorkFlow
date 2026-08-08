# Lightweight Code-First Core Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the default SelfWorkFlow runtime and routing code-first and lightweight while retaining install, release, native validation, and knowledge features behind explicit profiles.

**Architecture:** Add one compact workflow source as the default bootstrap. Build deterministic `core`, `knowledge`, and `maintainer` runtime profiles from allowlisted content; filter the compiled Catalog to match each profile. Keep the existing repository governance implementation unchanged and unreachable from ordinary task routing unless explicitly selected.

**Tech Stack:** Python 3.11, `unittest`, YAML/JSON Catalogs, argparse, Git.

---

## Chunk 1: Runtime boundary

### Task 1: Lock the lightweight profile behavior with failing tests

**Files:**
- Modify: `tests/conformance/test_runtime_snapshot.py`
- Modify: `tests/unit/test_router.py`

- [x] Add a test proving default `build_runtime` records profile `core`, installs the compact workflow, and excludes `extensions`, detailed governance YAML, and maintainer-only modules.
- [x] Add profile tests proving `knowledge` adds knowledge files and `maintainer` retains the complete source set.
- [x] Add CLI coverage proving `--profile` defaults to `core` and rejects unknown values.
- [x] Change checked-in Catalog routing expectation so an ordinary C1 code implementation selects only `workflow-core`; the compact core already contains the essential code-quality rules.
- [x] Run `python -m unittest tests.conformance.test_runtime_snapshot tests.unit.test_router -v`; expect the new assertions to fail before implementation.

### Task 2: Add the compact workflow and profile-aware runtime builder

**Files:**
- Create: `workflow/core.md`
- Modify: `src/selfworkflow/adapters.py`
- Modify: `src/selfworkflow/cli.py`

- [x] Write a compact, self-contained code-first entry containing classification, owner-first implementation, diff Review, narrow verification, protected safety rules, and explicit extension triggers.
- [x] Add a closed `profile` argument to `build_runtime`, defaulting to `core`.
- [x] Build `core` from an allowlist; copy `workflow/core.md` to runtime `WORKFLOW.md`.
- [x] Add only knowledge-contract content for `knowledge`; preserve the existing complete snapshot for `maintainer`.
- [x] Record the selected profile in `artifact-manifest.json` so artifacts cannot be confused.
- [x] Add argparse `--profile {core,knowledge,maintainer}` and pass it to the builder.
- [x] Run the focused runtime tests until Green.
- [x] Commit the runtime boundary.

## Chunk 2: Routing and documentation

### Task 3: Make ordinary code routing minimal

**Files:**
- Modify: `catalog/domains/workflow.yaml`
- Modify: `catalog/domains/code-quality.yaml`
- Modify: `tests/unit/test_catalog.py` only if fixture source setup requires the new compact source

- [x] Point `workflow-core` at `workflow/core.md` and bind its exact content hash.
- [x] Stop making the verbose protected-rule document mandatory for ordinary tasks; keep it selectable for rule changes, install, and publish operations.
- [x] Keep the full workflow/code-quality Skills `unverified` until a real Agent evaluation succeeds; do not promote them merely to make routing convenient.
- [x] Keep the full quality Skills as optional candidates and remove the verbose protected-rule source from ordinary routing.
- [x] Refresh source revision/hash metadata in a separate provenance commit after source changes are committed.
- [x] Run Catalog, router, code-quality, and Superpowers-routing tests until Green.
- [x] Commit the routing change and provenance refresh separately.

### Task 4: Synchronize the user-facing design and verify the pivot

**Files:**
- Modify: `README.md`
- Modify: `docs/design/2026-08-07-selfworkflow-design.md`
- Modify: `docs/superpowers/plans/2026-08-07-selfworkflow-v1-checklist.md`

- [x] State that `core` is the default operational product and that repository complexity is not default context.
- [x] Move Tasks 16–18 and release/native gates under an explicit maintainer follow-up; do not present them as prerequisites for using the code workflow locally.
- [x] Preserve the existing uncommitted installer acceptance changes without mixing them into core commits; rerun their two focused tests before a separate commit.
- [x] Run `python -m unittest tests.conformance.test_runtime_snapshot tests.unit.test_router tests.unit.test_catalog tests.behavioral.test_code_quality_scenarios tests.behavioral.test_workflow_matrix -v`.
- [x] Run `git diff --check` and inspect the complete diff for unrelated changes, safety regressions, and default-context leakage.
- [x] If all focused checks pass, run the repository's automated suite once; report any skipped native/real-model checks as `unverified` rather than blocking the lightweight core.
- [x] Commit documentation and verified acceptance fixes separately.

## Verification record

The focused runtime, router, Catalog, code-quality contract, and workflow-matrix
checks passed. The one full automated run executed 304 tests: 302 passed and two
stale aggregate/document assertions failed. Both assertions were corrected and
their 18-test owning module then passed. The full 304-test suite was deliberately
not repeated; native Agent, account/model, production ACL, and real OpenWiki calls
remain `unverified`.
