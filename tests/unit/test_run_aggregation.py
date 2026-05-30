"""Unit tests for run-level token_usage_by_model accumulation via update_latest_attempt.

Tests the repository's update_latest_attempt method to verify that per-model
token usage is correctly accumulated at both the attempt and run level.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from orchestrator.db import Base, AttemptModel, RunModel, RunRepository, StepModel, TaskModel
from orchestrator.db.access.mutations import update_latest_attempt
from orchestrator.state.models import ModelTokenUsage, AttemptMetrics

_NOW = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def session(tmp_path) -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _make_run_graph(
    run_id: str = "run-1",
    task_id: str = "task-1",
    attempt_id: str = "att-1",
) -> RunModel:
    """Build a RunModel → StepModel → TaskModel → AttemptModel hierarchy."""
    run = RunModel(
        id=run_id,
        repo_name="test-repo",
        status="active",
        runner_config={},
        config={},
        created_at=_NOW,
        updated_at=_NOW,
        total_tokens_read=0,
        total_tokens_write=0,
        total_tokens_cache=0,
    )
    step = StepModel(
        id=f"{run_id}-step",
        run_id=run_id,
        config_id="S-01",
        order_index=0,
    )
    task = TaskModel(
        id=task_id,
        step_id=f"{run_id}-step",
        config_id="T-01",
        order_index=0,
        status="building",
        checklist=[],
    )
    attempt = AttemptModel(
        id=attempt_id,
        task_id=task_id,
        attempt_num=1,
        started_at=_NOW,
    )
    task.attempts.append(attempt)
    step.tasks.append(task)
    run.steps.append(step)
    return run


# ---------------------------------------------------------------------------
# R7 — multiple attempts with different models both appear in run total
# ---------------------------------------------------------------------------


async def test_two_different_models_both_appear_in_run(session: AsyncSession) -> None:
    """Calling update_latest_attempt twice with different models yields both in run total."""
    run = _make_run_graph()
    session.add(run)
    await session.flush()

    repo = RunRepository(session)
    task_id = "task-1"

    # First call — Sonnet
    await update_latest_attempt(
        repo.session,
        task_id,
        token_usage_by_model=[
            ModelTokenUsage(
                model="claude-sonnet-4-6",
                input_tokens=1_000,
                output_tokens=100,
                cost_per_m_input=3.0,
                cost_per_m_output=15.0,
            )
        ],
    )

    # Second call — Haiku
    await update_latest_attempt(
        repo.session,
        task_id,
        token_usage_by_model=[
            ModelTokenUsage(
                model="claude-haiku-4-5",
                input_tokens=2_000,
                output_tokens=200,
                cost_per_m_input=0.8,
                cost_per_m_output=4.0,
            )
        ],
    )

    # Reload from DB
    session.expire_all()
    result = await session.execute(select(RunModel).where(RunModel.id == "run-1"))
    run_model = result.scalar_one()

    assert run_model.token_usage_by_model is not None
    usage_by_model = {u["model"]: u for u in run_model.token_usage_by_model}

    assert "claude-sonnet-4-6" in usage_by_model, "Sonnet should appear in run totals"
    assert "claude-haiku-4-5" in usage_by_model, "Haiku should appear in run totals"
    assert usage_by_model["claude-sonnet-4-6"]["input_tokens"] == 1_000
    assert usage_by_model["claude-sonnet-4-6"]["output_tokens"] == 100
    assert usage_by_model["claude-haiku-4-5"]["input_tokens"] == 2_000
    assert usage_by_model["claude-haiku-4-5"]["output_tokens"] == 200


# ---------------------------------------------------------------------------
# R8 — same model used across multiple calls: tokens summed, rates preserved
# ---------------------------------------------------------------------------


async def test_same_model_tokens_are_summed_rates_preserved(session: AsyncSession) -> None:
    """Same model contributed across two calls: tokens sum, rates from first call."""
    run = _make_run_graph(run_id="run-2", task_id="task-2", attempt_id="att-2")
    session.add(run)
    await session.flush()

    repo = RunRepository(session)
    task_id = "task-2"

    # First call — 1000 input tokens at Sonnet rates
    await update_latest_attempt(
        repo.session,
        task_id,
        token_usage_by_model=[
            ModelTokenUsage(
                model="claude-sonnet-4-6",
                input_tokens=1_000,
                output_tokens=100,
                cost_per_m_input=3.0,
                cost_per_m_output=15.0,
            )
        ],
    )

    # Second call — 500 more input tokens for the same model (verifier phase)
    await update_latest_attempt(
        repo.session,
        task_id,
        token_usage_by_model=[
            ModelTokenUsage(
                model="claude-sonnet-4-6",
                input_tokens=500,
                output_tokens=50,
                cost_per_m_input=3.0,
                cost_per_m_output=15.0,
            )
        ],
    )

    session.expire_all()
    result = await session.execute(select(RunModel).where(RunModel.id == "run-2"))
    run_model = result.scalar_one()

    assert run_model.token_usage_by_model is not None
    usage_by_model = {u["model"]: u for u in run_model.token_usage_by_model}

    assert "claude-sonnet-4-6" in usage_by_model
    entry = usage_by_model["claude-sonnet-4-6"]
    # Tokens must be summed
    assert entry["input_tokens"] == 1_500, "input_tokens should be 1000 + 500"
    assert entry["output_tokens"] == 150, "output_tokens should be 100 + 50"
    # Rates must come from the first occurrence (not overwritten)
    assert entry["cost_per_m_input"] == pytest.approx(3.0)
    assert entry["cost_per_m_output"] == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# R9 — empty/None token_usage_by_model leaves run unchanged
# ---------------------------------------------------------------------------


async def test_empty_token_usage_leaves_run_unchanged(session: AsyncSession) -> None:
    """update_latest_attempt with empty/None token_usage_by_model does not modify run."""
    run = _make_run_graph(run_id="run-3", task_id="task-3", attempt_id="att-3")
    # Pre-set the run's token_usage_by_model
    run.token_usage_by_model = [
        {
            "model": "existing-model",
            "input_tokens": 5_000,
            "output_tokens": 500,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "cost_per_m_input": 2.5,
            "cost_per_m_output": 10.0,
            "cost_per_m_cache_read": 0.0,
            "cost_per_m_cache_creation": 0.0,
        }
    ]
    session.add(run)
    await session.flush()

    repo = RunRepository(session)
    task_id = "task-3"

    # Call with empty list — should be a no-op for token_usage_by_model
    await update_latest_attempt(repo.session, task_id, token_usage_by_model=[])

    session.expire_all()
    result = await session.execute(select(RunModel).where(RunModel.id == "run-3"))
    run_model = result.scalar_one()

    assert run_model.token_usage_by_model is not None
    assert len(run_model.token_usage_by_model) == 1, "existing entry should be unchanged"
    assert run_model.token_usage_by_model[0]["model"] == "existing-model"
    assert run_model.token_usage_by_model[0]["input_tokens"] == 5_000


async def test_none_token_usage_leaves_run_unchanged(session: AsyncSession) -> None:
    """update_latest_attempt with token_usage_by_model=None does not modify run."""
    run = _make_run_graph(run_id="run-4", task_id="task-4", attempt_id="att-4")
    run.token_usage_by_model = [
        {
            "model": "existing-model",
            "input_tokens": 3_000,
            "output_tokens": 300,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "cost_per_m_input": 2.5,
            "cost_per_m_output": 10.0,
            "cost_per_m_cache_read": 0.0,
            "cost_per_m_cache_creation": 0.0,
        }
    ]
    session.add(run)
    await session.flush()

    repo = RunRepository(session)

    # Call with None — default — should be a no-op for token_usage_by_model
    await update_latest_attempt(repo.session, "task-4", token_usage_by_model=None)

    session.expire_all()
    result = await session.execute(select(RunModel).where(RunModel.id == "run-4"))
    run_model = result.scalar_one()

    assert run_model.token_usage_by_model is not None
    assert run_model.token_usage_by_model[0]["input_tokens"] == 3_000


# ---------------------------------------------------------------------------
# R10 — run-level legacy fields (total_tokens_read, etc.) match per-model sum
# ---------------------------------------------------------------------------


async def test_run_legacy_fields_match_per_model_sum(session: AsyncSession) -> None:
    """Run-level total_tokens_read/write/cache are consistent with token_usage_by_model sum."""
    run = _make_run_graph(run_id="run-5", task_id="task-5", attempt_id="att-5")
    session.add(run)
    await session.flush()

    repo = RunRepository(session)
    task_id = "task-5"

    sonnet_input = 1_000_000
    sonnet_output = 100_000
    sonnet_cache = 200_000
    haiku_input = 500_000
    haiku_output = 50_000

    # Pass both metrics AND token_usage_by_model with consistent data
    metrics = AttemptMetrics(
        tokens_read=sonnet_input + haiku_input,
        tokens_write=sonnet_output + haiku_output,
        tokens_cache=sonnet_cache,
    )
    usage = [
        ModelTokenUsage(
            model="claude-sonnet-4-6",
            input_tokens=sonnet_input,
            output_tokens=sonnet_output,
            cache_read_tokens=sonnet_cache,
            cost_per_m_input=3.0,
            cost_per_m_output=15.0,
        ),
        ModelTokenUsage(
            model="claude-haiku-4-5",
            input_tokens=haiku_input,
            output_tokens=haiku_output,
            cost_per_m_input=0.8,
            cost_per_m_output=4.0,
        ),
    ]
    await update_latest_attempt(repo.session, task_id, metrics=metrics, token_usage_by_model=usage)

    session.expire_all()
    result = await session.execute(select(RunModel).where(RunModel.id == "run-5"))
    run_model = result.scalar_one()

    # Compute expected legacy totals from per-model breakdown
    by_model = run_model.token_usage_by_model or []
    total_input = sum(u["input_tokens"] for u in by_model)
    total_output = sum(u["output_tokens"] for u in by_model)
    total_cache = sum(u["cache_read_tokens"] for u in by_model)

    # Legacy fields should match sums of per-model data
    assert run_model.total_tokens_read == total_input, (
        f"total_tokens_read ({run_model.total_tokens_read}) should equal "
        f"sum of input_tokens across models ({total_input})"
    )
    assert run_model.total_tokens_write == total_output, (
        f"total_tokens_write ({run_model.total_tokens_write}) should equal "
        f"sum of output_tokens across models ({total_output})"
    )
    assert run_model.total_tokens_cache == total_cache, (
        f"total_tokens_cache ({run_model.total_tokens_cache}) should equal "
        f"sum of cache_read_tokens across models ({total_cache})"
    )
