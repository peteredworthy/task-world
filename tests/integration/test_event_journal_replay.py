"""Integration tests for JSONL event journaling and replay."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource, RunStatus, TaskStatus
from orchestrator.db import init_db
from orchestrator.db import resolve_default_journal_path
from orchestrator.db import replay_journal_to_repository
from orchestrator.db import CheckpointRepository, RunRepository
from orchestrator.workflow import InMemorySignalTransport
from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def file_db_client(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncClient, Path, FastAPI, DrainFn], None]:
    db_path = tmp_path / "orchestrator.db"
    signal_transport = InMemorySignalTransport()
    app = create_app(
        db_path=str(db_path),
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
        spawn_agents=False,
    )
    app.state.signal_transport = signal_transport
    await init_db(app.state.engine)
    drain = make_drain_fn(app, signal_transport)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, db_path, app, drain
    await app.state.engine.dispose()


async def test_event_journal_written_and_replay_restores_run_state(
    file_db_client: tuple[AsyncClient, Path, FastAPI, DrainFn],
) -> None:
    client, db_path, app, drain = file_db_client

    create_resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    assert create_resp.status_code == 201
    run = create_resp.json()
    run_id = run["id"]
    task_id = run["steps"][0]["tasks"][0]["id"]

    start_resp = await client.post(f"/api/runs/{run_id}/start")
    assert start_resp.status_code == 202
    await drain(run_id)
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


async def _create_run_and_generate_events(
    client: AsyncClient,
    drain: DrainFn,
) -> tuple[str, str]:
    """Helper: create a run, start it, start the task. Returns (run_id, task_id)."""
    create_resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    assert create_resp.status_code == 201
    run = create_resp.json()
    run_id = run["id"]
    task_id = run["steps"][0]["tasks"][0]["id"]

    start_resp = await client.post(f"/api/runs/{run_id}/start")
    assert start_resp.status_code == 202
    await drain(run_id)
    task_start_resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert task_start_resp.status_code == 200
    return run_id, task_id


def _corrupt_run_state(run: "Run") -> None:
    """Reset a run to stale draft state (simulates restoring from old backup)."""
    run.status = RunStatus.DRAFT
    run.started_at = None
    stale_task = run.steps[0].tasks[0]
    stale_task.status = TaskStatus.PENDING
    stale_task.current_attempt = 0
    stale_task.attempts = []


# Import Run type for type hints
from orchestrator.state.models import Run  # noqa: E402


async def test_batch_replay_with_checkpoint(
    file_db_client: tuple[AsyncClient, Path, FastAPI, DrainFn],
) -> None:
    """Batch replay writes a checkpoint after each batch and restores state."""
    client, db_path, app, drain = file_db_client
    run_id, task_id = await _create_run_and_generate_events(client, drain)

    journal_path = resolve_default_journal_path(db_path)
    assert journal_path is not None

    # Corrupt state
    async with app.state.session_factory() as session:
        repo = RunRepository(session)
        stale_run = await repo.get(run_id)
        _corrupt_run_state(stale_run)
        await repo.save(stale_run)
        await session.commit()

    # Replay with batching and checkpoint (batch_size=1 to test multiple batches)
    async with app.state.session_factory() as session:
        repo = RunRepository(session)
        cp_repo = CheckpointRepository(session)
        summary = await replay_journal_to_repository(
            repo,
            journal_path=journal_path,
            run_ids={run_id},
            batch_size=1,
            from_checkpoint=True,
            checkpoint_repo=cp_repo,
        )
        # Session committed inside batched replay, no manual commit needed

    assert summary.replayed_events >= 2
    assert summary.updated_runs == 1
    assert summary.missing_runs == 0
    assert summary.checkpoint_sequence is not None
    assert summary.resumed_from_sequence is None  # first replay, no prior checkpoint

    # Verify state restored
    run_resp = await client.get(f"/api/runs/{run_id}")
    assert run_resp.status_code == 200
    restored = run_resp.json()
    assert restored["status"] == "active"
    assert restored["steps"][0]["tasks"][0]["status"] == "building"

    # Verify checkpoint was persisted
    async with app.state.session_factory() as session:
        cp_repo = CheckpointRepository(session)
        checkpoint = await cp_repo.get_checkpoint(str(journal_path))
        assert checkpoint is not None
        assert checkpoint.last_applied_sequence == summary.checkpoint_sequence


async def test_checkpoint_resume_skips_already_applied(
    file_db_client: tuple[AsyncClient, Path, FastAPI, DrainFn],
) -> None:
    """Second replay with from_checkpoint resumes from checkpoint and skips already-applied events."""
    client, db_path, app, drain = file_db_client
    run_id, task_id = await _create_run_and_generate_events(client, drain)

    journal_path = resolve_default_journal_path(db_path)
    assert journal_path is not None

    # Corrupt and replay once to establish checkpoint
    async with app.state.session_factory() as session:
        repo = RunRepository(session)
        stale_run = await repo.get(run_id)
        _corrupt_run_state(stale_run)
        await repo.save(stale_run)
        await session.commit()

    async with app.state.session_factory() as session:
        repo = RunRepository(session)
        cp_repo = CheckpointRepository(session)
        first_summary = await replay_journal_to_repository(
            repo,
            journal_path=journal_path,
            run_ids={run_id},
            batch_size=100,
            from_checkpoint=True,
            checkpoint_repo=cp_repo,
        )

    first_checkpoint_seq = first_summary.checkpoint_sequence
    assert first_checkpoint_seq is not None

    # Second replay with from_checkpoint: no new events, should skip everything
    async with app.state.session_factory() as session:
        repo = RunRepository(session)
        cp_repo = CheckpointRepository(session)
        second_summary = await replay_journal_to_repository(
            repo,
            journal_path=journal_path,
            run_ids={run_id},
            batch_size=100,
            from_checkpoint=True,
            checkpoint_repo=cp_repo,
        )

    assert second_summary.resumed_from_sequence == first_checkpoint_seq
    assert second_summary.replayed_events == 0
    assert second_summary.updated_runs == 0


async def test_checkpoint_not_written_on_dry_run(
    file_db_client: tuple[AsyncClient, Path, FastAPI, DrainFn],
) -> None:
    """Dry run with from_checkpoint should not persist checkpoint."""
    client, db_path, app, drain = file_db_client
    run_id, task_id = await _create_run_and_generate_events(client, drain)

    journal_path = resolve_default_journal_path(db_path)
    assert journal_path is not None

    async with app.state.session_factory() as session:
        repo = RunRepository(session)
        cp_repo = CheckpointRepository(session)
        summary = await replay_journal_to_repository(
            repo,
            journal_path=journal_path,
            run_ids={run_id},
            dry_run=True,
            from_checkpoint=True,
            checkpoint_repo=cp_repo,
        )
        await session.rollback()

    assert summary.replayed_events >= 2
    assert summary.checkpoint_sequence is None  # dry_run: no checkpoint written

    # No checkpoint should exist
    async with app.state.session_factory() as session:
        cp_repo = CheckpointRepository(session)
        checkpoint = await cp_repo.get_checkpoint(str(journal_path))
        assert checkpoint is None


async def test_summary_includes_checkpoint_fields(
    file_db_client: tuple[AsyncClient, Path, FastAPI, DrainFn],
) -> None:
    """JournalReplaySummary includes checkpoint_sequence and resumed_from_sequence."""
    client, db_path, app, drain = file_db_client
    run_id, task_id = await _create_run_and_generate_events(client, drain)

    journal_path = resolve_default_journal_path(db_path)
    assert journal_path is not None

    # Non-checkpoint replay: fields should be None
    async with app.state.session_factory() as session:
        repo = RunRepository(session)
        summary = await replay_journal_to_repository(
            repo,
            journal_path=journal_path,
            run_ids={run_id},
            dry_run=True,
        )

    assert summary.checkpoint_sequence is None
    assert summary.resumed_from_sequence is None


async def test_batch_replay_multiple_runs(
    file_db_client: tuple[AsyncClient, Path, FastAPI, DrainFn],
) -> None:
    """Batch replay handles events for multiple runs in same journal."""
    client, db_path, app, drain = file_db_client

    # Create two runs
    run_id_1, _ = await _create_run_and_generate_events(client, drain)
    run_id_2, _ = await _create_run_and_generate_events(client, drain)

    journal_path = resolve_default_journal_path(db_path)
    assert journal_path is not None

    # Corrupt both
    async with app.state.session_factory() as session:
        repo = RunRepository(session)
        for rid in [run_id_1, run_id_2]:
            stale = await repo.get(rid)
            _corrupt_run_state(stale)
            await repo.save(stale)
        await session.commit()

    # Replay with batching
    async with app.state.session_factory() as session:
        repo = RunRepository(session)
        cp_repo = CheckpointRepository(session)
        summary = await replay_journal_to_repository(
            repo,
            journal_path=journal_path,
            batch_size=2,
            from_checkpoint=True,
            checkpoint_repo=cp_repo,
        )

    assert summary.updated_runs == 2
    assert summary.replayed_events >= 4  # at least 2 events per run
    assert summary.checkpoint_sequence is not None

    # Verify both runs restored
    for rid in [run_id_1, run_id_2]:
        resp = await client.get(f"/api/runs/{rid}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"
