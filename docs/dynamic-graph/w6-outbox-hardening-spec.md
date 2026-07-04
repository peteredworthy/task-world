# W6 — Outbox hardening: backoff, failed-row surfacing, requeue

Addresses weakness **W6** (medium) and improvement **#7** in
`dynamic-graph-implementation-review.html` (re-assessed 2026-07-03).

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
