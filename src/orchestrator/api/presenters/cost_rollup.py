"""Pure reduction of graph node-usage facts into cost rollups."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timezone

from orchestrator.api.schemas.cost_rollup import (
    CostRollupDimension,
    CostRollupFact,
    CostRollupResponse,
    CostRollupRow,
)


def _dimension_value(fact: CostRollupFact, dimension: CostRollupDimension) -> str | None:
    if dimension == "day":
        return fact.timestamp.astimezone(timezone.utc).date().isoformat()
    if dimension == "node_kind":
        return fact.node_kind
    if dimension == "model":
        return fact.model
    if dimension == "profile":
        return fact.profile
    return fact.run_id


def compute_cost_rollup(
    facts: Sequence[CostRollupFact],
    group_by: tuple[CostRollupDimension, ...],
    *,
    max_rows: int = 1000,
) -> CostRollupResponse:
    """Aggregate graph facts, retaining unknown-rate usage separately from cost."""
    if len(set(group_by)) != len(group_by):
        raise ValueError("group_by dimensions must be unique")

    grouped: dict[tuple[str | None, ...], list[CostRollupFact]] = {}
    for fact in facts:
        key = tuple(_dimension_value(fact, dimension) for dimension in group_by)
        if key not in grouped:
            if len(grouped) >= max_rows:
                raise ValueError(f"cost rollup exceeds maximum of {max_rows} groups")
            grouped[key] = []
        grouped[key].append(fact)

    rows: list[CostRollupRow] = []
    for key in sorted(
        grouped, key=lambda values: tuple("" if value is None else value for value in values)
    ):
        group_facts = grouped[key]
        execution_facts: dict[tuple[str, str], CostRollupFact] = {}
        missing_executions: set[tuple[str, str]] = set()
        for fact in group_facts:
            execution_identity = (fact.run_id, fact.execution_id)
            existing = execution_facts.get(execution_identity)
            if existing is None or fact.usage_index < existing.usage_index:
                execution_facts[execution_identity] = fact
            if fact.rate_missing:
                missing_executions.add(execution_identity)

        rows.append(
            CostRollupRow(
                dimensions=dict(zip(group_by, key, strict=True)),
                execution_count=len(execution_facts),
                gen_ai_usage_input_tokens=sum(f.gen_ai_usage_input_tokens for f in group_facts),
                gen_ai_usage_output_tokens=sum(f.gen_ai_usage_output_tokens for f in group_facts),
                gen_ai_usage_cache_read_input_tokens=sum(
                    f.gen_ai_usage_cache_read_input_tokens for f in group_facts
                ),
                gen_ai_usage_cache_creation_input_tokens=sum(
                    f.gen_ai_usage_cache_creation_input_tokens for f in group_facts
                ),
                gen_ai_usage_reasoning_output_tokens=sum(
                    f.gen_ai_usage_reasoning_output_tokens for f in group_facts
                ),
                latency_ms=sum(f.latency_ms for f in execution_facts.values()),
                num_actions=sum(f.num_actions for f in execution_facts.values()),
                cost_usd=sum(f.cost_usd for f in group_facts),
                rate_missing_execution_count=len(missing_executions),
                rate_missing_input_tokens=sum(
                    f.gen_ai_usage_input_tokens for f in group_facts if f.rate_missing
                ),
                rate_missing_output_tokens=sum(
                    f.gen_ai_usage_output_tokens for f in group_facts if f.rate_missing
                ),
                has_rate_missing=bool(missing_executions),
            )
        )
    return CostRollupResponse(group_by=group_by, rows=rows)
