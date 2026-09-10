# SelfWorkFlow core workflow

This document describes the checked-in, vendor-neutral core that is currently
implemented and tested. The linked YAML files are the declarative sources; the
Python module supplies deterministic protected-rule merging, JSON evidence
parsing, canonical content hashing, and completion decisions.

## Always-on communication

**Caveman lite 常驻**. Keep conversational output concise and professional by
removing filler and repetition while keeping 技术信息完整. Preserve 代码、命令、错误
exactly. SelfWorkFlow overrides upstream `Default: full`: the default is always
`lite`; `full`, `ultra`, and `wenyan` require explicit user selection and never
activate automatically. Persisted or third-party 文档、提交信息, comments, and messages use normal
professional prose. 安全警告、不可逆操作 confirmations, 多步流程, or any content
made ambiguous by compression must use 完整表达; resume lite after clarity is
restored. The official Caveman Skill remains installed for explicit level
switching, but it cannot weaken progress reporting, Review, verification, or
safety gates.

## Lifecycle

The phase order is `discovered` → `capability-checked` → `classified` →
`designed` → `planned` → `implemented` → `reviewed` → `verified` →
`completed`. Execution status and verification status remain separate. A task
may be `active`, `paused`, `blocked`, `failed`, or `completed`; verification is
`not-applicable`, `not-run`, `partial`, `passed`, or `failed`.

The exact phase and status vocabulary is in
[the lifecycle source](workflow/lifecycle.yaml). Classification thresholds and
upgrade-only overrides are in [the policy source](workflow/policies.yaml).

## Modular execution protocol

The checked-in Pipeline is the fixed lightweight spine; Catalog v2 is the only
runtime module registry. A Host performs this sequence:

```text
Discover -> Capability Check -> Classify -> Design -> Plan
-> Implement/Debug -> Review -> Verify -> optional Knowledge -> Complete
```

Ordinary tasks follow this lightweight policy directly and do not create a
PlanGraph or RunLedger. Only an explicitly contract-managed request may ask a
conforming Host to invoke the resolver with normalized input and fresh,
identity-bound capability evidence. An `active` result contains an immutable
PlanGraph; `paused` must never be promoted or silently degraded. Only modules in
the current PlanGraph stage are loaded. Runtime attempts, Gate results, skips,
and failures belong in a RunLedger bound to the exact `planHash`, `requestHash`,
and capability snapshot. Changed or expired evidence requires a new plan and
supersedes the old ledger.

Modifying tasks use the core design contract for bounded alignment. Light does
not auto-start Grill; Full automatically uses Matt `grilling` for a bounded
frontier; Deep automatically uses Matt `grill-me`, whose upstream workflow runs
the more comprehensive `grilling` frontier. Deep covers hidden assumptions,
boundaries, and failure paths without duplicating a second Grill round. Users
may explicitly select either module at any strength. Full and Deep use the
SelfWorkflow Plan contract and must load TEA. Grill completion is followed by
the applicable vendor-neutral independent design or integrated Review. Every modifying task still
requires complete-diff Review and the narrowest sufficient direct, failure-path,
and related-regression verification. Users are prompted only for material scope
or product choices, sensitive data, irreversible/external effects, protected
defaults, formal knowledge publication, and the implementation-contract
confirmation required before code edits.

Behavior-changing `implement`/`debug`, feature, bugfix, behavioral-refactor,
architecture, and migration tasks must load Matt `tdd` and record real RED and
GREEN commands. RED proves the expected missing behavior rather than an
environment or syntax error; GREEN reruns the same path and the narrowest
affected regression. Conflicting operation/archetype classification pauses.

Full has a T2 floor and Deep a T3 floor. Their TEA workflows run through the
installed `tea-quality` adapter without requiring a project `_bmad` directory.
Post-landing Standards and Spec reviewers receive the same readable package:
approved request, acceptance criteria, final documents, applicable rules, and
actual committed/staged/unstaged/untracked/deleted/binary/file-mode task delta,
with worktree and index bytes plus modes bound separately. Both
return the package hash and distinct execution IDs. Severity maps as
`critical -> Critical`, `high/medium -> Important`, `low/info -> Minor`.
Completion requires zero open Critical/Important, a disposition for every
Minor, and fresh verification receipts containing command, time range, exit
code, failure count, and consumer result. Package drift invalidates all Review
and Verify evidence.

`writeTask` is derived from the closed operation contract, not trusted as a free
caller assertion. `implement`, `debug`, `document`, `install`, `publish`, and
`knowledge-write` require `writeTask=true`; all remaining operations require
`false`. A mismatch is rejected before routing.

Knowledge exposes only optional, vendor-neutral `knowledge.read`,
`knowledge.propose`, and `knowledge.update` slots. A concrete backend is an
explicit adapter under `extensions/knowledge/<backend>` with its own contract,
capability checks, failure semantics, and Skill. The `knowledge` profile carries
the generic backend Skill and the optional SelfOpenWiki adapter, but the core
workflow does not depend on either. An adapter must fail closed on missing or
drifted capabilities and cannot invent provider, model, or database behavior.

## Review and decision closure

Every landed change requires post-landing Review before completion. A Review
fix remains in the active Review stage and creates a new RunLedger v2 attempt;
results from older attempts stay auditable but cannot satisfy the latest
attempt. The final Review receipt binds the final document or complete diff
hash. Only changed Request, capability, or other static PlanGraph inputs cause
re-planning.

Design and plan documents are intermediate artifacts. `design.gate` reviews a
final design/specification hash and `plan.gate` reviews a final implementation
plan hash before implementation continues. A document that is itself the final
deliverable still lands through `document`, post-landing Review, and Verify.
Writing a plan never completes an implementation request.

### Per-Agent Review model

Review model selection is machine-local and keyed by Agent identity. The
default file is
`%LOCALAPPDATA%\SelfWorkFlow\config\review-models.local.yaml`; it is not
part of the repository, runtime snapshot, Wiki, or credentials. Its schema is
`schemas/review-model-config.schema.json`, for example:

```yaml
schemaVersion: 1
agents:
  codex:
    review:
      model: gpt-5.6-sol
      reasoningEffort: max
  claude:
    review: null
```

When an Agent has no configured Review selection, the Host returns
`needs_user_configuration`; the Agent must ask the user for the exact model
and supported reasoning effort before saving a default. Model aliases are not
inferred (`Xmax` is not silently mapped to `max`). A user-requested switch
must be explicitly classified as either a new default or a one-time override;
the latter is carried only in the current Review dispatch and is not persisted.
The selected `reviewModel` is bound into the Review payload, and the Host must
return the same validated selection in its dispatch observation; a missing or
mismatched observation fails closed. Actual model execution and host capability
remain host-attested; configuration alone is not model-execution evidence. The
repository CLI can inspect or save the machine-local selection with
`selfworkflow review-model status` and
`selfworkflow review-model set --confirm`.

Review model selection never changes the parent conversation's model. Every
Host-owned independent Review dispatch must create a fresh ephemeral SubAgent
with the selected model and reasoning effort, pass only the bounded Review
package, collect the structured result and a bounded Markdown summary, then
clean up the SubAgent. The required lifecycle is
`created-executed-cleaned`; missing capability or cleanup failure is
fail-closed and cannot fall back to the parent conversation. The receipt binds
`reviewExecutionMode: ephemeral-subagent`, the lifecycle marker, and the
summary hash. Private reviewer reasoning is never returned or persisted.
Full/Deep code Review keeps two independent ephemeral SubAgents for Standards
and Spec. A matching project `.selfworkflow/review.yaml` Skill manifest is
ordered before the generic Review Skill within the ordinary Skill layer; it
cannot override protected workflow rules or completion gates. Code Review must
receive a hash-bound complete package containing the approved diff/materials,
acceptance specification, and verification plan, bound to the current plan,
stage, and attempt. Plan Review uses the same package and dispatch seam. The
dual code gate requires both axes to return independent, attested L2/L3
`approve` results with the same package and Skill-manifest hashes.

### 代码实施契约

Any task that adds, changes, or deletes behavior code forms a 代码实施契约 before
the **第一次编辑测试或生产代码前** boundary. Before confirmation, only 只读分析和文档修订
are allowed; test code, shaders, build scripts, behavior configuration, and
production code remain untouched. The contract states 修改预期, owner layer,
main files/symbols, alternatives, 影响半径/侵入性, 安全、性能、可维护性,
compatibility, rollback, test seams, and `unverified` evidence.

Light uses a 紧凑 inline summary and does not create formal documents or a
SubAgent. Full 和 Deep 必须加载 TEA. For Full/Deep, **设计/规格** records alternatives and code boundaries,
**TEA/测试设计** records direct/failure paths, invariants, performance evidence,
and non-invasive test seams, and the **实施计划** records expected files/behavior,
no-go boundaries, the 批准的侵入性预算, TDD, 回滚, and verification commands. After the complete
package passes independent Review and is corrected, present the final contract
to the user. The fixed order is `Review → 用户确认 → TDD`; only an **明确实施确认**
permits code edits.

Crossing the approved owner/module boundary; adding public API/ABI/Schema,
persistent formats, a global macro, or a Build variant; expanding a 共享热路径 or
测试来源的生产改动; changing a 关键测试接缝; or materially increasing safety,
performance, maintenance, rollback, or test-intrusion cost makes the old
Review and **确认失效**. Stop editing, revise the package, rerun Review, and obtain
new confirmation. Private local details inside the approved budget do not prompt
again, but post-landing Review reports them.

### Progress reporting

For tasks that use tools, change files, or perform side effects, 首条进度更新同时包含
`SelfWorkflow active: <profile>；mode: <Light|Full|Deep>` and the progress plus
initial-estimate line
`进度 <已完成主阶段/总主阶段>（约 <粗略区间>%）｜当前：<阶段>｜剩余：<关键阶段>｜预计：<时间区间或重估点>`.
Later updates reuse the second line.
Report only at start, main-stage transitions, meaningful checkpoints in a long
stage, blockers, or material estimate changes; 不得按每个命令机械刷屏. Both
percentage and time are 粗略区间. A 单点精确百分比 such as `50%` or an exact
countdown is forbidden. Normal progress must 保持单调; scope-driven regressions
must explain the cause and 重新估算. When evidence is insufficient, state
`暂无法可靠估算` and name the checkpoint after which the estimate will be
revised. Progress never replaces Review or verification evidence.

### Integrated pre-implementation Review

`Full/Deep` tasks, and tasks that produce 至少两份正式文档 among the design,
test design, and implementation plan, require a new 独立 SubAgent before
implementation. The latter is upgraded to Full; a Light inline task remains
lightweight. Whenever this gate or a post-landing independent Review is
required, it uses the same ephemeral SubAgent contract and never changes the
parent model. The reviewer receives the accepted scope, acceptance criteria,
project rules, complete final documents, and the 最终文档包 hash, but not the
main Agent's private reasoning. Chunk Review or 同一 Agent self-review cannot
replace this 完整文档包 Review.

Critical and Important findings must be resolved; every Minor finding receives
an explicit disposition. Any reviewed-document change invalidates the old
result and requires a fresh whole-package Review. If independent SubAgent
capability is unavailable, record `unverified` and 暂停实施; same-Agent fallback
is forbidden. This gate does not replace TDD, `post-landing Review`, or Verify.

### Intrusion budget

Judge code-design intrusion by **影响半径**, not line count. Public headers,
APIs or 公共枚举, ABI/Schema/persistent formats, 全局编译宏 and Build variants,
cross-module infrastructure, shared hot paths, and test-originated production
changes are high-intrusion signals. Design and plan must define an 侵入性预算,
compare at least one narrower alternative, and choose the narrowest owner-layer
solution that satisfies acceptance. If a narrower solution exists, the heavier
one is forbidden. Crossing a high-intrusion boundary with no narrower solution
is a critical decision requiring 用户明确确认.

Treat existing callers without current-feature ownership/tag whose behavior
need not change as stable boundaries. Make the new feature depend on the stable
path; do not reverse old callers onto a feature-owned abstraction for naming
consistency, one-line reuse, testing convenience, or hypothetical future use.
Migration is eligible only when the abstraction owns a real shared invariant,
the owner already governs all affected callers, no narrower design works, and
the approved budget covers the change.

测试覆盖不能反向驱动生产架构. Prefer a test-owned translation unit/module,
existing extension point, narrow injected seam, capture tool, or black-box
verification. A local test macro may stay inside a test-owned boundary, but it
must not by default change a public enum or its `Num`, a registration matrix,
object layout, or spread test-only branches through shared production paths.
Evidence unavailable within the approved budget is `unverified` with risk and
manual-verification guidance. Pre-implementation Review checks the budget;
`post-landing Review` compares the final `intrusion delta`. A diff that 超出预算
invalidates the old design and Review and returns to design/user decision.

Ask the user for every critical decision: scope or acceptance changes,
public/API/Schema/compatibility or persistent-data changes, security or
sensitive data, external or irreversible effects, protected defaults,
user-owned changes, or material uncertainty. A minor decision is eligible for
automatic recommendation only when it stays within the approved scope, affects
one local component, has easy rollback, preserves compatibility and security,
has no external side effects, and has low uncertainty. If an independent
SubAgent is available, it may compare two to four valid alternatives. Adopt its
recommendation and save a validated `decision-record`; automatic adoption
requires `selectedId == recommendationId`. A structured self-review records
independence as `unverified`. Any failed criterion or desired deviation becomes
a critical decision and returns to the user. Store conclusions and evidence,
never private model reasoning. Usage is `agent-policy`; only the record contract
is mechanically validated.

**任务外异常隔离**：当前任务自身的根因或完成当前目标必需的故障仍按任务内问题诊断；执行中若发现与当前目标无关的工作流、安装或环境意外，必须立即停止当前任务并向用户报告现象、影响和已有最小证据。不得在原任务对话中擅自搁置原目标，继续调查、修复、重构工作流，启动 SubAgent 扩大旁路分析，或为此大量消耗上下文；只有用户明确回复授权后，才能另行处理该任务外问题。

### Convergence and stability budget

**设计阶段允许发散，实施阶段必须收敛**. After a design is accepted, every
code, test, tool, document, or workflow change must directly serve the primary
goal, an acceptance criterion, or an indispensable failure path.

**Plan 是实施边界**. The Plan freezes the objective, acceptance criteria, owner
layer, **允许修改的组件**, intrusion budget, and no-go boundaries. Implementation
may choose equivalent private local details needed to realize the same planned
behavior, but it must not add a behavior objective, owner, component, or
maintenance surface.

**发现问题不等于获得解决授权，计划外发现不得自动进入实现**. Root-cause
proximity, a broad regression failure, small size, schedule pressure, or sunk
work cannot authorize an unplanned change. If it does not affect current
acceptance, record it as **相邻改进** and **完成当前目标** first. If it **阻塞当前验收**,
stop the affected edits, report minimal evidence, **修订 Plan**, test scope, and
intrusion budget, then obtain **重新确认** before handling it.
**相邻改进只记录并延后，不实施**; complete the approved objective, Review, and
verification before considering another problem.

When support work starts to create an **独立接口、状态、生命周期或构建变体**, or
changes consumers whose behavior need not change, perform one **有界的收敛检查**:
is it already in the Plan and indispensable to the **主目标、根因修复或验收条件**,
is there a **更窄方案** through the existing path, and does it create a long-lived
owner, maintenance surface, or compatibility risk? If it is not planned, treat
it as an unplanned finding; return to the narrower design when possible. Any
necessary scope change stops implementation until the Plan is revised and
**重新取得用户确认**.

## Phase capability contract

Before classification or state-changing work, identify the capabilities the
current phase needs and report each as `supported`, `unsupported`, or
`unverified`. Only `supported` satisfies a required capability. An unsupported,
unverified, or missing report pauses the task with the missing capability,
purpose, reason, recommendation, permitted one-time alternative, and
non-waivable boundaries.

A one-time manual alternative requires explicit user authorization. It does not
change the capability report and never permits automatic downgrade. The
standard names and pause contract are defined by
[the lifecycle source](workflow/lifecycle.yaml) and
[the policy source](workflow/policies.yaml).

## Rule precedence

Protected rules have priority over ordinary skill rules, project rules, and the
personal overlay, in that order. Lower-priority layers have only the typed
`add-requirement` and `advisory` operations under ordinary-layer contract
version 1. Each operation contains a closed `kind`/`target`/`mode`/`value`
constraint from a finite vocabulary; arbitrary prose has no rule authority.
Duplicate ordinary IDs are rejected across layers. New operations or values
require a contract, schema, version, and test change. Ordinary layers cannot
replace a protected rule or alter the fixed protected evaluators. Their merge
result is deterministic and deeply immutable.

Repository-owner changes to protected rules require all four gates together:
an explicit confirmation attestation, an actual SemVer major increase, an
independent Review attestation, and a passed behavioral-test execution receipt.
All three receipts bind the canonical proposal hash over the base and proposed
rule hashes, both policy versions, an operation nonce, proposal time, validity
window, and expected behavioral-test invocation hash. Before collection, the
behavioral invocation input binds a pre-test subject containing those operation
fields without the invocation, avoiding a hash cycle. The proposal must precede
all three receipts; receipts cannot
be future-dated or outlive the proposal window. Owner Review accepts L2 or L3
through the same review-level comparator used by completion. Every referenced
artifact is resolved from a collector-sealed store and its canonical hash is recomputed. The exact
invariants and gate shape are in
[the protected-rule source](workflow/protected-rules.yaml), its
[closed schema](schemas/protected-rules.schema.json), and
[the tested implementation](src/selfworkflow/evidence.py).

`enforced` means the checked-in code or schema performs the stated check.
agent-policy depends on agent adherence and has unit-tested structure; it is
not technical or behavioral enforcement.
The protected set forbids fabricated capability, Review, or test claims;
silent degradation; exposure of credentials or sensitive information;
unauthorized side effects or irreversible operations; damage to existing user
changes; and completion without fresh verification evidence.

## Completion evidence

A trusted, deeply immutable completion policy is passed separately from the
evidence. It fixes task kind, C/R classification, the ordered required
capability list, required criterion and verification IDs, and implementation
identity. It also fixes a per-task operation nonce, artifact freshness window,
and the canonical expected invocation hash for each required verification.
Evidence cannot declare its own governing policy. C1/R1 requires at
least L0 Review; any C/R level 2 or 3 requires at least L2, with reviewer and
context independent from implementation. Only level 2 may fall back to L1,
and only when the trusted policy carries a typed authorization recording that
independent Review capability is unsupported or unverified, the user was
prompted, and the user explicitly authorized the fallback. Level 3 cannot use
this path. L1 fallback is same-host, new-context Review: the actor may be the
implementer, but the Review context must differ from the implementation
context. Evidence cannot self-report or silently trigger the exception.

A modifying task records exactly `classification`, `capabilities`,
`selectedSkills`, `acceptanceCriteria`, `changes`, `review`, `verification`,
`skipped`, and `residualRisks`. Structured change, Review, and verification
records cannot be replaced by empty collections or prose claims. Capability,
Review, and verification references resolve only through a collector-sealed,
deeply immutable artifact store. Review attestations record provider, receipt,
input and output hashes, decision, level, and identities; the collector derives
the input hash from the completion subject and the output hash from the actual
provided receipt content. Verification execution receipts additionally bind a
frozen invocation containing executable/module identity, argv, repository cwd,
controlled environment keys and digest, and input digest. The canonical
envelope is retained with its hash for audit; its cwd is `.` or a canonical
Windows-safe repository-relative directory. The input digest binds the current
task nonce, manifests, derived changes, complete acceptance graph, and result
content before the policy adds the expected invocation hash. Receipts record finite
check type, exit code, timestamps, and criterion links. The trusted policy—not
the evidence—fixes the expected invocation hash. Every acceptance criterion and
verification artifact links in both directions. Every skipped or
not-applicable item has a non-empty reason; required policy items cannot be
skipped.

Base and final file manifests are hashed and compared to derive the exact
added, modified, and deleted paths; declared changes must match that derivation
in both directions. The completion subject hash binds the trusted policy hash,
both manifest hashes, derived changes, the complete criterion/verification
graph (including descriptions, applicability, reasons, and links), and the
result-content hash. Review and verification receipts must bind that subject.
Completion requires `passed` verification observed within its declared
validity window. `failed`,
`not-run`, `partial`, stale, future-dated, clock-rollback, and hash-mismatched
evidence cannot complete. `not-applicable` is eligible only for a pure
`read-only` task with no change items.

Inputs use character/count checks before sequence materialization or UTF-8
encoding where the shape permits, followed by exact UTF-8 accounting. Evidence
JSON is limited to 1 MiB by characters and UTF-8 bytes; ordinary direct text is
limited to 64 KiB and identifiers to 1 KiB; canonical values are limited to
50,000 nodes, 1 MiB per string, and 8 MiB total. Artifact stores are capped at
2,048 records and receipt output at 8 MiB. Evidence collections are capped at
64 capabilities, 256 skills, 512
criteria/verifications/skips, 256 residual risks, and 10,000 changes. Manifests
are capped at 20,000 paths, 8 MiB per file, and 64 MiB total. Repository paths
are canonical Windows-safe relative paths with a 1,024-character path and
255-character segment limit; aliases by NFC/casefold, reserved device names,
ADS, traversal, absolute paths, controls, invalid characters, and trailing dots
or spaces are rejected.

These checks provide deterministic structural, hash, time, manifest, and
policy validation. `ArtifactCollector` is an explicit trusted collection
boundary that preserves audit fields; it is not a defense against malicious
code in the same process and does not independently prove that an external
provider executed a command. Provider trust and receipt acquisition are
deployment responsibilities. Nonces bind receipts to the current trusted
policy/proposal, while durable cross-process replay registries remain a future
transaction-layer responsibility. The collector rejects duplicate
`(provider, receiptId)` pairs within one store, including across artifact kinds.
Separately, `agent-policy` rules depend on agent
adherence and have unit-tested structure, not technical or behavioral
enforcement.

The stable field list and status policy remain in
[the evidence source](workflow/evidence.yaml). The concrete immutable JSON
fixture contract and completion checks are exercised by
[the evidence tests](tests/unit/test_evidence.py). Shared bounded-value,
canonicalization, and manifest checks are in
[the value helper](src/selfworkflow/_evidence_values.py); the typed invocation,
collector, receipt, and trusted-store boundary is in
[the artifact helper](src/selfworkflow/_evidence_artifacts.py).

## On-demand loading

流程深度与能力 Skill 选择相互独立：复杂度、风险和副作用决定流程深度；显式请求以及语言、文件和任务语义决定是否加载通用能力 Skill。加载能力 Skill 不会自动创建 Design、Plan、Review 或 Verify 流程；只读任务只应用 reasoning core，修改和副作用规则只在对应行为实际发生时启用。

The default engineering foundation is the pinned `mattpocock/skills` Submodule.
Full design automatically uses `grilling`; Deep design automatically uses
`grill-me`, whose upstream workflow runs `grilling` with deeper frontier
coverage. Light does not auto-start either module, and explicit selection is
allowed at any strength. Code design uses `codebase-design` when justified. Implementation
uses `implement` plus `tdd`; debugging uses `diagnosing-bugs`; Full/Deep Review
uses `code-review`. `to-spec`, `to-tickets`, and `grill-with-docs` remain
explicit modules. SelfWorkflow owns Plan structure, authorization, scope and
intrusion gates, real verification commands, and evidence; no Skill can replace
those host responsibilities. User-invoked upstream wrappers are orchestration
templates inside these gates: their commit, issue publication, document write,
or other side-effect steps require the corresponding SelfWorkflow/user
authorization. In particular, `implement` does not grant automatic commit.

For a project that needs a project-owned Review policy, the first code task in a new
project conversation checks only the explicit `.selfworkflow/review.yaml`
profile. A valid profile lists project-relative Skill paths, exact UTF-8 file
hashes, ordered entries, and `required` flags. It never scans, downloads, or
loads a project's Skill directory implicitly. The profile and all listed Skill
hashes are bound to the project identity and conversation; drift invalidates
the prior result. A missing profile is `absent`; a missing, unsafe, unreadable,
or hash-drifted Skill is `unverified` (required entries pause Review; optional
entries remain residual risk and are excluded from the reviewer manifest).

In Full/Deep code Review, the existing independent Standards and Spec
subagents both receive the same ordered project Skill manifest and the same
hash-verified Skill bytes. When at least one project Skill is verified, those
project Skills are the primary Review policy and the pinned generic Review
Skill is loaded only as a supplementary policy. With no verified project Skill,
the generic Review Skill remains primary. This precedence is explicit and
hash-bound in the reviewer payload; it does not change the generic safety,
TEA, independence, severity, or completion gates. The Host
accepts the project root and conversation identity at construction; for
Full/Deep code tasks it lazily creates one `start_project_review_session()` and
automatically obtains these paired inputs from `build_code_review_context()`
for implement, debug, and explicit code-review operations.
`dispatch_independent_review` strictly validates and freezes the manifest and
bytes before passing them to the two reviewer contexts; the CLI never prints
Skill source text. If the Host detects profile
or Skill drift, or the project identity changes, it rejects the old session
and requires a new one. The non-Grill code path uses
`Host.dispatch_code_review()` for distinct Standards and Spec dispatches; the
post-Grill path keeps the existing single design-review gate. The
project profile cannot alter protected rules, scope, severity, independence,
completion gates, or TEA requirements. Light, non-code, and design-only tasks
do not auto-load these project Review Skills. Hosts without two independent
contexts must report `unverified`; they must not claim that the extra Skill was
applied.

C/C++/Unreal tasks load the compact `cpp-core` by default and only the specialist
references justified by code signals. When the current work directory has a
configured, project-bound, fresh CodeGraph that covers the target files, use its
symbol, call, dependency, and navigation queries as the primary code-reading
path before broad text scans. Keep `rg` for exact literal searches, files outside
the graph, and final text-level confirmation; it is complementary, not the
default substitute for an available fresh graph. Check the binding and index
freshness first. A commit/index/version mismatch makes CodeGraph stale reference
only; report the mismatch and may ask whether the user wants an explicit
sync/rebuild. Missing, stale, or runtime-unavailable CodeGraph falls back to
`rg` without blocking basic analysis and never becomes fresh evidence.

At the first code task in a new conversation, perform one CodeGraph preflight
for the current work directory. If a bound provider exists but its index is
stale, tell the user and offer three explicit choices: update/rebuild then use
CodeGraph, use the existing index as stale read-only reference, or use no
CodeGraph for this conversation. Updating or rebuilding requires the user's
side-effect confirmation. Record the selected choice as conversation-scoped
state and do not ask again in the same conversation unless the user changes it
or the project/provider identity changes. When the user chooses CodeGraph, use
it for every available structural code-reading query in that conversation;
after an unsuccessful or unsupported update, keep the stale/unavailable label
and use `rg` only for uncovered or exact-text work, never as a silently fresh
replacement.

任务完成 Review 和验证后，若形成可复用的技术知识，主动提示一次是否沉淀到已配置的知识后端；简单问答、机械修改、临时状态和未形成稳定结论的任务不提示。每个任务最多提示一次，用户拒绝后不再重复；用户明确要求维护知识库时直接进入知识流程。

Load only the source needed for the current phase: lifecycle and policy for
capability checking or classification, protected rules for merging or governed
changes, and evidence rules for Review or completion. Load
[the core implementation](src/selfworkflow/evidence.py) only when executing or
auditing those deterministic checks. This keeps unrelated phase material out of
the active context while preserving direct links to every implemented contract.

## Engineering Skill source support

SelfWorkflow installs only the curated Matt Skills named in
`dependencies/locks/matt-pocock-skills.lock.yaml` from the pinned
`dependencies/upstream/matt-pocock-skills` Gitlink. It does not copy or load the
whole upstream repository into task context, and updates require an explicit
Submodule revision change plus new hashes and tests. The upstream `grilling` and
`grill-me` are routed by workflow strength as stated above; they remain
capability- and confirmation-gated. SelfWorkflow does not require, install, route to, or silently
fall back to Superpowers. A user may explicitly request an already available
Superpowers Skill for one task; that choice does not replace protected workflow
gates or make Superpowers a default dependency.

## Adapters, knowledge, and release governance

Vendor adapters are thin capability declarations and bootstrap entries; they
cannot override protected invariants. Runtime builds contain checked-in sources
and generated Catalog data, never maintainer-local source paths. Knowledge is an
optional `read -> propose -> update` extension: propose never publishes, update
requires explicit confirmation and verified compare-and-swap semantics, and
private model reasoning is not durable knowledge. A backend contract gap remains
`unverified` rather than being inferred.

Release eligibility requires a clean source commit, fresh passed unit,
conformance, installer, and behavioral receipts, independent L2-or-higher Review,
and native evidence for both Codex CLI and Desktop. Static conformance cannot be
promoted to native support. Skipped checks and residual risks remain visible in
the release manifest.
