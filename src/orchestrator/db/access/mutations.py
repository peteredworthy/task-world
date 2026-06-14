"""Internal legacy database mutation helpers.

These helpers mutate read-model tables directly and are kept for narrowly
scoped compatibility tests and migration-era utilities. Runtime workflow paths
should use events_v2 command handlers and projectors instead.
"""

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from orchestrator.db.access.repositories import run_model_to_domain, run_to_model
from orchestrator.db.orm.models import (
    AttemptModel,
    ClarificationRequestModel,
    ClarificationResponseModel,
    RunModel,
    StepModel,
    TaskModel,
)
from orchestrator.state.errors import RunNotFoundError
from orchestrator.state.models import Run
from orchestrator.workflow import ClarificationRequest, ClarificationResponse


async def save_run(session: AsyncSession, run: Run) -> Run:
    """Persist a Run via session.merge for internal legacy compatibility tests."""
    model = run_to_model(run)
    merged = await session.merge(model)
    await session.flush()
    return run_model_to_domain(merged)


async def delete_run(session: AsyncSession, run_id: str) -> None:
    """Delete a run by ID. Raises RunNotFoundError if not found."""
    result = await session.execute(select(RunModel).where(RunModel.id == run_id))
    model = result.scalar_one_or_none()
    if model is None:
        raise RunNotFoundError(run_id)
    await session.delete(model)
    await session.flush()


def merge_token_usage_into_run(
    run_model: Any,
    *,
    tokens_read: int | None = None,
    tokens_write: int | None = None,
    tokens_cache: int | None = None,
    duration_ms: int | None = None,
    num_actions: int | None = None,
    token_usage_by_model: Any = None,
) -> None:
    """Accumulate one agent execution's usage into a run's running totals.

    Carrier-agnostic and the single home for run-level token accounting: the
    legacy attempt path (``update_latest_attempt``) and the graph dispatch path
    (via an injected usage callback) both call this, so token/cost numbers are
    computed identically regardless of which carrier ran the agent. No-op when
    ``run_model`` is None.
    """
    if run_model is None:
        return
    if tokens_read is not None:
        run_model.total_tokens_read = (run_model.total_tokens_read or 0) + tokens_read
    if tokens_write is not None:
        run_model.total_tokens_write = (run_model.total_tokens_write or 0) + tokens_write
    if tokens_cache is not None:
        run_model.total_tokens_cache = (run_model.total_tokens_cache or 0) + tokens_cache
    if duration_ms is not None:
        run_model.total_duration_ms = (run_model.total_duration_ms or 0) + duration_ms
    if num_actions is not None:
        run_model.total_num_actions = (run_model.total_num_actions or 0) + num_actions

    if token_usage_by_model is not None and len(token_usage_by_model) > 0:
        existing = cast("list[dict[str, Any]]", run_model.token_usage_by_model or [])
        merged: list[dict[str, Any]] = [dict(e) for e in existing]
        idx_by_model = {entry["model"]: i for i, entry in enumerate(merged)}
        for usage in token_usage_by_model:
            usage_dict = (
                usage.model_dump(mode="json") if hasattr(usage, "model_dump") else dict(usage)
            )
            model_name = usage_dict["model"]
            if model_name in idx_by_model:
                prev = merged[idx_by_model[model_name]]
                merged[idx_by_model[model_name]] = {
                    **prev,
                    "input_tokens": prev.get("input_tokens", 0) + usage_dict.get("input_tokens", 0),
                    "output_tokens": prev.get("output_tokens", 0)
                    + usage_dict.get("output_tokens", 0),
                    "cache_read_tokens": prev.get("cache_read_tokens", 0)
                    + usage_dict.get("cache_read_tokens", 0),
                    "cache_creation_tokens": prev.get("cache_creation_tokens", 0)
                    + usage_dict.get("cache_creation_tokens", 0),
                }
            else:
                merged.append(usage_dict)
                idx_by_model[model_name] = len(merged) - 1
        run_model.token_usage_by_model = merged


async def update_latest_attempt(
    session: AsyncSession,
    task_id: str,
    *,
    output_lines: list[str] | None = None,
    error: str | None = None,
    outcome: str | None = None,
    completed_at: datetime | None = None,
    auto_verify_results: list[dict[str, Any]] | None = None,
    tokens_read: int | None = None,
    tokens_write: int | None = None,
    tokens_cache: int | None = None,
    duration_ms: int | None = None,
    num_actions: int | None = None,
    new_task_status: Any = None,
    status: Any = None,
    metrics: Any = None,
    token_usage_by_model: Any = None,
    action_log: Any = None,
    builder_prompt: str | None = None,
    verifier_prompt: str | None = None,
) -> None:
    """Update the latest attempt directly for internal legacy compatibility tests."""
    result = await session.execute(
        select(AttemptModel)
        .where(AttemptModel.task_id == task_id)
        .order_by(AttemptModel.attempt_num.desc())
        .limit(1)
        .options(
            selectinload(AttemptModel.task).selectinload(TaskModel.step).selectinload(StepModel.run)
        )
    )
    attempt = result.scalar_one_or_none()
    resolved_status = new_task_status if new_task_status is not None else status
    if attempt is None:
        if resolved_status is not None:
            await session.execute(
                sql_update(TaskModel)
                .where(TaskModel.id == task_id)
                .values(status=getattr(resolved_status, "value", resolved_status))
            )
            await session.flush()
        return

    if output_lines is not None:
        new_text = "\n".join(output_lines)
        if attempt.agent_output:
            combined = f"{attempt.agent_output}\n{new_text}"
            attempt.agent_output = "\n".join(combined.splitlines()[-10000:])
        else:
            attempt.agent_output = "\n".join(output_lines[-10000:])
    if error is not None:
        attempt.error = error
    if outcome is not None:
        attempt.outcome = outcome
    if completed_at is not None:
        attempt.completed_at = completed_at
    if auto_verify_results is not None:
        attempt.auto_verify_results = auto_verify_results
    if action_log is not None:
        attempt.action_log_json = (
            action_log.model_dump(mode="json") if hasattr(action_log, "model_dump") else action_log
        )
    if builder_prompt is not None:
        attempt.builder_prompt = builder_prompt
    if verifier_prompt is not None:
        attempt.verifier_prompt = verifier_prompt

    effective_tokens_read = tokens_read
    effective_tokens_write = tokens_write
    effective_tokens_cache = tokens_cache
    effective_duration_ms = duration_ms
    effective_num_actions = num_actions
    if metrics is not None:
        effective_tokens_read = (effective_tokens_read or 0) + metrics.tokens_read
        effective_tokens_write = (effective_tokens_write or 0) + metrics.tokens_write
        effective_tokens_cache = (effective_tokens_cache or 0) + metrics.tokens_cache
        effective_duration_ms = (effective_duration_ms or 0) + metrics.duration_ms
        effective_num_actions = (effective_num_actions or 0) + metrics.num_actions

    if effective_tokens_read is not None:
        attempt.tokens_read = (attempt.tokens_read or 0) + effective_tokens_read
    if effective_tokens_write is not None:
        attempt.tokens_write = (attempt.tokens_write or 0) + effective_tokens_write
    if effective_tokens_cache is not None:
        attempt.tokens_cache = (attempt.tokens_cache or 0) + effective_tokens_cache
    if effective_duration_ms is not None:
        attempt.duration_ms = (attempt.duration_ms or 0) + effective_duration_ms
    if effective_num_actions is not None:
        attempt.num_actions = (attempt.num_actions or 0) + effective_num_actions

    run_model = attempt.task.step.run if attempt.task and attempt.task.step else None
    merge_token_usage_into_run(
        run_model,
        tokens_read=effective_tokens_read,
        tokens_write=effective_tokens_write,
        tokens_cache=effective_tokens_cache,
        duration_ms=effective_duration_ms,
        num_actions=effective_num_actions,
        token_usage_by_model=token_usage_by_model,
    )

    if resolved_status is not None:
        await session.execute(
            sql_update(TaskModel)
            .where(TaskModel.id == task_id)
            .values(status=getattr(resolved_status, "value", resolved_status))
        )
    await session.flush()


async def update_parent_oversight_facts(
    session: AsyncSession,
    run_id: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Merge oversight facts directly for internal legacy compatibility tests."""
    from orchestrator.db.projections.run_state import merge_oversight_patch

    result = await session.execute(select(RunModel).where(RunModel.id == run_id))
    run_model = result.scalar_one_or_none()
    if run_model is None:
        return {}
    current_state: dict[str, Any] = dict(run_model.oversight_state or {})
    merged = merge_oversight_patch(current_state, patch)
    run_model.oversight_state = merged  # delegation-boundary: ignore
    await session.flush()
    return merged


async def create_clarification_request(
    session: AsyncSession,
    request: ClarificationRequest,
) -> ClarificationRequest:
    """Persist a new clarification request."""
    model = ClarificationRequestModel(
        id=request.id,
        run_id=request.run_id,
        task_id=request.task_id,
        attempt_num=request.attempt_num,
        questions=[q.model_dump(mode="json") for q in request.questions],
        created_at=request.created_at,
        responded_at=request.responded_at,
    )
    session.add(model)
    await session.flush()
    return request


async def persist_clarification_response(
    session: AsyncSession,
    response: ClarificationResponse,
) -> None:
    """Save a clarification response and mark the request as responded."""
    model = ClarificationResponseModel(
        id=str(uuid.uuid4()),
        request_id=response.request_id,
        answers=[a.model_dump(mode="json") for a in response.answers],
        responded_by=response.answers[0].answered_by if response.answers else "unknown",
        responded_at=response.responded_at,
    )
    session.add(model)

    result = await session.execute(
        select(ClarificationRequestModel).where(ClarificationRequestModel.id == response.request_id)
    )
    request_model = result.scalar_one_or_none()
    if request_model:
        request_model.responded_at = response.responded_at

    await session.flush()
