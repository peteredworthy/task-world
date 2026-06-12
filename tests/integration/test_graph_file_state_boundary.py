from __future__ import annotations

import subprocess
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.config.enums import AgentRunnerType
from orchestrator.config.models import RoutineConfig
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.git import restore
from orchestrator.graph import project_leases, project_node_states, project_residue_report
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxDispatcher,
    seed_run,
)
from orchestrator.runners import AgentRunner
from orchestrator.runners.types import (
    AgentMetadataCallback,
    AgentRunnerInfo,
    ChecklistUpdateCallback,
    EscalationCallback,
    ExecutionContext,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
    SubmitCallback,
)


class FixedClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now += timedelta(seconds=seconds)


class SequentialIds:
    def __init__(self) -> None:
        self._next = 1

    def next_id(self, prefix: str = "") -> str:
        value = f"{prefix}-{self._next}"
        self._next += 1
        return value


class AgentFactory:
    def __init__(self, agent: AgentRunner) -> None:
        self._agent = agent

    def create_runner(self, context: GraphDispatchContext) -> AgentRunner:
        return self._agent


class BoundaryFixtureAgent:
    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CLI_SUBPROCESS, name="fixture")

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        worktree = Path(context.working_dir)
        (worktree / "README.md").write_text("# changed\n")
        (worktree / "residue.txt").write_text("temporary residue\n")
        cache_dir = worktree / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "app.cpython-312.pyc").write_bytes(b"cache")
        (worktree / "ignored.log").write_text("ignored but captured\n")
        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


class SecretFixtureAgent:
    def __init__(self) -> None:
        self.submissions = 0

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CLI_SUBPROCESS, name="secret")

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        worktree = Path(context.working_dir)
        self.submissions += 1
        secret = worktree / "fake_key.pem"
        if self.submissions == 1:
            secret.write_bytes(bytes(range(128)))
        else:
            secret.unlink(missing_ok=True)
            (worktree / "README.md").write_text("# recovered\n")
            (worktree / "residue.txt").write_text("safe residue\n")
        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


class NestedIgnoredSecretAgent:
    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CLI_SUBPROCESS, name="nested")

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        worktree = Path(context.working_dir)
        secrets = worktree / "secrets"
        secrets.mkdir()
        (secrets / "cache.txt").write_text("harmless ignored residue\n")
        (secrets / "key.pem").write_bytes(bytes(range(128)))
        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


@pytest.fixture
async def file_db(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]], None]:
    engine = create_engine(tmp_path / "graph-file-state.db")
    await init_db(engine)
    yield engine, create_session_factory(engine)
    await engine.dispose()


@pytest.mark.asyncio
async def test_file_state_boundary_accepts_residue_and_snapshots_captured_tree(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-accepted"
    _init_repo(repo)
    run_id = "file-state-accepted"
    controller = await _seed_active_run(session_factory, run_id)
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory(BoundaryFixtureAgent()),
        worktree_path=repo,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, FixedClock())

    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)

    events = await _read_events(session_factory, run_id)
    accepted = next(event for event in events if event.event_type == "file_state_accepted")
    classifications = {
        entry["path"]: entry["classification"] for entry in accepted.payload["classifications"]
    }
    assert classifications["README.md"] == "tracked_change"
    assert classifications["residue.txt"] == "unknown_untracked"
    assert classifications["__pycache__/app.cpython-312.pyc"] == "tool_cache"
    assert classifications["ignored.log"] == "unknown_ignored"
    assert accepted.payload["git"]["ref"].startswith("refs/orchestrator/snapshots/")

    snapshot_id = str(accepted.payload["snapshot_id"])
    (repo / "README.md").unlink()
    (repo / "residue.txt").unlink()
    (repo / "__pycache__" / "app.cpython-312.pyc").unlink()
    (repo / "ignored.log").unlink()
    restore(repo, snapshot_id)
    assert (repo / "README.md").read_text() == "# changed\n"
    assert (repo / "residue.txt").read_text() == "temporary residue\n"
    assert (repo / "__pycache__" / "app.cpython-312.pyc").read_bytes() == b"cache"
    assert (repo / "ignored.log").read_text() == "ignored but captured\n"

    report = project_residue_report(events)
    assert report["residue.txt"][0]["classification"] == "unknown_untracked"
    assert report["ignored.log"][0]["classification"] == "unknown_ignored"


@pytest.mark.asyncio
async def test_secret_file_state_rejection_releases_lease_and_retries_clean_attempt(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-secret"
    _init_repo(repo)
    run_id = "file-state-secret"
    controller = await _seed_active_run(session_factory, run_id)
    agent = SecretFixtureAgent()
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory(agent),
        worktree_path=repo,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, FixedClock())

    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)

    events = await _read_events(session_factory, run_id)
    rejection = next(event for event in events if event.event_type == "file_state_rejected")
    rejected_paths = {
        entry["path"]: entry["classification"] for entry in rejection.payload["rejected_paths"]
    }
    assert rejected_paths == {"fake_key.pem": "secret"}
    assert not any(event.event_type == "file_state_accepted" for event in events)
    assert "fake_key.pem" not in _all_snapshot_tree_paths(repo)
    assert not any(
        event.event_type == "node_state_changed" and event.payload.get("new_state") == "completed"
        for event in events
    )
    assert project_node_states(events)["worker-step-1-task-1"] == "ready"
    assert not any(lease.get("state") == "active" for lease in project_leases(events).values())

    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)

    retried_events = await _read_events(session_factory, run_id)
    accepted = next(event for event in retried_events if event.event_type == "file_state_accepted")
    assert project_node_states(retried_events)["worker-step-1-task-1"] == "completed"
    assert not any(
        lease.get("state") == "active" for lease in project_leases(retried_events).values()
    )
    assert "fake_key.pem" not in _tree_paths(repo, str(accepted.payload["git"]["commit_sha"]))


@pytest.mark.asyncio
async def test_nested_secret_inside_ignored_directory_is_classified_and_not_snapshotted(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-nested-secret"
    _init_repo(repo)
    _append_gitignore_and_commit(repo, "secrets/")
    run_id = "file-state-nested-secret"
    controller = await _seed_active_run(session_factory, run_id)
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory(NestedIgnoredSecretAgent()),
        worktree_path=repo,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, FixedClock())

    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)

    events = await _read_events(session_factory, run_id)
    rejection = next(event for event in events if event.event_type == "file_state_rejected")
    classifications = {
        entry["path"]: entry["classification"] for entry in rejection.payload["classifications"]
    }
    rejected_paths = {
        entry["path"]: entry["classification"] for entry in rejection.payload["rejected_paths"]
    }
    assert classifications["secrets/cache.txt"] == "unknown_ignored"
    assert classifications["secrets/key.pem"] == "secret"
    assert rejected_paths == {"secrets/key.pem": "secret"}
    assert not any(event.event_type == "file_state_accepted" for event in events)
    assert "secrets/key.pem" not in _all_snapshot_tree_paths(repo)


def test_symlinked_dir_inside_ignored_dir_is_classified_and_escape_rejected(
    tmp_path: Path,
) -> None:
    """A repo-escaping symlinked directory inside an ignored dir must appear in
    the boundary evidence and reject the boundary — not silently vanish."""
    from orchestrator.graph import classify_file_state, default_file_state_policy
    from orchestrator.graph_runtime.file_state import collect_worktree_status

    repo = tmp_path / "repo-symlink-dir"
    _init_repo(repo)
    _append_gitignore_and_commit(repo, "scratch/")
    outside = tmp_path / "outside-target"
    outside.mkdir()
    (outside / "leak.txt").write_text("outside the worktree\n")
    scratch = repo / "scratch"
    scratch.mkdir()
    (scratch / "harmless.log").write_text("residue\n")
    (scratch / "escape").symlink_to(outside, target_is_directory=True)

    policy = default_file_state_policy()
    status = collect_worktree_status(repo, policy)
    ignored_paths = {entry.path for entry in status.ignored}
    assert "scratch/escape" in ignored_paths
    assert "scratch/harmless.log" in ignored_paths

    by_status_path = {entry.path: entry for entry in status.ignored}
    assert by_status_path["scratch/escape"].symlink_escape is True

    classification = classify_file_state(status, policy)
    by_path = {entry.path: entry for entry in classification.paths}
    assert by_path["scratch/escape"].rejected is True
    assert classification.verdict == "rejected"
    assert any(entry.path == "scratch/escape" for entry in classification.rejected_paths)


async def _seed_active_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> GraphController:
    clock = FixedClock()
    ids = SequentialIds()
    await seed_run(session_factory, _routine(), run_id=run_id, clock=clock, id_gen=ids)
    controller = GraphController(session_factory, clock, ids, auto_dispatch=False)
    position = await controller.current_position(run_id)
    accepted = await controller.handle_command(run_id, position, "accept_run")
    await controller.handle_command(run_id, accepted.projection_position, "start")
    return controller


async def _schedule_dispatch_and_wait(
    controller: GraphController,
    dispatcher: OutboxDispatcher,
    executor: GraphDispatchExecutor,
    run_id: str,
) -> None:
    await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {"lease_seconds": 60, "max_grants": 1},
    )
    await dispatcher.dispatch_pending()
    await executor.wait_for_all()


async def _read_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
):
    async with session_factory() as session:
        return await GraphEventStore(session).read_run(run_id)


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "graph-file-state",
            "name": "Graph File State",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Touch the repo",
                            "task_context": "Produce one implementation candidate.",
                            "requirements": [{"id": "req-1", "desc": "Requirement passes."}],
                        }
                    ],
                }
            ],
        }
    )


def _init_repo(path: Path) -> None:
    path.mkdir()
    (path / "README.md").write_text("# tmp repo\n")
    (path / ".gitignore").write_text("__pycache__/\nignored.log\n")
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "add", "README.md", ".gitignore"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "init",
        ],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


def _append_gitignore_and_commit(repo: Path, pattern: str) -> None:
    with (repo / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write(pattern + "\n")
    subprocess.run(
        ["git", "add", ".gitignore"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "ignore nested secrets",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _all_snapshot_tree_paths(repo: Path) -> set[str]:
    refs = subprocess.run(
        [
            "git",
            "for-each-ref",
            "--format=%(objectname)",
            "refs/orchestrator/snapshots",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    paths: set[str] = set()
    for commit_sha in refs:
        paths.update(_tree_paths(repo, commit_sha))
    return paths


def _tree_paths(repo: Path, commit_sha: str) -> set[str]:
    return set(
        subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", commit_sha],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
