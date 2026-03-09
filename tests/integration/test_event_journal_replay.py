"""Integration tests for JSONL event journaling and replay."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config.enums import RoutineSource, RunStatus, TaskStatus
from orchestrator.db.connection import init_db
from orchestrator.db.event_journal import resolve_default_journal_path
from orchestrator.db.journal_replay import replay_journal_to_repository
from orchestrator.db.repositories import RunRepository

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def file_db_client(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncClient, Path, FastAPI], None]:
    db_path = tmp_path / "orchestrator.db"
    app = create_app(
        db_path=str(db_path),
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
        spawn_agents=False,
    )
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, db_path, app
    await app.state.engine.dispose()


async def test_event_journal_written_and_replay_restores_run_state(
    file_db_client: tuple[AsyncClient, Path, FastAPI],
) -> None:
    client, db_path, app = file_db_client

    create_resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    assert create_resp.status_code == 201
    run = create_resp.json()
    run_id = run["id"]
    task_id = run["steps"][0]["tasks"][0]["id"]

    start_resp = await client.post(f"/api/runs/{run_id}/start")
    assert start_resp.status_code == 200
    task_start_resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert task_start_resp.status_code == 200

    journal_path = resolve_default_journal_path(db_path)
    assert journal_path is not None
    assert journal_path.exists()

    # Corrupt state to simulate stale backup snapshot before replay.
    async with app.state.session_factory() as session:
        repo = RunRepository(session)
        stale_run = await repo.get(run_id)
        stale_run.status = RunStatus.DRAFT
        stale_run.started_at = None
        stale_task = stale_run.steps[0].tasks[0]
        stale_task.status = TaskStatus.PENDING
        stale_task.current_attempt = 0
        stale_task.attempts = []
        await repo.save(stale_run)
        await session.commit()

    # Replay journal to roll state forward.
    async with app.state.session_factory() as session:
        repo = RunRepository(session)
        summary = await replay_journal_to_repository(
            repo,
            journal_path=journal_path,
            run_ids={run_id},
        )
        await session.commit()
        assert summary.replayed_events >= 2
        assert summary.updated_runs == 1
        assert summary.missing_runs == 0

    run_resp = await client.get(f"/api/runs/{run_id}")
    assert run_resp.status_code == 200
    restored = run_resp.json()
    assert restored["status"] == "active"
    restored_task = restored["steps"][0]["tasks"][0]
    assert restored_task["status"] == "building"
    assert restored_task["current_attempt"] == 1
