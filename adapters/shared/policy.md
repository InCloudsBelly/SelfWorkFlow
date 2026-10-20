For ordinary tasks, follow installed `WORKFLOW.md` directly (`agent-policy`); do not create a PlanGraph or RunLedger. Use `selfworkflow resolve` only for an explicitly contract-managed task or a conforming Host already handling this task under contract with fresh capability evidence; capability availability alone never activates it.

`WORKFLOW.md` and its current-stage modules own workflow rules. In particular, `workflow/modules/review.md` owns Review scheduling, isolation and restrictions. Host notes supply only genuine host differences; they never override or duplicate those rules.

Bind required operations to the current host's actual tool schemas and permissions by capability, not by a fixed tool name or vendor name. Adapter `capabilities` are integration targets, not proof that tools are available or verified. Treat host tool names as hints; check context isolation and completion semantics before using an independent Reviewer. Report missing capabilities as `unverified` for the affected operation and continue independent work within the approved scope; do not invent a tool, a result, or an equivalent independent context.

{support-claim}
