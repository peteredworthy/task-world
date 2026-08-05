# W3 — Incremental projection snapshots on the write path; stop log inflation

Addresses weakness **W3** (high) and improvements **#3/#4** in
`dynamic-graph-implementation-review.html` (re-assessed 2026-07-03). The read-side
fold-once work is already done; this spec is the write path and log growth.

**Ordering:** do `w1b-residual-raw-scans-spec.md` first — snapshot+tail loading only
works once handlers read the projection, not raw events.

## Problem

1. `GraphController.handle_command` (`graph_runtime/controller.py`) calls
   `store.read_run` + `rebuild_projection` on every command — O(n) per command,
   O(n²) per run. The store already has a projection-snapshot read model, but appends
   *invalidate* it instead of advancing it, and the write path never loads it.
2. `_apply_schedule_tick` persists `node_deferred` audit events for every ineligible
   node on every tick, so the log grows while nothing happens — inflating replay and
   forcing the driver's signature-based progress check.
3. Startup recovery replays every run in the database, including terminal ones.

## Architecture

**Snapshot + tail.** Add a `PROJECTION_SCHEMA_VERSION` constant next to
`reduce_event`. On append, the store folds the newly appended events into the current
snapshot and persists it with its position and schema version (replacing the
invalidate-on-append). `handle_command` loads snapshot + events-after-position and
folds only the tail; on missing snapshot or version mismatch, fall back to full
replay and re-persist. Bump the version constant whenever `reduce_event` or
`GraphProjection` shape changes (add a code comment saying so at the constant).

**Deferral dedup.** Track last-deferred-reason per node in the projection; in
`_apply_schedule_tick`, emit `node_deferred` only when the reason *changes* (or the
node was previously eligible). The readback that surfaces deferral reasons must still
show the current reason.

**Recovery scope.** Startup recovery replays only runs whose projection is
non-terminal (use the persisted snapshot's terminal flag to skip without replay).

## Requirements

**R1 — Write path uses snapshot + tail.** `handle_command` no longer full-replays when
a valid snapshot exists. *Critical.*

**R2 — Parity.** New test: for a representative event stream, snapshot+tail projection
equals `rebuild_projection(all_events)` field-for-field. Build streams through the real
kernel; no `mock`/`patch` (AGENTS.md). *Critical.*

**R3 — Version safety.** Test: a snapshot persisted under a different schema version is
ignored and rebuilt, not trusted. *Critical.*

**R4 — Idle ticks stop growing the log.** Test: two consecutive `schedule_tick`
commands with no state change between them — the second appends no `node_deferred`
events. Deferral readback still reports the current reason. *Critical.*

**R5 — Crash safety unchanged.** Outbox crash-point suite passes: snapshot persistence
must be in the same transaction as the append or safely reconstructible — a crash
between append and snapshot write must not produce a wrong projection later. *Critical.*

**R6 — Startup recovery skips terminal runs.** Test with one terminal and one
in-flight run: only the in-flight run is replayed/reconciled. *Expected.*

## Constraints

- Kernel stays pure: version constant and reduce live in `graph/`; persistence in
  `graph_runtime/store.py`.
- Register snapshot tables and columns in current ORM metadata and verify them
  through `init_db` on a fresh temporary database. Never touch
  `orchestrator.db` directly.
- `StaleProjectionError` optimistic-concurrency semantics unchanged.

## Acceptance

```
uv run pytest tests/integration/test_graph_event_store.py \
  tests/integration/test_graph_outbox_crash_points.py \
  tests/unit/test_projection_rebuild.py tests/unit/test_graph_projections.py \
  tests/integration/test_graph_dynamic_e2e.py -q
```

All pass, plus new R2–R6 tests. Sanity-check perf: the evidence-digest path should not
regress and a long-run `handle_command` should show sublinear cost (a simple timing
assertion or manual measurement note is acceptable evidence).
