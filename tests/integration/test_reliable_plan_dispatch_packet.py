"""Production dispatch coverage for the reliable-plan planner tool packet."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
import yaml

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.config import AgentRunnerType, RoutineConfig
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import FakeClock, SequentialIdGenerator
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchExecutor,
    OutboxDispatcher,
    StaticGraphAgentFactory,
    seed_run,
)
from orchestrator.runners import (
    AgentRunner,
    CodexServerAgent,
    RELIABLE_PLAN_REQUIRED_TOOL_NAMES,
)
from tests.integration.git_helpers import _init_repo


class PacketTransport:
    """Concrete in-memory JSON-RPC transport recording the dispatched packet."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self._responses: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        for response in (
            {"jsonrpc": "2.0", "id": 1, "result": {"userAgent": "test/1.0"}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "thread": {
                        "id": "thread-reliable-plan",
                        "preview": "",
                        "modelProvider": "openai",
                        "createdAt": 0,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 3,
                "result": {
                    "turn": {
                        "id": "turn-reliable-plan",
                        "status": "inProgress",
                        "items": [],
                        "error": None,
                    }
                },
            },
            {
                "jsonrpc": "2.0",
                "method": "turn/completed",
                "params": {
                    "turn": {
                        "id": "turn-reliable-plan",
                        "status": "completed",
                        "items": [],
                        "error": None,
                    }
                },
            },
        ):
            self._responses.put_nowait(response)

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)

    async def recv(self) -> dict[str, Any]:
        return await self._responses.get()

    async def close(self) -> None:
        return None


class InjectedCodexRunnerBuilder:
    """Selected-runner DI boundary that avoids starting a real app-server."""

    def __init__(self, transport: PacketTransport) -> None:
        self._transport = transport
        self.calls: list[tuple[AgentRunnerType, dict[str, Any], str, str]] = []

    def __call__(
        self,
        agent_runner_type: AgentRunnerType,
        agent_runner_config: dict[str, Any],
        *,
        run_id: str,
        phase: str,
    ) -> AgentRunner:
        self.calls.append((agent_runner_type, dict(agent_runner_config), run_id, phase))
        return CodexServerAgent(
            local_provider="lmstudio",
            _transport=self._transport,
            _environ={},
        )


@pytest.mark.asyncio
async def test_routine_seed_outbox_dispatch_sends_reliable_macros_to_codex(
    tmp_path: Path,
) -> None:
    routine_path = Path(__file__).parents[2] / "routines" / "dynamic-graph-feature" / "routine.yaml"
    raw_routine = yaml.safe_load(routine_path.read_text())
    routine = RoutineConfig.model_validate(raw_routine["routine"])

    engine = create_engine(tmp_path / "dispatch-packet.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    clock = FakeClock()
    ids = SequentialIdGenerator()
    run_id = "reliable-plan-dispatch-packet"
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    try:
        await seed_run(
            session_factory,
            routine,
            run_id=run_id,
            clock=clock,
            id_gen=ids,
            source_path=str(routine_path),
            run_config={
                "feature_spec_path": "docs/dynamic-graph/reliable-plan-execution-contract.md",
                "feature_spec_content": "Reliable plan dispatch packet qualification.",
                "acceptance_command": "uv run pytest -q",
                "reliable_plan_skeleton_id": "reliable-plan-v1",
            },
        )
        controller = GraphController(session_factory, clock, ids, auto_dispatch=False)
        accepted = await controller.handle_command(
            run_id,
            await controller.current_position(run_id),
            "accept_run",
            {},
        )
        await controller.handle_command(
            run_id,
            accepted.projection_position,
            "start",
            {},
        )
        await controller.handle_command(
            run_id,
            await controller.current_position(run_id),
            "schedule_tick",
            {"base_snapshot_id": "snapshot-0", "max_grants": 1},
        )

        transport = PacketTransport()
        runner_builder = InjectedCodexRunnerBuilder(transport)
        executor = GraphDispatchExecutor(
            session_factory,
            controller,
            StaticGraphAgentFactory(
                AgentRunnerType.CODEX_SERVER,
                {"local_provider": "lmstudio"},
                runner_builder=runner_builder,
            ),
            worktree_path=repo,
            artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
        )
        dispatcher = OutboxDispatcher(session_factory, executor, clock)

        await dispatcher.dispatch_pending(run_id=run_id)
        await executor.wait_for_all()

        assert runner_builder.calls == [
            (
                AgentRunnerType.CODEX_SERVER,
                {"local_provider": "lmstudio"},
                run_id,
                "building",
            )
        ]
        thread_start = next(
            message for message in transport.sent if message.get("method") == "thread/start"
        )
        specs = thread_start["params"]["dynamicTools"]
        required_specs = [
            spec for spec in specs if spec["name"] in RELIABLE_PLAN_REQUIRED_TOOL_NAMES
        ]
        assert [spec["name"] for spec in required_specs] == list(RELIABLE_PLAN_REQUIRED_TOOL_NAMES)
        assert all(spec["inputSchema"]["type"] == "object" for spec in required_specs)
        assert all(spec["inputSchema"]["required"] for spec in required_specs)
    finally:
        await engine.dispose()
