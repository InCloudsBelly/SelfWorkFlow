---
name: bmad-testarch-atdd
description: Explicit TEA ATDD RED only; requires approved requirements, acceptance criteria, implementation plan and test design.
---

# Selected ATDD RED

This first-party entry selects upstream `bmad-tea-automate/red`; it does not select ordinary automate or GREEN implementation.
First apply `references/headless-contract.md` from the tea-quality root. Both root macros refer to this selected reference directory.
Read `red/instructions.md` and `red/workflow.yaml` for required inputs, order, exit criteria and output, then only the current `red/steps-c` step and its necessary resources.
SelfWorkflow replaces upstream activation/configuration, discovery, team delegation, progress files and automatic run/heal. Use only supplied context and approved output/test paths.
RED requires a test failure caused by the missing acceptance behavior; environment or syntax failures do not qualify. Without execution evidence, report RED unverified. Do not enter GREEN, fix production code or imply passing tests.
