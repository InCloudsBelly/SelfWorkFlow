# Lightweight Knowledge Handoff Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight, once-per-task knowledge prompt and pass processed conclusions together with key original evidence to C7OpenWiki.

**Architecture:** Keep the behavior as a compact Agent policy in the existing core workflow and C7 Skill. Reuse `materials` plus the confirmed `sourceManifestId`; do not add tools, state machines, or C7 backend behavior.

**Tech Stack:** Markdown workflow/Skill contracts, Python unittest, existing SelfWorkflow runtime builder and Windows installer.

---

## Chunk 1: Policy and Skill

### Task 1: Add failing behavioral contracts

**Files:**
- Modify: `tests/behavioral/test_workflow_matrix.py`
- Modify: `tests/conformance/test_c7_openwiki_adapter.py`

- [ ] Add assertions for reusable-knowledge prompting, one prompt per task, non-trigger cases, processed `materials`, key original sources, independent OpenWiki verification, and real adapter forwarding.
- [ ] Run the two tests and confirm they fail because the new policy text is absent.

### Task 2: Implement the minimum policy

**Files:**
- Modify: `workflow/core.md`
- Modify: `WORKFLOW.md`
- Modify: `extensions/knowledge/c7-openwiki/SKILL.md`
- Modify: `src/selfworkflow/c7_openwiki.py`

- [ ] Add the approved once-per-task prompt boundary to both workflow documents.
- [ ] Add the dual-layer evidence bundle and independent-verification rules to the C7 Skill.
- [ ] Validate and forward bounded `materials` together with source manifest fields in query/update.
- [ ] Run the targeted tests and confirm they pass.

## Chunk 2: Runtime and Installation

### Task 3: Restore catalog/runtime consistency only where required

**Files:**
- Modify only if validation requires it: `catalog/v3/modules/knowledge-*.yaml`, `catalog/v3/index.yaml`

- [ ] Recompute only hashes invalidated by the approved files; do not alter unrelated C7/C++ changes.
- [ ] Build the `knowledge` profile and run the smallest affected conformance/installer regression set.

### Task 4: Review, install, and verify

- [ ] Review the exact task diff for trigger overreach, source over-collection, sensitive-data regressions, confirmation bypasses, and unrelated changes.
- [ ] Install the verified `knowledge` profile without changing existing Superpowers or local provider choices.
- [ ] Re-read `current.json`, the installed `WORKFLOW.md`, installed `kg-c7-openwiki/SKILL.md`, and the Codex managed block; verify the new artifact hash and both policies.
- [ ] Report any unrelated blocker as `unverified` without expanding scope.
