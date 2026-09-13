# Isolated successor-planner experiment

Prepared September 11, 2026. **Independent deterministic preparation and review
passed. The complete repository gate passed. Paid execution is not authorized.**

The question is whether one fresh Luna-medium successor planner can consume the
production successor packet after accepted discovery and plan verification,
construct the one effectful final horizon for `stage3-smoke.txt`, then complete
plain submission and runner finalization without modifying the fixture.

The failed Stage 3 run identified this phase: its first successor execution
returned without successful submission after ten rejected commands; automatic
recovery started another execution with four more rejections. Ten historical
generic rejections lack original arguments. This fixture exercises the same
phase and semantic boundary; it is not an exact replay of those missing inputs.
Historical runs and evidence remain untouched.

## Fixture and production path

Use a fresh disposable Git repository and linked worktree with `SMOKE_SPEC.md`.
The eventual candidate contract is exactly one added regular file, mode 100644,
`stage3-smoke.txt`, containing `stage3-smoke-ok` plus one newline. The isolated
planner must leave the seed fixture unchanged. Its accepted graph describes the
effectful worker, check and verification work; those downstream phases are not
executed in this experiment.

Scripted initial planning, discovery and plan verification advance real
compiler/controller/dispatch/submission/store paths. The successor must be
created by that accepted history and carry its bound plan-verification record,
remaining horizon and sealed assignments. A root planner with a different label
does not satisfy this prerequisite. Deterministic setup is measured separately
and must succeed before constructing a paid runner.
The isolated seed uses synthetic qualification evidence, as the existing
no-model lifecycle does. This experiment does not exercise live REST
qualification, create/start admission or activation.

## Proposed allowance and stop rules

- Model: `gpt-5.6-luna`; reasoning: `medium`; runner: `codex_server` with managed
  restrictions. Exactly one fresh successor execution; no paid setup agents.
- Explicit routine inputs: `max_rejected_plan_proposals_per_planner: 2` and
  `max_planner_executions_per_node: 1`. Caps remain opt-in in production.
- At most 180 seconds before requesting cancellation of the successor phase.
  Setup and safe ownership draining are reported separately. No native token,
  action or dollar cap is claimed, and the stop deadline is not a guarantee that
  subprocess cleanup has already finished.
- No downstream dispatch, automatic paid recovery, manual resume, second
  invocation, budget extension, activation or historical-run mutation.
- On failure, missing submission, exhausted allowance, unexpected dispatch,
  timeout or evidence-integrity failure: stop, retain evidence, drain exact
  owners, and mark failed/incomplete. Do not convert a runner success flag into
  a probe pass.
- On any paid rejection, preserve exact bounded protected request/response
  evidence and replay it locally before another paid attempt is considered.
  Missing, oversized or non-replayable evidence blocks further spending.

## Required pass evidence

The saved result must identify the actual executing source, harness, routine,
fixture commit/tree/content and declared oracle. It must identify the three
scripted setup phases and the real successor node, authority and input evidence.
Phase-local receipts must show exactly one successor dispatch/execution, one
accepted effectful final-horizon proposal, one complete plain-submit lifecycle,
an unchanged seed checkout and no downstream dispatch. Exact-owner, lease and
outbox readback must establish cleanup without hiding intentionally unexecuted
downstream graph work.

Acceptance must satisfy the production
`non_gap_planner_completion_contract_satisfied` predicate for the successor.
Independently inspect the accepted patch: one effectful batch worker at the
successor's horizon and skeleton, the `dynamic_feature_acceptance` final
acceptance check, final-audit verifier, final gate and three gap planners. All
must belong to that successor's accepted patch. There must be no further
successor when the remaining horizon is one. The worker's declared scope and
plan/plan-verification sources must agree with the verified discovery plan.

Protected artifacts must survive disposable workspace deletion and include
bounded request/response, source identity and replayable graph prefix for
controller rejections. The final preparation review must resolve capture of
rejections that occur before the controller callback as well.

Received dynamic-tool failures before the controller need a protected exact
`CodexDynamicToolReceipt` and local production-routing replay; they are not
controller-graph replay artifacts. A failure upstream of `item/tool/call` may
expose no original arguments. Such a result is incomplete, records only the
available evidence and blocks further spending. Production tool schemas are
unchanged; the harness must not invent or infer missing arguments.
Dynamic receipts preserve canonical parsed JSON, not original wire whitespace.
Their response is the exact response prepared before sending; it does not prove
app-server delivery if the subsequent transport write fails.

## Validation and invocation

Run from `/Users/peter/code/task-world/worktrees/recovery-stabilization`.
The deterministic command uses a scripted Codex transport for the target with
the same sealed Luna assignment and production tool routing as the paid path:

```bash
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python -m \
  examples.recovery.successor_planner_probe deterministic \
  --evidence-root docs/reviews/recovery-successor-private-2026-09-11
```

After a result is retained, replay it with the no-model utility (substitute the
printed, per-invocation `result_path`):

```bash
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python -m \
  examples.recovery.replay_successor_probe RESULT_JSON_PATH
```

Proposed paid command, **not yet authorized**:

```bash
UV_CACHE_DIR=/tmp/orchestrator-recovery-uv uv run --no-sync python -m \
  examples.recovery.successor_planner_probe paid \
  --evidence-root docs/reviews/recovery-successor-private-2026-09-11 \
  --timeout-seconds 180 --confirm-one-paid-successor
```

The evidence root contains a distinct subdirectory for every invocation; prior
results must not be overwritten. Raw tool receipts and the context packet stay
in protected artifacts, while normal result JSON contains safe references and
hashes. The receipt collector is bounded at 16 calls and fails closed on
overflow, incomplete content or storage failure. Controller proposal caps still
apply separately; client/schema failures do not reset the one-execution limit.

Independent deterministic CLI proof is saved in
`recovery-successor-deterministic-result.json` (SHA-256
`89ee7f6f15741a6d85de82aa1507abd9ce7ab9c6ffbdf40ff101a5c872472a78`). It exited
0 in 8.90 seconds and reports one finalized successor, one accepted final
topology, one exact controller rejection replay and three complete protected
tool receipts. Downstream dispatches, active leases, pending outbox and process
owners are zero; the seed checkout is unchanged. Downstream graph nodes remain
planned intentionally. The model name describes the sealed assignment; the
transport and reported token usage in this deterministic record are scripted,
and no model tokens were purchased by the probe.

The retained fixture tree is `206f2bc139186a8a7d8b2857faeb3d15c7893bcc` and
spec SHA-256 is
`b28ca577bbd4f43e6001e5b826a4c9d62ba3b108c6a21289257d8feec625bb36`.
Run-specific commit, oracle and prompt hashes are in that result. New invocations
have fresh temporary paths and Git timestamps, so those run-specific hashes may
change; fixture content, source/helper/routine hashes and semantic authority must
remain bound and checked.

Independent final code review passes S1–S5 with no blocking findings. The full
repository gate passed: **6,082 tests passed, five skipped**, and all applicable
static/UI hooks passed (exit 0). The first independent result is preserved in
`recovery-successor-deterministic-result-initial-2026-09-11.json`; its source hashes
predate the final fixes and must not stand in for the current proof. These
commands are recorded for review, not permission to run a paid phase.

The final source and regression hashes, review verdict, focused checks and gate
accounting are collected in `recovery-successor-validation-result.json`. Before
an authorized paid invocation, compare the executing files to that manifest and
the harness/helper/routine/source identities in the final deterministic result.
Changed files require relevant deterministic revalidation; a base commit alone
does not identify this uncommitted repair. Do not rerun unchanged model phases
or tests merely to refresh a date.

The first full gate exposed a partial PID-file publication race in a
server-supervisor test fixture. Its log is retained in
`recovery-successor-gate-attempt-1.log`. The fixture now publishes atomically and
cleans up its owned leader on early failure; all assertions and deadlines remain.
The three focused cases pass, independent review approves, and the final full
gate passes. No successor or production source changed for that fixture repair.

Deterministic acceptance proves fixture and infrastructure behavior only. A
future paid pass would establish one successful successor observation for this
small fixture. It would not establish a reliability rate, full model-driven
lifecycle completion, recovery behavior or representative feature quality.

Final gate evidence is retained in `recovery-successor-gate-final.log` and
`recovery-successor-gate-final.json`. An intervening all-tests-passing attempt
returned a wrapper failure because the supervisor edited a tracked ledger during
the hook; its complete record remains in `recovery-successor-gate-attempt-2.log`.
The final run had all edits paused, exited 0, and changed no source hashes.
All 85 historical artifact hashes and both prior deterministic evidence JSONs
remain unchanged. Changes remain uncommitted and unactivated.
