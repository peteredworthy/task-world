# Step 5: Output Batching and Cleanup

**Milestone:** M5 — Output Batching and Cleanup
**Plan:** [step-05-plan.md](../step-05-plan.md)
**Architecture:** [architecture.md](../architecture.md) §Output Batching
**Intent:** [intent.md](../intent.md) — TD-09 (per-line event writes); full event-sourced cleanup

## Dry-Run Hardening Applied

- `OutputBatcher` must key buffers by `(run_id, task_id, attempt_id)` unless the implementation
  proves a single active stream per instance.
- Clear buffered output only after the event-store append succeeds; failed appends must leave the
  buffer available for retry.
- Flush pending output in exception, pause, cancellation, and phase-boundary paths so the most
  useful diagnostic lines are not lost.
- Preserve monotonic WebSocket/activity `line_offset` values after batching and assert all emitted
  lines arrive in order.
- JSONL bootstrap must read both legacy journal records and outbox records, or the outbox must write
  legacy-compatible keys from Step 01.
- Do not delete legacy recovery modules until bootstrap and projection rebuild are proven by tests.
- Before dropping `pending_signals`, migrate any remaining rows into signal events or assert the
  table is empty.

## Tasks

### Task 5.1: Implement OutputBatcher

Create `OutputBatcher` in `src/orchestrator/runners/execution/output_batcher.py`.
The batcher accumulates `AgentOutputEvent` lines and flushes to the event store
when either threshold is reached: 50 lines (count) or 100ms elapsed (time).
Both thresholds are constructor parameters. The clock is an injected dependency
(callable returning `float`) so tests can control time without sleeping. Expose
`add_line(run_id, task_id, attempt_id, text)`, `flush()`, and
`flush_immediate()` (for phase transitions). `flush()` is idempotent when the
buffer is empty.

**Files:** `src/orchestrator/runners/execution/output_batcher.py`,
`src/orchestrator/runners/execution/__init__.py`
**LOC estimate:** ~130
**Verify:** Construct with injected clock; call `add_line()` below count
threshold and before time threshold — assert `flush()` is not called. Reach
count threshold — assert flush is triggered. Advance injected clock past
interval — assert time-based flush. Call `flush_immediate()` with pending
lines — assert all lines flushed.

### Task 5.2: Unit tests for OutputBatcher

Write `tests/unit/test_output_batcher.py` covering all flush paths. Use a
`FakeClock` that starts at 0 and advances via `advance(ms)`. Inject a list
as the `event_store` stub that records appended events so tests can assert
batch contents without a real DB.

**Files:** `tests/unit/test_output_batcher.py`
**LOC estimate:** ~140
**Verify:** `uv run pytest tests/unit/test_output_batcher.py` passes. All four
flush paths tested: count threshold, time threshold, immediate flush, empty
buffer no-op. Batch `AgentOutputEvent` payloads contain the correct lines in
order.

### Task 5.3: Wire OutputBatcher into PhaseHandler

Replace the three per-line `await self._broadcaster.emit_log_event(event)`
calls in `src/orchestrator/runners/execution/phase_handler.py` with
`self._output_batcher.add_line(...)`. Inject `OutputBatcher` via the
`PhaseHandler` constructor alongside the existing `broadcaster` parameter.
Add `await self._output_batcher.flush_immediate()` calls at each phase
transition point (task completion, run pause, phase end) so no lines are lost
on boundaries.

**Files:** `src/orchestrator/runners/execution/phase_handler.py`,
`src/orchestrator/runners/execution/event_broadcaster.py`
**LOC estimate:** ~100
**Verify:** Unit tests for `PhaseHandler` pass with an injected `OutputBatcher`
stub. Confirm that `emit_log_event` is no longer called directly for
`AgentOutputEvent` in `phase_handler.py` (`grep -n "emit_log_event"
src/orchestrator/runners/execution/phase_handler.py` returns no matches).

### Task 5.4: Integration test for output batching via WebSocket

Write `tests/integration/test_output_batching.py`. Use a mock agent that
emits 60 lines in rapid succession. Assert that: (1) the lines arrive via
WebSocket as batched `AgentOutputEvent`s (not 60 individual events); (2)
`line_offset` values are monotonically increasing with no gaps; (3) all 60
lines are present in the correct order after the run completes.

**Files:** `tests/integration/test_output_batching.py`
**LOC estimate:** ~120
**Verify:** `uv run pytest tests/integration/test_output_batching.py` passes.
Assert that the number of `AgentOutputEvent` rows in `events_v2` is fewer
than 60 (batching occurred). `uv run pytest` full suite passes with no
regressions.

### Task 5.5: Implement JSONL bootstrap for empty-DB startup

Create `src/orchestrator/db/bootstrap.py` with an async
`bootstrap_from_jsonl(session, journal_path, projection_registry)` function.
It checks if `events_v2` is empty; if so, reads `history.jsonl` line by line,
inserts parsed events into `events_v2` (idempotent — skip on position
conflict), then calls `projection_registry.rebuild_all(session)`. If the JSONL
file is missing, log a warning and return without error. Wire the bootstrap
call into the application startup sequence (after Alembic migrations, before
accepting requests).

**Files:** `src/orchestrator/db/bootstrap.py`,
`src/orchestrator/db/__init__.py`
**LOC estimate:** ~150
**Verify:** Bootstrap function called with an empty DB and a known JSONL
fixture seeds `events_v2` and populates projection tables. Called with a
non-empty DB is a no-op. Missing JSONL logs a warning and does not raise.

### Task 5.6: Integration test for JSONL bootstrap

Write `tests/integration/test_jsonl_bootstrap.py`. Create a minimal JSONL
fixture with a known sequence of events (at least one `RunCreated`, one
`RunStatusChanged`, one `TaskCreated`). Start with an empty in-memory DB.
Call `bootstrap_from_jsonl()`. Assert `events_v2` row count matches the
fixture, `runs` projection table has the expected row, and
`projection_checkpoints` records the last processed position.

**Files:** `tests/integration/test_jsonl_bootstrap.py`
**LOC estimate:** ~80
**Verify:** `uv run pytest tests/integration/test_jsonl_bootstrap.py` passes
for all three scenarios: normal seed, empty-DB no-op when already populated,
and graceful handling of missing JSONL.

### Task 5.7: Remove legacy recovery code and EventStore dual-write path

Delete the three recovery modules no longer needed after projection-based
recovery is proven:
- `src/orchestrator/db/recovery/event_journal.py`
- `src/orchestrator/db/recovery/journal_replay.py`
- `src/orchestrator/db/recovery/recovery.py`

Remove the `JsonlEventJournal` import and inline journal-write path from
`src/orchestrator/db/access/event_store.py` (the `JsonlOutboxObserver` from
Step 01 is the live JSONL writer; the legacy inline path is now dead). Remove
the dead `JsonlEventJournal` and `EventStore` legacy re-exports from
`src/orchestrator/db/__init__.py`.

**Files:** `src/orchestrator/db/recovery/event_journal.py` (delete),
`src/orchestrator/db/recovery/journal_replay.py` (delete),
`src/orchestrator/db/recovery/recovery.py` (delete),
`src/orchestrator/db/access/event_store.py`,
`src/orchestrator/db/__init__.py`
**LOC estimate:** ~−350 (net deletion)
**Verify:** `grep -r "event_journal\|journal_replay\|recovery" src/` returns
no matches outside `db/recovery/__init__.py` (which may remain as an empty
package stub). `grep -r "JsonlEventJournal" src/` returns no matches.
`uv run pytest` full suite passes with no regressions.

### Task 5.8: Remove pending_signals table and update ARCHITECTURE.md

Add an Alembic migration that drops the `pending_signals` table (deprecated in
Step 04). Update `docs/ARCHITECTURE.md` to remove all references to the legacy
dual-write path, `pending_signals`, `_active_run_ids`, and recovery modules.
Add a concise description of the event-sourced data flow from the architecture
document's integration strategy section.

**Files:** `src/orchestrator/db/migrations/versions/<hash>_remove_pending_signals.py`,
`docs/ARCHITECTURE.md`
**LOC estimate:** ~40 migration + ~80 doc edits
**Verify:** `uv run alembic upgrade head` completes without error.
`pending_signals` table no longer exists in the schema (verified via
`sqlite_master` query in a schema test). `uv run pytest` full suite passes.
`docs/ARCHITECTURE.md` describes the current event-sourced architecture with
no references to removed components.
