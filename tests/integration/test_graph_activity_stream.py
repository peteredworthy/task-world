from __future__ import annotations

import subprocess
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.config.enums import AgentRunnerType
from orchestrator.config.models import RoutineConfig
from orchestrator.db import (
    create_engine,
    create_session_factory,
    create_wired_event_store_v2,
    init_db,
)
from orchestrator.graph_runtime import GraphController, GraphDispatchContext, GraphDispatchExecutor
from orchestrator.runners import AgentRunner, OutputBatcher
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
from orchestrator.state.factory import create_run_from_routine
from orchestrator.workflow import WorkflowService
from orchestrator.workflow.graph_driver import GraphRunDriver


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


class OutputAgent:
    def __init__(self, lines: list[str], grade: str | None = None) -> None:
        self._lines = lines
        self._grade = grade

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CLI_SUBPROCESS, name="output")

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
        if on_output is not None:
            await on_output(self._lines)
        if self._grade is not None and on_grade is not None:
            await on_grade("req-1", self._grade, None)
        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


@pytest.fixture
async def file_db(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]], None]:
    engine = create_engine(tmp_path / "graph-activity.db")
    await init_db(engine)
    yield engine, create_session_factory(engine)
    await engine.dispose()


def _routine(*, execution_mode: str = "graph") -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": f"{execution_mode}-activity",
            "name": f"{execution_mode} Activity",
            "execution_mode": execution_mode,
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Emit output",
                            "task_context": "Emit one output line.",
                            "requirements": [{"id": "req-1", "desc": "Output is visible."}],
                            "verifier": {
                                "rubric": [
                                    {
                                        "id": "req-1",
                                        "text": "Does output remain visible?",
                                    }
                                ]
                            },
                        }
                    ],
                }
            ],
        }
    )


def _init_repo(path: Path) -> None:
    path.mkdir()
    (path / "README.md").write_text("# tmp repo\n")
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "add", "README.md"], cwd=path, check=True, capture_output=True, text=True
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


async def _create_service(session: AsyncSession) -> WorkflowService:
    return WorkflowService(session)


async def _create_run(
    session_factory: async_sessionmaker[AsyncSession],
    routine: RoutineConfig,
    *,
    run_id: str,
    repo: Path,
) -> None:
    run = create_run_from_routine(routine, repo_name=repo.name, source_branch="main")
    run.id = run_id
    run.execution_mode = routine.execution_mode
    run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
    run.worktree_path = str(repo)
    run.agent_runner_type = AgentRunnerType.CLI_SUBPROCESS
    async with session_factory() as session:
        await WorkflowService(session).create_run(run)


def _driver(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    repo: Path,
    agents: dict[str, AgentRunner],
    on_agent_output: Any,
) -> GraphRunDriver:
    clock = FixedClock()
    ids = SequentialIds()

    def runtime_builder(
        session_factory_arg: async_sessionmaker[AsyncSession],
        clock_arg: Any,
        id_gen_arg: Any,
        *,
        worktree_path: str | Path,
        runner_type: AgentRunnerType,
        runner_config: dict[str, Any] | None = None,
        on_agent_output: Any = None,
    ) -> tuple[GraphController, GraphDispatchExecutor]:
        controller = GraphController(
            session_factory_arg, clock_arg, id_gen_arg, auto_dispatch=False
        )
        executor = GraphDispatchExecutor(
            session_factory_arg,
            controller,
            AgentFactory(agents),
            worktree_path=repo,
            on_agent_output=on_agent_output,
        )
        return controller, executor

    return GraphRunDriver(
        session_factory,
        _create_service,
        clock=clock,
        id_gen=ids,
        runtime_builder=runtime_builder,
        on_agent_output=on_agent_output,
    )


async def _activity_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> list[dict[str, Any]]:
    async with session_factory() as session:
        store = create_wired_event_store_v2(session)
        return await store.get_events_paginated(
            run_id,
            limit=100,
            event_type="agent_output",
        )


@pytest.mark.asyncio
async def test_graph_run_emits_agent_output_activity_events(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-graph-output"
    _init_repo(repo)
    run_id = "graph-output"
    await _create_run(session_factory, _routine(), run_id=run_id, repo=repo)
    batcher = OutputBatcher(session_factory=session_factory)

    async def on_agent_output(context: GraphDispatchContext, lines: list[str]) -> None:
        task_id = str(
            context.node_payload.get("task_id")
            or context.node_payload.get("task_region_id")
            or context.node_id
        )
        attempt_num = int(context.node_payload.get("attempt_number") or 1)
        for line in lines:
            await batcher.add_line(context.run_id, task_id, attempt_num, line)

    driver = _driver(
        session_factory,
        repo=repo,
        agents={
            "worker": OutputAgent(["worker line"]),
            "verifier": OutputAgent(["verifier line"], grade="A"),
        },
        on_agent_output=on_agent_output,
    )

    await driver.run(run_id)
    await batcher.flush_immediate()

    events = await _activity_events(session_factory, run_id)
    assert [event["event_type"] for event in events] == ["agent_output", "agent_output"]
    assert [event["payload"]["lines"] for event in events] == [
        ["worker line"],
        ["verifier line"],
    ]
    assert {event["payload"]["task_id"] for event in events} == {
        "task-1",
        "step-1/task-1",
    }
    assert {event["payload"]["attempt_num"] for event in events} == {1}


@pytest.mark.asyncio
async def test_legacy_runs_activity_unchanged(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    _, session_factory = file_db
    repo = tmp_path / "repo-legacy-output"
    _init_repo(repo)
    run_id = "legacy-output"
    await _create_run(
        session_factory,
        _routine(execution_mode="legacy"),
        run_id=run_id,
        repo=repo,
    )
    batcher = OutputBatcher(session_factory=session_factory)

    await batcher.add_line(run_id, "task-1", 1, "legacy line")
    await batcher.flush_immediate()

    events = await _activity_events(session_factory, run_id)
    assert len(events) == 1
    assert events[0]["event_type"] == "agent_output"
    assert events[0]["payload"]["task_id"] == "task-1"
    assert events[0]["payload"]["lines"] == ["legacy line"]
