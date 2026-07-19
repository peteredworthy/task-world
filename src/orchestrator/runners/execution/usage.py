"""Carrier-agnostic agent token-usage extraction.

A single place to turn an agent ``ExecutionResult`` into ``ExecutionMetrics`` +
per-model ``ModelTokenUsage``, so token/cost accounting is identical no matter
which carrier ran the agent — the legacy attempt path (``PhaseHandler``) and the
graph dispatch path (via an injected usage callback) both call this.
"""

from __future__ import annotations

from typing import Any

from orchestrator.runners.costs import resolve_model_costs
from orchestrator.runners.types import ExecutionMetrics
from orchestrator.state.models import ModelTokenUsage


def extract_metrics_and_usage(
    result: Any,
) -> tuple[ExecutionMetrics, list[ModelTokenUsage]]:
    """Extract ExecutionMetrics and per-model token usage from an execution result.

    Builds a ModelTokenUsage entry for the parent model and each distinct
    sub-agent model, with cost rates looked up from model_costs.yaml. Falls back
    to per-turn metrics when the action-log aggregate was not populated.
    """
    from orchestrator.state.models import ActionLog

    metrics = result.metrics
    usage_by_model: list[ModelTokenUsage] = []

    if result.action_log is not None:
        al: ActionLog = result.action_log
        computed_input = al.total_input_tokens
        computed_output = al.total_output_tokens
        computed_cache_read = al.total_cache_read_tokens
        computed_cache_creation = al.total_cache_creation_tokens

        if not computed_input and not computed_output:
            # Aggregate wasn't populated (e.g. result event reported zero);
            # recover from per-entry turn metrics instead.
            for entry in al.entries:
                if entry.metrics is not None:
                    computed_input += entry.metrics.input_tokens
                    computed_output += entry.metrics.output_tokens
                    computed_cache_read += entry.metrics.cache_read_tokens
                    computed_cache_creation += entry.metrics.cache_creation_tokens

        if computed_input or computed_output:
            # Parent model
            parent_costs = resolve_model_costs(al.agent_model)
            usage_by_model.append(
                ModelTokenUsage(
                    model=al.agent_model or "unknown",
                    gen_ai_usage_cache_read_input_tokens=computed_cache_read,
                    gen_ai_usage_cache_creation_input_tokens=computed_cache_creation,
                    gen_ai_usage_input_tokens=computed_input,
                    gen_ai_usage_output_tokens=computed_output,
                    rate_missing=parent_costs.rate_missing,
                )
            )

            # Each sub-agent execution produces its own immutable usage fact.
            for sa in al.sub_agents:
                model = sa.model or "unknown"
                sa_costs = resolve_model_costs(model)
                usage_by_model.append(
                    ModelTokenUsage(
                        model=model,
                        gen_ai_usage_cache_read_input_tokens=sa.total_cache_read_tokens,
                        gen_ai_usage_cache_creation_input_tokens=sa.total_cache_creation_tokens,
                        gen_ai_usage_input_tokens=sa.total_input_tokens,
                        gen_ai_usage_output_tokens=sa.total_output_tokens,
                        rate_missing=sa_costs.rate_missing,
                    )
                )

            # Build legacy flat metrics from the full per-model breakdown
            metrics = ExecutionMetrics(
                tokens_read=sum(u.gen_ai_usage_input_tokens for u in usage_by_model),
                tokens_write=sum(u.gen_ai_usage_output_tokens for u in usage_by_model),
                tokens_cache=sum(
                    u.gen_ai_usage_cache_read_input_tokens
                    + u.gen_ai_usage_cache_creation_input_tokens
                    for u in usage_by_model
                ),
                duration_ms=al.total_duration_ms,
                num_actions=sum(1 for e in al.entries if e.kind.value == "tool_use"),
            )

    return metrics, usage_by_model
