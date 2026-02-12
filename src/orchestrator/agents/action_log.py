"""Shared structured action log types for agent output capture.

Provides agent-agnostic Pydantic models for representing rich agent activity
(tool calls, text output, thinking, metrics) captured from CLI agent streams.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel


class ActionEntryKind(str, Enum):
    """Discriminator for action log entry types."""

    SYSTEM_INIT = "system_init"
    ASSISTANT_TEXT = "assistant_text"
    THINKING = "thinking"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    RESULT = "result"
    ERROR = "error"


class ToolUseDetail(BaseModel):
    """Detail for a tool_use entry."""

    tool_use_id: str = ""
    tool_name: str = ""
    arguments: dict[str, Any] = {}
    summary: str | None = None


class ToolResultDetail(BaseModel):
    """Detail for a tool_result entry."""

    tool_use_id: str = ""
    output: str = ""  # Truncated to MAX_TOOL_OUTPUT_SIZE
    exit_code: int | None = None
    success: bool = True
    output_length: int = 0  # Original output length before truncation


class TurnMetrics(BaseModel):
    """Per-turn token/cost metrics."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0


class ActionLogEntry(BaseModel):
    """A single entry in the action log.

    Uses `kind` discriminator + nullable content fields (not inheritance)
    for clean JSON serialization. `tool_use_id` on ToolUseDetail/ToolResultDetail
    links tool_use entries to their corresponding tool_result entries.
    """

    sequence_num: int = 0
    kind: ActionEntryKind
    timestamp: datetime | None = None
    text: str | None = None
    tool_use: ToolUseDetail | None = None
    tool_result: ToolResultDetail | None = None
    metrics: TurnMetrics | None = None
    raw_type: str | None = None  # Original event type from the agent stream


# Maximum size for tool result output (5KB)
MAX_TOOL_OUTPUT_SIZE = 5 * 1024


class ActionLog(BaseModel):
    """Complete structured action log for an agent execution.

    Contains individual entries plus session-level metadata and aggregate totals.
    """

    entries: list[ActionLogEntry] = []

    # Session metadata
    session_id: str | None = None
    agent_model: str | None = None
    tools_available: list[str] = []

    # Aggregate totals
    total_turns: int = 0
    total_cost_usd: float = 0.0
    total_duration_ms: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
