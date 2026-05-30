"""Integration coverage for event-sourced AttemptStore persistence."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config.enums import Priority, RunStatus, TaskStatus
from orchestrator.db import (
    EventV2Model,
    ProjectionRegistry,
    RunRepository,
    RunStateProjector,
    TaskStateProjector,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.runners import AttemptStore
from orchestrator.runners.types import ExecutionMetrics
from orchestrator.state.models import (
    ActionLog,
    ChecklistItem,
    ModelTokenUsage,
    Run,
    StepState,
    TaskState,
)
from orchestrator.workflow import deserialize_event
from orchestrator.workflow.service import WorkflowService


@pytest.fixture
async def session_factory_fixture() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    yield factory
    await engine.dispose()


def _run_with_task() -> Run:
    now = datetime.now(timezone.utc)
    task = TaskState(
        id="attempt-store-task",
        config_id="T-01",
        status=TaskStatus.PENDING,
        checklist=[
            ChecklistItem(
                req_id="R1",
                desc="Requirement",
                priority=Priority.CRITICAL,
            )
        ],
        current_attempt=0,
        max_attempts=3,
    )
    return Run(
        id="attempt-store-run",
        repo_name="test-project",
        status=RunStatus.DRAFT,
        source_branch="main",
        agent_runner_config={"model": "gpt-test"},
        steps=[
            StepState(
                id="attempt-store-step",
                config_id="S-01",
                tasks=[task],
            )
        ],
        created_at=now,
        updated_at=now,
    )


async def _create_started_attempt(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        service = WorkflowService(session)
        await service.create_run(_run_with_task())
        await service.apply_start_run("attempt-store-run")
        await service.start_task("attempt-store-run", "attempt-store-task")


async def _stored_event_types(session: AsyncSession) -> list[str]:
    result = await session.execute(select(EventV2Model).order_by(EventV2Model.position))
    return [event.event_type for event in result.scalars()]


async def _rebuild_read_models_from_events(session: AsyncSession) -> None:
    result = await session.execute(select(EventV2Model).order_by(EventV2Model.position))
    stored_events = list(result.scalars())
    workflow_events = [
        deserialize_event(event.event_type, event.payload) for event in stored_events
    ]
    await session.execute(text("DELETE FROM attempts"))
    await session.execute(text("DELETE FROM tasks"))
    await session.execute(text("DELETE FROM steps"))
    await session.execute(text("DELETE FROM runs"))
    await session.execute(text("DELETE FROM projection_checkpoints"))
    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    await registry.rebuild_all(workflow_events, session)
    await session.flush()


async def test_attempt_store_appends_events_and_projects_attempt_and_run_totals(
    session_factory_fixture: async_sessionmaker[AsyncSession],
) -> None:
    session_factory = session_factory_fixture
    await _create_started_attempt(session_factory)

    store = AttemptStore(session_factory)
    await store.store_attempt_prompt(
        "attempt-store-run",
        "attempt-store-task",
        builder_prompt="builder prompt",
    )
    await store.store_attempt_output(
        "attempt-store-run",
        "attempt-store-task",
        ["line 1", "line 2"],
        error="agent warning",
        action_log=ActionLog(session_id="session-1", total_turns=2),
    )
    await store.store_attempt_metrics(
        "attempt-store-run",
        "attempt-store-task",
        ExecutionMetrics(
            tokens_read=10,
            tokens_write=20,
            tokens_cache=3,
            duration_ms=40,
            num_actions=5,
        ),
        token_usage_by_model=[ModelTokenUsage(model="gpt-test", input_tokens=7, output_tokens=11)],
    )

    async with session_factory() as session:
        run = await RunRepository(session).get("attempt-store-run")
        task = run.steps[0].tasks[0]
        attempt = task.attempts[-1]
        assert attempt.builder_prompt == "builder prompt"
        assert attempt.agent_output == "line 1\nline 2"
        assert attempt.error == "agent warning"
        assert attempt.action_log is not None
        assert attempt.action_log.session_id == "session-1"
        assert attempt.metrics.tokens_read == 10
        assert attempt.metrics.tokens_write == 20
        assert attempt.metrics.tokens_cache == 3
        assert attempt.metrics.duration_ms == 40
        assert attempt.metrics.num_actions == 5
        assert attempt.token_usage_by_model is not None
        assert attempt.token_usage_by_model[0].model == "gpt-test"
        assert attempt.token_usage_by_model[0].input_tokens == 7
        assert run.total_tokens_read == 10
        assert run.total_tokens_write == 20
        assert run.total_tokens_cache == 3
        assert run.total_duration_ms == 40
        assert run.total_num_actions == 5
        assert run.token_usage_by_model is not None
        assert run.token_usage_by_model[0].model == "gpt-test"
        assert run.token_usage_by_model[0].output_tokens == 11

        result = await session.execute(
            select(EventV2Model).where(EventV2Model.event_type == "attempt_updated")
        )
        attempt_update_payloads = [json.loads(event.payload) for event in result.scalars()]
        assert sum(1 for payload in attempt_update_payloads if payload.get("builder_prompt")) == 1
        assert sum(1 for payload in attempt_update_payloads if payload.get("output_lines")) == 1
        assert (
            sum(1 for payload in attempt_update_payloads if payload.get("tokens_read") == 10) == 1
        )


async def test_attempt_store_merges_token_usage_and_agent_metadata_via_events(
    session_factory_fixture: async_sessionmaker[AsyncSession],
) -> None:
    session_factory = session_factory_fixture
    await _create_started_attempt(session_factory)

    store = AttemptStore(session_factory)
    await store.store_attempt_metrics(
        "attempt-store-run",
        "attempt-store-task",
        ExecutionMetrics(tokens_read=1),
        token_usage_by_model=[ModelTokenUsage(model="gpt-test", input_tokens=2, output_tokens=3)],
    )
    await store.store_attempt_metrics(
        "attempt-store-run",
        "attempt-store-task",
        ExecutionMetrics(tokens_read=4),
        token_usage_by_model=[ModelTokenUsage(model="gpt-test", input_tokens=5, output_tokens=7)],
    )
    await store.persist_agent_metadata("attempt-store-run", {"pid": 1234})

    async with session_factory() as session:
        run = await RunRepository(session).get("attempt-store-run")
        assert run.total_tokens_read == 5
        assert run.agent_runner_config == {"model": "gpt-test", "pid": 1234}
        assert run.token_usage_by_model is not None
        usage = run.token_usage_by_model[0]
        assert usage.model == "gpt-test"
        assert usage.input_tokens == 7
        assert usage.output_tokens == 10

        result = await session.execute(
            select(EventV2Model)
            .where(EventV2Model.event_type == "run_metadata_updated")
            .order_by(EventV2Model.position)
        )
        metadata_event = result.scalar_one()
        payload = json.loads(metadata_event.payload)
        assert payload["runner_config_delta"] == {"pid": 1234}


async def test_attempt_store_events_rebuild_attempt_and_run_read_models(
    session_factory_fixture: async_sessionmaker[AsyncSession],
) -> None:
    session_factory = session_factory_fixture
    await _create_started_attempt(session_factory)

    store = AttemptStore(session_factory)
    await store.store_attempt_prompt(
        "attempt-store-run",
        "attempt-store-task",
        verifier_prompt="verifier prompt",
    )
    await store.store_attempt_output(
        "attempt-store-run",
        "attempt-store-task",
        ["replay line"],
        action_log=ActionLog(session_id="replay-session"),
    )
    await store.store_attempt_metrics(
        "attempt-store-run",
        "attempt-store-task",
        ExecutionMetrics(tokens_read=6, tokens_write=8, duration_ms=10),
        token_usage_by_model=[ModelTokenUsage(model="gpt-test", input_tokens=4, output_tokens=9)],
    )
    await store.persist_agent_metadata("attempt-store-run", {"pid": 5678})

    async with session_factory() as session:
        await _rebuild_read_models_from_events(session)
        run = await RunRepository(session).get("attempt-store-run")
        task = run.steps[0].tasks[0]
        attempt = task.attempts[-1]
        assert attempt.verifier_prompt == "verifier prompt"
        assert attempt.agent_output == "replay line"
        assert attempt.action_log is not None
        assert attempt.action_log.session_id == "replay-session"
        assert attempt.metrics.tokens_read == 6
        assert attempt.metrics.tokens_write == 8
        assert attempt.metrics.duration_ms == 10
        assert run.total_tokens_read == 6
        assert run.total_tokens_write == 8
        assert run.total_duration_ms == 10
        assert run.agent_runner_config == {"model": "gpt-test", "pid": 5678}
        assert run.token_usage_by_model is not None
        assert run.token_usage_by_model[0].input_tokens == 4
        assert run.token_usage_by_model[0].output_tokens == 9
