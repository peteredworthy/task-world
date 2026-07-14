# W6 — Outbox hardening: backoff, failed-row surfacing, requeue

Addresses weakness **W6** (medium) and improvement **#7** in
`dynamic-graph-implementation-review.html` (re-assessed 2026-07-03).

## Status — closed 2026-07-07

The W6 scope has landed in commit `23746c228`.

Closed:
- `graph_outbox.next_attempt_at` exists with migration coverage.
- Failed attempts use exponential backoff plus stable jitter.
- Pending rows with future `next_attempt_at` are not claimed.
- Failed outbox rows are visible through graph final blockers.
- Operators can requeue a failed row through the graph API with a typed
  `OutboxRequeued` workflow event persisted into run activity audit history.
- The graph driver waits for future outbox retry times before declaring a run blocked.

Out of scope and still open as a separate performance improvement:
- Batch or parallel outbox claiming/dispatch. The dispatcher still claims one row at a time.

Evidence:
- `tests/integration/test_graph_outbox_crash_points.py`
- `tests/integration/test_graph_api.py::test_graph_final_blockers_surface_failed_outbox_rows`
- `tests/integration/test_graph_api.py::test_operator_requeues_failed_outbox_row_with_audit_event`
- `tests/integration/test_migrations.py::test_init_db_adds_graph_outbox_backoff_schema`
- `tests/unit/test_graph_driver_logic.py::test_driver_waits_for_future_outbox_backoff_before_declaring_blocked`

## Problem

`graph_runtime/outbox.py` (~250 lines — read it whole first):

1. A failed attempt goes straight back to `pending` — no backoff, so a deterministic
   failure burns all `max_attempts=3` in quick succession.
2. At 3 attempts the row lands in `OUTBOX_FAILED` and dead-ends: startup recovery
   redispatches `pending`/`dispatching` but never `failed`, and no graph readback or
   API surfaces failed rows.

## Architecture

1. **Backoff.** Add `next_attempt_at` to the outbox row (Alembic migration — see
   constraints). `_mark_failed_attempt` sets it via exponential backoff with jitter
   (e.g. base 2s, factor 4, cap 60s — constants injectable for tests). The claim
   query skips rows with `next_attempt_at` in the future. Use the injected
   clock/session time, not `datetime.now()` scattered in logic, so tests stay
   deterministic.
2. **Surfacing.** Add failed-row info to an existing readback — `/graph/final-blockers`
   already has the right shape (check `api/routers/graph.py` and the projection/store
   read model it uses). A run with failed outbox rows must be visibly blocked, not
   silently quiescent.
3. **Requeue.** `POST /api/runs/{run_id}/graph/outbox/requeue/{event_id}` resets a
   `failed` row to `pending`, zeroes attempts, and atomically persists the typed
   `OutboxRequeued` workflow event through `events_v2`; it is therefore visible in
   the run activity audit rather than represented as an untyped graph payload.
   Executors are already documented at-least-once/idempotent, so requeue is safe by
   contract.

Out of scope: batch/parallel claiming (improvement #7's parallelism half) — separate
slice, do not mix in.

## Requirements

**R1 — Backoff honored.** Test: executor fails twice then succeeds; with a fake clock,
row is not re-claimable before `next_attempt_at`, and delays grow per schedule.
*Critical.*

**R2 — Failed rows visible.** Test: row exhausts attempts → readback reports it with
run id, kind, last error. *Critical.*

**R3 — Requeue works end-to-end.** Test: failed row → requeue endpoint → row
redispatches and completes; attempts reset; audit trail present. *Critical.*

**R4 — Crash semantics preserved.** `test_graph_outbox_crash_points.py` passes
unmodified. *Critical.*

**R5 — No busy-wait regression.** Dispatcher with only future-`next_attempt_at` rows
returns idle (no spin). *Expected.*

## Constraints

- New column ⇒ **Alembic migration** (`create_all` won't add columns — project
  memory). Never touch `orchestrator.db` directly; stop server before local schema
  work.
- At-least-once contract unchanged; do not add dedup logic to executors.
- No `mock`/`patch` in tests (AGENTS.md) — use a stub executor class and the
  injectable clock.

## Acceptance

```
uv run pytest tests/unit/test_jsonl_outbox.py \
  tests/integration/test_graph_outbox_crash_points.py \
  tests/integration/test_graph_event_store.py \
  tests/integration/test_graph_api.py -q
```

All pass, plus new R1–R3/R5 tests and `uv run alembic upgrade head` succeeding on a
scratch copy of the DB.
