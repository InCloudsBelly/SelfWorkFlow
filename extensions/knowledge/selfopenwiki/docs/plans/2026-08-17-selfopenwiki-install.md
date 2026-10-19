# SelfOpenWiki Install Entry Implementation Plan

> **For agentic workers:** Implement this plan with TDD. Keep `Setup.bat` backward compatible.

**Goal:** Add a fail-closed Install entry that requires an Agent-confirmed Wiki root and binds the existing SelfOpenWiki integration without modifying the Wiki repository.

**Architecture:** `Install.bat` forwards to `scripts/install.mjs`. The Node entry validates the explicit Wiki root and confirmation flags, runs the existing setup plan, then reuses `configure-storage.mjs`. No new storage schema or MCP public API is introduced.

**Tech Stack:** Windows batch, Node.js 22 ESM, existing storage-config and setup scripts, Node test runner.

---

### Task 1: Install contract tests

**Files:**

- Create: `test/install-script.test.mjs`
- Reference: `scripts/install.mjs`, `scripts/configure-storage.mjs`, `scripts/setup.mjs`

- [ ] Add black-box tests for missing root, missing safety confirmation, Git root without authorization, plain directory success, Git directory success, and no Wiki `.git` mutation.
- [ ] Run `corepack pnpm@10.33.2 test -- test/install-script.test.mjs` and capture the expected missing-module RED.

### Task 2: Install implementation

**Files:**

- Create: `Install.bat`
- Create: `scripts/install.mjs`

- [ ] Implement strict argument parsing for `--wiki-root`, `--confirm-data-safety`, and `--confirm-git-authorization`.
- [ ] Validate absolute existing non-link directory before any setup step; detect `.git` without modifying it.
- [ ] Run the existing setup plan with MCP, then call the existing storage writer with the confirmed root.
- [ ] Return bounded messages and non-zero exit codes on every failed precondition or child step.

### Task 3: README and verification

**Files:**

- Modify: `README.md`

- [ ] Document the Agent preflight questions, exact Install command, data-safety warning, Git authorization requirement, and the preserved Setup commands.
- [ ] Run focused install tests, full root tests, Node syntax checks, Prettier, and `git diff --check`.
- [ ] Review the complete diff for no Wiki `.git`, migration, commit, push, or public MCP schema changes.
