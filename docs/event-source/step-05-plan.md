# Step 05 — Output Batching and Cleanup

## Purpose

Implement `AgentOutputEvent` batching (resolving TD-09), remove all legacy
dual-write code, and add the JSONL bootstrap path for empty-DB startup. After
this step the system is fully event-sourced with no legacy persistence paths
remaining.

## Prerequisites / Dependencies

- **All previous steps** (S-00 through S-04) must be complete.
- Projectors and command handlers must be proven reliable before legacy
  recovery code is removed.

## Functional Contract

### Inputs

| Input | Description |
|-------|-------------|
| `OutputBatcher` | Accumulates `AgentOutputEvent` lines; flushes to event store on threshold |
| Flush thresholds | 100ms time interval (default), 50 lines batch size (default); both configurable |
| Immediate flush trigger | Phase transitions (task completion, run pause) flush any pending batch |
| Bootstrap script | Reads JSONL on empty-DB startup to seed `events_v2` and rebuild projections |

### Outputs

- `OutputBatcher` at `src/orchestrator/runners/execution/output_batcher.py`.
- `EventBroadcaster.emit_log_event()` replaced with
  `OutputBatcher.add_lines()`.
- WebSocket broadcast updated to work from batched events (maintaining
  `line_offset` ordering).
- **Removed**: legacy `EventStore` (old `events` table), legacy
  `JsonlEventJournal` inline write path, `db/recovery/event_journal.py`,
  `db/recovery/journal_replay.py`, `db/recovery/recovery.py`.
- **Retained**: `JsonlOutboxObserver` (from Step 01) as the live JSONL writer.
- Bootstrap on empty DB: startup reads JSONL → seeds `events_v2` → rebuilds
  projections.
- Deprecated `pending_signals` table removed (migration from Step 04).
- `docs/ARCHITECTURE.md` updated to reflect new event-sourced architecture.

### Errors

| Error | Handling |
|-------|----------|
| Batch flush failure | Retry once; if still failing, flush individual events to avoid data loss |
| JSONL file missing on bootstrap | Log warning, start with empty event store (no events to replay) |
| WebSocket latency from batching | Configurable flush interval (default 100ms); immediate flush on phase transitions |

## Verification Strategy

1. **Unit tests** (`tests/unit/test_output_batcher.py`):
   - Inject mock clock; add lines below threshold, assert no flush.
   - Add lines to reach batch size, assert flush triggered.
   - Advance clock past interval, assert time-based flush.
   - Trigger immediate flush, assert all pending lines flushed.
2. **Integration test** (`tests/integration/test_output_batching.py`):
   - Run agent, assert batched events arrive via WebSocket with correct
     `line_offset` ordering.
3. **Bootstrap test** (`tests/integration/test_jsonl_bootstrap.py`):
   - Start with empty DB and a known JSONL file; assert `events_v2` populated
     and projections rebuilt correctly.
4. **Legacy removal verification**:
   - Grep for removed module imports; assert no references remain.
   - Assert old `events` table is not queried anywhere in the codebase.
5. **Performance validation**:
   - Measure end-to-end API latency; confirm <10% regression vs. baseline.
   - Measure event append latency with batching enabled.
6. **Existing test suite**: `uv run pytest` — full suite passes.

## Deliverables

| Artifact | Location |
|----------|----------|
| `OutputBatcher` | `src/orchestrator/runners/execution/output_batcher.py` |
| Bootstrap script | `src/orchestrator/db/` or `src/orchestrator/cli/` |
| Updated `docs/ARCHITECTURE.md` | `docs/ARCHITECTURE.md` |
| Removal of legacy recovery code | `src/orchestrator/db/recovery/` (deleted) |
| Unit tests | `tests/unit/test_output_batcher.py` |
| Integration tests | `tests/integration/test_output_batching.py`, `tests/integration/test_jsonl_bootstrap.py` |
