"""Schemas for graph-node usage cost rollups."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, cast

from pydantic import Field, model_validator

from orchestrator.api.schemas.base import ApiModel

CostRollupDimension = Literal["day", "node_kind", "model", "profile", "run"]
RunStatusFilter = Literal[
    "draft", "active", "paused", "stopping", "completed", "failed", "cancelled"
]
SelectableRunnerTypeFilter = Literal[
    "openhands_local", "openhands_docker", "cli_subprocess", "codex_server"
]


class CostRollupFilters(ApiModel):
    """SQL-level predicates for immutable graph usage facts."""

    statuses: tuple[RunStatusFilter, ...] = ()
    runner_types: tuple[SelectableRunnerTypeFilter, ...] = ()
    start: datetime | None = None
    end: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_time_filters(cls, value: object) -> object:
        """Normalize equally-aware bounds to UTC and reject mixed awareness."""
        if not isinstance(value, dict):
            return value
        data = dict(cast(dict[str, object], value))
        start = _parse_datetime(data.get("start"))
        end = _parse_datetime(data.get("end"))
        if start is not None and end is not None and (start.tzinfo is None) != (end.tzinfo is None):
            raise ValueError("'from' and 'to' must use the same timezone awareness")
        for field, timestamp in (("start", start), ("end", end)):
            if timestamp is not None:
                data[field] = (
                    timestamp.replace(tzinfo=timezone.utc)
                    if timestamp.tzinfo is None
                    else timestamp.astimezone(timezone.utc)
                )
        return data

    @model_validator(mode="after")
    def start_precedes_end(self) -> "CostRollupFilters":
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("'from' must be less than or equal to 'to'")
        return self


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class CostRollupFact(ApiModel):
    """Canonical usage values from one ``node_usage_recorded`` graph event."""

    run_id: str
    timestamp: datetime
    node_kind: str
    profile: str | None
    execution_id: str
    usage_index: int = Field(ge=0)
    model: str
    gen_ai_usage_input_tokens: int = Field(default=0, ge=0)
    gen_ai_usage_output_tokens: int = Field(default=0, ge=0)
    gen_ai_usage_cache_read_input_tokens: int = Field(default=0, ge=0)
    gen_ai_usage_cache_creation_input_tokens: int = Field(default=0, ge=0)
    gen_ai_usage_reasoning_output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    latency_ms: int = Field(default=0, ge=0)
    num_actions: int = Field(default=0, ge=0)
    rate_missing: bool = False


class CostRollupRow(ApiModel):
    dimensions: dict[CostRollupDimension, str | None]
    execution_count: int
    gen_ai_usage_input_tokens: int
    gen_ai_usage_output_tokens: int
    gen_ai_usage_cache_read_input_tokens: int
    gen_ai_usage_cache_creation_input_tokens: int
    gen_ai_usage_reasoning_output_tokens: int
    latency_ms: int
    num_actions: int
    cost_usd: float
    rate_missing_execution_count: int
    rate_missing_input_tokens: int
    rate_missing_output_tokens: int
    has_rate_missing: bool


class CostRollupResponse(ApiModel):
    group_by: tuple[CostRollupDimension, ...]
    rows: list[CostRollupRow]
