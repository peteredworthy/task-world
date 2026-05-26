# Step 02: Projection Infrastructure

**Plan:** [step-02-plan.md](../step-02-plan.md)
**Architecture:** [architecture.md](../architecture.md)
**Intent:** [intent.md](../intent.md)
**Prerequisite:** Step 01 (Event Store Foundation) must be complete.

Build the projection framework: a `Projector` protocol, a `ProjectionRegistry` that coordinates
event dispatch and rebuild, and concrete projectors (`RunStateProjector`, `TaskStateProjector`)
that maintain the existing read-model tables from events. Add a `projection_checkpoints` table
to track per-projector progress and a CLI command to rebuild all projections from the event log
(requires server stop). Wire the registry into `PersistentEventEmitter` so projectors run
synchronously after every append.

The five tasks build upward: schema first, then the protocol and registry, then the two concrete
projectors, then the CLI command and emitter wiring, and finally the tests.

## Dry-Run Hardening Applied

- Projection failures must abort the append transaction rather than being swallowed after partial
  read-model mutation.
- Per-projector checkpoints must advance only when that projector successfully handles an event, or
  during an explicit full rebuild.
- Add rebuild tests that append through `SqliteEventStore`, read back stored events with `get_all()`,
  and rebuild from those deserialized events.
- Make `RunCreated` / `TaskCreated` placeholder handling explicit and link it to Step 03 so empty-DB
  rebuild support cannot be forgotten.
- Rebuild must clear projection-owned tables or use deterministic upserts that remove stale rows;
  resetting checkpoints alone is insufficient.
- Define and test the exact server lock path used by `orchestrator db rebuild-projections`.

## Intent Verification

**Original Intent**: [I-25] Projection framework with `Projector` protocol, `ProjectionRegistry`,
and concrete projectors that maintain read-model tables from events. [I-26] `rebuild-projections`
CLI command replays the full event stream to rebuild projections from scratch. [I-04] Projectors
run synchronously post-append within the same transaction to maintain current consistency
guarantees.

**Functionality to Produce**:
- `Projector` protocol: `handle(event, session) -> None`, `rebuild(events, session) -> None`,
  with a `handled_events` class attribute declaring which event types the projector processes.
- `ProjectionRegistry`: registers projectors; dispatches events to handlers (only dispatches to
  projectors that declare the event type in `handled_events`); coordinates full-rebuild by calling
  each projector's `rebuild` with `SqliteEventStore.get_all()`.
- `ProjectionCheckpointModel` ORM model (`projection_checkpoints` table): `projector_name` (PK),
  `last_position` (int), `updated_at` (ISO 8601 string).
- Alembic migration creating the `projection_checkpoints` table.
- `RunStateProjector` in `db/projections/run_state.py`: handles `RunStatusChanged`,
  `TaskStatusChanged`, `StepCompleted`, `StepSkipped`, `RunStepBackward`, `GradesEvaluated`,
  `AutoVerifyCompleted`, `ChecklistGateEvaluated`, `HealthCheckEvent`. Placeholder cases for
  `RunCreated` and `TaskCreated` (to be filled in Step 03 when those event types are added).
- `TaskStateProjector` in `db/projections/task_state.py`: handles `TaskStatusChanged`,
  `ClarificationRequested`, `ClarificationResponded`, `ApprovalRequested`, `ApprovalDecision`,
  `TaskReverted`, `FanOutSpawned`, `ChildSpawned`, `ChildCompleted`, `ChildFailed`,
  `FanOutCompleted`.
- `ProjectionRegistry` registered as a post-append listener on `SqliteEventStore` in
  `api/deps.py` (called synchronously after every append, same session).
- `orchestrator db rebuild-projections` CLI command that: checks for a server lock file (refuses
  if server appears to be running), replays all events from `SqliteEventStore.get_all()` through
  all registered projectors, resets checkpoints to 0 before replaying.

**Final Verification Criteria**:
- `uv run pytest tests/unit/test_projectors.py tests/unit/test_projection_rebuild.py -v` — all pass.
- `uv run pytest tests/integration/test_projection_recovery.py -v` — passes.
- `uv run pytest` — full suite passes with no regressions.
- `uv run pyright src/orchestrator/db/projections/ src/orchestrator/cli/db.py` — no type errors.
- `orchestrator db rebuild-projections --db <path>` against a test DB with pre-loaded events
  populates read-model tables correctly.

---

## Task 2.1: ProjectionCheckpointModel ORM Model and Alembic Migration

**Description**: Add the `ProjectionCheckpointModel` SQLAlchemy model to `orm/models.py` and
create an Alembic migration that creates the `projection_checkpoints` table. This is the schema
foundation that stores per-projector progress and must exist before projectors can track their
last-processed position.

**Implementation Plan (Do These Steps)**

- [ ] Extend `src/orchestrator/db/orm/models.py` — add `ProjectionCheckpointModel` after
  `EventModel`:

```python
class ProjectionCheckpointModel(Base):
    __tablename__ = "projection_checkpoints"

    projector_name: Mapped[str] = mapped_column(String, primary_key=True)
    last_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)  # ISO 8601
```

- [ ] Create a new Alembic migration file in `src/orchestrator/db/migrations/versions/` named
  `u2a3b4c5d6e7_add_projection_checkpoints_table.py`. The `upgrade()` creates the
  `projection_checkpoints` table; `downgrade()` drops it. Follow the naming convention of
  existing migrations in that directory.

- [ ] Export `ProjectionCheckpointModel` from `src/orchestrator/db/__init__.py` alongside the
  existing model exports.

**Dependencies**
- [ ] Task 1.1 must be complete (Alembic migration infrastructure is in place).

**Constraints**
- [ ] Do not modify any existing migration files.
- [ ] Do not alter `EventV2Model`, `RunModel`, or any other existing ORM class.

**Functionality (Expected Outcomes)**
- [ ] `ProjectionCheckpointModel` is importable from `orchestrator.db`.
- [ ] Running `uv run alembic upgrade head` on a fresh DB creates the `projection_checkpoints`
  table with `projector_name` as the primary key.
- [ ] `uv run alembic downgrade -1` drops `projection_checkpoints` cleanly.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `uv run pyright src/orchestrator/db/orm/models.py` — no type errors on the new model.
- [ ] `uv run python -c "from orchestrator.db import ProjectionCheckpointModel; print(ProjectionCheckpointModel.__tablename__)"` — prints `projection_checkpoints`.
- [ ] `uv run alembic upgrade head` completes without error.

---

## Task 2.2: Projector Protocol and ProjectionRegistry

**Description**: Define the `Projector` protocol and implement `ProjectionRegistry` in
`src/orchestrator/db/projections/`. The registry registers projectors, dispatches events to the
subset of projectors that declare the event type in `handled_events`, and coordinates full
projection rebuilds. It also updates the `projection_checkpoints` table after each dispatch.

**Implementation Plan (Do These Steps)**

- [ ] Create `src/orchestrator/db/projections/__init__.py` exporting `Projector`,
  `ProjectionRegistry`.

- [ ] Create `src/orchestrator/db/projections/registry.py`:

```python
"""Projector protocol and registry for event-driven read-model maintenance."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.orm.models import ProjectionCheckpointModel
from orchestrator.time_utils import format_utc_datetime

if TYPE_CHECKING:
    from orchestrator.workflow.events.types import WorkflowEvent

logger = logging.getLogger(__name__)


@runtime_checkable
class Projector(Protocol):
    """Protocol for event-driven read-model projectors."""

    handled_events: frozenset[type]

    async def handle(self, event: WorkflowEvent, session: AsyncSession) -> None:
        """Apply a single event to the read model."""
        ...

    async def rebuild(
        self, events: Sequence[WorkflowEvent], session: AsyncSession
    ) -> None:
        """Replay a full event stream to rebuild the read model from scratch."""
        ...


class ProjectionRegistry:
    """Registers projectors and coordinates event dispatch and rebuild.

    Registered as a post-append listener on SqliteEventStore so projectors
    run synchronously after every append within the same session.
    """

    def __init__(self) -> None:
        self._projectors: list[Projector] = []

    def register(self, projector: Projector) -> None:
        self._projectors.append(projector)

    async def __call__(
        self,
        stored_events: list,     # list[StoredEvent] from event_store_v2
        session: AsyncSession,
        workflow_events: list[WorkflowEvent],
    ) -> None:
        """Dispatch a batch of appended events to all registered projectors.

        Projector exceptions propagate and abort the append transaction,
        maintaining the consistency guarantee that the event log and read-model
        tables are always in sync. A projector bug must not allow events to be
        committed without a corresponding read-model update.
        """
        handled_by: dict[str, int] = {}  # projector name → count of events handled

        for event in workflow_events:
            for projector in self._projectors:
                if type(event) in projector.handled_events:
                    # Let exceptions propagate — they abort the transaction
                    await projector.handle(event, session)
                    name = type(projector).__name__
                    handled_by[name] = handled_by.get(name, 0) + 1

        # Only advance checkpoint for projectors that handled at least one event
        if stored_events and handled_by:
            last_position = stored_events[-1].position
            now = format_utc_datetime(datetime.now(timezone.utc))
            for projector in self._projectors:
                name = type(projector).__name__
                if name not in handled_by:
                    continue
                existing = await session.get(ProjectionCheckpointModel, name)
                if existing is None:
                    session.add(ProjectionCheckpointModel(
                        projector_name=name,
                        last_position=last_position,
                        updated_at=now,
                    ))
                else:
                    existing.last_position = last_position
                    existing.updated_at = now

    async def rebuild_all(
        self,
        all_events: Sequence[WorkflowEvent],
        session: AsyncSession,
    ) -> None:
        """Replay the full event stream through all projectors.

        Resets all checkpoints to 0 before replaying. Requires server stop
        (no live-event coordination needed for this single-instance deployment).
        """
        for projector in self._projectors:
            name = type(projector).__name__
            existing = await session.get(ProjectionCheckpointModel, name)
            if existing is not None:
                existing.last_position = 0
                existing.updated_at = format_utc_datetime(datetime.now(timezone.utc))
            await projector.rebuild(all_events, session)
```

Note: The `__call__` signature includes `workflow_events` because the listener must receive both
the `StoredEvent` list (for position tracking) and the deserialized `WorkflowEvent` objects (for
dispatch). Update `SqliteEventStore.add_listener` in `event_store_v2.py` accordingly in Task 2.4.

**Dependencies**
- [ ] Task 2.1 must be complete (`ProjectionCheckpointModel` must exist).
- [ ] Task 1.2 must be complete (`SqliteEventStore` must exist).

**Constraints**
- [ ] Unknown event types (not in any projector's `handled_events`) are silently skipped — no
  error or log noise for normal operation.
- [ ] Projector failures during dispatch propagate and abort the append transaction. This is
  intentional: the event log and read-model tables must remain in sync. Do not catch projector
  exceptions in the registry's `__call__` method.
- [ ] Per-projector checkpoints advance only after that projector successfully handles at least one
  event in the batch. Do not advance checkpoints for projectors whose `handled_events` set does not
  include any event type in the current batch.
- [ ] Do not import concrete projector classes into `registry.py` — projectors are registered at
  wire-up time in `deps.py`.

**Functionality (Expected Outcomes)**
- [ ] `ProjectionRegistry.register(projector)` accepts any `Projector` implementor.
- [ ] `registry.__call__(stored_events, session, workflow_events)` dispatches each event only to
  projectors whose `handled_events` includes that event type; projector exceptions propagate.
- [ ] After dispatch, `projection_checkpoints` rows are upserted only for projectors that handled
  at least one event in the batch; projectors that handled no events in this batch are skipped.
- [ ] `rebuild_all(all_events, session)` resets checkpoints to 0 and calls each projector's
  `rebuild` with the full event list.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `uv run pyright src/orchestrator/db/projections/registry.py` — no type errors.
- [ ] `from orchestrator.db.projections import Projector, ProjectionRegistry` imports without error.
- [ ] Unit tests in Task 2.5 for registry dispatch and rebuild pass.

---

## Task 2.3: RunStateProjector and TaskStateProjector

**Description**: Implement the two concrete projectors. `RunStateProjector` handles run-lifecycle
events to update the `runs`, `steps`, and related tables. `TaskStateProjector` handles
task-lifecycle events to update the `tasks` and `attempts` tables. Both projectors only handle
events they declare; unknown events are no-ops. Placeholder cases for `RunCreated` and
`TaskCreated` (event types added in Step 03) log a debug message and return without error.

**Implementation Plan (Do These Steps)**

- [ ] Create `src/orchestrator/db/projections/run_state.py`:

```python
"""RunStateProjector: maintains runs, steps read-model tables from events."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.orm.models import RunModel, StepModel
from orchestrator.workflow.events.types import (
    AutoVerifyCompleted,
    ChecklistGateEvaluated,
    GradesEvaluated,
    HealthCheckEvent,
    RunStatusChanged,
    RunStepBackward,
    StepCompleted,
    StepSkipped,
    TaskStatusChanged,
    WorkflowEvent,
)

logger = logging.getLogger(__name__)


class RunStateProjector:
    """Maintains runs and steps tables from run-lifecycle events."""

    handled_events: frozenset[type] = frozenset({
        RunStatusChanged,
        TaskStatusChanged,
        StepCompleted,
        StepSkipped,
        RunStepBackward,
        GradesEvaluated,
        AutoVerifyCompleted,
        ChecklistGateEvaluated,
        HealthCheckEvent,
    })

    async def handle(self, event: WorkflowEvent, session: AsyncSession) -> None:
        match event:
            case RunStatusChanged():
                await session.execute(
                    update(RunModel)
                    .where(RunModel.id == event.run_id)
                    .values(
                        status=event.new_status.value,
                        pause_reason=event.pause_reason,
                        last_error=event.last_error,
                    )
                )
            case StepCompleted():
                await session.execute(
                    update(StepModel)
                    .where(StepModel.id == event.step_id)
                    .values(completed=True)
                )
                await session.execute(
                    update(RunModel)
                    .where(RunModel.id == event.run_id)
                    .values(current_step_index=event.step_index + 1)
                )
            case StepSkipped():
                await session.execute(
                    update(StepModel)
                    .where(StepModel.id == event.step_id)
                    .values(skipped=True, skip_reason=event.skip_reason)
                )
            case RunStepBackward():
                await session.execute(
                    update(RunModel)
                    .where(RunModel.id == event.run_id)
                    .values(current_step_index=event.to_step_index)
                )
            case _:
                pass  # GradesEvaluated, AutoVerifyCompleted, ChecklistGateEvaluated,
                      # HealthCheckEvent, TaskStatusChanged — no run-table mutation needed here

    async def rebuild(
        self, events: Sequence[WorkflowEvent], session: AsyncSession
    ) -> None:
        for event in events:
            if type(event) in self.handled_events:
                await self.handle(event, session)
```

- [ ] Create `src/orchestrator/db/projections/task_state.py`:

```python
"""TaskStateProjector: maintains tasks, attempts read-model tables from events."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.orm.models import TaskModel
from orchestrator.workflow.events.types import (
    ApprovalDecision,
    ApprovalRequested,
    ClarificationRequested,
    ClarificationResponded,
    ChildCompleted,
    ChildFailed,
    ChildSpawned,
    FanOutCompleted,
    FanOutSpawned,
    TaskReverted,
    TaskStatusChanged,
    WorkflowEvent,
)

logger = logging.getLogger(__name__)


class TaskStateProjector:
    """Maintains tasks and attempts tables from task-lifecycle events."""

    handled_events: frozenset[type] = frozenset({
        TaskStatusChanged,
        ClarificationRequested,
        ClarificationResponded,
        ApprovalRequested,
        ApprovalDecision,
        TaskReverted,
        FanOutSpawned,
        ChildSpawned,
        ChildCompleted,
        ChildFailed,
        FanOutCompleted,
    })

    async def handle(self, event: WorkflowEvent, session: AsyncSession) -> None:
        match event:
            case TaskStatusChanged():
                await session.execute(
                    update(TaskModel)
                    .where(TaskModel.id == event.task_id)
                    .values(status=event.new_status.value)
                )
            case ClarificationRequested():
                await session.execute(
                    update(TaskModel)
                    .where(TaskModel.id == event.task_id)
                    .values(
                        pending_action_type="clarification",
                        pending_clarification_id=event.clarification_id,
                    )
                )
            case ClarificationResponded():
                await session.execute(
                    update(TaskModel)
                    .where(TaskModel.id == event.task_id)
                    .values(
                        pending_action_type=None,
                        pending_clarification_id=None,
                    )
                )
            case ApprovalRequested():
                await session.execute(
                    update(TaskModel)
                    .where(TaskModel.id == event.task_id)
                    .values(pending_action_type="approval")
                )
            case ApprovalDecision():
                await session.execute(
                    update(TaskModel)
                    .where(TaskModel.id == event.task_id)
                    .values(pending_action_type=None)
                )
            case _:
                pass  # TaskReverted, FanOut*, Child* — complex mutations handled by
                      # RunRepository until Step 03 command refactor

    async def rebuild(
        self, events: Sequence[WorkflowEvent], session: AsyncSession
    ) -> None:
        for event in events:
            if type(event) in self.handled_events:
                await self.handle(event, session)
```

- [ ] Update `src/orchestrator/db/projections/__init__.py` to export `RunStateProjector` and
  `TaskStateProjector` alongside `Projector` and `ProjectionRegistry`.

**Dependencies**
- [ ] Task 2.2 must be complete (`Projector` protocol and `ProjectionRegistry` must exist).
- [ ] Step 00 must be complete (event types must be Pydantic models with `model_dump_json()`).

**Constraints**
- [ ] Projectors must not import from `api/` or `workflow/service.py` — only from
  `workflow/events/types.py` and `db/orm/models.py`.
- [ ] Do not raise exceptions from `handle()` for unrecognised events — use `case _: pass`.
- [ ] The `handled_events` attribute must be a `frozenset[type]` (not a list) so membership
  tests in `ProjectionRegistry` are O(1).
- [ ] `rebuild()` must not clear existing table rows — the CLI command (Task 2.4) is responsible
  for clearing rows before calling `rebuild_all()`. The projector simply replays mutations.

**Functionality (Expected Outcomes)**
- [ ] `RunStateProjector.handle(RunStatusChanged(new_status=ACTIVE, ...), session)` updates
  `RunModel.status` to `"active"` for the given `run_id`.
- [ ] `TaskStateProjector.handle(ClarificationRequested(...), session)` sets
  `TaskModel.pending_action_type = "clarification"` for the given `task_id`.
- [ ] Events not in `handled_events` are ignored without error.
- [ ] `rebuild(events, session)` iterates the full event sequence and applies each handled event.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `uv run pyright src/orchestrator/db/projections/run_state.py src/orchestrator/db/projections/task_state.py` — no type errors.
- [ ] `from orchestrator.db.projections import RunStateProjector, TaskStateProjector` imports without error.
- [ ] Unit tests in Task 2.5 for `test_projectors.py` pass.

---

## Task 2.4: Wire Registry into PersistentEventEmitter and Add rebuild-projections CLI

**Description**: Update `api/deps.py` so `ProjectionRegistry` (with both projectors registered)
is added as a post-append listener on `SqliteEventStore`. Then extend `cli/db.py` with the
`rebuild-projections` command that replays all events from `SqliteEventStore.get_all()` through
`ProjectionRegistry.rebuild_all()`.

**Implementation Plan (Do These Steps)**

- [ ] Update `src/orchestrator/db/access/event_store_v2.py`: the `add_listener` method currently
  accepts a single callable. Update it to support a second optional argument so projections can
  receive both the `StoredEvent` list and the original `WorkflowEvent` list. The simplest
  approach: store a second list `_event_listeners` that receive
  `(stored_events, session, workflow_events)`. Keep the existing `_listeners` list for observers
  like `JsonlOutboxObserver` that only need `StoredEvent` objects.

  ```python
  def add_projection_listener(self, listener) -> None:
      """Register a listener that receives (stored_events, session, workflow_events)."""
      self._projection_listeners.append(listener)
  ```

  Call `projection_listeners` after `_listeners` in `append()`, passing the session and the
  original `WorkflowEvent` list alongside the stored events.

- [ ] In `src/orchestrator/api/deps.py`:
  - Import `ProjectionRegistry`, `RunStateProjector`, `TaskStateProjector` from
    `orchestrator.db.projections`.
  - In `get_event_store_v2`, create a `ProjectionRegistry`, register both projectors, and call
    `store.add_projection_listener(registry)`.
  - The registry callable signature is `(stored_events, session, workflow_events)` — pass the
    same `session` that `SqliteEventStore` already holds.

- [ ] In `src/orchestrator/cli/db.py`:

```python
@db.command("rebuild-projections")
@click.option(
    "--db",
    "db_path_override",
    type=click.Path(path_type=Path),
    default=None,
    help="Database path (default: from context)",
)
@click.pass_context
def rebuild_projections_cmd(ctx: click.Context, db_path_override: Path | None) -> None:
    """Rebuild all projections from the event log. Requires server stop."""

    async def _rebuild() -> None:
        from orchestrator.db import ProjectionCheckpointModel
        from orchestrator.db.access.connection import get_session_factory
        from orchestrator.db.access.event_store_v2 import SqliteEventStore
        from orchestrator.db.projections import ProjectionRegistry, RunStateProjector, TaskStateProjector

        db_path = db_path_override or Path(ctx.obj["db"])

        # Warn if server appears to be running (lock file heuristic)
        lock_file = db_path.parent / ".orchestrator" / "server.lock"
        if lock_file.exists():
            click.echo(
                "Warning: server lock file found. Stop the server before rebuilding projections.",
                err=True,
            )
            raise SystemExit(1)

        async with get_session_factory(str(db_path))() as session:
            store = SqliteEventStore(session)
            stored_events = await store.get_all(after_position=0)

            # Deserialize stored events back to WorkflowEvent objects
            from orchestrator.workflow.events.types import WorkflowEvent
            workflow_events = _deserialize_events(stored_events)

            registry = ProjectionRegistry()
            registry.register(RunStateProjector())
            registry.register(TaskStateProjector())

            # Clear projection-owned tables before replay so stale rows don't survive.
            # Resetting checkpoints alone is insufficient if the store uses insert-only logic.
            from sqlalchemy import delete
            from orchestrator.db.orm.models import RunModel, TaskModel, StepModel, ProjectionCheckpointModel
            click.echo("Clearing projection-owned tables...")
            await session.execute(delete(ProjectionCheckpointModel))
            # RunModel and TaskModel rows are rebuilt from RunCreated/TaskCreated events.
            # Clear them only if RunCreated/TaskCreated events are present (Step 03 adds them).
            # Unconditionally clear for a correct rebuild; accept API downtime during this operation.
            await session.execute(delete(TaskModel))
            await session.execute(delete(RunModel))
            await session.flush()

            click.echo(f"Replaying {len(workflow_events)} events through {len(registry._projectors)} projectors...")
            await registry.rebuild_all(workflow_events, session)
            await session.commit()

        click.echo("Projection rebuild complete.")

    asyncio.run(_rebuild())


def _deserialize_events(stored_events):
    """Deserialize StoredEvent payloads back to WorkflowEvent objects."""
    import json
    from orchestrator.workflow.events import deserialize_event
    result = []
    for se in stored_events:
        try:
            result.append(deserialize_event(se.event_type, se.payload))
        except Exception:
            pass  # unknown or future event type — skip
    return result
```

  Note: `deserialize_event` is a helper to be added to `src/orchestrator/workflow/events/__init__.py`
  that dispatches on `event_type` string and calls `.model_validate_json()` on the correct
  Pydantic class. If it doesn't exist yet, add it there: a dict mapping `event_type` string →
  `WorkflowEvent` subclass, with a fallback that skips unknown types.

**Dependencies**
- [ ] Tasks 2.1–2.3 must be complete.
- [ ] Task 1.4 must be complete (`SqliteEventStore` wired in `deps.py`).

**Constraints**
- [ ] Do not remove existing `get_event_store` or legacy `EventStore` wiring from `deps.py`.
- [ ] The `rebuild-projections` command must fail loudly (exit 1) if the server lock file exists.
- [ ] `rebuild_all` must reset checkpoints to 0 before replaying — this is already in
  `ProjectionRegistry.rebuild_all()` from Task 2.2.

**Functionality (Expected Outcomes)**
- [ ] After wiring, every `SqliteEventStore.append()` call dispatches events to both projectors
  synchronously before returning.
- [ ] `orchestrator db rebuild-projections` reads all events from `events_v2` and replays them
  through both projectors, updating `runs` and `tasks` table state.
- [ ] Running rebuild twice produces the same read-model state (idempotent, since projectors
  apply absolute state — e.g. `status = new_status.value` — not deltas).

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `uv run pyright src/orchestrator/api/deps.py src/orchestrator/cli/db.py` — no type errors.
- [ ] `uv run pytest` — full suite passes (no regressions from wiring change).
- [ ] Manual test: `orchestrator db rebuild-projections` against a DB with at least one
  `RunStatusChanged` event in `events_v2` sets `RunModel.status` to the correct value.

---

## Task 2.5: Unit Tests and Integration Test

**Description**: Write focused unit tests for the projectors and rebuild flow, and an integration
test that verifies the full lifecycle: emit events → clear projections → rebuild → assert API
returns correct state.

**Implementation Plan (Do These Steps)**

- [ ] Create `tests/unit/test_projectors.py`:
  - Helper fixture: `async_session` — in-memory SQLite with all tables created via
    `Base.metadata.create_all` (include `RunModel`, `TaskModel`, `StepModel`,
    `ProjectionCheckpointModel`). Pre-populate a `RunModel` and `TaskModel` row so projector
    `update` statements have rows to act on.
  - `test_run_status_changed_updates_run_model` — create a `RunModel(id="r1", status="queued")`,
    call `RunStateProjector().handle(RunStatusChanged(run_id="r1", new_status=ACTIVE, ...), session)`,
    assert `RunModel.status == "active"`.
  - `test_step_completed_marks_step_and_advances_run` — assert `StepModel.completed == True`
    and `RunModel.current_step_index` incremented after `StepCompleted`.
  - `test_step_skipped_sets_skip_fields` — assert `StepModel.skipped == True` and
    `skip_reason` set after `StepSkipped`.
  - `test_task_status_changed_updates_task_model` — assert `TaskModel.status` updated after
    `TaskStatusChanged`.
  - `test_clarification_requested_sets_pending` — assert `pending_action_type == "clarification"`
    and `pending_clarification_id` set after `ClarificationRequested`.
  - `test_clarification_responded_clears_pending` — assert `pending_action_type == None` after
    `ClarificationResponded`.
  - `test_unknown_event_type_is_silently_skipped` — assert neither projector raises when given
    an event type not in `handled_events`.

- [ ] Create `tests/unit/test_projection_rebuild.py`:
  - Helper: `make_event_store(session)` — creates `SqliteEventStore` with an in-memory session,
    appends a sequence of events (`RunStatusChanged` × 3 with different statuses).
  - `test_rebuild_all_restores_run_status` — append events, manually corrupt `RunModel.status`
    to `"draft"`, call `registry.rebuild_all(events, session)`, assert status matches the last
    `RunStatusChanged.new_status`.
  - `test_rebuild_resets_checkpoint_to_zero` — append events (checkpoints advance), call
    `rebuild_all`, assert `ProjectionCheckpointModel.last_position == 0` before rebuild starts.
  - `test_registry_dispatch_updates_checkpoint` — append one event via the listener call path;
    assert a `ProjectionCheckpointModel` row exists with `last_position > 0`.
  - `test_registry_skips_projectors_that_dont_handle_event` — register a projector with an
    empty `handled_events` set; assert its `handle()` is never called (use a spy/subclass).

- [ ] Create `tests/integration/test_projection_recovery.py`:
  - `test_full_lifecycle_rebuild` — end-to-end:
    1. Use the test client to create a run (via `POST /api/runs`) and update its status.
    2. Directly zero out `RunModel.status` in the DB (bypassing the API) to simulate corruption.
    3. Call `ProjectionRegistry.rebuild_all(await store.get_all(), session)`.
    4. Assert `GET /api/runs/{run_id}` returns the correct status.
  - `test_rebuild_is_idempotent` — run rebuild twice; assert the final read-model state is
    identical after both runs.

- [ ] All tests: use `pytest-asyncio` in `asyncio` mode (consistent with existing test setup).

**Dependencies**
- [ ] Tasks 2.1–2.4 must be complete.
- [ ] Existing test fixtures in `tests/conftest.py` for the integration test client.

**References**
- Existing unit tests in `tests/unit/` for fixture patterns.
- `tests/integration/` for client setup patterns.

**Constraints**
- [ ] No mocking of SQLAlchemy or SQLite — use real `aiosqlite` in-memory sessions for unit tests.
- [ ] Integration test uses the existing test database setup (not production DB).
- [ ] Tests must be runnable in isolation with `uv run pytest tests/unit/test_projectors.py -v`.

**Functionality (Expected Outcomes)**
- [ ] All unit tests pass with real in-memory SQLite sessions.
- [ ] Integration test confirms that rebuild restores API-visible state after corruption.
- [ ] No test asserts stub or error-stub behavior as success.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `uv run pytest tests/unit/test_projectors.py tests/unit/test_projection_rebuild.py -v` — all pass, none skipped.
- [ ] `uv run pytest tests/integration/test_projection_recovery.py -v` — passes.
- [ ] `uv run pytest tests/unit/test_projectors.py --collect-only` — shows at least 7 test items.
- [ ] `uv run pytest tests/unit/test_projection_rebuild.py --collect-only` — shows at least 4 test items.
- [ ] `uv run pytest` — full suite passes (no regressions).
