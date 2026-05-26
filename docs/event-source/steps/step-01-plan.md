# Step 01: Event Store Foundation

**Plan:** [step-01-plan.md](../step-01-plan.md)
**Architecture:** [architecture.md](../architecture.md)
**Intent:** [intent.md](../intent.md)
**Prerequisite:** Step 00 (Pydantic Event Conversion) must be complete.

Replace the current dual-write path (`EventStore` + `JsonlEventJournal`) with a unified event store
backed by a new `events_v2` SQLite table. JSONL writing moves out of the critical `_persist` path
into an idempotent outbox observer, fixing the atomicity bug. The concurrency strategy is factored
behind a swappable abstraction for future PostgreSQL migration.

The five tasks build upward: schema first, then the store and concurrency layer, then the JSONL
observer, then wiring it all into `PersistentEventEmitter`, and finally the unit tests that verify
each component in isolation.

## Dry-Run Hardening Applied

- The migration must set `down_revision = "t1a2b3c4d5e6"` and verification must confirm there is a
  single Alembic head after adding `events_v2`.
- `RetryWithBackoff` must re-raise non-conflict exceptions unchanged; only SQLite unique/version
  conflicts are retried and eventually wrapped in `ConcurrencyConflictError`.
- `PersistentEventEmitter.emit()` must pass `[event]` to the new store and `emit_batch()` must call
  the sequence append path; add an `append_batch` compatibility alias during transition.
- `JsonlOutboxObserver` must wrap filesystem writes in `try/except Exception` and log failures
  without making an already-durable DB append appear failed.
- The JSONL outbox record must remain readable by existing tooling: include legacy-compatible
  `run_id` and `sequence_number` keys, or add tests proving the replay/bootstrap reader accepts the
  new shape.
- Add an integration test that appends through `PersistentEventEmitter` and asserts both an
  `events_v2` row and a JSONL line are produced.

## Intent Verification

**Original Intent**: [I-04] Consolidate the dual-write path into a single append-only SQLite event
store; JSONL continues as a real-time secondary write via an outbox observer (keyed by position,
idempotent on retry). [I-31] Dual-write path unified: SQLite is the single source of truth.

**Functionality to Produce**:
- `events_v2` table exists with `position`, `aggregate_id`, `event_type`, `payload`, `timestamp`,
  `version` columns; `UNIQUE(aggregate_id, version)` constraint; two indexes.
- `EventStore` protocol (append, get_stream, get_all) and `SqliteEventStore` implementation in
  `db/access/event_store_v2.py`.
- `ConcurrencyStrategy` protocol and `RetryWithBackoff` implementation in
  `db/access/concurrency.py`; raises `ConcurrencyConflictError` after 3 failed attempts.
- `JsonlOutboxObserver` in `db/access/jsonl_outbox.py`; writes JSONL by event position;
  re-appending the same position is a no-op.
- `PersistentEventEmitter` wired to `SqliteEventStore`; `JsonlOutboxObserver` registered as a
  post-append listener.
- Legacy dual-write path in `EventStore.append` is bypassed for new writes; event flow goes
  through `SqliteEventStore` → observer chain.

**Final Verification Criteria**:
- `uv run pytest tests/unit/test_event_store_v2.py tests/unit/test_concurrency_strategy.py tests/unit/test_jsonl_outbox.py -v` — all pass.
- `uv run pytest` — full suite passes with no regressions.
- `uv run pyright src/orchestrator/db/access/event_store_v2.py src/orchestrator/db/access/concurrency.py src/orchestrator/db/access/jsonl_outbox.py` — no type errors.
- Integration: appending events via `PersistentEventEmitter` stores rows in `events_v2` and
  writes to JSONL; reading back via `SqliteEventStore.get_stream()` returns events in order.

---

## Task 1.1: events_v2 ORM Model and Alembic Migration

**Description**: Add the `EventV2Model` SQLAlchemy model and create an Alembic migration that
creates the `events_v2` table with its indexes. This is the schema foundation; all other tasks
depend on this table existing.

**Implementation Plan (Do These Steps)**

- [ ] Extend `src/orchestrator/db/orm/models.py` — add `EventV2Model` class after the existing
  `EventModel`. The table must match the schema exactly:

```python
class EventV2Model(Base):
    __tablename__ = "events_v2"
    __table_args__ = (
        UniqueConstraint("aggregate_id", "version", name="uq_events_v2_aggregate_version"),
        Index("idx_events_v2_aggregate", "aggregate_id", "position"),
        Index("idx_events_v2_type", "event_type", "position"),
    )

    position: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    aggregate_id: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)   # JSON string
    timestamp: Mapped[str] = mapped_column(String, nullable=False)  # ISO 8601
    version: Mapped[int] = mapped_column(Integer, nullable=False)
```

- [ ] Create a new Alembic migration file in
  `src/orchestrator/db/migrations/versions/` named `u1a2b3c4d5e6_add_events_v2_table.py`.
  The migration creates `events_v2` in `upgrade()` and drops it in `downgrade()`. Follow the
  naming convention of existing migrations in that directory (see
  `t1a2b3c4d5e6_rename_runner_profile_defaults_table.py` for format reference). Include
  both indexes and the unique constraint in the `upgrade()` step.

- [ ] Export `EventV2Model` from `src/orchestrator/db/__init__.py` alongside the existing model
  exports.

**Dependencies**
- [ ] Alembic is already configured; existing migrations in `src/orchestrator/db/migrations/versions/` can be used as templates.

**Constraints**
- [ ] Do not delete or modify any existing migration files.
- [ ] Do not alter `EventModel` or any other existing ORM class.
- [ ] `payload` must be `Text` (not `JSON`) — the event store serializes to a JSON string and stores
  it verbatim; the ORM must not attempt to re-serialize.

**Functionality (Expected Outcomes)**
- [ ] `EventV2Model` is importable from `orchestrator.db`.
- [ ] Running `uv run alembic upgrade head` on a fresh DB creates the `events_v2` table with the
  `UNIQUE(aggregate_id, version)` constraint and both indexes.
- [ ] `uv run alembic downgrade -1` drops `events_v2` cleanly.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `uv run pyright src/orchestrator/db/orm/models.py` — no type errors on the new model.
- [ ] Start a Python REPL with `uv run python -c "from orchestrator.db import EventV2Model; print(EventV2Model.__tablename__)"` — prints `events_v2`.
- [ ] `uv run alembic upgrade head` completes without error on a temporary in-memory DB (use `uv run python -c "import asyncio; from orchestrator.db.access.connection import init_db; asyncio.run(init_db('sqlite+aiosqlite://'))"` — no exception).

---

## Task 1.2: ConcurrencyStrategy, EventStore Protocol, and SqliteEventStore

**Description**: Define the `ConcurrencyStrategy` abstraction and `RetryWithBackoff`
implementation in `concurrency.py`, then define the `EventStore` protocol and implement
`SqliteEventStore` in `event_store_v2.py`. The store uses the concurrency strategy to handle
`UNIQUE(aggregate_id, version)` conflicts, and exposes `append`, `get_stream`, and `get_all`.

**Implementation Plan (Do These Steps)**

- [ ] Create `src/orchestrator/db/access/concurrency.py`:

```python
"""Swappable concurrency strategy for event-store append operations."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class ConcurrencyConflictError(Exception):
    """Raised when optimistic concurrency retries are exhausted."""


class ConcurrencyStrategy:
    """Protocol: wraps an async operation with conflict-retry logic."""

    async def execute_with_retry(self, operation: Callable[[], Awaitable[T]]) -> T:
        raise NotImplementedError


class RetryWithBackoff(ConcurrencyStrategy):
    """SQLite strategy: retry up to max_attempts with exponential backoff.

    base_delay_ms is the initial delay in milliseconds; each retry doubles it.
    Swap this for PostgreSQL advisory-lock or serializable-transaction strategy
    without changing SqliteEventStore.
    """

    def __init__(self, max_attempts: int = 3, base_delay_ms: float = 10.0) -> None:
        self.max_attempts = max_attempts
        self.base_delay_ms = base_delay_ms

    async def execute_with_retry(self, operation: Callable[[], Awaitable[T]]) -> T:
        delay = self.base_delay_ms / 1000.0
        for attempt in range(1, self.max_attempts + 1):
            try:
                return await operation()
            except Exception as exc:
                if not _is_version_conflict(exc):
                    raise  # re-raise original — not a concurrency conflict; do NOT wrap in ConcurrencyConflictError
                if attempt == self.max_attempts:
                    raise ConcurrencyConflictError(
                        f"Version conflict unresolved after {attempt} attempt(s)"
                    ) from exc
                await asyncio.sleep(delay)
                delay *= 2
        raise ConcurrencyConflictError("unreachable")  # pragma: no cover


def _is_version_conflict(exc: Exception) -> bool:
    """Return True if the exception is a UNIQUE constraint violation on events_v2."""
    msg = str(exc).lower()
    return "unique" in msg and ("aggregate_id" in msg or "uq_events_v2" in msg)
```

- [ ] Create `src/orchestrator/db/access/event_store_v2.py` with:
  - A `StoredEvent` dataclass (position, aggregate_id, event_type, payload str, timestamp str, version).
  - An `EventStore` `Protocol` with three methods: `append`, `get_stream`, `get_all`.
  - `SqliteEventStore` implementing the protocol with a real `AsyncSession` and a
    `ConcurrencyStrategy` (defaults to `RetryWithBackoff()`).

```python
"""Unified event store backed by the events_v2 SQLite table."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.access.concurrency import ConcurrencyStrategy, RetryWithBackoff
from orchestrator.db.orm.models import EventV2Model
from orchestrator.time_utils import format_utc_datetime

if TYPE_CHECKING:
    from orchestrator.workflow import WorkflowEvent


@dataclasses.dataclass(frozen=True)
class StoredEvent:
    position: int
    aggregate_id: str
    event_type: str
    payload: str          # raw JSON string
    timestamp: str        # ISO 8601
    version: int


@runtime_checkable
class EventStore(Protocol):
    async def append(self, events: Sequence[WorkflowEvent]) -> list[StoredEvent]: ...
    async def get_stream(self, aggregate_id: str) -> list[StoredEvent]: ...
    async def get_all(self, after_position: int = 0) -> list[StoredEvent]: ...


class SqliteEventStore:
    """EventStore backed by the events_v2 table with optimistic concurrency."""

    def __init__(
        self,
        session: AsyncSession,
        concurrency: ConcurrencyStrategy | None = None,
    ) -> None:
        self._session = session
        self._concurrency = concurrency or RetryWithBackoff()
        self._listeners: list[...] = []   # post-append observers

    def add_listener(self, listener) -> None:
        self._listeners.append(listener)

    async def append(self, events: Sequence[WorkflowEvent]) -> list[StoredEvent]:
        """Append events with optimistic concurrency control."""

        async def _do_append():
            # Fetch current max version per aggregate_id in this batch
            aggregate_ids = {e.run_id for e in events}
            versions: dict[str, int] = {}
            for agg_id in aggregate_ids:
                result = await self._session.execute(
                    select(EventV2Model.version)
                    .where(EventV2Model.aggregate_id == agg_id)
                    .order_by(EventV2Model.version.desc())
                    .limit(1)
                )
                row = result.scalar_one_or_none()
                versions[agg_id] = (row or 0)

            models = []
            for event in events:
                versions[event.run_id] += 1
                models.append(EventV2Model(
                    aggregate_id=event.run_id,
                    event_type=event.event_type,
                    payload=event.model_dump_json(),
                    timestamp=format_utc_datetime(event.timestamp),
                    version=versions[event.run_id],
                ))
            self._session.add_all(models)
            await self._session.flush()
            return models

        models = await self._concurrency.execute_with_retry(_do_append)

        stored = [
            StoredEvent(
                position=m.position,
                aggregate_id=m.aggregate_id,
                event_type=m.event_type,
                payload=m.payload,
                timestamp=m.timestamp,
                version=m.version,
            )
            for m in models
        ]
        for listener in self._listeners:
            await listener(stored)
        return stored

    async def get_stream(self, aggregate_id: str) -> list[StoredEvent]:
        """Return all stored events for an aggregate in position order."""
        result = await self._session.execute(
            select(EventV2Model)
            .where(EventV2Model.aggregate_id == aggregate_id)
            .order_by(EventV2Model.position)
        )
        return [_to_stored(m) for m in result.scalars()]

    async def get_all(self, after_position: int = 0) -> list[StoredEvent]:
        """Return all events after a global position cursor."""
        result = await self._session.execute(
            select(EventV2Model)
            .where(EventV2Model.position > after_position)
            .order_by(EventV2Model.position)
        )
        return [_to_stored(m) for m in result.scalars()]


def _to_stored(m: EventV2Model) -> StoredEvent:
    return StoredEvent(
        position=m.position,
        aggregate_id=m.aggregate_id,
        event_type=m.event_type,
        payload=m.payload,
        timestamp=m.timestamp,
        version=m.version,
    )
```

Note: `_listeners` type annotation and listener callable signature will be tightened in Task 1.3
once `JsonlOutboxObserver`'s interface is defined. Use `list[Any]` for now; pyright will accept it.

**Dependencies**
- [ ] Task 1.1 must be complete (`EventV2Model` must exist in `models.py`).
- [ ] Step 00 must be complete (events must be Pydantic models with `model_dump_json()`).

**Constraints**
- [ ] Do not modify the existing `EventStore` class in `event_store.py`. The new store lives in
  `event_store_v2.py`.
- [ ] `SqliteEventStore` must not import from `workflow` at module level — use `TYPE_CHECKING`
  guard or string annotations to avoid circular imports (mirror pattern in `event_store.py`).
- [ ] All I/O must be async.

**Functionality (Expected Outcomes)**
- [ ] `SqliteEventStore` can append a batch of `WorkflowEvent` objects to `events_v2` and return
  a list of `StoredEvent` with populated `position` and `version` fields.
- [ ] `get_stream(aggregate_id)` returns events for a single run in ascending position order.
- [ ] `get_all(after_position)` returns events after the given global cursor.
- [ ] Version conflict (simulated by injecting a callable that raises a `UNIQUE` error) triggers
  retry via `RetryWithBackoff`; after `max_attempts` the `ConcurrencyConflictError` propagates.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `uv run pyright src/orchestrator/db/access/concurrency.py src/orchestrator/db/access/event_store_v2.py` — no errors.
- [ ] `from orchestrator.db.access.event_store_v2 import SqliteEventStore, EventStore, StoredEvent` imports without error in a Python REPL.
- [ ] Unit tests written in Task 1.5 for `test_event_store_v2.py` and `test_concurrency_strategy.py` pass.

---

## Task 1.3: JsonlOutboxObserver

**Description**: Implement `JsonlOutboxObserver` in `db/access/jsonl_outbox.py`. The observer
subscribes to `SqliteEventStore` post-append notifications and writes events to the JSONL file
keyed by event `position`. Re-writing the same position is a no-op (idempotent), ensuring that
retried appends never produce duplicate JSONL lines.

**Implementation Plan (Do These Steps)**

- [ ] Create `src/orchestrator/db/access/jsonl_outbox.py`:

```python
"""JSONL outbox observer: writes stored events to the JSONL journal after append."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from orchestrator.db.access.event_store_v2 import StoredEvent

logger = logging.getLogger(__name__)


class JsonlOutboxObserver:
    """Post-append listener that writes events to JSONL keyed by position.

    Idempotent: if a position has already been written (e.g. after a retry),
    the write is skipped.  This prevents duplicate lines on version-conflict
    retries where the first attempt partially wrote before the DB rolled back.

    Register via: ``event_store.add_listener(observer)``
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._written: set[int] = set()
        self._lock = asyncio.Lock()

    async def __call__(self, events: list[StoredEvent]) -> None:
        """Called by SqliteEventStore after a successful append."""
        try:
            new_events = [e for e in events if e.position not in self._written]
            if not new_events:
                return
            lines = "\n".join(json.dumps(_to_record(e)) for e in new_events) + "\n"
            async with self._lock:
                await asyncio.to_thread(self._path.parent.mkdir, parents=True, exist_ok=True)
                await asyncio.to_thread(_append_lines, self._path, lines)
                for e in new_events:
                    self._written.add(e.position)
        except Exception:
            logger.warning(
                "JSONL outbox write failed; event already durable in SQLite",
                exc_info=True,
            )


def _to_record(e: StoredEvent) -> dict:
    return {
        "position": e.position,
        "aggregate_id": e.aggregate_id,
        "event_type": e.event_type,
        "timestamp": e.timestamp,
        "payload": json.loads(e.payload),
    }


def _append_lines(path: Path, lines: str) -> None:
    with open(path, "a") as f:
        f.write(lines)
```

- [ ] Update `SqliteEventStore.add_listener` in `event_store_v2.py` to type the `_listeners` list
  as `list[Callable[[list[StoredEvent]], Awaitable[None]]]` (import `Callable` and `Awaitable`
  from `collections.abc`).

**Constraints**
- [ ] `JsonlOutboxObserver` must not import from `workflow` — it only depends on `StoredEvent`
  from `event_store_v2`.
- [ ] JSONL write failures must be caught and logged; they must not propagate to the caller
  (JSONL is secondary; the event is already durable in SQLite). Wrap the `__call__` body in
  `try/except Exception` and log via `logger.warning`.
- [ ] The `_written` set is process-local; it is acceptable to re-scan the JSONL on startup
  to rebuild it (not required in this step — addressed in the bootstrap step).

**Functionality (Expected Outcomes)**
- [ ] After `await observer([stored_event])`, the JSONL file contains a line with
  `"position": stored_event.position`.
- [ ] Calling `await observer([stored_event])` a second time with the same position does not
  add a second line to the JSONL file.
- [ ] A write failure (e.g. disk full) is logged and swallowed; no exception propagates.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `uv run pyright src/orchestrator/db/access/jsonl_outbox.py` — no type errors.
- [ ] Unit tests written in Task 1.5 for `test_jsonl_outbox.py` pass.

---

## Task 1.4: Wire PersistentEventEmitter to SqliteEventStore

**Description**: Update `PersistentEventEmitter` to accept `SqliteEventStore` (via the new
`EventStore` protocol from `event_store_v2.py`) and register `JsonlOutboxObserver` as a
post-append listener. Update `api/deps.py` so both the request-scoped and session-factory paths
use `SqliteEventStore`. Export new types from `db/__init__.py`.

**Implementation Plan (Do These Steps)**

- [ ] Update `src/orchestrator/workflow/events/logger.py` — change the type annotation on
  `self._store` from `orchestrator.db.EventStore` (legacy) to the new
  `orchestrator.db.access.event_store_v2.EventStore` protocol. The `emit` and `emit_batch`
  implementations can stay the same because both stores share `append` / `append_batch`
  surface. The key change: `PersistentEventEmitter.__init__` must accept either store.

  The simplest approach: import the new protocol at the top level and annotate with it.
  Keep the constructor signature as `__init__(self, event_store: EventStore)` using a
  `Union` or `Protocol` type so both old and new stores are accepted during the transition.

- [ ] In `src/orchestrator/api/deps.py`:
  - Add a `get_event_store_v2` dependency function that constructs `SqliteEventStore` bound
    to the current session, with a `JsonlOutboxObserver` registered as a listener if a JSONL
    path can be resolved (reuse `resolve_default_journal_path_from_session` from the existing
    journal code).
  - Update `get_workflow_service` to call `get_event_store_v2` for the emitter's backing
    store while keeping the legacy `event_store` parameter for `WorkflowService` (which still
    reads from `EventStore` in this step — full cutover happens in Step 03).
  - Update `make_service_factory` similarly.

```python
# New dependency in deps.py
async def get_event_store_v2(
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
) -> SqliteEventStore:
    from orchestrator.db.access.event_store_v2 import SqliteEventStore
    from orchestrator.db.access.jsonl_outbox import JsonlOutboxObserver
    from orchestrator.db.recovery.event_journal import resolve_default_journal_path_from_session

    store = SqliteEventStore(session)
    journal_path = resolve_default_journal_path_from_session(session)
    if journal_path is not None:
        store.add_listener(JsonlOutboxObserver(journal_path))
    return store
```

- [ ] Update `src/orchestrator/db/__init__.py` to export `SqliteEventStore`, `EventV2Model`,
  `StoredEvent`, `ConcurrencyConflictError`, and `RetryWithBackoff` from their new modules,
  following the existing lazy-import pattern.

- [ ] Add `SqliteEventStore`, `EventV2Model`, and `StoredEvent` to `__all__` in
  `src/orchestrator/db/__init__.py`.

**Dependencies**
- [ ] Tasks 1.1, 1.2, 1.3 must be complete.

**Constraints**
- [ ] Do not remove `get_event_store` or the legacy `EventStore` construction from `deps.py`
  — the legacy path remains in use by `WorkflowService` until Step 03.
- [ ] `WorkflowService` still receives the legacy `event_store` (the old `EventStore`) for
  its read operations; only the `PersistentEventEmitter` switches to `SqliteEventStore` in
  this step.
- [ ] Do not modify `WorkflowService`'s constructor signature in this step.

**Side Effects**
- New events will now be written to `events_v2` as well as the legacy `events` table (the old
  `EventStore.append` path inside `WorkflowService._persist` still fires until Step 03). This
  is intentional dual-write during the transition period.

**Functionality (Expected Outcomes)**
- [ ] Creating a `PersistentEventEmitter(SqliteEventStore(session))` and calling `emit(event)`
  inserts a row into `events_v2` and notifies the `JsonlOutboxObserver`.
- [ ] The legacy `EventStore` construction path in `api/deps.py` is untouched; the new
  `get_event_store_v2` is an additive dependency.
- [ ] `from orchestrator.db import SqliteEventStore, EventV2Model, StoredEvent` all work.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `uv run pyright src/orchestrator/api/deps.py src/orchestrator/workflow/events/logger.py src/orchestrator/db/__init__.py` — no type errors.
- [ ] `uv run pytest` — full test suite passes (no regressions from the wiring change).
- [ ] **Mandatory integration test** (add to `tests/integration/test_event_store_wiring.py`):
  construct a `SqliteEventStore` with `JsonlOutboxObserver` registered, call
  `PersistentEventEmitter.emit(event)`, assert (1) a row appears in `events_v2` via
  `SqliteEventStore.get_stream(run_id)`, and (2) the JSONL file contains the corresponding
  line. This is the only reliable way to verify the dual-write wiring is active. The `uv run
  pytest tests/integration/test_event_store_wiring.py -v` command must pass.

---

## Task 1.5: Unit Tests

**Description**: Write unit tests for the three new modules — `event_store_v2.py`,
`concurrency.py`, and `jsonl_outbox.py`. All tests use real in-memory SQLite; no mocking.

**Implementation Plan (Do These Steps)**

- [ ] Create `tests/unit/test_event_store_v2.py`:
  - Helper fixture: `async_session` — in-memory SQLite with `events_v2` table created via
    `Base.metadata.create_all`.
  - `test_append_and_get_stream` — append two events for run-1, assert `get_stream("run-1")`
    returns them in order with correct `event_type` and `payload`.
  - `test_get_all_after_position` — append 5 events (mix of two aggregate IDs), assert
    `get_all(after_position=3)` returns only events with `position > 3`.
  - `test_version_auto_increments` — append events for the same `aggregate_id`, assert
    `version` increments 1, 2, 3.
  - `test_version_conflict_raises_concurrency_error` — use `RetryWithBackoff(max_attempts=1)`
    and inject a session that always raises an `IntegrityError` with "UNIQUE" in the message;
    assert `ConcurrencyConflictError` is raised.
  - `test_listener_called_after_append` — register a listener on `SqliteEventStore`; append
    an event; assert the listener was awaited with the `StoredEvent` list.

- [ ] Create `tests/unit/test_concurrency_strategy.py`:
  - `test_retry_succeeds_on_second_attempt` — inject a callable that raises a conflict error
    once, then returns `"ok"`. Assert result is `"ok"` and the callable was called twice.
  - `test_retry_exhausted_raises` — inject a callable that always raises a conflict error.
    With `max_attempts=3`, assert `ConcurrencyConflictError` is raised and callable was called
    3 times.
  - `test_non_conflict_error_not_retried` — inject a callable that raises `ValueError`.
    Assert `ValueError` propagates on the first attempt (not retried).
  - `test_backoff_timing` — mock `asyncio.sleep`; assert it is called with increasing delays
    (10ms, 20ms) on successive conflict retries.

- [ ] Create `tests/unit/test_jsonl_outbox.py`:
  - `test_write_event_to_jsonl` — construct `JsonlOutboxObserver(path)` with a `tmp_path`;
    call with a single `StoredEvent`; assert the JSONL file contains one line whose parsed
    JSON has `"position"` equal to the event's position.
  - `test_idempotent_same_position` — call the observer twice with the same `StoredEvent`;
    assert the JSONL file has exactly one line (not two).
  - `test_multiple_events_written` — call with a list of three `StoredEvent`s with distinct
    positions; assert three lines in the JSONL file.
  - `test_write_failure_does_not_propagate` — monkeypatch `_append_lines` to raise
    `OSError`; assert no exception propagates from `await observer([event])`.

- [ ] All tests: use `pytest-asyncio` in `asyncio` mode (check existing test files to confirm
  the project-level `asyncio_mode` setting in `pyproject.toml`).

**Dependencies**
- [ ] Tasks 1.1–1.4 must be complete.
- [ ] `EventV2Model` must be created via `Base.metadata.create_all(engine)` in the fixture —
  not via Alembic — so tests are hermetic.

**References**
- Existing unit tests in `tests/unit/` for fixture patterns and `pytest-asyncio` setup.

**Constraints**
- [ ] No mocking of SQLAlchemy or SQLite — use real `aiosqlite` in-memory sessions.
- [ ] No mocking of `JsonlEventJournal` or the legacy `EventStore`.
- [ ] Tests must be runnable in isolation with `uv run pytest tests/unit/test_event_store_v2.py -v`.

**Functionality (Expected Outcomes)**
- [ ] All test functions are collected by pytest (`--collect-only` shows them).
- [ ] All tests pass.
- [ ] No test asserts stub or error-stub behavior as success (each test exercises real I/O).

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `uv run pytest tests/unit/test_event_store_v2.py tests/unit/test_concurrency_strategy.py tests/unit/test_jsonl_outbox.py -v` — all pass, none skipped.
- [ ] `uv run pytest tests/unit/test_event_store_v2.py --collect-only` — shows at least 5 test items.
- [ ] `uv run pytest tests/unit/test_concurrency_strategy.py --collect-only` — shows at least 4 test items.
- [ ] `uv run pytest tests/unit/test_jsonl_outbox.py --collect-only` — shows at least 4 test items.
- [ ] `uv run pytest` — full suite passes (no regressions).
