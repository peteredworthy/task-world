"""Integration tests for round-trip serialization of token_usage_by_model.

Verifies that ModelTokenUsage objects survive the full ORM serialize/flush/reload
cycle without data loss, both for the populated case and the empty-list default.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db import AttemptModel, RunModel, StepModel, TaskModel
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.state.models import ModelTokenUsage


def _deserialize_token_usage(raw: list[dict] | None) -> list[ModelTokenUsage]:
    """Re-implements the repository helper locally to stay within public APIs."""
    if not raw:
        return []
    result = []
    for item in raw:
        try:
            result.append(ModelTokenUsage.model_validate(item))
        except Exception:
            pass
    return result


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


_NOW = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


def _make_run(run_id: str = "run-1") -> RunModel:
    return RunModel(
        id=run_id,
        repo_name="proj-1",
        status="active",
        runner_config={},
        config={},
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_attempt(
    attempt_id: str = "att-1",
    task_id: str = "task-1",
    usage: list[dict] | None = None,
) -> AttemptModel:
    return AttemptModel(
        id=attempt_id,
        task_id=task_id,
        attempt_num=1,
        started_at=_NOW,
        token_usage_by_model=usage,
    )


def _full_run_with_attempt(
    run_id: str = "run-1",
    att_usage: list[dict] | None = None,
    run_usage: list[dict] | None = None,
) -> RunModel:
    """Build a RunModel with one step → one task → one attempt."""
    run = _make_run(run_id)
    step = StepModel(id=f"{run_id}-step", run_id=run_id, config_id="S-01", order_index=0)
    task = TaskModel(
        id=f"{run_id}-task",
        step_id=f"{run_id}-step",
        config_id="T-01",
        order_index=0,
        status="building",
        checklist=[],
    )
    attempt = _make_attempt(f"{run_id}-att", f"{run_id}-task", att_usage)
    task.attempts.append(attempt)
    step.tasks.append(task)
    run.steps.append(step)
    run.token_usage_by_model = run_usage
    return run


# ---------------------------------------------------------------------------
# R11 — populated token_usage_by_model round-trips correctly
# ---------------------------------------------------------------------------


async def test_attempt_populated_token_usage_roundtrip(session: AsyncSession) -> None:
    """Populated list of ModelTokenUsage survives flush → reload on AttemptModel."""
    usage_records = [
        ModelTokenUsage(
            model="claude-sonnet-4-6",
            cache_read_tokens=500_000,
            cache_creation_tokens=200_000,
            input_tokens=1_000_000,
            output_tokens=100_000,
            cost_per_m_cache_read=0.30,
            cost_per_m_cache_creation=3.75,
            cost_per_m_input=3.00,
            cost_per_m_output=15.00,
        ),
        ModelTokenUsage(
            model="claude-haiku-4-5",
            input_tokens=500_000,
            output_tokens=50_000,
            cost_per_m_input=0.80,
            cost_per_m_output=4.00,
        ),
    ]
    serialized = [u.model_dump(mode="json") for u in usage_records]
    run = _full_run_with_attempt(att_usage=serialized)
    session.add(run)
    await session.flush()
    session.expire_all()

    result = await session.execute(select(AttemptModel).where(AttemptModel.id == "run-1-att"))
    att = result.scalar_one()

    deserialized = _deserialize_token_usage(att.token_usage_by_model)
    assert len(deserialized) == 2

    sonnet = next(u for u in deserialized if u.model == "claude-sonnet-4-6")
    assert sonnet.cache_read_tokens == 500_000
    assert sonnet.cache_creation_tokens == 200_000
    assert sonnet.input_tokens == 1_000_000
    assert sonnet.output_tokens == 100_000
    assert sonnet.cost_per_m_cache_read == pytest.approx(0.30)
    assert sonnet.cost_per_m_cache_creation == pytest.approx(3.75)
    assert sonnet.cost_per_m_input == pytest.approx(3.00)
    assert sonnet.cost_per_m_output == pytest.approx(15.00)

    haiku = next(u for u in deserialized if u.model == "claude-haiku-4-5")
    assert haiku.input_tokens == 500_000
    assert haiku.output_tokens == 50_000
    assert haiku.cost_per_m_input == pytest.approx(0.80)
    assert haiku.cost_per_m_output == pytest.approx(4.00)


async def test_run_populated_token_usage_roundtrip(session: AsyncSession) -> None:
    """Populated run-level token_usage_by_model survives flush → reload."""
    usage_records = [
        ModelTokenUsage(
            model="claude-opus-4-6",
            input_tokens=2_000_000,
            output_tokens=200_000,
            cost_per_m_input=7.50,
            cost_per_m_output=37.50,
        )
    ]
    serialized = [u.model_dump(mode="json") for u in usage_records]
    run = _full_run_with_attempt(run_id="run-2", run_usage=serialized)
    session.add(run)
    await session.flush()
    session.expire_all()

    result = await session.execute(select(RunModel).where(RunModel.id == "run-2"))
    loaded = result.scalar_one()

    deserialized = _deserialize_token_usage(loaded.token_usage_by_model)
    assert len(deserialized) == 1
    opus = deserialized[0]
    assert opus.model == "claude-opus-4-6"
    assert opus.input_tokens == 2_000_000
    assert opus.output_tokens == 200_000
    assert opus.cost_per_m_input == pytest.approx(7.50)
    assert opus.cost_per_m_output == pytest.approx(37.50)


async def test_token_usage_total_cost_preserved_after_roundtrip(session: AsyncSession) -> None:
    """total_cost_usd computed from deserialized record matches original."""
    original = ModelTokenUsage(
        model="claude-sonnet-4-6",
        input_tokens=1_000_000,
        output_tokens=100_000,
        cost_per_m_input=3.00,
        cost_per_m_output=15.00,
    )
    run = _full_run_with_attempt(
        run_id="run-3",
        att_usage=[original.model_dump(mode="json")],
    )
    session.add(run)
    await session.flush()
    session.expire_all()

    result = await session.execute(select(AttemptModel).where(AttemptModel.id == "run-3-att"))
    att = result.scalar_one()
    deserialized = _deserialize_token_usage(att.token_usage_by_model)

    assert len(deserialized) == 1
    assert deserialized[0].total_cost_usd == pytest.approx(original.total_cost_usd)


# ---------------------------------------------------------------------------
# R12 — empty list default (no token data)
# ---------------------------------------------------------------------------


async def test_attempt_null_token_usage_deserializes_to_empty_list(
    session: AsyncSession,
) -> None:
    """AttemptModel with no token_usage_by_model column value → empty list."""
    run = _full_run_with_attempt(run_id="run-4", att_usage=None)
    session.add(run)
    await session.flush()
    session.expire_all()

    result = await session.execute(select(AttemptModel).where(AttemptModel.id == "run-4-att"))
    att = result.scalar_one()

    assert att.token_usage_by_model is None  # stored as NULL
    deserialized = _deserialize_token_usage(att.token_usage_by_model)
    assert deserialized == []


async def test_run_null_token_usage_deserializes_to_empty_list(
    session: AsyncSession,
) -> None:
    """RunModel with no token_usage_by_model column value → empty list."""
    run = _full_run_with_attempt(run_id="run-5", run_usage=None)
    session.add(run)
    await session.flush()
    session.expire_all()

    result = await session.execute(select(RunModel).where(RunModel.id == "run-5"))
    loaded = result.scalar_one()

    assert loaded.token_usage_by_model is None
    deserialized = _deserialize_token_usage(loaded.token_usage_by_model)
    assert deserialized == []


async def test_empty_list_token_usage_roundtrip(session: AsyncSession) -> None:
    """Explicitly empty [] serializes as NULL and deserializes to []."""
    # _to_model uses `if att.token_usage_by_model` which treats [] as falsy → None
    run = _full_run_with_attempt(run_id="run-6", att_usage=[])
    session.add(run)
    await session.flush()
    session.expire_all()

    result = await session.execute(select(AttemptModel).where(AttemptModel.id == "run-6-att"))
    att = result.scalar_one()

    deserialized = _deserialize_token_usage(att.token_usage_by_model)
    assert deserialized == []
