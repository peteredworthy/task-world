"""Integration tests for agent log capture and storage."""

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.app import create_app
from orchestrator.config import AgentRunnerType, Priority, RoutineSource, RunStatus, TaskStatus
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.db import RunRepository
from orchestrator.db import SqliteEventStore
from orchestrator.db import StoredEvent
from orchestrator.db.access.mutations import save_run
from orchestrator.state.models import (
    Attempt,
    ChecklistItem,
    Run,
    StepState,
    TaskState,
)
from orchestrator.workflow import AgentErrorEvent, AgentOutputEvent, InMemorySignalTransport
from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def repo(session: AsyncSession) -> RunRepository:
    return RunRepository(session)


@pytest.fixture
def event_store(session: AsyncSession) -> SqliteEventStore:
    return SqliteEventStore(session)


@pytest.fixture
async def client_and_drain() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    signal_transport = InMemorySignalTransport()
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    app.state.signal_transport = signal_transport
    await init_db(app.state.engine)
    drain = make_drain_fn(app, signal_transport)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, drain
    await app.state.engine.dispose()


def _payload(event: StoredEvent) -> dict[str, Any]:
    payload = json.loads(event.payload)
    assert isinstance(payload, dict)
    return payload


@pytest.fixture
async def client(client_and_drain: tuple[AsyncClient, DrainFn]) -> AsyncClient:
    return client_and_drain[0]


def _make_run_with_attempt(
    agent_output: str | None = None,
    error: str | None = None,
) -> Run:
    """Create a run with one task that has one attempt."""
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return Run(
        id="run-log-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.ACTIVE,
        routine_id="simple-routine",
        routine_source=RoutineSource.LOCAL,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id="task-1",
                        config_id="T-01",
                        title="Test Task",
                        status=TaskStatus.BUILDING,
                        checklist=[
                            ChecklistItem(
                                req_id="R1",
                                desc="Do something",
                                priority=Priority.CRITICAL,
                            )
                        ],
                        current_attempt=1,
                        attempts=[
                            Attempt(
                                id="att-1",
                                attempt_num=1,
                                started_at=now,
                                agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
                                agent_output=agent_output,
                                error=error,
                            )
                        ],
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
        started_at=now,
    )


async def test_attempt_output_roundtrip(repo: RunRepository, session: AsyncSession) -> None:
    """Agent output and error persist through save/load cycle."""
    run = _make_run_with_attempt(
        agent_output="line 1\nline 2\nline 3",
        error=None,
    )
    await save_run(repo.session, run)
    await session.commit()

    loaded = await repo.get("run-log-1")
    attempt = loaded.steps[0].tasks[0].attempts[0]
    assert attempt.agent_output == "line 1\nline 2\nline 3"
    assert attempt.error is None


async def test_attempt_error_roundtrip(repo: RunRepository, session: AsyncSession) -> None:
    """Error message persists through save/load cycle."""
    run = _make_run_with_attempt(
        agent_output="partial output",
        error="Agent stuck after 3 nudges, killed",
    )
    await save_run(repo.session, run)
    await session.commit()

    loaded = await repo.get("run-log-1")
    attempt = loaded.steps[0].tasks[0].attempts[0]
    assert attempt.agent_output == "partial output"
    assert attempt.error == "Agent stuck after 3 nudges, killed"


async def test_attempt_no_output_roundtrip(repo: RunRepository, session: AsyncSession) -> None:
    """Null output/error round-trips correctly."""
    run = _make_run_with_attempt(agent_output=None, error=None)
    await save_run(repo.session, run)
    await session.commit()

    loaded = await repo.get("run-log-1")
    attempt = loaded.steps[0].tasks[0].attempts[0]
    assert attempt.agent_output is None
    assert attempt.error is None


async def test_agent_output_event_stored(
    event_store: SqliteEventStore, session: AsyncSession
) -> None:
    """AgentOutputEvent can be stored and retrieved via events_v2."""
    # First create a run so the FK constraint is satisfied
    repo = RunRepository(session)
    run = _make_run_with_attempt()
    await save_run(repo.session, run)
    await session.flush()

    event = AgentOutputEvent(
        timestamp=datetime(2025, 1, 15, 10, 31, 0, tzinfo=timezone.utc),
        run_id="run-log-1",
        event_type="agent_output",
        task_id="task-1",
        attempt_num=1,
        lines=["building feature...", "running tests..."],
        line_offset=0,
    )
    await event_store.append(event)
    await session.commit()

    events = await event_store.get_stream("run-log-1")
    assert len(events) == 1
    assert events[0].event_type == "agent_output"
    payload = _payload(events[0])
    assert payload["lines"] == ["building feature...", "running tests..."]
    assert payload["line_offset"] == 0


async def test_agent_error_event_stored(
    event_store: SqliteEventStore, session: AsyncSession
) -> None:
    """AgentErrorEvent can be stored and retrieved via events_v2."""
    repo = RunRepository(session)
    run = _make_run_with_attempt()
    await save_run(repo.session, run)
    await session.flush()

    event = AgentErrorEvent(
        timestamp=datetime(2025, 1, 15, 10, 31, 0, tzinfo=timezone.utc),
        run_id="run-log-1",
        event_type="agent_error",
        task_id="task-1",
        attempt_num=1,
        error_type="AgentExecutionError",
        error_message="Agent stuck after 3 nudges, killed",
    )
    await event_store.append(event)
    await session.commit()

    events = await event_store.get_stream("run-log-1")
    assert len(events) == 1
    assert events[0].event_type == "agent_error"
    payload = _payload(events[0])
    assert payload["error_type"] == "AgentExecutionError"
    assert payload["error_message"] == "Agent stuck after 3 nudges, killed"


async def _setup_run_with_logs(client: AsyncClient, drain: DrainFn) -> tuple[str, str]:
    """Create a run, start it, start the task, and store some output."""
    # Create the run
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]
    task_id = resp.json()["steps"][0]["tasks"][0]["id"]

    # Start the run
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)

    # Start the task (creates attempt)
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert resp.status_code == 200

    return run_id, task_id


async def test_get_attempt_logs_endpoint(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    """GET .../attempts/{num}/logs returns stored output."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_run_with_logs(client, drain)

    # The attempt is created but has no output yet - should return empty
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/attempts/1/logs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == run_id
    assert data["task_id"] == task_id
    assert data["attempt_num"] == 1
    assert data["output"] is None
    assert data["error"] is None
    assert data["line_count"] == 0


async def test_get_attempt_logs_not_found(client_and_drain: tuple[AsyncClient, DrainFn]) -> None:
    """GET .../attempts/{num}/logs returns 404 for nonexistent attempt."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_run_with_logs(client, drain)

    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/attempts/999/logs")
    assert resp.status_code == 404


async def test_get_task_shows_has_output_and_error(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """GET task endpoint includes has_output and error fields in attempt."""
    client, drain = client_and_drain
    run_id, task_id = await _setup_run_with_logs(client, drain)

    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["attempts"]) == 1
    att = data["attempts"][0]
    assert "has_output" in att
    assert att["has_output"] is False  # No output stored yet
    assert "error" in att
    assert att["error"] is None
