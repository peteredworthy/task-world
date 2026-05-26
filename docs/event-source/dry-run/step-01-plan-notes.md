# Step 01 Plan — Dry-Run Analysis Notes

## Summary

Five tasks build upward: ORM + migration → concurrency + store → JSONL observer →
wiring into `PersistentEventEmitter` → unit tests. The overall structure is sound,
but several concrete failure modes exist that would prevent tests from passing as
written. Findings are ordered by severity.

---

## Task 1.1: events_v2 ORM Model and Alembic Migration

### Assumptions

- `EventV2Model` inherits from `orchestrator.db.orm.base.Base` (DeclarativeBase), so it is
  automatically included in `Base.metadata` and picked up by `init_db` / test fixtures
  that call `Base.metadata.create_all`.
- The most recent migration is `t1a2b3c4d5e6_rename_runner_profile_defaults_table.py`; the
  new migration must set `down_revision = "t1a2b3c4d5e6"`.

### Failure Modes

**F1.1-A — Missing `down_revision` in migration spec**

The step names the new migration file `u1a2b3c4d5e6_add_events_v2_table.py` and shows
the `upgrade()` / `downgrade()` bodies, but never states what `down_revision` must be.
If the implementor guesses incorrectly or leaves it `None`, `alembic upgrade head` will
silently succeed on a fresh DB (creates the chain from scratch) but fail on an existing
DB because Alembic cannot find the migration that connects `t1a2b3c4d5e6` → `u1a2b3c4d5e6`.

**Hardening**: Explicitly state `down_revision = "t1a2b3c4d5e6"` in the step
instructions. Add verification: `uv run alembic history | grep u1a2b3c4d5e6` should show
it as the head.

**F1.1-B — `UniqueConstraint` / `Index` already imported in `models.py`**

Both `UniqueConstraint` and `Index` are already imported. No new imports needed. This is
fine, but the step doesn't verify the existing import list — an implementor might
accidentally add duplicate imports that break Pyright.

**Hardening**: Low risk, no action needed. Pyright will flag duplicate-import lint errors
in verification.

**F1.1-C — No FK to `runs` table (intentional, but must not be added by mistake)**

`EventV2Model` intentionally has no FK to `runs.id` (events should be appendable before
or independently of projection tables during bootstrap). If an implementor adds a FK, the
bootstrap replay scenario breaks.

**Hardening**: Add an explicit note in the implementation plan: "Do not add a ForeignKey
from `aggregate_id` to `runs.id`; this decoupling is required for empty-DB bootstrap."

---

## Task 1.2: ConcurrencyStrategy and SqliteEventStore

### Assumptions

- Step 00 is complete: `WorkflowEvent` subclasses are Pydantic `BaseModel` and have
  `.model_dump_json()`. If Step 00 is incomplete, `SqliteEventStore.append` will raise
  `AttributeError` at runtime.
- `event.run_id` exists on all `WorkflowEvent` instances (it does — it's the base-class
  field in both the current dataclass and post-M0 Pydantic form).
- `format_utc_datetime(event.timestamp)` works because `timestamp` is a `datetime` object.

### Failure Modes

**F1.2-A (HIGH) — `RetryWithBackoff.execute_with_retry` wraps non-conflict errors in `ConcurrencyConflictError`**

The provided implementation:

```python
except Exception as exc:
    if attempt == self.max_attempts or not _is_version_conflict(exc):
        raise ConcurrencyConflictError(
            f"Version conflict unresolved after {attempt} attempt(s)"
        ) from exc
    await asyncio.sleep(delay)
    delay *= 2
```

When a non-conflict exception (e.g. `ValueError`) is raised on the first attempt
(`attempt=1`, `max_attempts=3`): `attempt == self.max_attempts` is `False`,
`not _is_version_conflict(exc)` is `True`, so the condition is `True` and
`ConcurrencyConflictError` is raised — not `ValueError`.

The Task 1.5 test `test_non_conflict_error_not_retried` asserts `ValueError` propagates
directly. This test will **fail** as written against the provided implementation.

The correct implementation re-raises the original exception for non-conflict errors:

```python
except Exception as exc:
    if not _is_version_conflict(exc):
        raise  # re-raise original — not a concurrency conflict
    if attempt == self.max_attempts:
        raise ConcurrencyConflictError(...) from exc
    await asyncio.sleep(delay)
    delay *= 2
```

**Hardening**: Fix the `execute_with_retry` logic so non-conflict exceptions propagate
unchanged. Update the test to assert `ValueError` propagates (not `ConcurrencyConflictError`).

**F1.2-B — `_listeners` type annotation uses bare ellipsis**

The provided stub contains `self._listeners: list[...] = []`. This is not valid Python
— `list[...]` uses an `Ellipsis` literal as a type argument, which Pyright will reject.
The note says "Use `list[Any]` for now", but the code shows `list[...]`. The final
verification step runs Pyright; this would fail immediately.

**Hardening**: The stub in the step should consistently use `list[Any]` (import `Any`
from `typing`). Task 1.3 then narrows it to the correct `Callable` type.

**F1.2-C — `SqliteEventStore.append` interface incompatible with `PersistentEventEmitter`**

`PersistentEventEmitter.emit` (line 26 of `logger.py`) calls:
```python
await self._store.append(event)   # single WorkflowEvent
```
`PersistentEventEmitter.emit_batch` (line 33) calls:
```python
await self._store.append_batch(events)  # Sequence[WorkflowEvent]
```

The new `SqliteEventStore` exposes:
- `append(events: Sequence[WorkflowEvent])` — takes a **sequence**
- No `append_batch` method

So after Task 1.4 wires `PersistentEventEmitter` to `SqliteEventStore`, both `emit` and
`emit_batch` will raise `AttributeError` at runtime because:
- `emit` passes a single event where a sequence is expected
- `emit_batch` calls `.append_batch()` which does not exist on `SqliteEventStore`

Task 1.4 mentions updating `PersistentEventEmitter.__init__` but doesn't specify how
`emit` and `emit_batch` should be rewritten for the new interface.

**Hardening**: Task 1.4 must explicitly require:
1. Change `PersistentEventEmitter.emit` to call `await self._store.append([event])`.
2. Change `PersistentEventEmitter.emit_batch` to call `await self._store.append(events)`.
3. Add an `append_batch` method to `SqliteEventStore` as a simple alias:
   `async def append_batch(self, events): return await self.append(events)` — this
   preserves backward compatibility with the old `EventStore` signature during transition.

Alternatively: document that `PersistentEventEmitter` needs full rewrite for the new
`append(Sequence)` interface and that existing `test_event_store.py` tests must adapt.

**F1.2-D — `_is_version_conflict` checks `"aggregate_id" in msg` which is column-name-specific**

SQLite's UNIQUE constraint error for `UNIQUE(aggregate_id, version)` is:
```
UNIQUE constraint failed: events_v2.aggregate_id, events_v2.version
```
(confirmed via direct SQLite test). So `"aggregate_id" in msg.lower()` correctly
identifies this constraint violation. This is acceptable for the single-instance
SQLite deployment.

Risk: A future table with an `aggregate_id` column and its own unique constraint would
false-positive. Mitigated by also checking `"uq_events_v2" in msg` (the named constraint).

No action needed, but worth documenting as a known limitation.

**F1.2-E — `version` column on `TaskModel` clashes with the new `version` concept**

`TaskModel` already has a `version` column used for SQLAlchemy optimistic locking
(`__mapper_args__ = {"version_id_col": version}`). The new `EventV2Model.version` is a
different concept (per-aggregate event sequence number). No name clash at the ORM level
since they are separate models, but documentation and code reviewers may be confused.

**Hardening**: Low risk; clarify in code comments that `EventV2Model.version` is the
per-aggregate event sequence counter, not a SQLAlchemy optimistic-lock version column.

---

## Task 1.3: JsonlOutboxObserver

### Assumptions

- `JsonlOutboxObserver.__call__` is the post-append listener signature:
  `async def __call__(self, events: list[StoredEvent]) -> None`.
- JSONL write failures are swallowed; the event is already durable in SQLite.

### Failure Modes

**F1.3-A — Missing outer `try/except` for JSONL write failure**

The provided implementation code for `__call__` does not include the required outer
`try/except Exception` block specified in the Constraints section. The `_append_lines`
call inside `asyncio.to_thread(...)` would propagate `OSError` upward into the caller
(the `SqliteEventStore` post-append listener chain), which would then fail the entire
event append from the caller's perspective even though the event is already durable.

The step says "Wrap the `__call__` body in `try/except Exception` and log via
`logger.warning`" but the shown implementation code doesn't reflect this.

**Hardening**: Add explicit `try/except` wrapping the `asyncio.to_thread` call in
`__call__`. The test `test_write_failure_does_not_propagate` will catch the absence of
this guard, so the tests are well-designed to catch this — but only if the test is
implemented before the guard is added.

**F1.3-B — `_written` set is process-local and not pre-populated on startup**

On restart, `_written` is empty. If a crash occurred after the DB write but before the
JSONL write, the outbox would re-write events that already exist in the JSONL file, but
with their DB position as the key. Since the observer is keyed by `position` (not
content), re-writing events that are already in the JSONL would produce duplicates.

The step acknowledges this: "It is acceptable to re-scan the JSONL on startup to rebuild
it (not required in this step — addressed in the bootstrap step)." This is a known gap,
not a bug for Step 01.

**F1.3-C — `asyncio.to_thread` for `_path.parent.mkdir`**

`await asyncio.to_thread(self._path.parent.mkdir, parents=True, exist_ok=True)` — this
calls the function with positional args `parents=True, exist_ok=True` passed as keyword
arguments to `asyncio.to_thread`. The signature is:
`asyncio.to_thread(func, *args, **kwargs)`.

However, `Path.mkdir` has signature `mkdir(mode=0o777, parents=False, exist_ok=False)`.
Calling `asyncio.to_thread(self._path.parent.mkdir, parents=True, exist_ok=True)` passes
`parents=True` and `exist_ok=True` as keyword arguments, which is valid Python.

Actually this is correct — `asyncio.to_thread(func, **kwargs)` does pass kwargs through.
No issue here.

---

## Task 1.4: Wire PersistentEventEmitter to SqliteEventStore

### Assumptions

- `resolve_default_journal_path_from_session(session)` uses `session.get_bind()` which
  works in the current codebase (confirmed in `event_store.py`).
- Both `get_workflow_service` and `make_service_factory` need updating.

### Failure Modes

**F1.4-A (HIGH) — `PersistentEventEmitter` interface change breaks existing `test_event_store.py`**

`tests/unit/test_event_store.py` (currently in the unit test directory despite the file
header saying "Integration tests") tests `PersistentEventEmitter(old_event_store)` and
calls `.emit(event)` and `.emit_batch(events)`. After Task 1.4 changes
`PersistentEventEmitter.emit` to call `self._store.append([event])` (to match the new
sequence-based interface), the old `EventStore.append(event)` (single-arg) would receive
a list and likely raise a type error or mismatch.

The step says to "keep the legacy `EventStore` construction path in `api/deps.py`
untouched" and that both old and new stores should be accepted via `Union` or `Protocol`.
This implies `PersistentEventEmitter` must branch on store type or both stores must share
a common interface.

If `PersistentEventEmitter.emit` stays as `await self._store.append(event)` (single), it
works for the old `EventStore` but fails for `SqliteEventStore` (expects sequence). If it
changes to `await self._store.append([event])`, it fails for the old `EventStore` (no
list arg).

The step does not resolve this interface incompatibility. It's the most likely cause of
a broken test suite after Task 1.4.

**Hardening options** (pick one):
1. Add `append_single(event)` as an alias on `SqliteEventStore` that calls
   `self.append([event])`, and define a unified protocol that includes both
   `append(events)` and `append_single(event)`.
2. Add `append_batch(events)` alias on `SqliteEventStore` and keep `PersistentEventEmitter`
   calling `append(event)` / `append_batch(events)` — but update `SqliteEventStore.append`
   to accept both a single event and a sequence (runtime dispatch on type).
3. Preferred: Update `PersistentEventEmitter.emit` to call `self._store.append([event])`
   AND add `append(event)` method to the old `EventStore` that accepts a single event (it
   already does) AND add an `append_batch` alias to `SqliteEventStore`. This keeps both
   paths working.

The cleanest approach: add `append_batch` to `SqliteEventStore` as an alias, and define
the protocol to include both `append` and `append_batch`.

**F1.4-B — `get_event_store_v2` function signature includes `Request` which is unused**

The proposed `get_event_store_v2` dependency takes `request: Request` but does not use
it directly — `resolve_default_journal_path_from_session(session)` gets the path from the
session's engine URL. The `request` parameter adds unnecessary coupling. Pyright may flag
an unused-parameter warning.

**Hardening**: Remove `request: Request` from the `get_event_store_v2` signature. The
journal path is already resolved from the session.

**F1.4-C — `make_service_factory` creates `EventStore` and `PersistentEventEmitter` inline**

Lines 269-270 of `deps.py`:
```python
event_store = EventStore(session)
emitter = PersistentEventEmitter(event_store)
```
Task 1.4 says to update `make_service_factory` similarly to `get_workflow_service`, but
provides no implementation details. The background task path (signal consumer, stale-run
sweeper) uses this factory. If `make_service_factory` is not updated, the background tasks
continue using the old `EventStore` only, and the "new events written to `events_v2`"
claim in the task's Side Effects section is only partially true.

**Hardening**: Explicitly require updating `make_service_factory` with the same pattern:
construct `SqliteEventStore(session)`, register `JsonlOutboxObserver`, pass to
`PersistentEventEmitter`.

**F1.4-D — Dual-write not verified by any test**

The "Side Effects" section says "new events will now be written to `events_v2` as well as
the legacy `events` table." The Final Verification says to "manually confirm or add a
quick integration test." This is under-specified — without an actual assertion, it's easy
to claim success while the dual-write is not actually happening (e.g., because
`PersistentEventEmitter` still uses the old store).

**Hardening**: Task 1.4's Final Verification should include a mandatory integration test
(not "manually confirm") that:
1. Creates a `SqliteEventStore` backed by in-memory SQLite.
2. Calls `PersistentEventEmitter.emit(event)`.
3. Asserts `SqliteEventStore.get_stream(run_id)` returns the event.
4. Asserts `events_v2` table has a row (not just the old `events` table).

---

## Task 1.5: Unit Tests

### Assumptions

- `asyncio_mode = "auto"` in `pyproject.toml` means async test functions need no
  decorator.
- `asyncio_default_fixture_loop_scope = "module"` means all async fixtures in a module
  share one event loop per pytest module. Function-scoped async fixtures work within this.
- Unit tests must not import `sqlalchemy.pool.StaticPool` directly (conftest enforcement).
- Using `orchestrator.db.create_engine(":memory:")` is allowed (it uses `StaticPool`
  internally but the import is not in the test file).

### Failure Modes

**F1.5-A — Test fixture strategy conflicts with unit test boundary enforcement**

Task 1.5 says: "Helper fixture: `async_session` — in-memory SQLite with `events_v2`
table created via `Base.metadata.create_all`."

Two implementation paths exist:
1. Use `orchestrator.db.create_engine(":memory:")` + `init_db(engine)` — allowed, same
   as `test_event_store.py`.
2. Use `create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)` directly —
   FORBIDDEN by unit test conftest (imports `StaticPool`).

The step doesn't specify which path to use. If the implementor uses path 2, the conftest
will raise `pytest.UsageError` at collection time and block the entire test run.

**Hardening**: Explicitly state to use `orchestrator.db.create_engine(":memory:")` and
`orchestrator.db.init_db(engine)` (same pattern as `test_event_store.py`). Add a note
that direct `StaticPool` import is forbidden in unit tests.

**F1.5-B — `test_version_conflict_raises_concurrency_error` requires injecting a session that fails**

The test should "inject a session that always raises an `IntegrityError` with 'UNIQUE'
in the message." The constraint says "no mocking of SQLAlchemy or SQLite." The natural
approach is to actually trigger a UNIQUE constraint violation by inserting duplicate
`(aggregate_id, version)` values.

However, `SqliteEventStore.append` auto-calculates the next version number by querying
`MAX(version)` before inserting. To produce a conflict, two concurrent appends for the
same aggregate must race. In a single-threaded test, this requires manually inserting a
row with a specific version to steal it before the `_do_append` executes.

A cleaner approach: use `RetryWithBackoff(max_attempts=1)` and manually insert a row that
conflicts with what `append` will try to insert, between the version query and the flush.
This requires patching the session's `flush` to insert a conflict before proceeding —
which is mocking SQLAlchemy.

The simplest no-mock approach: directly insert a row with `(aggregate_id="run-1", version=1)`,
then call `append` for the same run, rely on the session re-querying and getting version 1,
try to insert version 1 again, trigger IntegrityError. But `SqliteEventStore.append` queries
MAX(version) first — it would get 1 and try to insert version 2, not 1. So there's no
natural conflict unless two concurrent appenders race.

**Hardening**: The test should use a mock or subclass of `AsyncSession` that simulates a
conflict by raising `IntegrityError` with the right message from `flush()`. Since "no
mocking of SQLAlchemy" is stated but the test requires an unreproducible race condition
without mocking, the constraint and the test are in tension. The resolution is to inject
a failing `_do_append` callable directly into `RetryWithBackoff.execute_with_retry` rather
than through the session — testing the concurrency layer independently of the store.

Alternatively: test the `RetryWithBackoff` in isolation (Task 1.5 `test_concurrency_strategy.py`)
by injecting a callable that raises a fake exception, and test the `SqliteEventStore` with
real SQLite without testing the retry path end-to-end (covered by integration tests).

**F1.5-C — `test_backoff_timing` mocks `asyncio.sleep` which is consistent with constraints**

"Mock `asyncio.sleep`; assert it is called with increasing delays (10ms, 20ms)." This is
fine — the constraint only prohibits mocking SQLAlchemy/SQLite, not stdlib functions. Use
`monkeypatch.setattr("orchestrator.db.access.concurrency.asyncio.sleep", mock_sleep)`.

**F1.5-D — `test_listener_called_after_append` requires an async listener**

`SqliteEventStore._listeners` will hold async callables. The test should create an `async`
listener function to verify it is awaited. If the test uses a sync lambda, `await listener(stored)`
in the store will raise `TypeError`.

**Hardening**: Specify that the listener in this test must be declared as `async def` and
that the test asserts the listener received the correct `StoredEvent` list.

**F1.5-E — `test_event_store.py` is located in `tests/unit/` despite being integration tests**

The existing file `tests/unit/test_event_store.py` has the header "Integration tests for
EventStore and PersistentEventEmitter." It uses `create_engine(":memory:")` which is
allowed by the unit test conftest. The new `test_event_store_v2.py` should follow the
same pattern. No action needed, but this naming inconsistency may confuse implementors.

---

## Cross-Cutting Concerns

### CC-1 (HIGH) — Component Wiring: PersistentEventEmitter Still Uses Old EventStore

The step's "Side Effects" say "new events will now be written to `events_v2` as well as
the legacy `events` table." But the existing tests in `test_event_store.py` test the old
`EventStore` path via `PersistentEventEmitter(old_event_store)`. After Task 1.4, if
`PersistentEventEmitter` is updated to require `SqliteEventStore`, those tests will fail.
If it's NOT updated (kept as a `Union`), the wiring is not verified and the system may
continue using only the old path.

The critical question is: **what replaces what, and how is it verified?** The step says
to update `get_workflow_service` in `deps.py` to use `get_event_store_v2` for the emitter.
But it does not require removing `get_event_store` from `get_workflow_service`'s
parameters. If both stores are created and only one is used by the emitter, the wiring
verification is incomplete.

**Hardening**: Add an explicit integration test (in `tests/integration/`) that starts a
real request through the API, persists one event, and asserts a row appears in `events_v2`.
This is the only reliable way to verify the wiring is active.

### CC-2 — Step 00 Completion Check

`SqliteEventStore.append` calls `event.model_dump_json()`. If Step 00 is incomplete
(events are still dataclasses), every append will raise `AttributeError: 'RunStatusChanged'
object has no attribute 'model_dump_json'`. The step only states the dependency; it does
not require a guard or runtime check.

**Hardening**: The task should include a verification step: run
`python -c "from orchestrator.workflow.events import RunStatusChanged; RunStatusChanged.__bases__"` and
assert it shows `pydantic.BaseModel` in the MRO, not `dataclass`.

### CC-3 — Alembic Migration in Integration Tests vs. `Base.metadata.create_all`

`init_db` for in-memory databases uses `Base.metadata.create_all`, not Alembic. After
`EventV2Model` is added to the Base, the in-memory tables include `events_v2`
automatically. This means unit tests get the table "for free" without needing to
understand migrations. However, the Alembic migration itself is only exercised against
file-backed DBs. The Final Verification's "run alembic upgrade head" step should be
explicitly tested against a temp file-backed DB (not memory).

### CC-4 — `format_utc_datetime` import in `event_store_v2.py`

The step imports `from orchestrator.time_utils import format_utc_datetime`. This is a
simple utility and will work. However, after M0, Pydantic events serialize datetimes as
ISO strings via `model_dump_json()`. The `timestamp` field stored in `EventV2Model` is
set via `format_utc_datetime(event.timestamp)`, which is correct — the ORM field is
`String`, and this function returns a UTC ISO-8601 string.

No action needed.

### CC-5 — `db/access/__init__.py` may need updating

The step doesn't specify updating `src/orchestrator/db/access/__init__.py`. If that file
re-exports from `event_store.py`, adding new exports there (or not) could affect imports.

**Current state**: `db/access/__init__.py` contains only a single docstring line. It is
not a barrel file. New files (`event_store_v2.py`, `concurrency.py`, `jsonl_outbox.py`)
are added to that directory and are importable by direct module path regardless. No
changes needed to this file.

### CC-6 — `asyncio_default_fixture_loop_scope = "module"` and function-scoped fixtures

With module-level loop scope, a function-scoped `async_session` fixture creates a new
engine per test function — all sharing the same event loop for the module. This works
correctly; no issue.

### CC-7 (HIGH) — `JsonlOutboxObserver._to_record` format is incompatible with existing `journal_replay.py`

The `_to_record` function in the provided implementation produces:
```json
{"position": 1, "aggregate_id": "run-1", "event_type": "...", "timestamp": "...", "payload": {...}}
```

But `journal_replay._load_and_filter_entries` reads these fields from JSONL entries:
- `entry.get("run_id", "")` — the new format uses `aggregate_id`, not `run_id`
- `entry.get("sequence_number", 0)` — the new format uses `position`, not `sequence_number`
- `entry.get("event_type", "")` — matches ✓
- `entry.get("timestamp")` — matches ✓
- `entry.get("payload")` — matches ✓

Because `run_id` is missing (returns empty string), new-format entries fail the validation
guard at `if not run_id ...` in `_load_and_filter_entries` and are silently filtered out.
Sequence-number-based checkpoint resumption also breaks because `sequence_number` is always
0 for new entries.

**Impact by step:**
- **Step 01 (this step):** Low risk. The old `EventStore.append` path continues to write
  old-format JSONL entries (via `make_journal_entry`) in parallel. The old-format entries
  are readable by `journal_replay.py`. New outbox entries are skipped but tolerable.
- **Step 03 (after old path removed):** HIGH risk. Only new-format entries are written.
  `journal_replay.py` can no longer recover any events, violating I-18.
- **Step 05:** `journal_replay.py` is removed and replaced by `rebuild-projections`. If
  Step 02 delivers that CLI command first, the gap is covered.

**Constraint violation:** I-18 states "The JSONL journal format must remain readable by
existing tooling during the transition." The proposed outbox format breaks this from
Step 03 onward unless the format is aligned.

**Hardening:**
1. Change `JsonlOutboxObserver._to_record` to produce output compatible with `make_journal_entry`:
   use `run_id` (not `aggregate_id`), `sequence_number` (not `position`), and include
   `schema_version` and `logged_at`. This makes the outbox format readable by all existing
   tooling.
2. Alternatively, explicitly acknowledge in the step that `journal_replay.py` will stop
   working after Step 03, and ensure Step 02 delivers the `rebuild-projections` CLI before
   Step 03 removes the old write path.
3. Add a test that reads outbox-written JSONL through `journal_replay._load_and_filter_entries`
   and asserts entries are not silently filtered out.

---

## Summary of Required Hardening Actions

| ID | Severity | Task | Action |
|----|----------|------|--------|
| F1.1-A | HIGH | 1.1 | Specify `down_revision = "t1a2b3c4d5e6"` in migration |
| F1.1-C | MED | 1.1 | Add explicit note: no FK from `aggregate_id` to `runs.id` |
| F1.2-A | HIGH | 1.2 | Fix `execute_with_retry` to re-raise non-conflict exceptions unchanged |
| F1.2-B | HIGH | 1.2 | Replace `list[...]` with `list[Any]` in `_listeners` type annotation |
| F1.2-C | HIGH | 1.2/1.4 | Resolve interface mismatch: add `append_batch` alias to `SqliteEventStore`; update `PersistentEventEmitter.emit` to pass `[event]` |
| F1.3-A | HIGH | 1.3 | Add outer `try/except Exception` around `asyncio.to_thread` call in `__call__` |
| F1.4-A | HIGH | 1.4 | Specify exactly how `PersistentEventEmitter.emit/emit_batch` must change for both old and new stores |
| F1.4-B | LOW | 1.4 | Remove unused `request: Request` from `get_event_store_v2` |
| F1.4-C | HIGH | 1.4 | Add explicit implementation plan for updating `make_service_factory` |
| F1.4-D | HIGH | 1.4 | Replace "manually confirm" with a required integration test |
| F1.5-A | HIGH | 1.5 | Specify using `orchestrator.db.create_engine(":memory:")`, not direct `StaticPool` |
| F1.5-B | MED | 1.5 | Clarify conflict test: test `RetryWithBackoff` independently via callable injection |
| F1.5-D | MED | 1.5 | Specify listener must be `async def` in `test_listener_called_after_append` |
| CC-1 | HIGH | all | Add integration test verifying `events_v2` row is written via API request |
| CC-2 | MED | all | Add Step 00 completion check to prerequisites verification |
| CC-7 | HIGH | 1.3 | Fix `_to_record` to use `run_id`/`sequence_number` keys (not `aggregate_id`/`position`) for `journal_replay.py` compatibility |
