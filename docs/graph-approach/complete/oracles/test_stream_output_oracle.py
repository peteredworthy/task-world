"""HIDDEN ORACLE — graph-carrier agent output must stream to the frontend live.

This file is intentionally kept out of the agent's repository snapshot. It is
copied into the completed run's worktree and executed with
``uv run pytest docs/graph-approach/oracles/test_stream_output_oracle.py -q``
*outside* the agent, as the comparison's hidden acceptance test.

Acceptance (what "stream agent output to the frontend, live" really requires for
the graph carrier — the default carrier):

1. The production graph runner factory ``make_graph_runner`` wires a
   ``connection_manager`` into its agent-output sink, so graph-node stdout is
   *broadcast* (not merely persisted). It must also accept an injectable
   ``runtime_builder`` so this behaviour is testable without a live LLM.
2. While a graph node is executing, the lines it streams via ``on_output`` reach
   the connection manager as an ``agent_output`` broadcast — i.e. during the run,
   not only after it ends.
3. The broadcast is attributed to the producing graph node (its task/region id),
   so the frontend can place the output under the right node.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api.deps import make_graph_runner
from orchestrator.config.enums import AgentRunnerType
from orchestrator.config.models import RoutineConfig
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph_runtime import GraphController, GraphDispatchContext, GraphDispatchExecutor
from orchestrator.runners.types import (
    AgentRunnerInfo,
    ExecutionContext,
    ExecutionResult,
)
from orchestrator.state.factory import create_run_from_routine
from orchestrator.workflow import WorkflowService

MARKER = "LIVE-STREAM-MARKER-7f3a"


class _SpyConnectionManager:
    """Captures broadcast_event calls (the WS broadcast surface)."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def broadcast_event(self, event: Any) -> None:
        self.events.append(event)

    async def broadcast_to_run(self, run_id: str, data: dict[str, Any]) -> None:  # pragma: no cover
        self.events.append(data)


class _StreamingWorker:
    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CLI_SUBPROCESS, name="stream")

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: Any,
        on_submit: Any,
        on_output: Any = None,
        on_grade: Any = None,
        on_agent_metadata: Any = None,
        on_escalation: Any = None,
    ) -> ExecutionResult:
        assert on_output is not None, "graph dispatch must pass on_output to the runner"
        await on_output([f"{MARKER} building the change..."])
        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


class _GradingVerifier(_StreamingWorker):
    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: Any,
        on_submit: Any,
        on_output: Any = None,
        on_grade: Any = None,
        on_agent_metadata: Any = None,
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
            "id": "stream-oracle",
            "name": "Stream Oracle",
            "execution_mode": "graph",
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
                            "verifier": {
                                "rubric": [{"id": "req-1", "text": "Does it satisfy req-1?"}]
                            },
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
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.asyncio
async def test_graph_agent_output_streams_live_with_attribution(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "oracle.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    repo = tmp_path / "repo"
    _init_repo(repo)

    run = create_run_from_routine(_routine(), repo_name=repo.name, source_branch="main")
    run.id = "stream-oracle-run"
    run.execution_mode = "graph"
    run.routine_embedded = _routine().model_dump(mode="json", by_alias=True)
    run.worktree_path = str(repo)
    run.agent_runner_type = AgentRunnerType.CLI_SUBPROCESS
    async with session_factory() as session:
        await WorkflowService(session).create_run(run)

    async def service_factory(session: AsyncSession) -> WorkflowService:
        return WorkflowService(session)

    agents = {"worker": _StreamingWorker(), "verifier": _GradingVerifier()}

    class _Factory:
        def create_runner(self, context: GraphDispatchContext) -> Any:
            return agents[context.node_kind]

    def runtime_builder(
        sf: async_sessionmaker[AsyncSession],
        clock: Any,
        id_gen: Any,
        *,
        worktree_path: Any,
        runner_type: AgentRunnerType,
        runner_config: dict[str, Any] | None = None,
        on_agent_output: Any = None,
        on_agent_usage: Any = None,
    ) -> tuple[GraphController, GraphDispatchExecutor]:
        controller = GraphController(sf, clock, id_gen, auto_dispatch=False)
        executor = GraphDispatchExecutor(
            sf,
            controller,
            _Factory(),
            worktree_path=repo,
            on_agent_output=on_agent_output,
        )
        return controller, executor

    spy = _SpyConnectionManager()

    # REQUIREMENT 1: make_graph_runner must accept a connection_manager (so graph
    # output is broadcast) and an injectable runtime_builder (so it is testable).
    runner = make_graph_runner(
        session_factory,
        service_factory,
        connection_manager=spy,
        runtime_builder=runtime_builder,
        clock=_Clock(),
        id_gen=_Ids(),
    )

    await runner("stream-oracle-run")
    # Allow the batcher's time-based flush to fire (it broadcasts on a ~100ms
    # window). A live stream reaches the connection manager without waiting for
    # the run to finish; this sleep only covers the final flush window.
    await asyncio.sleep(0.4)

    output_events = [e for e in spy.events if getattr(e, "event_type", None) == "agent_output"]
    assert output_events, (
        "no agent_output broadcast reached the connection manager — graph agent "
        "output is not streaming to the frontend live"
    )

    # REQUIREMENT 2: the streamed line actually arrived.
    streamed = [
        line
        for e in output_events
        for line in getattr(e, "lines", [])
        if MARKER in line
    ]
    assert streamed, f"streamed line with {MARKER!r} not broadcast; got {output_events!r}"

    # REQUIREMENT 3: attribution — the broadcast identifies the producing node.
    attributed = [
        e
        for e in output_events
        if MARKER in " ".join(getattr(e, "lines", []))
        and (getattr(e, "task_id", "") or getattr(getattr(e, "payload", None), "get", lambda *_: "")("node_id"))
    ]
    assert attributed, "agent_output broadcast is not attributed to a graph node"

    await engine.dispose()
