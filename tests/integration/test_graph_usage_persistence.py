"""Integration coverage for graph-owned usage persistence."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.db import RunModel, create_engine, create_session_factory, init_db
from orchestrator.graph import FakeClock, SequentialIdGenerator
from orchestrator.graph_runtime import GraphController
from orchestrator.graph_runtime.dispatch import GraphDispatchContext
from orchestrator.state import ModelTokenUsage


@pytest.fixture
async def session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine: AsyncEngine = create_engine(":memory:")
    await init_db(engine)
    yield create_session_factory(engine)
    await engine.dispose()


def _context() -> GraphDispatchContext:
    return GraphDispatchContext(
        run_id="usage-run",
        node_id="worker-1",
        node_kind="worker",
        node_role="builder",
        node_payload={"profile": "coder"},
        requirements=[],
        worktree_path="/tmp/worktree",
        lease_id="lease-1",
        lease_generation=1,
        execution_id="execution-1",
        base_snapshot_id="S0",
        dispatch_event_id="dispatch-1",
    )


@pytest.mark.asyncio
async def test_controller_persists_usage_event_and_replays_run_usage_read_model(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    controller = GraphController(
        session_factory, FakeClock(), SequentialIdGenerator(), auto_dispatch=False
    )
    context = _context()
    async with session_factory() as session:
        async with session.begin():
            session.add(
                RunModel(
                    id=context.run_id,
                    repo_name="usage-repo",
                    status="active",
                    execution_mode="graph",
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                    updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )
    usage = [
        ModelTokenUsage(
            model="model-a",
            gen_ai_usage_input_tokens=100,
            gen_ai_usage_output_tokens=50,
            latency_ms=900,
        ),
        ModelTokenUsage(
            model="model-b",
            gen_ai_usage_input_tokens=200,
            gen_ai_usage_output_tokens=20,
            latency_ms=900,
            rate_missing=True,
        ),
    ]

    result = await controller.record_node_usage(context, usage)
    duplicate = await controller.record_node_usage(context, usage)

    assert [event.event_type for event in result.events] == [
        "node_usage_recorded",
        "node_usage_recorded",
    ]
    assert duplicate.events == []

    async with session_factory() as session:
        projection = await GraphController(
            session_factory, FakeClock(), SequentialIdGenerator()
        ).read_projection(context.run_id)
        run = (
            await session.execute(select(RunModel).where(RunModel.id == context.run_id))
        ).scalar_one()

    assert projection["tokens_by_node"] == {"worker-1": 370}
    assert run.total_duration_ms == 900
    assert len(run.token_usage_by_model or []) == 2
