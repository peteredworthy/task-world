"""HIDDEN ORACLE v2 — corrected to test the *feature requirement*, not a seam.

v1 over-specified an injectable ``runtime_builder`` on ``make_graph_runner`` — a
test convenience that was never part of the feature. v2 tests only what the
feature actually requires, independently of the agent's own tests:

A. ``make_graph_runner`` accepts a ``connection_manager`` and the production call
   site (``api/app.py``) passes one (static wiring facts).
B. Driving a real graph run, the lines a node streams via ``on_output`` are
   broadcast through the connection manager as ``agent_output`` events
   (live streaming), each attributed to the producing node (``node_id``).
"""

from __future__ import annotations

import inspect
import subprocess
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import orchestrator.api.app as app_module
from orchestrator.api.deps import make_graph_runner
from orchestrator.config.enums import AgentRunnerType
from orchestrator.config.models import RoutineConfig
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph_runtime import GraphController, GraphDispatchContext, GraphDispatchExecutor
from orchestrator.runners import OutputBatcher
from orchestrator.runners.types import AgentRunnerInfo, ExecutionContext, ExecutionResult
from orchestrator.state.factory import create_run_from_routine
from orchestrator.workflow import WorkflowService
from orchestrator.workflow.graph_driver import GraphRunDriver

MARKER = "LIVE-STREAM-MARKER-7f3a"


def test_a_make_graph_runner_and_callsite_wire_connection_manager() -> None:
    """A. Static wiring: factory accepts connection_manager; app.py passes it."""
    params = inspect.signature(make_graph_runner).parameters
    assert "connection_manager" in params, (
        "make_graph_runner must accept a connection_manager so graph output is broadcast"
    )
    src = inspect.getsource(app_module)
    assert "connection_manager=" in src and "make_graph_runner(" in src, (
        "api/app.py must pass a connection_manager into make_graph_runner"
    )


class _Spy:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def broadcast_event(self, event: Any) -> None:
        self.events.append(event)


class _StreamWorker:
    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CLI_SUBPROCESS, name="s")

    async def execute(
        self, context: ExecutionContext, on_checklist_update: Any, on_submit: Any,
        on_output: Any = None, on_grade: Any = None, on_agent_metadata: Any = None,
        on_escalation: Any = None,
    ) -> ExecutionResult:
        assert on_output is not None
        await on_output([f"{MARKER} worker streaming"])
        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


class _Verifier(_StreamWorker):
    async def execute(
        self, context: ExecutionContext, on_checklist_update: Any, on_submit: Any,
        on_output: Any = None, on_grade: Any = None, on_agent_metadata: Any = None,
        on_escalation: Any = None,
    ) -> ExecutionResult:
        if on_grade is not None:
            await on_grade("req-1", "A", None)
        await on_submit()
        return ExecutionResult(success=True)


class _Clock:
    def now(self) -> Any:
        from datetime import UTC, datetime

        return datetime(2026, 1, 1, tzinfo=UTC)


class _Ids:
    def __init__(self) -> None:
        self._n = 0

    def next_id(self, prefix: str = "") -> str:
        self._n += 1
        return f"{prefix}-{self._n}"


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "stream-oracle-v2",
            "name": "Stream Oracle v2",
            "execution_mode": "graph",
            "steps": [
                {
                    "id": "step-1",
                    "title": "S1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "T1",
                            "task_context": "Produce one candidate.",
                            "requirements": [{"id": "req-1", "desc": "passes"}],
                            "verifier": {"rubric": [{"id": "req-1", "text": "ok?"}]},
                        }
                    ],
                }
            ],
        }
    )


def _init_repo(path: Path) -> None:
    path.mkdir()
    (path / "README.md").write_text("# tmp\n")
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "i"],
        cwd=path, check=True, capture_output=True, text=True,
    )


@pytest.mark.asyncio
async def test_b_graph_output_streams_live_attributed(tmp_path: Path) -> None:
    """B. Behavioral: graph node output is broadcast live, attributed to the node."""
    engine = create_engine(tmp_path / "o2.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    repo = tmp_path / "repo"
    _init_repo(repo)

    run = create_run_from_routine(_routine(), repo_name=repo.name, source_branch="main")
    run.id = "o2-run"
    run.execution_mode = "graph"
    run.routine_embedded = _routine().model_dump(mode="json", by_alias=True)
    run.worktree_path = str(repo)
    run.agent_runner_type = AgentRunnerType.CLI_SUBPROCESS
    async with session_factory() as session:
        await WorkflowService(session).create_run(run)

    async def service_factory(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    spy = _Spy()
    # Production sink shape: a connection_manager-backed batcher fed per node,
    # carrying node_id attribution (the feature under test).
    batcher = OutputBatcher(session_factory=session_factory, connection_manager=spy)

    async def on_agent_output(context: GraphDispatchContext, lines: list[str]) -> None:
        for line in lines:
            await batcher.add_line(
                context.run_id, context.node_id, 1, line, node_id=context.node_id
            )

    agents = {"worker": _StreamWorker(), "verifier": _Verifier()}

    class _Factory:
        def create_runner(self, context: GraphDispatchContext) -> Any:
            return agents[context.node_kind]

    def runtime_builder(
        sf: async_sessionmaker[AsyncSession], clock: Any, id_gen: Any, *,
        worktree_path: Any, runner_type: AgentRunnerType,
        runner_config: dict[str, Any] | None = None, on_agent_output: Any = None,
        on_agent_usage: Any = None,
    ) -> tuple[GraphController, GraphDispatchExecutor]:
        controller = GraphController(sf, clock, id_gen, auto_dispatch=False)
        executor = GraphDispatchExecutor(
            sf, controller, _Factory(), worktree_path=repo, on_agent_output=on_agent_output
        )
        return controller, executor

    driver = GraphRunDriver(
        session_factory, service_factory, clock=_Clock(), id_gen=_Ids(),
        runtime_builder=runtime_builder, on_agent_output=on_agent_output,
    )
    await driver.run("o2-run")
    await batcher.flush_immediate()

    output_events = [e for e in spy.events if getattr(e, "event_type", None) == "agent_output"]
    streamed = [e for e in output_events if MARKER in " ".join(getattr(e, "lines", []))]
    assert streamed, f"graph node output not broadcast live; events={spy.events!r}"
    assert any(getattr(e, "node_id", None) for e in streamed), (
        "broadcast agent_output is not attributed to a graph node (node_id missing)"
    )
    await engine.dispose()
