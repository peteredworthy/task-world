"""Carrier-agnostic agent token-usage extraction.

A single place to turn an agent ``ExecutionResult`` into ``ExecutionMetrics`` +
per-model ``ModelTokenUsage``, so token/cost accounting is identical no matter
which carrier ran the agent — the legacy attempt path (``PhaseHandler``) and the
graph dispatch path (via an injected usage callback) both call this.
"""

from __future__ import annotations

from typing import Any

from orchestrator.runners.costs import calculate_model_usage_cost, resolve_model_costs
from orchestrator.runners.types import ExecutionMetrics
from orchestrator.state import ActionLog, ModelTokenUsage


def _canonical_input_tokens(
    input_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    *,
    includes_cache: bool,
) -> int:
    """Normalize provider usage to cache-inclusive OTel input tokens."""
    if includes_cache:
        return input_tokens
    return input_tokens + cache_read_tokens + cache_creation_tokens


def _usage_fact(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    input_tokens_include_cache: bool,
) -> ModelTokenUsage:
    """Build one immutable execution x model fact from one pricing resolution."""
    canonical_input = _canonical_input_tokens(
        input_tokens,
        cache_read_tokens,
        cache_creation_tokens,
        includes_cache=input_tokens_include_cache,
    )
    resolution = resolve_model_costs(model)
    return ModelTokenUsage(
        model=model,
        gen_ai_usage_input_tokens=canonical_input,
        gen_ai_usage_output_tokens=output_tokens,
        gen_ai_usage_cache_read_input_tokens=cache_read_tokens,
        gen_ai_usage_cache_creation_input_tokens=cache_creation_tokens,
        rate_missing=resolution.rate_missing,
        cost_usd=calculate_model_usage_cost(
            input_tokens=canonical_input,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read_tokens,
            cache_creation_input_tokens=cache_creation_tokens,
            resolution=resolution,
        ),
    )


def extract_metrics_and_usage(
    result: Any,
) -> tuple[ExecutionMetrics, list[ModelTokenUsage]]:
    """Extract ExecutionMetrics and per-model token usage from an execution result.

    Builds append-only ModelTokenUsage facts for parent and sub-agent executions.
    Provider parser semantics identify whether their raw input already includes
    cache components; raw wire fields remain unchanged at parser boundaries.
    """
    metrics = result.metrics
    usage_by_model: list[ModelTokenUsage] = []

    if result.action_log is not None:
        al: ActionLog = result.action_log
        computed_input = al.gen_ai_usage_input_tokens
        computed_output = al.gen_ai_usage_output_tokens
        computed_cache_read = al.gen_ai_usage_cache_read_input_tokens
        computed_cache_creation = al.gen_ai_usage_cache_creation_input_tokens

        if not computed_input and not computed_output:
            # Aggregate wasn't populated (e.g. result event reported zero);
            # recover from per-entry turn metrics instead.
            for entry in al.entries:
                if entry.metrics is not None:
                    computed_input += entry.metrics.gen_ai_usage_input_tokens
                    computed_output += entry.metrics.gen_ai_usage_output_tokens
                    computed_cache_read += entry.metrics.gen_ai_usage_cache_read_input_tokens
                    computed_cache_creation += (
                        entry.metrics.gen_ai_usage_cache_creation_input_tokens
                    )

        if computed_input or computed_output or computed_cache_read or computed_cache_creation:
            usage_by_model.append(
                _usage_fact(
                    model=al.agent_model or "unknown",
                    input_tokens=computed_input,
                    output_tokens=computed_output,
                    cache_read_tokens=computed_cache_read,
                    cache_creation_tokens=computed_cache_creation,
                    input_tokens_include_cache=al.input_tokens_include_cache,
                )
            )

        for sa in al.sub_agents:
            if not (
                sa.gen_ai_usage_input_tokens
                or sa.gen_ai_usage_output_tokens
                or sa.gen_ai_usage_cache_read_input_tokens
                or sa.gen_ai_usage_cache_creation_input_tokens
            ):
                continue
            usage_by_model.append(
                _usage_fact(
                    model=sa.model or "unknown",
                    input_tokens=sa.gen_ai_usage_input_tokens,
                    output_tokens=sa.gen_ai_usage_output_tokens,
                    cache_read_tokens=sa.gen_ai_usage_cache_read_input_tokens,
                    cache_creation_tokens=sa.gen_ai_usage_cache_creation_input_tokens,
                    input_tokens_include_cache=sa.input_tokens_include_cache,
                )
            )

        if usage_by_model:
            # Build legacy flat metrics from the full per-model breakdown.
            metrics = ExecutionMetrics(
                gen_ai_usage_input_tokens=sum(u.gen_ai_usage_input_tokens for u in usage_by_model),
                gen_ai_usage_output_tokens=sum(
                    u.gen_ai_usage_output_tokens for u in usage_by_model
                ),
                gen_ai_usage_cache_read_input_tokens=sum(
                    u.gen_ai_usage_cache_read_input_tokens
                    + u.gen_ai_usage_cache_creation_input_tokens
                    for u in usage_by_model
                ),
                duration_ms=al.total_duration_ms,
                num_actions=sum(1 for e in al.entries if e.kind.value == "tool_use"),
            )

    return metrics, usage_by_model
