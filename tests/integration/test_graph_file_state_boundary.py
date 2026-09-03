from __future__ import annotations

import subprocess
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.config.enums import AgentRunnerType
from orchestrator.config.models import RoutineConfig
from orchestrator.db import RunModel, create_engine, create_session_factory, init_db
from orchestrator.git import prepare_snapshot, restore
from orchestrator.graph import (
    FileStatePolicy,
    FileStateScanBudget,
    project_leases,
    project_node_states,
    project_residue_report,
)
from orchestrator.graph_runtime import (
    CacheScanBudgetExceededError,
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxDispatcher,
    capture_file_state_boundary,
    capture_worktree_file_state_baseline,
    seed_run,
)
from orchestrator.runners import AgentRunner
from orchestrator.runners.types import (
    AgentMetadataCallback,
    AgentRunnerInfo,
    ChecklistUpdateCallback,
    EscalationCallback,
    ExecutionContext,
    ExecutionMetrics,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
    SubmitCallback,
)
from orchestrator.state import ActionEntryKind, ActionLog, ActionLogEntry

pytestmark = pytest.mark.slow


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
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    dispatcher = OutboxDispatcher(session_factory, executor, FixedClock())

    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)

    events = await _read_events(session_factory, run_id)
    accepted = next(event for event in events if event.event_type == "file_state_accepted")
    assert not any(
        event.event_type == "output_record_accepted"
        and event.payload.get("record_kind") == "file_state"
        for event in events
    )
    classifications = {
        entry["path"]: entry["classification"] for entry in accepted.payload["paths"]
    }
    assert classifications["README.md"] == "tracked_change"
    assert classifications["residue.txt"] == "unknown_untracked"
    # Cache paths participate in classification/security scanning but are not
    # duplicated in the durable accepted record.
    assert "__pycache__" not in classifications
    assert classifications["ignored.log"] == "unknown_ignored"
    assert accepted.payload["git"]["ref"].startswith("refs/orchestrator/snapshots/")

    snapshot_id = str(accepted.payload["snapshot_id"])
    drained = await dispatcher.dispatch_pending(run_id=run_id)
    assert {item.kind for item in drained} == {"snapshot_publish", "snapshot_cleanup"}
    drained_events = await _read_events(session_factory, run_id)
    assert [
        event.payload["snapshot_role"]
        for event in drained_events
        if event.event_type == "cleanup_requested"
    ] == ["baseline", "final"]
    assert _ref_exists(repo, str(accepted.payload["git"]["ref"]))
    (repo / "README.md").unlink()
    (repo / "residue.txt").unlink()
    (repo / "__pycache__" / "app.cpython-312.pyc").unlink()
    (repo / "ignored.log").unlink()
    restore(repo, snapshot_id)
    assert (repo / "README.md").read_text() == "# changed\n"
    assert (repo / "residue.txt").read_text() == "temporary residue\n"
    assert not (repo / "__pycache__" / "app.cpython-312.pyc").exists()
    assert (repo / "ignored.log").read_text() == "ignored but captured\n"

    report = project_residue_report(events)
    assert report["residue.txt"][0]["classification"] == "unknown_untracked"
    assert report["ignored.log"][0]["classification"] == "unknown_ignored"


@pytest.mark.asyncio
async def test_file_state_snapshot_publication_replays_from_durable_staging(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """A restart redelivery publishes only the staged file-state identity."""
    _, session_factory = file_db
    repo = tmp_path / "repo-publish-replay"
    _init_repo(repo)
    run_id = "file-state-publish-replay"
    controller = await _seed_active_run(session_factory, run_id)
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory(BoundaryFixtureAgent()),
        worktree_path=repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    dispatcher = OutboxDispatcher(session_factory, executor, FixedClock())

    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)
    accepted = next(
        event
        for event in await _read_events(session_factory, run_id)
        if event.event_type == "file_state_accepted"
    )
    git = accepted.payload["git"]
    assert isinstance(git, dict)
    ref, commit = str(git["ref"]), str(git["commit_sha"])
    subprocess.run(["git", "update-ref", "-d", ref], cwd=repo, check=True, timeout=30)
    assert not _ref_exists(repo, ref)

    completed = await dispatcher.dispatch_pending(
        run_id=run_id, allowed_kinds=frozenset({"snapshot_publish"})
    )

    # Baseline/final publication intents may be picked up in this same outbox
    # tranche when real Git boundaries finish after the dispatcher's prior
    # scan.  The contract under test is exactly one replay of this staged ref,
    # independent of that legitimate scheduling order.
    assert completed
    assert all(item.kind == "snapshot_publish" for item in completed)
    assert sum(item.payload.get("snapshot_ref") == ref for item in completed) == 1
    assert _ref_exists(repo, ref)
    assert (
        subprocess.run(
            ["git", "rev-parse", ref],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        == commit
    )


def test_file_state_prepare_before_staging_leaves_no_named_ref(tmp_path: Path) -> None:
    """The prepare-to-stage crash point leaves only an unreachable Git object."""
    repo = tmp_path / "repo-prepare-before-stage"
    _init_repo(repo)
    (repo / "ignored.log").write_text("boundary content\n")
    boundary = capture_file_state_boundary(
        worktree_path=repo,
        run_id="prepare-before-stage",
        node_id="worker-1",
        execution_id="execution-1",
        base_snapshot_id="base-snapshot",
    )
    prepared = prepare_snapshot(
        repo,
        "file-state submission prepared but not staged",
        snapshot_id="a" * 64,
        force_include_paths=list(boundary.force_include_paths),
    )

    # Simulate process death / append rejection before stage_runner_submission:
    # no durable ownership command ran, so publication is prohibited.
    assert not _ref_exists(repo, prepared.ref)


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
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    dispatcher = OutboxDispatcher(session_factory, executor, FixedClock())

    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)

    events = await _read_events(session_factory, run_id)
    rejection = next(event for event in events if event.event_type == "file_state_rejected")
    rejected_paths = {
        entry["path"]: entry["classification"]
        for entry in rejection.payload["paths"]
        if entry.get("rejected") is True
    }
    assert rejected_paths == {"fake_key.pem": "secret"}
    assert not any(event.event_type == "file_state_accepted" for event in events)
    assert "fake_key.pem" not in _all_snapshot_tree_paths(repo)
    assert not any(
        event.event_type == "node_state_changed" and event.payload.get("new_state") == "completed"
        for event in events
    )
    assert project_node_states(events)["worker-step-1-task-1"] == "running"
    await dispatcher.dispatch_pending(run_id=run_id, allowed_kinds=frozenset({"runner_recovery"}))
    recovered_events = await _read_events(session_factory, run_id)
    assert project_node_states(recovered_events)["worker-step-1-task-1"] == "ready"
    assert not any(
        lease.get("state") == "active" for lease in project_leases(recovered_events).values()
    )

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
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )
    dispatcher = OutboxDispatcher(session_factory, executor, FixedClock())

    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)

    events = await _read_events(session_factory, run_id)
    rejection = next(event for event in events if event.event_type == "file_state_rejected")
    classifications = {
        entry["path"]: entry["classification"] for entry in rejection.payload["paths"]
    }
    rejected_paths = {
        entry["path"]: entry["classification"]
        for entry in rejection.payload["paths"]
        if entry.get("rejected") is True
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


def test_large_ui_node_modules_respects_compiled_budget_and_keeps_security_visible(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo-large-ui-node-modules"
    _init_repo(repo)
    _append_gitignore_and_commit(repo, "ui/node_modules/")
    cache = repo / "ui" / "node_modules" / "dependency"
    cache.mkdir(parents=True)
    for index in range(10_050):
        (cache / f"ordinary-{index:05d}.js").write_text("x", encoding="utf-8")
    policy = FileStatePolicy(
        scan_budget=FileStateScanBudget(max_entries=50_000, max_bytes=1_073_741_824)
    )

    baseline = capture_worktree_file_state_baseline(repo, policy)
    boundary = capture_file_state_boundary(
        worktree_path=repo,
        run_id="large-ui-cache",
        node_id="planner-1",
        execution_id="execution-1",
        base_snapshot_id="base-1",
        policy=policy,
        baseline=baseline,
    )

    assert boundary.classification.verdict == "captured"
    assert [entry.path for entry in baseline.status.ignored] == ["ui/node_modules"]
    assert [entry.path for entry in boundary.classification.paths] == []

    security = repo / "ui" / "node_modules" / "00-security"
    security.mkdir()
    (security / "id_rsa").write_bytes(bytes(range(256)))
    (security / "outside").symlink_to(tmp_path / "outside", target_is_directory=True)
    rejected = capture_file_state_boundary(
        worktree_path=repo,
        run_id="large-ui-cache",
        node_id="planner-1",
        execution_id="execution-2",
        base_snapshot_id="base-1",
        policy=policy,
    )
    rejected_by_path = {entry.path: entry for entry in rejected.classification.paths}

    assert set(rejected_by_path) == {
        "ui/node_modules",
        "ui/node_modules/00-security/id_rsa",
        "ui/node_modules/00-security/outside",
    }
    assert rejected_by_path["ui/node_modules"].classification == "tool_cache"
    assert rejected_by_path["ui/node_modules/00-security/id_rsa"].classification == "secret"
    assert rejected_by_path["ui/node_modules/00-security/outside"].reason == "repo_escape"
    assert rejected.classification.verdict == "rejected"

    over_limit = FileStatePolicy(
        scan_budget=FileStateScanBudget(max_entries=10_000, max_bytes=1_073_741_824)
    )
    failures: list[tuple[str, int, int, str]] = []
    for _ in range(2):
        with pytest.raises(CacheScanBudgetExceededError) as raised:
            capture_worktree_file_state_baseline(repo, over_limit)
        error = raised.value
        failures.append((error.metric, error.limit, error.observed, error.path))

    assert failures[0] == failures[1]
    assert failures[0][:3] == ("entries", 10_000, 10_001)


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


def _ref_exists(repo: Path, ref: str) -> bool:
    return (
        subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", ref],
            cwd=repo,
            check=False,
            timeout=30,
        ).returncode
        == 0
    )


class _UsageFixtureAgent:
    """Fixture agent that submits cleanly and reports token usage."""

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=AgentRunnerType.CLI_SUBPROCESS, name="usage-fixture"
        )

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
        await on_submit()
        return ExecutionResult(
            success=True,
            metrics=ExecutionMetrics(
                gen_ai_usage_input_tokens=11,
                gen_ai_usage_output_tokens=22,
                gen_ai_usage_cache_read_input_tokens=33,
                num_actions=0,
            ),
            action_log=ActionLog(
                agent_model="usage-model",
                gen_ai_usage_input_tokens=11,
                gen_ai_usage_output_tokens=22,
                entries=[
                    ActionLogEntry(kind=ActionEntryKind.TOOL_USE),
                    ActionLogEntry(kind=ActionEntryKind.TOOL_USE),
                ],
            ),
        )

    async def cancel(self) -> None:
        return None


@pytest.mark.asyncio
async def test_graph_dispatch_surfaces_agent_usage(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """The graph executor invokes the injected on_agent_usage callback with the
    execution result, so token/cost accounting can flow through the SAME shared
    sink the legacy path uses (regression for graph runs recording 0 tokens)."""
    _, session_factory = file_db
    repo = tmp_path / "repo-usage"
    _init_repo(repo)
    run_id = "graph-usage"
    async with session_factory() as session:
        async with session.begin():
            session.add(
                RunModel(
                    id=run_id,
                    repo_name="graph-usage-repo",
                    status="active",
                    execution_mode="graph",
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                    updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )
    controller = await _seed_active_run(session_factory, run_id)

    captured: list[ExecutionResult] = []

    async def on_agent_usage(_ctx: GraphDispatchContext, result: ExecutionResult) -> None:
        captured.append(result)

    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory(_UsageFixtureAgent()),
        worktree_path=repo,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
        on_agent_usage=on_agent_usage,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, FixedClock())
    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)

    assert len(captured) == 1
    assert captured[0].metrics.gen_ai_usage_output_tokens == 22
    assert captured[0].metrics.num_actions == 0
    events = await _read_events(session_factory, run_id)
    usage_event = next(event for event in events if event.event_type == "node_usage_recorded")
    projection = await controller.read_projection(run_id)
    async with session_factory() as session:
        run = (await session.execute(select(RunModel).where(RunModel.id == run_id))).scalar_one()

    assert usage_event.payload["usage_index"] == 0
    assert usage_event.payload["num_actions"] == 2
    assert projection.usage.action_count_by_node_kind == {"worker": 2}
    assert run.total_num_actions == 2
