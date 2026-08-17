# C7OpenWiki External-Agent Adapter Conformance

## Bound scope

This evidence binds the uninstalled joint acceptance candidate to C7 clean HEAD
`73b8229ffb75bf4151ce019a95b3b23946202f84` on
`codex/openwiki-external-agent` and capability build
`ca6f8f0c-2729-4d25-9e25-9d403ee03256`. It does not claim OAuth, a C7-owned
model call, or model/reasoning verification. External Review evidence is exactly
`host_attested`.

## Contract and implementation result

| Requirement | Fresh evidence | Result |
| --- | --- | --- |
| External mode is the default | Real built stdio status returned `executionMode=external_agent`, `authRequired=false` | Conformant |
| Both capabilities are mandatory | SelfWorkflow requires `update.external-agent.begin` and `update.external-agent.reviewed-finalize` plus `externalAgent.ready`; no legacy fallback exists | Conformant |
| Exact nine-tool runtime | Capability evidence and the Codex configurator bind the same ordered nine tools | Conformant |
| C7 owns source/rule/request packages | Writer and Reviewer receive C7 paths and hashes unchanged; the Host does not rebuild materials | Conformant |
| Writer and Reviewer are distinct | Real Writer and independent Reviewer executions produced separately bound receipts | Conformant |
| Review precedes publication | Candidate became read-only at `prepare_review`; only C7 `submit_review` published it | Conformant |
| Failure is resumable | Candidate and Reviewer host failures retained state; resume returned the correct writable/read-only package | Conformant |
| Clarification does not publish | Blocking candidate returned `needs_clarification`; confirmed abort left formal revision unchanged | Conformant |
| Legacy is explicit only | External routing never calls `openwiki_update`; legacy provider fields cannot satisfy external readiness | Conformant |
| Adapter schemas fail closed | Status, packages, receipts, terminal states and capability evidence use closed key sets and cross-binding checks | Conformant |
| Installation is transactional | Apply/rollback recheck target bytes and parent identity under lock, persist rollback progress and preserve concurrent edits | Conformant, uninstalled |

## Independent Review closure

The first independent joint Review reported 0 Critical and 5 Important findings:
incomplete provenance/install binding, stale seven-tool configuration, permissive
adapter outputs, installer preimage races and C7 snapshot path races. The
SelfWorkflow items were closed with focused TDD. C7 closed the snapshot finding
with real Windows symlink, ancestor-junction and replacement races; its final
SPEC and QUALITY Reviews both returned 0 Critical / 0 Important / 0 Minor.

A new whole-package joint Review is still required after the final SelfWorkflow
diff and provenance binding. Until that Review reports zero Critical/Important,
the Knowledge profile must not be installed.

## Fresh verification evidence

- C7 full verifier: 74/74 suites, 612/612 tests, Agent eval 14+6, real built-stdio
  publish passed. Capability evidence SHA-256 is
  `5e6f62285e27e789988c8840cd9a37adee59e43b9f6b05fbbef79b8f980dd983`.
- C7 snapshot repair: 3/3 old-behavior RED, 6/6 GREEN; post-commit typecheck,
  build and diff-check passed. One shared aggregate invocation had the known
  parallel five-second source timeout; the exact test passed independently in
  2.072 seconds and the complete fresh verifier passed.
- Real host E2E: external status → begin → Writer failure/resume → actual Writer
  → prepare Review → Reviewer failure/resume → actual independent Reviewer pass
  → submit → published. A separate blocking transaction returned
  `needs_clarification`, then confirmed abort without changing the formal Wiki.
- SelfWorkflow focused evidence before final provenance binding: Codex MCP 13/13,
  installer apply/rollback 15/15, adapter behavior 29/30 with the sole expected
  failure being the deliberately stale provenance hash. After rebinding, the
  same adapter suite must be fully Green and the complete automated suite must
  be rerun.
- The SelfWorkflow Codex configurator consumed the exact final C7 evidence and
  completed a real staged-evidence stdio preflight successfully.

## Exact bindings

`extensions/knowledge/c7-openwiki/provenance.yaml` binds the C7 HEAD, clean
state, contract/matrix/Agent Skill bytes, built MCP index and snapshot, Win32
helper, all eight capability fingerprints, raw capability evidence, and the
SelfWorkflow Skill/adapter/configurator/installer bytes. The frozen tool contract
is independently hash-bound before any backend call.

## Current boundary

The source provenance remains `verified-uninstalled` by design: it binds candidate
bytes and is not a self-referential machine installation receipt. The final joint
Reviews reached zero Critical/Important, the Knowledge profile installation path
passed transactionally, and the stable C7 stdio preflight returned the bound build
ID. Final machine state must instead be proven by the StateRoot current manifest,
installed-byte verification and a final idempotent install. A Codex restart is still
required before a new task can treat the MCP and Skills as newly discovered; the
current task cannot prove host rediscovery.
