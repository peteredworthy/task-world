# Slice DG-5.1t Spec: Final Invariant Completion And Graph Read Health

## Objective

Repair the DG-5.1 live-smoke completion gap where a dynamic graph run reached
workflow `completed` after corrective verification evidence was bound into a
final invariant check, but before the final check itself emitted visible
ready/running/completed evidence.

## Scope

In scope:

- Make graph-run completion wait for pending check nodes.
- Preserve ordinary worker/verifier task acceptance for routines with no check
  nodes.
- Keep the fix in pure graph projection/runtime logic.
- Verify completed-run graph read APIs remain usable enough for validation and
  comparison.

Out of scope:

- Broad scheduler rewrites.
- Full five-arm comparison.
- Manual graph event injection as proof of operational status.

## Live Failure Evidence

Run `4a147a09-fb6d-46a6-9d5f-2dec0a338c15` completed after:

- root planner patch `patch-smoke-full-plan` was accepted;
- initial worker, initial verifier, gap planner, corrective worker, and
  corrective verifier all submitted accepted callbacks;
- corrective verification record
  `verification-exec-632c1c3dbee64b3b9d62ff555c08cdb8` bound to
  `check-smoke-invariant.verification_evidence`.

The event stream did not show `check-smoke-invariant` reaching ready, running,
or completed before workflow completion. After completion, `/graph`,
`/graph/scheduler`, and a narrow `/graph/events?from_position=132` read timed
out in an 8 second probe while `/health` still returned OK.

## Required Behavior

- A pending `check` node in `planned`, `ready`, `leased`, or `running` state is
  a final invariant blocker.
- `project_run_state(events)` must remain `active` when tasks are accepted but
  a check node is pending.
- The graph `complete` command must reject completion while that blocker exists.
- The graph driver must continue scheduling the pending check instead of
  classifying the run as completed from accepted task state alone.

## Validation Commands

```bash
uv run pytest tests/unit/test_graph_projections.py tests/unit/test_graph_commands.py tests/unit/test_graph_driver_logic.py tests/integration/test_graph_run_driver.py -q
uv run ruff check src/orchestrator/graph/projections.py tests/unit/test_graph_projections.py tests/integration/test_graph_run_driver.py
uv run pyright src/orchestrator/graph/projections.py tests/unit/test_graph_projections.py tests/integration/test_graph_run_driver.py
```

Then launch a fresh DG-5.1 smoke run with `dynamic-graph-feature` using
`cli_subprocess`/Claude CLI and confirm:

1. The run does not complete before final invariant check evidence is visible.
2. The final invariant check reaches terminal evidence or a clear blocker is
   recorded.
3. `/graph`, `/graph/events`, and `/graph/scheduler` respond for the fresh run.
4. `uv run python scripts/compare_carriers.py dynamic=<run-id>` succeeds.

## Durable Update

Update `docs/graph-approach/dynamic-graph-operational-plan.md` with the focused
validation and the fresh live-run result before moving to DG-5.2.
