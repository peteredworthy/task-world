# Live qualification result — 7 September 2026

**The five-run qualification was not achieved. Trial 1 stopped automatically
before implementation because the accepted plan-revision worker lacked the
controller-owned runner/model assignment required for dispatch.** Trials 2–5
and the restart exercise were not run after this failure. No graph edits, state
repairs, server restarts, or implementation changes were made by the operator.

This is a live result with real Codex models, distinct from the ten canonical
offline qualification scenarios, which passed immediately before the attempt.

## Attempt and evidence

| Field | Observed value |
| --- | --- |
| Run | `c15e02ab-052c-45af-ab65-b3334b2c9ffb` |
| Task | Small standalone JSONL validator with explicit behavior, CLI, real tests, and an operator-owned acceptance script |
| Source | `13b6ebd07678ed404ebf8024013af2374699700d` |
| Routine | Checked-in `dynamic-graph-feature`; API routine SHA/commit fields were null, so source SHA, embedded routine, and YAML hash are retained |
| Worktree | `/Users/peter/code/task-world/worktrees/r199` |
| Models | Luna discovery/implementation/correction; Sol planner/verifier/successor. Actual usage shows Luna discovery and Sol planning, plan verification, and recovery planning. Implementation/correction never executed. |
| Started / paused | `2026-09-07T14:53:45.116143Z` / `2026-09-07T15:07:57.246558Z` |
| Wall time | 852.13 seconds (14 minutes 12 seconds) |
| Result | Run `paused`, reason `graph_blocked`; zero accepted implementation candidates |
| Tokens | 1,968,703 input, including 1,737,728 cached input; 32,569 output; 2,001,272 input plus output total |
| Actions | 54 recorded agent actions |
| Cost | Unavailable: all model usage entries have `rate_missing=true`; zero-valued cost fields are not evidence of free execution |
| Leases | Zero active; four released and one revoked |
| Graph | 208 contiguous canonical events; two accepted patches, eight rejected graph patches, one malformed-command rejection |
| Remaining qualification | Five consecutive successful tasks, implementation correction, and restart proof all remain open |

Machine-readable outcome: [task1_result.json](live-qualification-2026-09-07/task1_result.json).
Full event evidence: [task1_graph_events.json](live-qualification-2026-09-07/task1_graph_events.json).
Artifact integrity: [SHA256SUMS.json](live-qualification-2026-09-07/SHA256SUMS.json).

## Failure chain

1. The initial Sol planner had two graph submissions rejected, then created the
   discovery/plan-verifier/successor skeleton at position 35.
2. Luna completed discovery and submitted a semantic implementation plan. The
   accepted artifact is recorded at position 82.
3. Sol rejected the plan at position 108 because it omitted explicit recovery
   obligations for failed checks. The review recognized the feature scope and
   two-batch structure; this was not a completed-code verification failure.
4. The runtime automatically created a recovery planner. After seven unsuccessful
   submissions (six graph rejections and one malformed command), it accepted
   `recover-trial1-jsonl-plan-failure-8` at position 167.
5. The accepted revision worker and verifier at positions 169–170 have no
   `reliable_plan_assignment_carrier` or model override. The separately created
   successor planner at position 171 does have both. This is observable directly
   in the accepted events.
6. Outbox dispatch 3459 repeatedly failed with: “reliable-plan execution is
   missing sealed assignment carrier; recreate the run with a qualified
   assignment arm.” The run already had a valid server-issued qualification
   grant, and earlier nodes executed with the sealed assignments.
7. With no runtime execution/callback created for the revision worker, the
   controller recorded `runtime_execution_missing_no_callback`, revoked its lease,
   required recovery authorization, and automatically paused the quiescent run.
   The public pause error primarily lists blocked downstream inputs rather than
   the earlier assignment-validation cause.

The [dispatch log excerpt](live-qualification-2026-09-07/task1_dispatch_log.txt)
preserves the underlying error. The [runtime readback](live-qualification-2026-09-07/task1_runtime_health.json)
preserves zero active leases and four finalized earlier executions.

## Source explanation and repair target

The source supports a specific explanation for the observed missing assignments:
`_stamp_reliable_plan_successor_authority` in
`src/orchestrator/graph/_commands.py:3504` stamps direct `create_node` operations.
Its loop does not visit the nested `worker_node` and `verifier_node` fields of
`create_revision_attempt`. Dispatch requires the sealed assignment on every
reliable-plan executable node in
`src/orchestrator/graph_runtime/dispatch.py:1167`.

Before another qualification sequence, repair and verify propagation for nested
revision nodes while preserving controller ownership and the user-selected
models. A regression should cross patch acceptance, persisted/replayed node
readback, dispatch, semantic-plan correction, and resumed forward progress. The
original dispatch-validation cause should also survive into operator-facing
blockage diagnostics. This report does not claim that implementing only this
repair would make the five-run campaign pass.

## Additional reporting defect

The cost-rollup request for this run's time window returned HTTP 500.
The server traceback ends in `api/routers/cost_rollup.py:75`:
`CostRollupFact() got multiple values for keyword argument 'run_id'`.
The loader supplies `run_id` explicitly while expanding a payload that also
contains it. [Traceback evidence](live-qualification-2026-09-07/cost_rollup_error.txt).
Token totals above come from the run's retained usage records and reconcile to
the four canonical `node_usage_recorded` events; no price estimate was invented.

The graph health endpoint returned `partial`, with scheduler/lease/final-blocker
sections unavailable. Its empty `blockers` array therefore was not treated as a
clean result; canonical events and runtime lease readback established the outcome.

## Initial connectivity correction

The initial sandboxed curl failure did not establish server downtime. A later
health call returned `{"status":"ok"}`, port 8000 had a listener, and API
requests outside the sandbox succeeded. The existing development server was
used throughout. The earlier statement that it was offline was incorrect.

## Verification of this report

- Server-owned canonical qualification: all ten scenarios passed before trial 1.
- Live create/start and automatic pause observed through the public API.
- Canonical graph events checked for contiguous positions 1–208 and consistent
  overlapping pages.
- Lifecycle events establish wall time; canonical usage sums match run totals.
- Retained JSON artifacts parse successfully and have SHA-256 hashes.
- No full-suite or final-acceptance success is claimed for this live trial; it
  did not reach implementation. The operator-owned acceptance script was syntax
  checked but never executed against a completed candidate.
