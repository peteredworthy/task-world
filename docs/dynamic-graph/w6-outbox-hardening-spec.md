# W6 — Outbox hardening: backoff, failed-row surfacing, requeue

Addresses weakness **W6** (medium) and improvement **#7** in
`dynamic-graph-implementation-review.html` (re-assessed 2026-07-03).

## Status — closed 2026-07-07

The W6 scope has landed in commit `23746c228`.

Closed:
- `graph_outbox.next_attempt_at` exists in current ORM metadata with fresh-schema coverage.
- Failed attempts use exponential backoff plus stable jitter.
- Pending rows with future `next_attempt_at` are not claimed.
- Failed outbox rows are visible through graph final blockers.
- Operators can requeue a failed row through the graph API with an audit event.
- The graph driver waits for future outbox retry times before declaring a run blocked.

Out of scope and still open as a separate performance improvement:
- Batch or parallel outbox claiming/dispatch. The dispatcher still claims one row at a time.

Evidence:
- `tests/integration/test_graph_outbox_crash_points.py`
- `tests/integration/test_graph_api.py::test_graph_final_blockers_surface_failed_outbox_rows`
- `tests/integration/test_graph_api.py::test_operator_requeues_failed_outbox_row_with_audit_event`
- `tests/integration/test_database.py::test_file_database_is_created_directly_from_current_metadata`
- `tests/unit/test_graph_driver_logic.py::test_driver_waits_for_future_outbox_backoff_before_declaring_blocked`

## Problem

`graph_runtime/outbox.py` (~250 lines — read it whole first):

1. A failed attempt goes straight back to `pending` — no backoff, so a deterministic
   failure burns all `max_attempts=3` in quick succession.
2. At 3 attempts the row lands in `OUTBOX_FAILED` and dead-ends: startup recovery
   redispatches `pending`/`dispatching` but never `failed`, and no graph readback or
   API surfaces failed rows.

## Architecture

1. **Backoff.** Add `next_attempt_at` to the outbox ORM row and current schema.
   `_mark_failed_attempt` sets it via exponential backoff with jitter
   (e.g. base 2s, factor 4, cap 60s — constants injectable for tests). The claim
   query skips rows with `next_attempt_at` in the future. Use the injected
   clock/session time, not `datetime.now()` scattered in logic, so tests stay
   deterministic.
2. **Surfacing.** Add failed-row info to an existing readback — `/graph/final-blockers`
   already has the right shape (check `api/routers/graph.py` and the projection/store
   read model it uses). A run with failed outbox rows must be visibly blocked, not
   silently quiescent.
3. **Requeue.** Operator endpoint (follow existing graph router conventions) that
   resets a `failed` row to `pending` with attempts zeroed and an audit trail (either
   an outbox column or a graph event — match whichever the codebase already uses for
   operator actions). Executors are already documented at-least-once/idempotent, so
   requeue is safe by contract.

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

- New columns belong in current ORM metadata and are verified through `init_db`
  on a fresh temporary database. Never touch `orchestrator.db` directly.
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

All pass, plus new R1–R3/R5 tests and fresh-file schema inspection through
`init_db`.
