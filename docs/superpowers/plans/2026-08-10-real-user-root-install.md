# Real User Root Installation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Windows one-click installer safely install into real `.agents` and `.codex` roots without scanning unrelated Agent runtime data, while transactionally migrating a compatible Superpowers junction.

**Architecture:** Replace whole-root baseline hashing with exact managed-target snapshots derived from the artifact and install identity. Extend Superpowers staging with an explicit, source-bound junction migration receipt so the PowerShell orchestrator can restore the previous junction on every failure path.

**Tech Stack:** Python 3.11+, `unittest`, PowerShell 5.1+, Windows junction semantics, existing hash-bound installer transactions.

---

## Chunk 1: Managed installation surface

### Task 1: Reproduce real-root failures

**Files:**
- Modify: `tests/installer/test_doctor.py`
- Modify: `tests/installer/test_plan.py`
- Modify: `tests/installer/test_apply.py`

- [x] Add tests whose unrelated Codex files exceed 8 MiB and whose unrelated subtree is a reparse point.
- [x] Assert doctor/plan can inspect the roots without reading those unrelated entries.
- [x] Add negative tests proving a reparse or oversized exact managed target remains rejected.
- [x] Replace the obsolete whole-root drift assertion with paired tests: unrelated changes are allowed; every exact managed target and `StateRoot/current-manifest.json` still fail on pre-lock and in-lock drift.
- [x] Add pairwise root containment rejection tests.
- [x] Run the exact tests and confirm RED from `file-too-large` / `reparse-path-rejected`.

### Task 2: Implement scoped target snapshots

**Files:**
- Modify: `src/selfworkflow/installer.py`
- Modify: `tests/installer/test_doctor.py`
- Modify: `tests/installer/test_plan.py`
- Modify: `tests/installer/test_apply.py`

- [x] Add bounded helpers that hash only exact managed targets and reject reparse in their target chain.
- [x] Derive plan baselines from snapshot files, mapped Skill files, current pointer, Codex `AGENTS.md` and StateRoot `current-manifest.json`.
- [x] Reject equality or ancestor/descendant overlap among artifact, AgentsRoot, CodexRoot and StateRoot.
- [x] Make doctor report root presence plus managed-surface hashes without traversing unrelated runtime content.
- [x] Run focused tests to GREEN, then run all installer plan/doctor tests.

## Chunk 2: Superpowers junction migration

### Task 3: Reproduce compatible and hostile target behavior

**Files:**
- Modify: `tests/unit/test_superpowers_overlay.py`
- Modify: `tests/installer/test_one_click.py`

- [x] Add a compatible-link test bound to the selected source `skills` directory.
- [x] Add wrong-target and missing-explicit-authorization rejection tests.
- [x] Add backup-in-source, reparse-parent and cross-volume rejection tests.
- [x] Add restoration tests for staging failure, lost CLI output, simulated process interruption and later one-click failure.
- [x] Run focused tests and confirm RED.

### Task 4: Implement source-bound migration and rollback

**Files:**
- Modify: `src/selfworkflow/sources.py`
- Modify: `src/selfworkflow/cli.py`
- Modify: `scripts/install-selfworkflow.ps1`
- Modify: `tests/unit/test_superpowers_overlay.py`
- Modify: `tests/installer/test_one_click.py`

- [x] Extend `source stage` with explicit compatible-link, StateRoot migration-journal and backup arguments; add recover/commit operations over the durable journal.
- [x] Validate resolved link target, same-volume backup, disjoint source/managed roots, reparse-free parent chains and source inventory before moving anything.
- [x] Persist intent before moving; restore the junction inside staging on publication/output failure and on the next run for every non-committed phase.
- [x] Record migration receipt, restore it from the one-click catch path after removing only the verified staged target, and mark committed only after final doctor/provider verification.
- [x] Run focused tests to GREEN.

## Chunk 3: Verification and live installation

### Task 5: Regression verification

**Files:**
- Modify if required by changed output contracts: `schemas/install-plan.schema.json`
- Modify: `README.md`

- [x] Document managed-surface ownership and compatible junction migration.
- [x] Run installer, unit, conformance and automated verification suites.
- [x] Review the complete diff for unrelated changes, unsafe path handling and rollback asymmetry.

### Task 6: Install and verify the approved local configuration

**Files:**
- Runtime only: `%USERPROFILE%/.agents`, `%USERPROFILE%/.codex/AGENTS.md`
- State only: `%LOCALAPPDATA%/SelfWorkFlow/**`

- [ ] Run `Install_SelfWorkFlow.bat` non-interactively with the approved dirty local Superpowers source, bundled explicit-only Grill-me and `E:/kg-code-graph` override.
- [ ] Verify the returned manifest and run doctor against the formal roots.
- [ ] Confirm unmanaged global text and Codex runtime data are unchanged.
- [ ] Read the installed `WORKFLOW.md` from the manifest-bound snapshot before starting C7OpenWiki work.
