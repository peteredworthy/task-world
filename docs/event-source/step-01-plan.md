# Step 01 — Event Store Foundation

## Purpose

Replace the current dual-write path (`EventStore` + `JsonlEventJournal`) with
a unified event store backed by a new `events_v2` SQLite table. JSONL writing
moves out of the critical `_persist` path and into an idempotent outbox
observer, fixing the atomicity bug. The concurrency strategy (retry with
backoff) is factored behind an abstraction so it can be swapped for PostgreSQL
primitives later.

## Prerequisites / Dependencies

- **Step 00** must be complete — events must be Pydantic models so
  `model_dump_json()` can serialize them into the `payload` column.

## Functional Contract

### Inputs

| Input | Description |
|-------|-------------|
| `EventStore` protocol | `append(events)`, `get_stream(aggregate_id)`, `get_all(after_position)` |
| `events_v2` schema | `position` (auto-inc PK), `aggregate_id`, `event_type`, `payload` (JSON), `timestamp`, `version`; `UNIQUE(aggregate_id, version)` |
| `ConcurrencyStrategy` protocol | `execute_with_retry(operation)` — wraps append with retry-on-conflict |
| `JsonlOutboxObserver` | Post-append listener; writes events to JSONL keyed by position |

### Outputs

- `SqliteEventStore` implementation satisfying `EventStore` protocol.
- `RetryWithBackoff` concurrency strategy (max 3 attempts, 10ms base delay).
- `JsonlOutboxObserver` writing JSONL idempotently by event position.
- Alembic migration creating `events_v2` table and indexes.
- `PersistentEventEmitter` wired to `SqliteEventStore` + `JsonlOutboxObserver`.
- Legacy dual-write path in `_persist` is bypassed (event flow goes through
  `SqliteEventStore` → observer chain).

### Errors

| Error | Handling |
|-------|----------|
| Version conflict (`UNIQUE` violation on `aggregate_id, version`) | `RetryWithBackoff` retries up to 3 times with exponential backoff; raises `ConcurrencyConflictError` if exhausted |
| JSONL write failure | Logged and skipped — JSONL is secondary; event is already durable in SQLite |
| Migration failure | Alembic rolls back; existing tables unaffected |

## Verification Strategy

1. **Unit tests** (`tests/unit/test_event_store_v2.py`):
   - Append events, read back by aggregate, assert order and content.
   - Simulate version conflict (two appends with same version), assert retry
     behavior via `RetryWithBackoff`.
   - `get_all(after_position)` returns correct tail.
2. **Unit tests** (`tests/unit/test_jsonl_outbox.py`):
   - Append events, assert JSONL file contains matching entries.
   - Re-append same position, assert no duplicate lines (idempotency).
3. **Unit tests** (`tests/unit/test_concurrency_strategy.py`):
   - Inject a callable that fails N times then succeeds; assert retry count
     and backoff timing.
4. **Integration test**: Append via `PersistentEventEmitter`, read back via
   `SqliteEventStore`, verify JSONL file updated.
5. **Existing test suite**: `uv run pytest` — full suite passes.
6. **Performance**: Integration test asserts append latency <5ms for a batch
   of 10 events.

## Deliverables

| Artifact | Location |
|----------|----------|
| `EventStore` protocol + `SqliteEventStore` | `src/orchestrator/db/access/event_store_v2.py` |
| `ConcurrencyStrategy` + `RetryWithBackoff` | `src/orchestrator/db/access/concurrency.py` |
| `JsonlOutboxObserver` | `src/orchestrator/db/access/jsonl_outbox.py` |
| `events_v2` ORM model | `src/orchestrator/db/orm/models.py` (extend) |
| Alembic migration | `src/orchestrator/db/migrations/versions/` |
| Unit tests | `tests/unit/test_event_store_v2.py`, `tests/unit/test_jsonl_outbox.py`, `tests/unit/test_concurrency_strategy.py` |
