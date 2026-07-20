"""Integration coverage for graph-owned usage persistence."""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.api import token_usage_to_schema
from orchestrator.db import EventV2Model, RunModel, create_engine, create_session_factory, init_db
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock, SequentialIdGenerator
from orchestrator.graph_runtime import GraphController, GraphEventStore
from orchestrator.graph_runtime.store import graph_aggregate_id
from orchestrator.graph_runtime.dispatch import GraphDispatchContext
from orchestrator.state import ModelTokenUsage


def _legacy_usage_snapshot(value: object) -> object:
    """Mark an intentional pre-cutover fixture value for the vocabulary guard."""
    return value


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


def _event(event_id: str, event_type: str, payload: dict[str, object]) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        run_id="usage-run",
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=payload,
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

    result = await controller.record_node_usage(context, usage, num_actions=4)
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
    assert run.total_num_actions == 4
    assert len(run.token_usage_by_model or []) == 2


@pytest.mark.asyncio
async def test_rebuild_preserves_untagged_historical_usage_when_graph_usage_is_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = _context()
    async with session_factory() as session:
        async with session.begin():
            session.add(
                RunModel(
                    id=context.run_id,
                    repo_name="usage-repo",
                    status="active",
                    execution_mode="graph",
                    total_duration_ms=999,
                    total_num_actions=88,
                    token_usage_by_model=[{"model": "stale"}],
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                    updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )
            await GraphEventStore(session).append_events(
                context.run_id,
                0,
                [_event("node-1", "node_created", {"node_id": "worker-1", "kind": "worker"})],
            )
            await GraphEventStore(session).rebuild_read_models(context.run_id)

    async with session_factory() as session:
        run = await session.get(RunModel, context.run_id)

    assert run is not None
    assert run.token_usage_by_model == [{"model": "stale"}]
    assert run.total_duration_ms == 999
    assert run.total_num_actions == 88


@pytest.mark.asyncio
async def test_rebuild_replaces_only_graph_usage_and_preserves_legacy_baseline(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = _context()
    graph_usage = ModelTokenUsage(model="graph-model", latency_ms=50).model_dump(mode="json")
    async with session_factory() as session:
        async with session.begin():
            session.add(
                RunModel(
                    id=context.run_id,
                    repo_name="usage-repo",
                    status="active",
                    execution_mode="graph",
                    total_duration_ms=150,
                    total_num_actions=6,
                    token_usage_by_model=[
                        _legacy_usage_snapshot({"model": "legacy", "input_tokens": 7}),
                        {"graph_usage_key": "execution-1:0", **graph_usage},
                    ],
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                    updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )
            await GraphEventStore(session).append_events(
                context.run_id,
                0,
                [_event("node-1", "node_created", {"node_id": "worker-1", "kind": "worker"})],
            )
            await GraphEventStore(session).rebuild_read_models(context.run_id)

    async with session_factory() as session:
        run = await session.get(RunModel, context.run_id)

    assert run is not None
    assert run.token_usage_by_model == [
        _legacy_usage_snapshot({"model": "legacy", "input_tokens": 7})
    ]
    assert run.total_duration_ms == 100
    assert run.total_num_actions == 6


@pytest.mark.asyncio
async def test_rebuild_persists_exact_node_usage_provenance_without_api_leakage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = _context()
    usage_key = f"{context.execution_id}:0"
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
            store = GraphEventStore(session)
            await store.append_events(
                context.run_id,
                0,
                [
                    _event(
                        "usage-1",
                        "node_usage_recorded",
                        {
                            "node_id": context.node_id,
                            "node_kind": context.node_kind,
                            "node_role": context.node_role,
                            "profile": "coder",
                            "execution_id": context.execution_id,
                            "usage_index": 0,
                            "usage_count": 1,
                            "usage_key": usage_key,
                            "model": "gpt-5",
                            "gen_ai_usage_input_tokens": 17,
                            "gen_ai_usage_output_tokens": 9,
                            "cost_usd": 0.42,
                            "latency_ms": 321,
                            "num_actions": 6,
                        },
                    )
                ],
            )
            await store.rebuild_read_models(context.run_id)

    async with session_factory() as session:
        run = await session.get(RunModel, context.run_id)

    assert run is not None
    assert run.total_duration_ms == 321
    assert run.total_num_actions == 6
    assert run.token_usage_by_model == [
        {
            "model": "gpt-5",
            "gen_ai_usage_input_tokens": 17,
            "gen_ai_usage_output_tokens": 9,
            "gen_ai_usage_cache_read_input_tokens": 0,
            "gen_ai_usage_cache_creation_input_tokens": 0,
            "gen_ai_usage_reasoning_output_tokens": 0,
            "gen_ai_response_finish_reasons": [],
            "cost_usd": 0.42,
            "latency_ms": 321,
            "rate_missing": False,
            "graph_usage_key": usage_key,
            "graph_usage_num_actions": 6,
        }
    ]
    api_usage = token_usage_to_schema(ModelTokenUsage.model_validate(run.token_usage_by_model[0]))
    assert "graph_usage_key" not in api_usage.model_dump()
    assert "graph_usage_num_actions" not in api_usage.model_dump()


@pytest.mark.asyncio
async def test_unrelated_append_does_not_rescan_historical_event_bodies(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
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
            store = GraphEventStore(session)
            await store.append_events(
                context.run_id,
                0,
                [_event("node-1", "node_created", {"node_id": "worker-1", "kind": "worker"})],
            )
        async with session.begin():
            await session.execute(
                update(EventV2Model)
                .where(EventV2Model.aggregate_id == graph_aggregate_id(context.run_id))
                .where(EventV2Model.version == 1)
                .values(payload="{historical payload intentionally unavailable")
            )
        async with session.begin():
            await GraphEventStore(session).append_events(
                context.run_id,
                1,
                [_event("node-2", "node_created", {"node_id": "worker-2", "kind": "worker"})],
            )


@pytest.mark.asyncio
async def test_concurrent_usage_appends_retry_and_persist_without_agent_death(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "concurrent-usage.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    first_context = _context()
    second_context = replace(first_context, execution_id="execution-2")
    try:
        async with session_factory() as session:
            async with session.begin():
                session.add(
                    RunModel(
                        id=first_context.run_id,
                        repo_name="usage-repo",
                        status="active",
                        execution_mode="graph",
                        created_at=datetime(2026, 1, 1, tzinfo=UTC),
                        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                    )
                )

        usage = [ModelTokenUsage(model="model-a", gen_ai_usage_input_tokens=10)]
        first = GraphController(
            session_factory, FakeClock(), SequentialIdGenerator(), auto_dispatch=False
        )
        second = GraphController(
            session_factory, FakeClock(), SequentialIdGenerator(), auto_dispatch=False
        )
        results = await asyncio.gather(
            first.record_node_usage(first_context, usage),
            second.record_node_usage(second_context, usage),
        )

        assert all(result.events for result in results)
        async with session_factory() as session:
            events = await GraphEventStore(session).read_run(first_context.run_id)
            run = await session.get(RunModel, first_context.run_id)

        assert [event.event_type for event in events] == [
            "node_usage_recorded",
            "node_usage_recorded",
        ]
        assert run is not None and len(run.token_usage_by_model or []) == 2
        assert all(event.event_type != "agent_died" for event in events)
    finally:
        await engine.dispose()
