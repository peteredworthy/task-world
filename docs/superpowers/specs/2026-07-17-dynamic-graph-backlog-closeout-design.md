# Dynamic Graph Backlog Closeout Design

## Objective

Close the post-W5.5 dynamic-graph backlog from fresh main without trusting stale
status prose. Re-triage the four July 7 findings, regression-pin every confirmed
bug before fixing it, complete the W8 residual, and leave the graph runner policy
explicit and executable.

The work starts from `60ca04f96` on `codex/backlog-closeout` in
`worktrees/backlog-closeout`. It does not merge to main or modify durable runtime
state.

## Confirmed Triage

Fresh-main source inspection classifies all four Task 0 findings as `OPEN`:

1. The incremental projection-snapshot path still calls the local
   `_scheduler_view_from_projection`, whose behavior differs from canonical
   `project_scheduler_view` for `max_grants_reached`.
2. The graph UI displays pending gates without an action and the CLI approval
   command still submits only to the legacy step approval endpoint.
3. `CLIProcessAgent` still prepends Codex `--model` before the `exec`
   subcommand.
4. Cross-region supersession has focused projection/read-model tests, but no
   incident-shape replay through the real graph store that proves task states,
   final blockers, and completion-gate state are clean together.

The `claude_sdk` graph-runner fence is already implemented and regression-tested.
Task 2 therefore documents and retains the fence rather than duplicating it.

## Delivery Strategy

Use guarded consolidation rather than limiting the change to isolated symptoms.
Every consolidation starts with an executable parity oracle, preserves the
kernel as the source of truth, and lands in a separately reviewable commit.

The delivery units are:

1. Triage ledger and regression fixes.
2. Canonical read-model consolidation.
3. Pure driver-policy relocation.
4. Graph export pruning and incident-guard retirement ledger.
5. `claude_sdk` graph-runner decision record.
6. Final branch verification and durable evidence update.

## Regression Fixes

### Snapshot Scheduler Drift

Add a regression that drives representative events through the real store,
captures the incremental snapshot scheduler view, rebuilds read models, and
compares both with the canonical projection. The fixture must include a ready
node whose latest deferral is `max_grants_reached`.

The implementation replaces hand-derived scheduler and lease snapshot views
with canonical projection functions. The snapshot path may adapt return types,
but it must not restate classification policy.

### Human-Gate Approval

Support both shipped operator surfaces:

- The Graph panel presents actions for pending human gates. An action opens a
  full modal with the gate prompt, consequences, optional note, Cancel, and a
  clearly labelled approve or reject action. No inline confirm/cancel pair is
  placed in the compact gate row.
- `orchestrator runs approve` detects graph execution, reads pending graph
  decisions, and submits approval or rejection to the graph decisions endpoint.
  Legacy runs retain the existing step-approval path.

Both paths send typed decision data containing the target gate identity,
decision, actor, and optional reason. API-boundary validation rejects unknown
decision values and invalid or non-pending gate targets. Integration coverage
proves the decision is durable, visible in graph readback, and releases a
successor waiting on approval.

### Codex CLI Model Routing

Add a construction test for the exact Codex argv. For Codex, insert
`--model <name>` after `exec`; retain existing ordering for other subprocess
commands unless their parser requires a different placement. The test asserts
the complete argv rather than an internal fragment.

### July 4 Supersession Replay

Replay the incident sequence shape through a real SQLite-backed
`GraphEventStore`: origin candidate, failed verifier, recovery/gap-planner
continuation, corrective candidate that declares the origin-region
supersession, passing corrective verification and file state, and final-gate
evidence. Assert:

- origin and corrective task regions both project as accepted;
- compact, incremental-snapshot, and rebuilt projections agree;
- final blockers are empty; and
- the final gate permits completion.

If RED exposes projection residue, make the smallest correction in
`projections.py`. If it is already behaviorally fixed, the test and stale
incident/recommendation status updates are the closure.

## Canonical Mirror Consolidation

Use the implementation review's mirror census as a closed scope. Before
replacing any mirror, add a parity test that exercises its decision fields.
Derived read models must then do one of the following:

1. call the canonical kernel projection;
2. derive fields from the typed event schema; or
3. retain a dedicated parity/AST guard where direct reuse is not practical.

Do not redesign unrelated read models. A failed parity test stops the sub-slice
and narrows the discrepancy; it does not justify a broad rewrite.

## Driver Policy Relocation

Move only pure, projection-derived classification from
`workflow/graph_driver.py` into the graph kernel's public surface. Candidate
functions include graph outcome classification, completion eligibility, blocked
reason derivation, failed/deferred-node explanations, missing-input sources,
active-lease wait planning, and node retry limits.

The following remain effectful driver responsibilities:

- worktree contamination snapshots and enforcement;
- lease renewal, expiry, and orphan recovery;
- operator reopen and crash bridges;
- stale-projection and transient SQLite retries;
- lifecycle persistence and signal integration; and
- polling and wait timing.

Before moving policy, tests pin completed, blocked, failed, active-lease,
retry-exhaustion, and contamination outcomes. Relocation is mechanical: behavior
and event ordering must remain unchanged. Event-triggered driving and lease or
lifecycle semantic changes are out of scope.

## Graph Export Pruning

Build the package-level consumer set from imports across `src` and `tests`, as
required by the W8 spec. Remove only names with no repository consumer. Symbols
used solely by tests still have consumers and remain available through
`orchestrator.graph`, preserving the W5 public-import rule. Do not introduce
external direct imports from graph submodules as a pruning shortcut.

Run full test collection immediately after the prune, followed by pyright and
the full suite.

## Guard Retirement Ledger

Create a durable ledger for each incident-era guard in driver, dispatch, and
recovery code. Each row records:

- guard and source location;
- originating incident or failure class;
- current observable behavior;
- current regression evidence;
- kernel/runtime behavior required before retirement; and
- current disposition: load-bearing, replaceable, or retired.

The ledger must reconcile the review's July 7 conclusion that the remaining
effectful guards are still load-bearing with the newly relocated pure policy.
It does not treat event-triggered driving as a retirement prerequisite.

## Claude SDK Decision

Record `fence off` as the decision:

- `claude_sdk` remains supported for non-graph runs;
- `codex_server` remains the only supported graph runner;
- graph runs using `claude_sdk` are refused before graph seeding with
  `graph_runner_unsupported`; and
- the historical Stream-closed/cancel-scope failure and existing regression
  tests are the rationale and enforcement evidence.

No inline SDK repair is attempted. Reconsideration requires a separate plan
with a deterministic reproducer, SDK lifecycle analysis, callback transport
tests, and graph-run product proof.

## Documentation And Evidence

Update the durable sources as items close:

- `docs/dynamic-graph/status.md`;
- `docs/dynamic-graph/w8-drive-loop-cleanup-spec.md`;
- `docs/dynamic-graph/dynamic-graph-implementation-review.html`;
- the July 4 incident report;
- R01 in `research/recommendations/`; and
- new guard-retirement and runner-decision documents.

Each status entry records the RED test, GREEN test, verification commands,
counts, and commit SHA. Documentation must distinguish an already-present code
fix from newly added regression evidence.

## Verification And Commit Boundaries

Builders run focused tests while iterating. Each delivery task ends in a task
commit, then a fresh verifier with no builder context runs:

```bash
uv run pytest tests/ -q -n auto --dist worksteal
uv run ruff check .
uv run pyright
git diff --check
```

The verifier result is recorded in the relevant durable document and committed
as evidence. A final fresh verifier repeats all four commands over the complete
branch. No builder self-report counts as verification.

## Scope Brakes

This closeout does not:

- convert the driver to event-triggered execution;
- alter lease or run-lifecycle semantics;
- perform wholesale legacy-engine retirement;
- repair or remove `claude_sdk`;
- introduce direct external imports from graph submodules; or
- modify `orchestrator.db` or `.orchestrator/state/history.jsonl`.
