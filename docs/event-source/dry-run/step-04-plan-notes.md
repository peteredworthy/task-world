# Step 04 Plan - Dry-Run Analysis Notes

## Summary

Step 04 migrates the signal system from process-local and table-backed state to event-backed
signals. This addresses the active-run registry restart problem, but the step touches live run
control paths. The main risks are stale active-run state, duplicate signal processing, and
inconsistent behavior during startup recovery.

---

## Task 4.1: Add SignalEnqueued and SignalProcessed event types

### Failure Modes

**F4.1-A - Signal payload schema can become unbounded**

`SignalEnqueued.payload` is a dict. If arbitrary data is accepted, signal events can contain values
that are not JSON-serializable or not understood by future consumers.

**Hardening**: Validate signal type and payload at the API/service boundary before constructing the
event. Keep payloads JSON-compatible and small. Add round-trip tests with representative pause,
resume, and cancel payloads.

**F4.1-B - `SignalProcessed` needs a stable reference to the original event**

The plan uses `enqueued_position`, which is correct for SQLite event positions. If a future store
changes position semantics, processed matching can break.

**Hardening**: Keep `enqueued_position` non-null and unique per processed signal. Add a uniqueness
constraint or query guard that prevents duplicate `SignalProcessed` records for the same enqueued
position.

---

## Task 4.2: Implement RunLifecycleProjector

### Failure Modes

**F4.2-A - In-memory active set still disappears on restart unless rebuilt**

Replacing `_active_run_ids` with an in-memory projector only fixes the problem if the projector is
rebuilt from events on startup before signal redelivery begins.

**Hardening**: Wire projector rebuild into startup before `SignalConsumer._redeliver_on_startup`.
Add an integration test that starts with event history for an active run and asserts the projector
reports it active after startup.

**F4.2-B - Paused, failed, stopping, and completed states must all deactivate**

Only checking for `ACTIVE` and `PAUSED` can leave failed or completed runs active in the projector.

**Hardening**: Define the active-state set explicitly: active only when status is `RunStatus.ACTIVE`
or any other intentionally executable state. Unit tests should cover transitions to paused, failed,
completed, cancelled, and stopping.

---

## Task 4.3: Implement EventSignalTransport

### Failure Modes

**F4.3-A - Drain can process the same signal twice under concurrency**

Two consumers draining at the same time can both read the same unprocessed `SignalEnqueued` event
before either appends `SignalProcessed`.

**Hardening**: Append `SignalProcessed` with an idempotency key or enforce uniqueness on
`enqueued_position`. If a duplicate insert conflict occurs, one drain should treat it as already
claimed and skip that signal.

**F4.3-B - Querying by aggregate_id assumes aggregate_id is run_id**

The event store's `aggregate_id` is expected to be `run_id` for workflow events. Signal events must
follow the same convention or `_find_pending_run_ids()` will miss them.

**Hardening**: Add a test that appends a `SignalEnqueued` event and verifies its stored
`aggregate_id` equals the signal `run_id`.

**F4.3-C - Inactive run rejection can race with status changes**

The transport checks active state via `RunLifecycleProjector`. If a run becomes inactive after the
check but before append, the signal can still be enqueued.

**Hardening**: Treat stale signals as no-ops during drain as well as rejecting obviously inactive
signals at enqueue time. The Step 04 integration test already calls out stale signals; keep that
case mandatory.

---

## Task 4.4: Replace _active_run_ids with RunLifecycleProjector

### Failure Modes

**F4.4-A - Test-only imports can keep forbidden registry functions alive**

The signal routing checker forbids registry functions outside `consumer.py` and dedicated tests.
Removing the functions from production code but leaving imports in tests can fail pre-commit.

**Hardening**: Run the exact grep checks in the step and `scripts/check_signal_routing.py` before
considering this task complete.

**F4.4-B - Consumer constructor must receive projector dependency explicitly**

The design constraints prohibit cross-boundary process-local shared state and `app.state` access
from workflow internals. If `SignalConsumer` reaches into global state to find the projector, this
reintroduces the dependency problem.

**Hardening**: Inject `RunLifecycleProjector` or a lifecycle query protocol through the consumer
constructor. Tests should instantiate the consumer with a real projector instance.

---

## Task 4.5: Wire EventSignalTransport into WorkflowService and RunWorkflow

### Failure Modes

**F4.5-A - Mixed pending_signals and event-backed writes can split the queue**

If pause/resume/cancel use `EventSignalTransport` but startup recovery still scans
`pending_signals`, some signals will never be delivered.

**Hardening**: Update all queue producers and consumers in the same task. Add a grep check that no
production write path inserts into `pending_signals`.

**F4.5-B - RunWorkflow may still receive the old transport in tests**

Tests often construct runtime objects directly. If the default test fixture still uses
`InMemorySignalTransport`, integration behavior can pass while production wiring is wrong.

**Hardening**: Keep `InMemorySignalTransport` for isolated unit tests, but add one integration test
through `WorkflowService.pause_run()` and a real `EventSignalTransport`.

---

## Task 4.6: Alembic migration to mark pending_signals deprecated

### Failure Modes

**F4.6-A - Adding `_deprecated` can break ORM assumptions if model is unchanged**

Adding a column to a table that still has an ORM model is generally safe, but if tests assert exact
columns or insert via raw SQL without column lists, they can fail.

**Hardening**: Use nullable `_deprecated` with a server default, or document it as a migration-only
marker. Add a schema inspection test rather than relying on application code to read the column.

---

## Task 4.7 and 4.8: Tests

### Failure Modes

**F4.7-A - Unit tests can accidentally mock the queue**

The project rules prohibit mocking for this codebase. Signal tests should use real event store,
real in-memory SQLite, and injected dependencies.

**Hardening**: Build tests with `orchestrator.db.create_engine(":memory:")` and real store/projector
instances. Avoid `patch`, `MagicMock`, and monkeypatching SQLAlchemy.

**F4.8-A - Startup recovery needs an actual new consumer instance**

A test that calls a method twice on the same consumer does not prove restart behavior. The active
projector state and consumer need to be rebuilt from persisted events.

**Hardening**: The integration test should create events, dispose the first app/consumer objects,
construct a new consumer/projector, rebuild from events, and then assert signal redelivery.

---

## Summary of Required Hardening Actions

| ID | Severity | Task | Action |
|----|----------|------|--------|
| F4.2-A | HIGH | 4.2 | Rebuild lifecycle projector on startup before redelivery |
| F4.3-A | HIGH | 4.3 | Make signal processing idempotent under concurrent drains |
| F4.3-C | MED | 4.3 | Treat stale signals as no-ops during drain |
| F4.4-B | HIGH | 4.4 | Inject lifecycle dependency into consumer explicitly |
| F4.5-A | HIGH | 4.5 | Move all producers and consumers off `pending_signals` together |
| F4.8-A | HIGH | 4.8 | Test startup recovery with a fresh consumer/projector instance |
