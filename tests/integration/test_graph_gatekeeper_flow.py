from __future__ import annotations

import subprocess
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.config.enums import AgentRunnerType
from orchestrator.config.models import RoutineConfig
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import (
    GatekeeperTaxonomy,
    initial_projection,
    project_gatekeeper_report,
    project_residue_report,
    reduce_event,
)
from orchestrator.graph_runtime import (
    GatekeeperVerdict,
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxDispatcher,
    ResidueMetadata,
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
    def __init__(self, agents: dict[str, AgentRunner]) -> None:
        self._agents = agents

    def create_runner(self, context: GraphDispatchContext) -> AgentRunner:
        return self._agents[context.node_kind]


class RecordingClassifier:
    def __init__(self, classification: GatekeeperTaxonomy = "test_artifact") -> None:
        self._classification = classification
        self.calls: list[list[ResidueMetadata]] = []

    def classify(self, items: list[ResidueMetadata]) -> list[GatekeeperVerdict]:
        self.calls.append(list(items))
        return [
            GatekeeperVerdict(
                path=item.path,
                classification=cast(GatekeeperTaxonomy, self._classification),
                confidence=0.92,
                rationale="metadata-only fake verdict",
                model_id="fake-small-model",
                input_tokens=7,
                output_tokens=2,
                cost_usd=0.0001,
                wall_time_ms=5,
            )
            for item in items
        ]


class ResidueWorker:
    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CLI_SUBPROCESS, name="worker")

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
        reports = worktree / "reports"
        reports.mkdir(exist_ok=True)
        (reports / "first.xml").write_text("<testsuite />\n")
        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


class PatternVerifier:
    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CLI_SUBPROCESS, name="verifier")

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
        reports = worktree / "reports"
        reports.mkdir(exist_ok=True)
        (reports / "second.xml").write_text("<testsuite />\n")
        if on_grade is not None:
            await on_grade("req-1", "A", None)
        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


class ManyResidueWorker(ResidueWorker):
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
        for index in range(25):
            (worktree / f"item-{index}.xml").write_text("<testsuite />\n")
        await on_submit()
        return ExecutionResult(success=True)


class SecretWorker(ResidueWorker):
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
        (worktree / "residue.txt").write_text("ordinary residue\n")
        (worktree / "fake_key.pem").write_bytes(bytes(range(128)))
        await on_submit()
        return ExecutionResult(success=True)


class RetroactiveSecretWorker(ResidueWorker):
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
        (worktree / "residue.txt").write_text("missed by deterministic classifier\n")
        await on_submit()
        return ExecutionResult(success=True)


@pytest.fixture
async def file_db(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]], None]:
    engine = create_engine(tmp_path / "graph-gatekeeper.db")
    await init_db(engine)
    yield engine, create_session_factory(engine)
    await engine.dispose()


@pytest.mark.asyncio
async def test_gatekeeper_flow_metadata_only_pattern_reuse_and_replay(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-pattern"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "gatekeeper-pattern"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    fake = RecordingClassifier()
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": ResidueWorker(), "verifier": PatternVerifier()}),
        worktree_path=repo,
        residue_classifier=fake,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)
    assert len(fake.calls) == 1
    assert [item.path for item in fake.calls[0]] == ["reports/first.xml"]
    assert [set(item.__dict__) for item in fake.calls[0]] == [
        {
            "path",
            "size_bytes",
            "entropy",
            "source",
            "prior_classification",
            "matched_rule",
            "record_id",
        }
    ]

    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)
    assert len(fake.calls) == 1

    events = await _read_events(session_factory, run_id)
    residue_report = project_residue_report(events)
    assert residue_report["reports/first.xml"][-1]["classification"] == "test_artifact"
    assert residue_report["reports/first.xml"][-1]["needs_gatekeeper"] is False
    assert residue_report["reports/second.xml"][0]["matched_rule"] == (
        "pattern_library:reports/*.xml"
    )
    assert residue_report["reports/second.xml"][0]["needs_gatekeeper"] is False

    replayed_report = project_residue_report(events)
    assert replayed_report == residue_report

    gatekeeper_report = project_gatekeeper_report(events)[run_id]
    assert gatekeeper_report["gatekeeper_consults"] == 1
    assert gatekeeper_report["gatekeeper_resolved"] == 1
    assert gatekeeper_report["pattern_library_size"] == 1
    assert gatekeeper_report["hit_rate"] > 0
    assert gatekeeper_report["models"]["fake-small-model"]["consults"] == 1


@pytest.mark.asyncio
async def test_gatekeeper_cap_leaves_remainder_flagged(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-cap"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "gatekeeper-cap"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    fake = RecordingClassifier()
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": ManyResidueWorker(), "verifier": PatternVerifier()}),
        worktree_path=repo,
        residue_classifier=fake,
        max_gatekeeper_items_per_boundary=3,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)

    assert len(fake.calls) == 1
    assert len(fake.calls[0]) == 3
    events = await _read_events(session_factory, run_id)
    residue_report = project_residue_report(events)
    resolved = [
        entries[0]
        for entries in residue_report.values()
        if entries[0]["classification"] == "test_artifact"
    ]
    unresolved = [
        entries[0] for entries in residue_report.values() if entries[0]["needs_gatekeeper"]
    ]
    assert len(resolved) == 3
    assert len(unresolved) == 22


@pytest.mark.asyncio
async def test_secret_suspects_are_not_sent_to_gatekeeper(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-secret"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "gatekeeper-secret"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    fake = RecordingClassifier()
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": SecretWorker(), "verifier": PatternVerifier()}),
        worktree_path=repo,
        residue_classifier=fake,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)

    assert fake.calls == []
    events = await _read_events(session_factory, run_id)
    rejection = next(event for event in events if event.event_type == "file_state_rejected")
    rejected_paths = {entry["path"] for entry in rejection.payload["rejected_paths"]}
    assert rejected_paths == {"fake_key.pem"}


@pytest.mark.asyncio
async def test_gatekeeper_secret_verdict_scrubs_compromised_snapshot(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-retroactive-secret"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "gatekeeper-retroactive-secret"
    controller = await _seed_active_run(session_factory, run_id, clock, ids)
    fake = RecordingClassifier("secret")
    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        AgentFactory({"worker": RetroactiveSecretWorker(), "verifier": PatternVerifier()}),
        worktree_path=repo,
        residue_classifier=fake,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)

    await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)

    events = await _read_events(session_factory, run_id)
    accepted_records = [event for event in events if event.event_type == "file_state_accepted"]
    original = accepted_records[0]
    superseding = next(
        event
        for event in accepted_records
        if event.payload.get("supersedes_record_id") == original.payload["record_id"]
    )
    old_snapshot_id = str(original.payload["snapshot_id"])
    new_snapshot_id = str(superseding.payload["snapshot_id"])
    old_ref = f"refs/orchestrator/snapshots/{old_snapshot_id}"
    new_ref = f"refs/orchestrator/snapshots/{new_snapshot_id}"

    assert _ref_exists(repo, old_ref) is False
    assert _ref_exists(repo, new_ref) is True
    assert "residue.txt" not in _tree_paths(repo, str(superseding.payload["git"]["commit_sha"]))
    assert any(event.event_type == "cleanup_requested" for event in events)
    assert any(event.event_type == "cleanup_applied" for event in events)

    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    original_record = projection["file_state_records"][original.payload["record_id"]]
    superseding_record = projection["file_state_records"][superseding.payload["record_id"]]
    assert original_record["compromised"] is True
    assert original_record["superseded_pending"] is False
    assert original_record["superseded_by_record_id"] == superseding.payload["record_id"]
    assert superseding_record["supersedes_record_id"] == original.payload["record_id"]


async def _seed_active_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    clock: FixedClock,
    ids: SequentialIds,
) -> GraphController:
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
    await dispatcher.dispatch_pending()


async def _read_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
):
    async with session_factory() as session:
        return await GraphEventStore(session).read_run(run_id)


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "graph-gatekeeper",
            "name": "Graph Gatekeeper",
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
                            "verifier": {"rubric": [{"id": "req-1", "text": "Does it pass?"}]},
                        }
                    ],
                }
            ],
        }
    )


def _init_repo(path: Path) -> None:
    path.mkdir()
    (path / "README.md").write_text("# tmp repo\n")
    reports = path / "reports"
    reports.mkdir()
    (reports / ".gitkeep").write_text("")
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "add", "README.md", "reports/.gitkeep"],
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


def _ref_exists(repo: Path, ref: str) -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", ref],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )


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
