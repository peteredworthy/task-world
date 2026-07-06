"""Executor-level coverage for stale-base worktree seed refusal.

Twice now, graph runs were seeded from a stale base commit and their fixes
needed manual ports plus repair commits (docs/dynamic-graph/
dynamic-graph-implementation-review.html P0 #2). These tests exercise the
full path: WorkflowService.create_run records `intended_seed_sha`, then
AgentRunnerExecutor._prepare_worktree_with_service classifies staleness
against the repo's current branch head before seeding a fresh worktree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select

from orchestrator.config import RequirementConfig, RoutineConfig, RunStatus, StepConfig, TaskConfig
from orchestrator.config.global_config import GlobalConfig, PathsConfig
from orchestrator.db import (
    EventV2Model,
    RunRepository,
    create_engine,
    create_session_factory,
    create_wired_event_store_v2,
    init_db,
)
from orchestrator.runners import AgentRunnerExecutor
from orchestrator.state import create_run_from_routine
from orchestrator.workflow import LocalAutoVerifyRunner, PersistentEventEmitter, WorkflowService


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(repo: Path) -> str:
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "tracked.txt").write_text("commit-a\n")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "commit A")
    return _git(repo, "rev-parse", "HEAD")


def _commit(repo: Path, content: str, message: str) -> str:
    (repo / "tracked.txt").write_text(content)
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _routine() -> RoutineConfig:
    return RoutineConfig(
        id="seed-staleness-routine",
        name="Seed Staleness Routine",
        steps=[
            StepConfig(
                id="S-01",
                title="Step 1",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task 1",
                        task_context="Do the work",
                        requirements=[RequirementConfig(id="R1", desc="Complete the work")],
                    )
                ],
            )
        ],
    )


@pytest.fixture
async def _harness(tmp_path: Path):
    """Real sqlite engine + WorkflowService + AgentRunnerExecutor wired to a
    real repos_dir/worktrees_dir pair, so worktree creation actually runs git."""
    repos_dir = tmp_path / "repos"
    worktrees_dir = tmp_path / "worktrees"
    worktrees_dir.mkdir(parents=True)
    repo_path = repos_dir / "seed-repo"
    commit_a = _init_repo(repo_path)

    global_config = GlobalConfig(
        paths=PathsConfig(repos_dir=str(repos_dir), worktrees_dir=str(worktrees_dir))
    )

    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        repo_db = RunRepository(session)
        event_store = create_wired_event_store_v2(session)
        service = WorkflowService(
            session=session,
            repo=repo_db,
            event_store_v2=event_store,
            event_emitter=PersistentEventEmitter(event_store),
            auto_verify_runner=LocalAutoVerifyRunner(),
            global_config=global_config,
        )
        executor = AgentRunnerExecutor(
            session_factory=session_factory,
            global_config=global_config,
            service_factory=lambda _session: service,
            spawn_agents=False,
        )
        yield session, service, executor, repo_path, repo_db, commit_a

    await engine.dispose()


async def _event_types(session, run_id: str) -> list[str]:
    result = await session.execute(
        select(EventV2Model.event_type)
        .where(EventV2Model.aggregate_id == run_id)
        .order_by(EventV2Model.position)
    )
    return list(result.scalars())


@pytest.mark.asyncio
async def test_refuses_stale_base_by_default(_harness) -> None:
    """Repo's current head is BEHIND intended_seed_sha: refuse, no worktree."""
    session, service, executor, repo_path, repo_db, commit_a = _harness

    # Branch advances to commit B *before* the run is created, so creation
    # resolves intended_seed_sha to B (the head visible at that moment).
    commit_b = _commit(repo_path, "commit-b\n", "commit B")
    run = create_run_from_routine(routine=_routine(), repo_name="seed-repo", source_branch="main")
    run = await service.create_run(run)
    assert run.intended_seed_sha == commit_b

    # Simulate a clone/mirror that lags behind what run creation saw: rewind
    # the branch back to commit A before the worktree is seeded.
    _git(repo_path, "reset", "--hard", commit_a)
    assert _git(repo_path, "rev-parse", "main") == commit_a

    prepared = await executor.prepare_worktree(run.id, service=service)
    assert prepared is False

    persisted = await repo_db.get(run.id)
    assert persisted.worktree_path is None
    assert persisted.status == RunStatus.PAUSED
    assert persisted.last_error is not None
    assert "stale_seed_base" in persisted.last_error
    assert commit_a in persisted.last_error
    assert commit_b in persisted.last_error

    events = await _event_types(session, run.id)
    assert "run_worktree_creation_requested" in events
    assert "run_worktree_creation_failed" in events


@pytest.mark.asyncio
async def test_allow_stale_base_override_proceeds(_harness) -> None:
    """allow_stale_base=true in run.config overrides the refusal."""
    session, service, executor, repo_path, repo_db, commit_a = _harness

    commit_b = _commit(repo_path, "commit-b\n", "commit B")
    run = create_run_from_routine(routine=_routine(), repo_name="seed-repo", source_branch="main")
    run.config = {"allow_stale_base": True}
    run = await service.create_run(run)
    assert run.intended_seed_sha == commit_b

    _git(repo_path, "reset", "--hard", commit_a)

    prepared = await executor.prepare_worktree(run.id, service=service)
    assert prepared is True

    persisted = await repo_db.get(run.id)
    assert persisted.worktree_path is not None
    assert Path(persisted.worktree_path).exists()


@pytest.mark.asyncio
async def test_advanced_branch_warns_and_proceeds(_harness) -> None:
    """intended_seed_sha is an ancestor of the current head: branch moved
    forward since run creation — proceed without refusal."""
    session, service, executor, repo_path, repo_db, commit_a = _harness

    run = create_run_from_routine(routine=_routine(), repo_name="seed-repo", source_branch="main")
    run = await service.create_run(run)
    assert run.intended_seed_sha == commit_a

    # Branch advances after run creation, before the worktree is seeded.
    _commit(repo_path, "commit-b\n", "commit B")

    prepared = await executor.prepare_worktree(run.id, service=service)
    assert prepared is True

    persisted = await repo_db.get(run.id)
    assert persisted.worktree_path is not None
    assert Path(persisted.worktree_path).exists()


@pytest.mark.asyncio
async def test_matching_sha_proceeds(_harness) -> None:
    """intended_seed_sha equals the current head: proceed silently."""
    session, service, executor, repo_path, repo_db, commit_a = _harness

    run = create_run_from_routine(routine=_routine(), repo_name="seed-repo", source_branch="main")
    run = await service.create_run(run)
    assert run.intended_seed_sha == commit_a

    prepared = await executor.prepare_worktree(run.id, service=service)
    assert prepared is True

    persisted = await repo_db.get(run.id)
    assert persisted.worktree_path is not None
