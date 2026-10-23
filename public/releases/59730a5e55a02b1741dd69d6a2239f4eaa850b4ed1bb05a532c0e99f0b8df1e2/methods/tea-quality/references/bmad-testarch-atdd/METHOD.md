---
name: bmad-testarch-atdd
description: 'Generate red-phase acceptance test scaffolds using the TDD cycle. Use when the user says "lets write acceptance tests" or "I want to do ATDD"'
---

# Acceptance Test Generation

`bmad-testarch-automate` owns test generation in red and expand modes.
This entry preserves the ATDD command and AT menu code, with red as its default.

1. Preserve the original request, supplied artifacts and Create, Resume, Validate or Edit operation. Set `test_entry = bmad-testarch-atdd`; default to red only when the task has no explicit mode signal.
2. Set `skill-root` to the sibling `bmad-testarch-automate` directory. Require its `METHOD.md`, `resources/test-generation-routing.md`, `resources/run-and-heal.md`, and `red/steps-c/step-01-preflight-and-context.md`. If any are missing, report the canonical document dependency as unverified and stop; do not install or search another version. The local headless contract overrides upstream activation, hooks, menus and command execution.
3. Read `{skill-root}/METHOD.md` completely and execute its router and activation with the original request. Keep `{skill-root}` canonical throughout. Run only the selected mode's customization hooks; do not activate twice or repeat its operation menu.

Existing ATDD customization files and checklist paths keep working.
Resume accepts interrupted 2.0.0 checklists and preserves their story identity and saved next step.
