"""Unit tests for ProjectionRegistry dispatch and rebuild."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import RunStatus
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.db import ProjectionCheckpointModel, RunModel
from orchestrator.db import SqliteEventStore
from orchestrator.db import (
    ProjectionRegistry,
    RunLifecycleProjector,
    RunStateProjector,
    TaskStateProjector,
)
from orchestrator.workflow import RunStatusChanged, WorkflowEvent

NOW = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


def _make_run(run_id: str = "r1", status: str = "draft") -> RunModel:
    return RunModel(
        id=run_id,
        repo_name="proj-1",
        status=status,
        runner_config={},
        config={},
        created_at=NOW,
        updated_at=NOW,
    )


def _status_changed(run_id: str, new_status: RunStatus) -> RunStatusChanged:
    return RunStatusChanged(
        run_id=run_id,
        event_type="run_status_changed",
        old_status=RunStatus.DRAFT,
        new_status=new_status,
        timestamp=NOW,
    )


async def test_rebuild_all_restores_run_status(session: AsyncSession) -> None:
    """Corrupt the RunModel status, rebuild from events, assert status restored."""
    session.add(_make_run("r1", "draft"))
    await session.flush()

    events: list[WorkflowEvent] = [
        _status_changed("r1", RunStatus.ACTIVE),
        _status_changed("r1", RunStatus.PAUSED),
        _status_changed("r1", RunStatus.ACTIVE),
    ]

    registry = ProjectionRegistry()
    registry.register(RunStateProjector())

    # Corrupt the status
    await session.execute(text("UPDATE runs SET status = 'corrupted' WHERE id = 'r1'"))
    await session.flush()

    await registry.rebuild_all(events, session)
    await session.flush()

    result = await session.execute(text("SELECT status FROM runs WHERE id = 'r1'"))
    row = result.fetchone()
    assert row is not None
    assert row[0] == "active"


async def test_rebuild_all_restores_run_lifecycle_projector(session: AsyncSession) -> None:
    projector = RunLifecycleProjector()
    events: list[WorkflowEvent] = [
        _status_changed("active-run", RunStatus.ACTIVE),
        _status_changed("paused-run", RunStatus.PAUSED),
        _status_changed("done-run", RunStatus.COMPLETED),
    ]

    registry = ProjectionRegistry()
    registry.register(projector)

    await registry.rebuild_all(events, session)

    assert projector.is_active("active-run")
    assert projector.is_active("paused-run")
    assert projector.is_terminal("done-run")


async def test_rebuild_resets_checkpoint_to_zero(session: AsyncSession) -> None:
    """Checkpoints should be reset to 0 by rebuild_all before replay."""
    session.add(_make_run("r1", "draft"))
    await session.flush()

    # Manually add a checkpoint with last_position > 0
    from orchestrator.time_utils import format_utc_datetime

    session.add(
        ProjectionCheckpointModel(
            projector_name="RunStateProjector",
            last_position=99,
            updated_at=format_utc_datetime(NOW),
        )
    )
    await session.flush()

    events: list[WorkflowEvent] = [_status_changed("r1", RunStatus.ACTIVE)]

    registry = ProjectionRegistry()
    registry.register(RunStateProjector())

    await registry.rebuild_all(events, session)
    await session.flush()

    result = await session.execute(
        text(
            "SELECT last_position FROM projection_checkpoints WHERE projector_name = 'RunStateProjector'"
        )
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == 0


async def test_registry_dispatch_updates_checkpoint(session: AsyncSession) -> None:
    """After calling the registry as a listener, a checkpoint row should exist."""
    session.add(_make_run("r1", "draft"))
    await session.flush()

    store = SqliteEventStore(session)
    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    store.add_projection_listener(registry)

    event = _status_changed("r1", RunStatus.ACTIVE)
    stored_events = await store.append(event)
    await session.flush()  # flush pending checkpoint INSERT

    result = await session.execute(
        text(
            "SELECT last_position FROM projection_checkpoints WHERE projector_name = 'RunStateProjector'"
        )
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] > 0
    assert row[0] == stored_events[-1].position


async def test_registry_skips_projectors_that_dont_handle_event(session: AsyncSession) -> None:
    """A projector with empty handled_events should never have handle() called."""

    class _NeverCalledProjector:
        handled_events: frozenset[type] = frozenset()

        async def handle(self, event: WorkflowEvent, session: AsyncSession) -> None:
            raise AssertionError("handle() should never be called on this projector")

        async def rebuild(self, events: Sequence[WorkflowEvent], session: AsyncSession) -> None:
            pass

    registry = ProjectionRegistry()
    registry.register(_NeverCalledProjector())  # type: ignore[arg-type]

    session.add(_make_run("r1", "draft"))
    await session.flush()

    store = SqliteEventStore(session)
    store.add_projection_listener(registry)

    event = _status_changed("r1", RunStatus.ACTIVE)
    # This should NOT call _NeverCalledProjector.handle() since the event type
    # is not in its (empty) handled_events set
    await store.append(event)
    # If we reach here without AssertionError, the test passes


async def test_registry_dispatch_runs_multiple_projectors(session: AsyncSession) -> None:
    """Both RunStateProjector and TaskStateProjector are called for relevant events."""
    session.add(_make_run("r1", "draft"))
    await session.flush()

    store = SqliteEventStore(session)
    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    store.add_projection_listener(registry)

    event = _status_changed("r1", RunStatus.ACTIVE)
    await store.append(event)
    await session.flush()

    result = await session.execute(text("SELECT status FROM runs WHERE id = 'r1'"))
    row = result.fetchone()
    assert row is not None
    assert row[0] == "active"
