"""Carrier-agnostic agent token-usage extraction.

A single place to turn an agent ``ExecutionResult`` into ``ExecutionMetrics`` +
per-model ``ModelTokenUsage``, so token/cost accounting is identical no matter
which carrier ran the agent — the legacy attempt path (``PhaseHandler``) and the
graph dispatch path (via an injected usage callback) both call this.
"""

from __future__ import annotations

from typing import Any

from orchestrator.runners.costs import get_model_costs
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
            parent_costs = get_model_costs(al.agent_model)
            usage_by_model.append(
                ModelTokenUsage(
                    model=al.agent_model or "unknown",
                    cache_read_tokens=computed_cache_read,
                    cache_creation_tokens=computed_cache_creation,
                    input_tokens=computed_input,
                    output_tokens=computed_output,
                    cost_per_m_cache_read=parent_costs["cost_per_m_cache_read"],
                    cost_per_m_cache_creation=parent_costs["cost_per_m_cache_creation"],
                    cost_per_m_input=parent_costs["cost_per_m_input"],
                    cost_per_m_output=parent_costs["cost_per_m_output"],
                )
            )

            # Sub-agent models (group by model name and sum)
            sa_by_model: dict[str, ModelTokenUsage] = {}
            for sa in al.sub_agents:
                model = sa.model or "unknown"
                if model not in sa_by_model:
                    sa_costs = get_model_costs(model)
                    sa_by_model[model] = ModelTokenUsage(
                        model=model,
                        cost_per_m_cache_read=sa_costs["cost_per_m_cache_read"],
                        cost_per_m_cache_creation=sa_costs["cost_per_m_cache_creation"],
                        cost_per_m_input=sa_costs["cost_per_m_input"],
                        cost_per_m_output=sa_costs["cost_per_m_output"],
                    )
                entry = sa_by_model[model]
                entry.cache_read_tokens += sa.total_cache_read_tokens
                entry.cache_creation_tokens += sa.total_cache_creation_tokens
                entry.input_tokens += sa.total_input_tokens
                entry.output_tokens += sa.total_output_tokens
            usage_by_model.extend(sa_by_model.values())

            # Build legacy flat metrics from the full per-model breakdown
            metrics = ExecutionMetrics(
                tokens_read=sum(u.input_tokens for u in usage_by_model),
                tokens_write=sum(u.output_tokens for u in usage_by_model),
                tokens_cache=sum(
                    u.cache_read_tokens + u.cache_creation_tokens for u in usage_by_model
                ),
                duration_ms=al.total_duration_ms,
                num_actions=sum(1 for e in al.entries if e.kind.value == "tool_use"),
            )

    return metrics, usage_by_model
