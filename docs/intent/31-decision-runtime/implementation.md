# Sol implementation prompts

Execute the slices in order. Each numbered section is a builder assignment.
Start every assignment by reading these shared rules, [architecture.md](architecture.md)
and the normative [contracts.md](contracts.md). Implement those settled contracts;
do not independently choose different answer shapes or accounting semantics.
The architect owns cross-slice contract decisions; one builder edits shared graph
and runtime code at a time. A fresh Sol reviewer uses [review-prompt.md](review-prompt.md)
after each slice. Review is based on concrete code and evidence, not the builder's
conclusion.

## Shared execution rules

Work only in `/Users/peter/code/task-world/worktrees/recovery-stabilization`.
Read `AGENTS.md` and inspect current status before touching files. Compare
unchanged baseline files with `docs/reviews/recovery-successor-validation-result.json`;
after implementation starts, use the preceding slice's recorded hashes too.
Do not restore the old baseline over valid newer slice changes.

Run Python commands with:

```bash
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync ...
```

The worktree contains a large, already reviewed, uncommitted recovery change.
Preserve it, its exact evidence and all historical documents. Do not operate on
the main checkout, live database or live history. No live server starts,
activation, historical-run resumes, paid orchestration probes, commits or paid
automatic retries are authorized by these prompts. Temporary repositories,
SQLite stores, injected scripted transports and test servers inside disposable
integration fixtures are the authorized validation environment.

Use real objects and dependency injection, no mocking or monkeypatching. Keep
public module import boundaries, immutable projections and event/outbox ownership.
No migrations, schema deletion, new service or generic decision framework.
Use Pydantic at new boundaries. Preserve unsupported-runner rejection and user
runner/model selection. Caps remain opt-in; recovery cases explicitly use two
received rejected proposals and one model execution, with a model stop deadline
of at most 180 seconds and separately bounded exact-owner cleanup.

Run focused checks for changed behavior. Repeat a test only for a changed file,
failure or named unresolved concern. Run the complete repository gate once after
the final slice is integrated and reviewed; if a commit is separately requested,
its unmodified hooks can supply that gate. Never bypass or suppress a failure.
Pause all tracked-file edits while pre-commit runs, including ledger edits.
The previous supervisor caused an avoidable full rerun by editing a ledger during
the test hook; do not repeat it.

For each slice record: starting/final source hashes, changed files and removed
duplication, exact commands and results, regression evidence, accepted contract
changes, independent review and remaining concerns. Create a new implementation
ledger under this directory; do not rewrite old recovery results. A scriptable
schema/lifecycle pass proves infrastructure only. No model reliability claim may
be inferred from it.

If the proposed atomic finalization or one-owner schema design cannot be achieved
using the named boundaries, stop the affected slice with a minimal reproducer and
a precise alternative for architectural review. Continue independent safe work.
Do not quietly introduce a second protocol, weaken authority, or defer a required
behavior while marking the slice complete.

## Slice 1 — Canonical decision contracts and frozen selection

**Builder prompt:**

Implement the minimal contract foundation from the architecture. This slice must
not activate new runtime behavior. Its purpose is to give later slices one typed
source for each answer and one authoritative selection of its interpretation.

Inspect `graph/contracts.py`, `graph/models.py`, `graph/compiler.py`,
`graph/semantic_artifacts.py`, `graph/macros.py`, `graph/command_bindings.py`,
`config/models.py`, `runners/types.py`, `runners/submission.py` and their public
exports. Confirm the exact current fields before extending them.

Add the optional validated routine selection `agent_interaction_contract` with
`decision-v1` as the new value and omission selecting legacy. Freeze selection
in the existing routine snapshot record. Resolve node applicability through one
graph-owned function using node contracts, trusted role/stage and exact bound
snapshot. Reject unknown versions and partial/untrusted references. Do not read
mutable routine config to interpret an existing attempt.

Create the graph-owned built-in models specified in contracts.md: discovery
brief, implementation plan, batch decision, correction, verification and work
result. Stage their use through the ordered slices. Implement the specified
fields, discriminators, aliases and strict validation. Exclude graph
positions, lease/candidate/record IDs, raw ops and duplicated known plan fields.
Use scoped aliases only for meaningful choices among supplied alternatives.

Define executable check choice once, reusing current command-binding semantics.
Generate built-in answer JSON Schema from its Pydantic owner. Preserve custom
YAML-authored semantic schemas as their own authority. Existing plan `checks`
strings remain descriptive; never execute them by interpreting arbitrary prose.
New built-in typed plan declarations use a new identity/version. Generate and
freeze them through the existing semantic declaration machinery instead of
duplicating their fields into routine YAML.

Reuse `SubmissionContract`/`SubmissionOutputContract` as the graph-agnostic runner
view. Implement the specified tagged CAS envelope and frozen request bindings;
preserve legacy `output_records` decoding. Add the small trusted internal
submission-invocation envelope for delivery identity through the existing
callback, without changing authored output schemas or adding another registry.

Acceptance:

- Absent/new/unknown contract values and snapshot round trips are tested on fresh
  temporary state. Old serialized records still validate and replay as legacy.
- Runtime cannot accept a model-selected contract, schema version or authority.
- A built-in answer-field change propagates from one owner through the generated
  declaration and submission schema. Invalid extra fields are rejected.
- Tests expose the descriptive-check/executable-check distinction and reject a
  missing executable binding; no second handwritten shape is added.
- No existing runner, tool catalog or runtime behavior changes before slice 2.

## Slice 2 — One successor answer through atomic finalization

**Builder prompt:**

Prerequisite: slice 1 reviewed and passing. Implement the first complete vertical
slice for a decision-v1 successor. A model supplies one typed answer through
`submit(outputs=...)`; the runtime derives its graph consequences and completes
the existing lifecycle. Use the existing deterministic successor fixture as the
starting point, giving new-contract results separate identities.

Inspect `graph_runtime/dispatch.py` (`_submission_contract`, `on_submit`,
`_submit_callback`, `_finalize_runner_execution`),
`graph/commands/boundary.py` staging/finalization, `graph/callbacks.py`,
`graph/patch_validator.py`, `graph/macros.py`, and the existing controller/store
event-plus-outbox transaction. Implement the graph-owned pure decision compiler,
sharing the existing macro's semantic expansion rather than calling a live graph
patch command from the answer callback.

Bind the selected batch, accepted plan/verifier records, exact requirements,
check policy and remaining horizon in code. A `proceed` answer may add useful
implementation notes; it does not re-enter known scope/identity/check metadata.
Derive deterministic effect IDs and read sets from the bound request, canonical
answer and contract. Validate complete topology through existing graph rules.

At submit, validate and stage the answer/context as bounded CAS content. Dry-run
the same compiler and effect validation without publishing graph effects. The
adapter then closes the phase as specified in contracts.md, without depending
on another model action. After trusted terminal closure and exact boundary
witness, finalization publishes
decision, graph effects and completion in the same controller transaction.
Evaluate the planner completion contract on the prospective graph. Remove the
construct-first pre-submit condition only for the new contract.

Exclude decision-v1 from `accepted_graph_patch_before_agent_death` completion.
No staged answer, successful tool response or accepted dry-run can finish a node
after the runner fails. Preserve exact legacy behavior for old snapshots.

Use the existing shared submit schema for Codex dynamic tools and Claude CLI's
per-execution graph MCP. The new successor catalog exposes no graph constructor,
raw patch or separate finalization tool. Keep permitted evidence-inspection tools.
Do not add graph support to OpenHands or CLI Codex as part of this slice.

Acceptance, through production routing and disposable Git/SQLite:

- One successor answer yields the exact required final horizon, one finalized
  execution, no duplicate effects and no model-authored internal IDs.
- A scripted model that continues after answering cannot perform further work;
  the runtime closes the phase. Lost response delivery does not require another
  model turn. Generic interruption and unexpected process loss cannot pass.
- No downstream region/dispatch is published between staged acknowledgement and
  successful completion witness. Failed return, cancellation and post-answer
  mutation each prevent publication and drain ownership. Exercise cancellation
  on both sides of the serialized finalization boundary, including after witness.
- Lost acknowledgement, duplicate answer and duplicate finalization preserve
  one effect set; a different answer after staging conflicts.
- Unrelated graph movement can complete without another model execution; changed
  bound plan/evidence/authority cannot reuse the old answer.
- Both supported transport surfaces advertise and validate the same answer
  contract. Legacy constructor+submit and historical replay remain passing.

## Remaining slice structure

Each lettered sub-slice below is a separate builder assignment and is reviewed
before the next begins. The Builder follows the behavior-first test rule in the
`mind-the-gap` skill: create or update high-quality behavioral tests, observe the
expected failure, and only then change implementation code. Keep judgment where
it is useful and remove bookkeeping from model answers; do not replace the
runtime changes with more instructions in macro prompts.

## Slice 3A — Shared decision schema consumers

**Builder prompt:**

Prerequisite: slice 2 reviewed. Consolidate decision-v1 schema and shape
consumers in `graph_runtime/prompts.py`, `runners/planner_tools.py`,
`runners/agents/codex/common.py`, `graph_runtime/graph_mcp_tools.py` and
`runners/submission.py` without adding another decision lifecycle. Decision
packets describe the question, bound evidence, available choices and generated
answer schema. Remove current-profile handwritten JSON shapes and
constructor/submit sequencing instructions. Preserve useful task guidance and
all legacy schemas.

Acceptance: one canonical answer-field change reaches prompts plus the actual
Codex and Claude/FastMCP submit validators. Both real catalogs build and accept
or reject the same authored values. Decision catalogs expose no graph mutation
tools; legacy catalogs and unsupported-runner preflight remain unchanged.

## Slice 3B — Initial planning decisions

**Builder prompt:**

Prerequisite: slice 3A reviewed. Implement decision-v1 initial planning with the
canonical `DiscoveryBrief` answer. Bind known scope, requirements and available
evidence in code; the model supplies only the remaining judgment. A fully
supplied brief stays deterministic when the routine contract permits it, and a
requested independent step is never silently bypassed.

Acceptance: behavior covers a valid brief, missing/duplicate/unknown choices,
fully supplied deterministic input, frozen authority and restart. No answer can
broaden scope, replace requirements or author internal identity.

## Slice 3C — Discovery plan and verifier handoff

**Builder prompt:**

Prerequisite: slice 3B reviewed. Make discovery produce the declared
`ImplementationPlan` semantic artifact in a read-only workspace. Reuse the
existing semantic artifact assembler and controller-owned provenance. Validate
and bind the exact schema/version, requirements, plan record and independent
plan verifier before successor dispatch.

Acceptance: the real discovery→plan-verifier handoff preserves fresh contexts
and exact records. Read-only discovery cannot modify the candidate. Invalid plan
shape, requirement aliases, dependency cycles, unknown checks, failed
verification and post-answer mutation fail before successor publication.

## Slice 3D — Successor amendment and blocker decisions

**Builder prompt:**

Prerequisite: slice 3C reviewed. Complete the `BatchDecision` branches not
implemented by slice 2. `revise_plan` creates an independently verified plan
amendment and follows existing supersession rules before new work. It cannot
alter accepted work or weaken required acceptance. `blocked` uses the existing
blocker/human-action path. Preserve the working `proceed` behavior.

Acceptance: behavior covers valid and rejected amendments, accepted-work
preservation, final/non-final horizons, dependency ordering, blocker routing,
stale authority, replay and cancellation. Unknown aliases or cyclic amendments
publish no effects.

## Slice 3E — Gap and correction decisions

**Builder prompt:**

Prerequisite: slice 3D reviewed. Implement canonical gap-planner answers for
`no_gap`, corrective work, plan revision and escalation. Replace inference from
executor-local `_accepted_gap_planner_patch_had_ops` with the durable answer.
Derive gap records, correction topology and exact baseline/evidence bindings in
code.

Acceptance: deterministic and production-path behavior covers no-gap, valid
correction, plan revision, escalation, unknown evidence, stale baseline,
restart, cancellation and duplicate delivery. A decision cannot broaden scope,
drop mandatory commands or mutate an accepted candidate.

## Slice 3F — Mixed planning integration

**Builder prompt:**

Prerequisite: slices 3A–3E reviewed. Run the real
root→discovery→plan-verifier→successor and rejected-plan→correction paths through
disposable Git/SQLite and production dispatch. Verify exact typed handoffs,
fresh contexts, continuation/final horizons and zero leftover ownership.

Acceptance: the joined planning cases pass for Codex Server and Claude CLI's
per-execution graph MCP. Legacy constructor+submit, historical replay,
unsupported graph runners and existing non-graph OpenHands/CLI behavior remain
passing.

## Slice 4A — Typed verifier judgments

### Review prerequisite and lessons from slice 3

The September 12 review found that slice 3 is not yet fully closed. See
[slice-3-review.md](slice-3-review.md) for the current evidence and corrections.
In particular, the generated rejected-plan recovery path must run through gap
dispatch before slice 4 begins. The current correction resolver requires a
verified baseline batch; a rejected initial plan has neither a passed plan
verifier nor a selected batch. A seeded rejected-batch test does not prove this
handoff. Resolve the plan-repair authority contract explicitly, then prove the
generated rejection path without fabricating a passing report or batch identity.

Apply the following constraints throughout slices 4A–4E:

- Freeze the question, ordered obligation/evidence aliases, candidate, schema
  and policy at dispatch. Staging and finalization must validate those exact
  bindings. Permit unrelated graph movement through the existing read-set
  checks; never refresh an old answer's authority from the latest projection.
- Keep plan verification, prior-batch verification and final audit as distinct
  authorities. Exercise disjoint requirement sets across dependent batches,
  shared requirements, and amendment verification at the same horizon. Derive
  coverage and aliases from the bound ordered obligation set, not map iteration
  or the global run requirements.
- Validate meaning as well as shape in every disposition. Slice 3 review found
  unknown evidence accepted by `no_gap` and unchanged amendments accepted as new
  work. Include unknown/cross-candidate evidence and semantically ineffective
  answers in the verifier and worker negatives.
- Exercise one report citing several failed mandatory checks. Preserve every
  exact receipt and its provenance; multiple check failures do not imply
  multiple candidate or verification authorities. Check reuse must validate all
  candidate, command, environment, policy and freshness dimensions.
- Apply shared decision-contract precedence before legacy role/tool flags, so
  typed verifiers cannot advertise `graph_grade` or require a second submit.
  Test generated schemas through actual Codex ingress and connected Claude MCP
  calls. A registered route or a direct callback alone proves neither transport.
- Continue rejected cases through the generated corrective dispatch and its
  independent verification. Assert fresh contexts, exact accepted records,
  terminal leases/attempts and removed MCP routes at each completed phase;
  distinguish deliberately unexecuted downstream nodes from completed work.
  During process cleanup, distinguish unavailable inspection from proven exit:
  wait within the existing bound and revalidate identity before another signal.
- When adding records, update the output-record payload inventory, canonical
  projection record set, flexible-JSON manifest and public exports together.
  Preserve explicit legacy applicability and custom YAML schema authority.
- Check whether repository boundary tools include untracked files. The graph
  boundary command scans `git ls-files`, so its pre-staging success missed
  private storage access in new slice 3 tests. Include new files in the index
  before claiming that check covers them; keep all test reads on public queries.

Fully supplied initial input still retains the explicitly requested planner:
the frozen routine schema has no policy authorizing deterministic bypass. This
is a documented policy limitation, not evidence that bypass was implemented.

**Builder prompt:**

Prerequisite: slice 3F reviewed. Replace decision-v1 verifier `grade(...)` plus
submit sequences with one canonical `VerificationDecision` for the exact bound
obligation set. Implement ordered obligation aliases, coverage and grade rules,
the canonical decision artifact and minimal report reference. Do not create
requirement records for rubric text.

The model supplies judgments, reasons and evidence aliases. Code resolves those
aliases, derives the outcome and constructs candidate/provenance fields. Derive
coverage from bound obligations rather than global run requirements. Keep
verifier and final-audit contexts independent.

Acceptance: valid, empty, missing, duplicate, unknown and cross-candidate
findings have behavioral coverage. A validly shaped answer cannot omit an
obligation or select another candidate.

## Slice 4B — Runtime-owned mandatory checks

**Builder prompt:**

Prerequisite: slice 4A reviewed. Execute mandatory checks through the existing
runtime command machinery against the exact candidate being judged. Reuse a
receipt only when candidate, command, environment, policy and freshness all
match; otherwise execute once at the correct boundary.

Acceptance: prose or model grades cannot override a missing or failed receipt,
wrong candidate, incomplete coverage or post-answer mutation. Exact
command/candidate evidence retains attribution across restart. Work products,
judgments and mechanical receipts remain distinct in public evidence.

## Slice 4C — Worker results and semantic products

**Builder prompt:**

Prerequisite: slice 4B reviewed. Implement decision-v1 worker `WorkResult`
submission while retaining the code and artifact authoring tools required by the
task. The answer supplies readiness or a blocker plus declared semantic
products. Code owns checks, file-state snapshots, commits and completion. Do not
add a second model pass to announce the same result.

Acceptance: ready, blocked, required custom semantic outputs, missing outputs,
failed checks and post-answer mutation run through the real worker path. The
reported passing candidate is the committed candidate.

## Slice 4D — Advisory typed submissions

**Builder prompt:**

Prerequisite: slice 4C reviewed. Route existing appeal, oversight and recovery
advisory outputs through the shared typed submission plumbing without granting
their authors lifecycle or graph-mutation authority.

Acceptance: advisory output retains exact provenance, cannot complete or mutate
authoritative work, and preserves existing legacy behavior.

## Slice 4E — Verification integration

**Builder prompt:**

Prerequisite: slices 4A–4D reviewed. Run correct and deliberately defective
neutral candidates through the production worker, verifier, mandatory-check and
correction path using disposable Git/SQLite.

Acceptance: correct work completes with a committed candidate and complete
evidence; semantic failure creates the existing bounded corrective path; false
acceptance cases remain blocked. Legacy grader adapters and YAML-authored custom
semantic outputs retain their recorded behavior.

## Slice 5A — Failure classification and diagnostics

**Builder prompt:**

Prerequisite: slice 4E reviewed. Centralize classification of answer-validation,
stale-binding, execution, candidate/check, infrastructure/environment and budget
failures using existing failure carriers where possible. Do not create
provider-specific retry taxonomies. Publish concise diagnostics with protected
evidence references and an explicit next action when correction is allowed.

Acceptance: bad shape, stale evidence, failed checks, process failure,
environment blockage and exhaustion take distinct observable paths. An
environment failure never dispatches a code correction.

## Slice 5B — Attempt and rejection budgets

**Builder prompt:**

Prerequisite: slice 5A reviewed. Implement contracts.md's first/second rejection
behavior. Recovery fixtures explicitly use two rejected proposals and one
execution. Count every invalid answer received at orchestrator ingress,
including normalization failures. Deduplicate transport redelivery, but count a
new delivery/answer attempt even when its invalid content is identical.

Keep runner creation observations separate from recorded attempts. Cancellation,
transport reconnect, checkpoint rebuild and restart cannot reset counters.
Upstream provider/FastMCP rejections that never reach ingress remain diagnostics,
not invented attempts. Preserve opt-in legacy limits.

Acceptance: behavior covers first rejection, second rejection/exhaustion,
identical redelivery, a new identical attempt, upstream rejection, restart and
graph-position-only conflicts without spending execution allowance.

## Slice 5C — Deterministic recovery and cleanup

**Builder prompt:**

Prerequisite: slice 5B reviewed. Route infrastructure failure through bounded
deterministic recovery and exact-owner cleanup. A semantic correction requires
diagnostic evidence, applicable inputs and remaining allowance. Exhaustion stops
dispatch; a stronger model or different runner still requires explicit user
selection. Restore the last accepted baseline and preserve rejected candidates.

Acceptance: recovery and repeated restart preserve ownership, counters and
evidence. A staged decision followed by death never uses the legacy
accepted-patch shortcut. Cleanup affects only the exact execution owner.

## Slice 5D — Protected receipts and local replay

**Builder prompt:**

Prerequisite: slice 5C reviewed. Extend protected receipt/replay to the new
answer schemas and compiler identity. Preserve canonical request/response,
contract hash and bound context within existing byte/count limits. Missing,
oversized or unreceived evidence stays explicitly incomplete. Local replay must
precede another paid execution after a paid rejection; this slice performs no
paid execution.

Acceptance: accepted and rejected answers replay after disposable workspace
deletion. Source, contract or receipt tampering, empty receipts and unknown
versions fail closed. Replay never relabels the original experiment result.

## Slice 5E — Recovery crash matrix

**Builder prompt:**

Prerequisite: slices 5A–5D reviewed. Exercise crashes at pre-stage, post-stage,
post-witness and post-commit/pre-ack boundaries through production recovery.

Acceptance: replay/redelivery creates no duplicate effects, lost decision or
incorrect completion. Cancellation and repeated restart preserve budgets and
exact ownership, and all failure classes retain the intended next action.

## Slice 6A — Qualification identity and deterministic probes

**Builder prompt:**

Prerequisite: slices 1–5E reviewed with no unresolved required behavior. Extend
the existing qualification identity and deterministic probes without running a
model evaluation. Do not treat legacy qualification as proof of decision-v1.

Extend existing `reliable_plan_evaluation` manifests/qualification identity to
bind the new interaction and generated schema/compiler contract. Retain legacy
qualification semantics and replay. Use the current sequential product-path and
deterministic lifecycle infrastructure rather than creating a second driver.
Update recovery probes with separate new-contract cases/results; preserve their
old source-bound evidence.

Acceptance: qualification and replay distinguish legacy from decision-v1 and
reject mismatched schema/compiler identities. No model call is made.

## Slice 6B — Joined planning and execution cases

**Builder prompt:**

Prerequisite: slice 6A reviewed. Use the existing production driver for the core
joined success cases.

Use disposable real Git/SQLite and production create/start,
signal consumer, graph driver, dispatcher, controller, runner routing and
completion for one batch, dependent multiple batches and an independently
verified plan amendment. Keep exact product oracles, a clean committed candidate
and zero remaining active ownership/outbox work where completion is claimed.

Acceptance: all three cases complete through the production path with their
exact candidate and evidence, including restart-safe public readback.

## Slice 6C — Joined correction and failure cases

**Builder prompt:**

Prerequisite: slice 6B reviewed. Add an evidence-backed corrective cycle, a
blocked case, cancellation/restart, defective-candidate/verifier negatives and
contract compatibility controls to the same production driver.

Acceptance: failures remain bounded, false acceptance is zero in the declared
cases, and interventions are recorded. Distinguish intentionally unexecuted
isolated nodes from unfinished joined execution.

## Slice 6D — Smoke result and public readback

**Builder prompt:**

Prerequisite: slice 6C reviewed. Run the deterministic smoke case and verify its
public explanation.

For the smoke case, require only `stage3-smoke.txt` added, mode 100644, exact bytes
`stage3-smoke-ok\n`, and a clean candidate checkout. Phase counts must follow the
new semantics, not an arbitrary requirement to retain seven model phases.
Distinguish intentionally unexecuted isolated-probe nodes from unfinished joined
execution. Verify public readback still explains the accepted result.

Acceptance: the exact file oracle, clean checkout, terminal ownership and public
evidence all agree.

## Slice 6E — Evaluation manifest

**Builder prompt:**

Prerequisite: slice 6D reviewed. Prepare the fixed model-evaluation manifest; do
not run it.

Prepare a fixed model-evaluation manifest using the same cases and existing
evaluation carriers. Declare expected product outcomes, false-acceptance
negatives, allowed intervention, model/runner assignment, per-case and total
budgets and stop rules. Report raw counts/denominator, correct completion,
false acceptance, bounded failure, intervention rate, latency and available
actual usage/cost, including failed attempts. Missing accounting stays unknown.
Do not propose an arbitrary reliability percentage from a handful of successes.
The operator must authorize the manifest and budget before any paid batch.

## Slice 6F — Final gate and handoff

**Builder prompt:**

Prerequisite: slice 6E independently reviewed.

After independent integrated review, run the complete unmodified repository
gate once with all edits paused. Fix any failure; preserve every attempt's
exact log and source hashes. Update architecture navigation only for modules,
contracts or routes actually implemented. Save a final source manifest, review,
compatibility matrix, deterministic results and limitations in the new ledger.

Completion requires all earlier criteria, full gate success and a concrete
reviewable rollout/evaluation card. Leave changes unactivated and uncommitted
unless the operator separately authorized those actions. No live-history
conversion, paid probe or historical-run resume is part of completion.
