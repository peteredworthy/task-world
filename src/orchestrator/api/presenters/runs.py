"""Run response presenters."""

from __future__ import annotations

from typing import Any

from orchestrator.api.schemas.runs import (
    RunTraceAttempt,
    RunTracePhase,
    RunTraceResponse,
)
from orchestrator.api.schemas.tasks import (
    ActionLogEntrySchema,
    ActionLogSchema,
    AttemptSchema,
    GradeSnapshotItemSchema,
    ModelTokenUsageSchema,
    ToolResultDetailSchema,
    ToolUseDetailSchema,
    TurnMetricsSchema,
)
from orchestrator.state import Run
from orchestrator.state.models import ModelTokenUsage


def compute_run_totals_from_attempts(
    run: Run,
) -> tuple[int, int, int, int, int, list[ModelTokenUsage]]:
    """Aggregate run-level token and timing metrics by summing attempt data.

    Used as a fallback when run-level DB totals were not accumulated (e.g. a bug
    caused the projector to skip the update, or the result event overwrote real
    token counts with zeros).

    Priority for token data:
      1. attempt.token_usage_by_model — has embedded cost rates, most accurate
      2. attempt.action_log totals — raw counts, no cost rates
      3. attempt.metrics flat fields — least preferred

    Returns (tokens_read, tokens_write, tokens_cache, duration_ms, num_actions, usage_list).
    """
    merged_usage: dict[str, ModelTokenUsage] = {}
    tokens_read_fallback = 0
    tokens_write_fallback = 0
    tokens_cache_fallback = 0
    duration_ms = 0
    num_actions = 0

    for step in run.steps:
        for task in step.tasks:
            for attempt in task.attempts:
                has_per_model_data = bool(attempt.token_usage_by_model)

                for usage in attempt.token_usage_by_model:
                    model = usage.model
                    if model in merged_usage:
                        existing = merged_usage[model]
                        merged_usage[model] = ModelTokenUsage(
                            model=model,
                            cache_read_tokens=existing.cache_read_tokens + usage.cache_read_tokens,
                            cache_creation_tokens=existing.cache_creation_tokens
                            + usage.cache_creation_tokens,
                            input_tokens=existing.input_tokens + usage.input_tokens,
                            output_tokens=existing.output_tokens + usage.output_tokens,
                            cost_per_m_cache_read=existing.cost_per_m_cache_read
                            or usage.cost_per_m_cache_read,
                            cost_per_m_cache_creation=existing.cost_per_m_cache_creation
                            or usage.cost_per_m_cache_creation,
                            cost_per_m_input=existing.cost_per_m_input or usage.cost_per_m_input,
                            cost_per_m_output=existing.cost_per_m_output or usage.cost_per_m_output,
                        )
                    else:
                        merged_usage[model] = ModelTokenUsage(
                            model=model,
                            cache_read_tokens=usage.cache_read_tokens,
                            cache_creation_tokens=usage.cache_creation_tokens,
                            input_tokens=usage.input_tokens,
                            output_tokens=usage.output_tokens,
                            cost_per_m_cache_read=usage.cost_per_m_cache_read,
                            cost_per_m_cache_creation=usage.cost_per_m_cache_creation,
                            cost_per_m_input=usage.cost_per_m_input,
                            cost_per_m_output=usage.cost_per_m_output,
                        )

                if attempt.action_log is not None:
                    al = attempt.action_log
                    duration_ms += al.total_duration_ms
                    num_actions += sum(1 for e in al.entries if e.kind.value == "tool_use")
                    if not has_per_model_data:
                        al_input = al.total_input_tokens
                        al_output = al.total_output_tokens
                        al_cache_read = al.total_cache_read_tokens
                        al_cache_creation = al.total_cache_creation_tokens
                        if not al_input and not al_output:
                            # Aggregate wasn't populated; recover from per-entry metrics.
                            for entry in al.entries:
                                if entry.metrics is not None:
                                    al_input += entry.metrics.input_tokens
                                    al_output += entry.metrics.output_tokens
                                    al_cache_read += entry.metrics.cache_read_tokens
                                    al_cache_creation += entry.metrics.cache_creation_tokens
                        tokens_read_fallback += al_input
                        tokens_write_fallback += al_output
                        tokens_cache_fallback += al_cache_read + al_cache_creation
                else:
                    duration_ms += attempt.metrics.duration_ms
                    num_actions += attempt.metrics.num_actions
                    if not has_per_model_data:
                        tokens_read_fallback += attempt.metrics.tokens_read
                        tokens_write_fallback += attempt.metrics.tokens_write
                        tokens_cache_fallback += attempt.metrics.tokens_cache

    usage_list = list(merged_usage.values())
    if usage_list:
        tokens_read = sum(u.input_tokens for u in usage_list)
        tokens_write = sum(u.output_tokens for u in usage_list)
        tokens_cache = sum(u.cache_read_tokens + u.cache_creation_tokens for u in usage_list)
    else:
        tokens_read = tokens_read_fallback
        tokens_write = tokens_write_fallback
        tokens_cache = tokens_cache_fallback

    return tokens_read, tokens_write, tokens_cache, duration_ms, num_actions, usage_list


def token_usage_to_schema(usage: Any) -> ModelTokenUsageSchema:
    return ModelTokenUsageSchema(
        model=usage.model,
        cache_read_tokens=usage.cache_read_tokens,
        cache_creation_tokens=usage.cache_creation_tokens,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_per_m_cache_read=usage.cost_per_m_cache_read,
        cost_per_m_cache_creation=usage.cost_per_m_cache_creation,
        cost_per_m_input=usage.cost_per_m_input,
        cost_per_m_output=usage.cost_per_m_output,
        total_cost_usd=round(usage.total_cost_usd, 6),
    )


def action_log_to_schema(action_log: Any | None) -> ActionLogSchema | None:
    if action_log is None:
        return None

    return ActionLogSchema(
        entries=[
            ActionLogEntrySchema(
                sequence_num=entry.sequence_num,
                kind=entry.kind.value,
                timestamp=entry.timestamp,
                text=entry.text,
                tool_use=ToolUseDetailSchema(
                    tool_use_id=entry.tool_use.tool_use_id,
                    tool_name=entry.tool_use.tool_name,
                    arguments=entry.tool_use.arguments,
                    summary=entry.tool_use.summary,
                )
                if entry.tool_use
                else None,
                tool_result=ToolResultDetailSchema(
                    tool_use_id=entry.tool_result.tool_use_id,
                    output=entry.tool_result.output,
                    exit_code=entry.tool_result.exit_code,
                    success=entry.tool_result.success,
                    output_length=entry.tool_result.output_length,
                )
                if entry.tool_result
                else None,
                metrics=TurnMetricsSchema(
                    input_tokens=entry.metrics.input_tokens,
                    output_tokens=entry.metrics.output_tokens,
                    cache_read_tokens=entry.metrics.cache_read_tokens,
                    cache_creation_tokens=entry.metrics.cache_creation_tokens,
                    cost_usd=entry.metrics.cost_usd,
                )
                if entry.metrics
                else None,
                raw_type=entry.raw_type,
            )
            for entry in action_log.entries
        ],
        session_id=action_log.session_id,
        agent_model=action_log.agent_model,
        tools_available=action_log.tools_available,
        total_turns=action_log.total_turns,
        total_cost_usd=action_log.total_cost_usd,
        total_duration_ms=action_log.total_duration_ms,
        total_input_tokens=action_log.total_input_tokens,
        total_output_tokens=action_log.total_output_tokens,
        total_cache_read_tokens=action_log.total_cache_read_tokens,
        total_cache_creation_tokens=action_log.total_cache_creation_tokens,
    )


def attempt_to_schema(attempt: Any) -> AttemptSchema:
    return AttemptSchema(
        id=attempt.id,
        attempt_num=attempt.attempt_num,
        started_at=attempt.started_at,
        completed_at=attempt.completed_at,
        builder_prompt=attempt.builder_prompt,
        verifier_prompt=attempt.verifier_prompt,
        verifier_comment=attempt.verifier_comment,
        outcome=attempt.outcome,
        metrics=attempt.metrics.model_dump(mode="json"),
        grade_snapshot=[
            GradeSnapshotItemSchema(
                req_id=snapshot.req_id,
                grade=snapshot.grade,
                grade_reason=snapshot.grade_reason,
                note=snapshot.note,
            )
            for snapshot in attempt.grade_snapshot
        ],
        auto_verify_results=attempt.auto_verify_results,
        token_usage_by_model=[
            token_usage_to_schema(usage) for usage in attempt.token_usage_by_model
        ],
        agent_runner_type=attempt.agent_runner_type.value if attempt.agent_runner_type else None,
        agent_model=attempt.agent_model,
        agent_settings=attempt.agent_settings,
        error=attempt.error,
        has_output=bool(attempt.agent_output),
        has_action_log=bool(attempt.action_log),
        start_commit=attempt.start_commit,
        end_commit=attempt.end_commit,
    )


def run_to_trace_response(run: Run) -> RunTraceResponse:
    trace_attempts: list[RunTraceAttempt] = []
    for step_index, step in enumerate(run.steps):
        for task in step.tasks:
            for attempt in task.attempts:
                action_log_schema = action_log_to_schema(attempt.action_log)
                action_entries = attempt.action_log.entries if attempt.action_log else []
                phases: list[RunTracePhase] = []
                if attempt.builder_prompt or action_entries:
                    phases.append(
                        RunTracePhase(
                            phase="builder",
                            prompt=attempt.builder_prompt,
                            message_count=len(action_entries),
                            action_sequence_start=action_entries[0].sequence_num
                            if action_entries
                            else None,
                            action_sequence_end=action_entries[-1].sequence_num
                            if action_entries
                            else None,
                        )
                    )
                if attempt.verifier_prompt or attempt.verifier_comment:
                    phases.append(
                        RunTracePhase(
                            phase="verifier",
                            prompt=attempt.verifier_prompt,
                            note=attempt.verifier_comment,
                        )
                    )
                if not phases:
                    phases.append(RunTracePhase(phase="builder"))
                trace_attempts.append(
                    RunTraceAttempt(
                        step_index=step_index,
                        step_id=step.id,
                        step_config_id=step.config_id,
                        step_title=step.title,
                        task_id=task.id,
                        task_config_id=task.config_id,
                        task_title=task.title,
                        task_status=task.status.value,
                        task_current_attempt=task.current_attempt,
                        task_max_attempts=task.max_attempts,
                        attempt=attempt_to_schema(attempt),
                        phases=phases,
                        action_log=action_log_schema,
                    )
                )

    tokens_read = run.total_tokens_read
    tokens_write = run.total_tokens_write
    tokens_cache = run.total_tokens_cache
    duration_ms = run.total_duration_ms
    num_actions = run.total_num_actions
    usage = run.token_usage_by_model

    if not tokens_read and not tokens_write and not usage:
        tokens_read, tokens_write, tokens_cache, duration_ms, num_actions, usage = (
            compute_run_totals_from_attempts(run)
        )

    return RunTraceResponse(
        run_id=run.id,
        total_tokens_read=tokens_read,
        total_tokens_write=tokens_write,
        total_tokens_cache=tokens_cache,
        total_duration_ms=duration_ms,
        total_num_actions=num_actions,
        token_usage_by_model=[token_usage_to_schema(u) for u in usage],
        attempts=trace_attempts,
    )


__all__ = [
    "action_log_to_schema",
    "attempt_to_schema",
    "compute_run_totals_from_attempts",
    "run_to_trace_response",
    "token_usage_to_schema",
]
