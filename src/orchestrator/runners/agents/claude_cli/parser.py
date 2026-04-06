"""Parser for Claude Code ``--output-format stream-json --verbose`` NDJSON output.

Claude stream-json event mapping:
| Claude event                                        | ActionEntryKind |
|-----------------------------------------------------|-----------------|
| {"type":"system","subtype":"init"}                  | system_init     |
| {"type":"assistant"} content block type=text        | assistant_text  |
| {"type":"assistant"} content block type=thinking    | thinking        |
| {"type":"assistant"} content block type=tool_use    | tool_use        |
| {"type":"user"} content block type=tool_result      | tool_result     |
| {"type":"result"}                                   | result          |
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, cast

from orchestrator.state.models import (
    MAX_TOOL_OUTPUT_SIZE,
    ActionEntryKind,
    ActionLog,
    ActionLogEntry,
    ToolResultDetail,
    ToolUseDetail,
    TurnMetrics,
)
from orchestrator.runners.parsers.base import tool_summary

logger = logging.getLogger(__name__)

# Matches the rate-limit message emitted by Claude CLI when the Anthropic
# credit/usage limit is reached.  The pattern is generous to accommodate
# variations like "5-hour limit", "weekly limit", etc.
RATE_LIMIT_PATTERN = re.compile(r"You've hit your (?:\S+ )?limit")

# Extracts the human-readable reset time and IANA timezone from the message.
# Example: "resets 6pm (America/New_York)" → ("6pm", "America/New_York")
RATE_LIMIT_RESET_PATTERN = re.compile(r"resets?\s+(.+?)\s+\(([^)]+)\)")


class ClaudeStreamParser:
    """Parses Claude Code stream-json NDJSON output into an ActionLog."""

    def __init__(self) -> None:
        self._entries: list[ActionLogEntry] = []
        self._seq = 0
        self._session_id: str | None = None
        self._model: str | None = None
        self._tools: list[str] = []
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cache_read = 0
        self._total_cache_creation = 0
        self._total_cost = 0.0
        self._total_duration_ms = 0
        self._num_turns = 0
        self._readable_parts: list[str] = []

        # Rate-limit detection state
        self._rate_limit_hit = False
        self._rate_limit_resets_at: datetime | None = None

    def parse_line(self, line: str) -> None:
        """Parse a single NDJSON line from Claude stream-json output."""
        line = line.strip()
        if not line:
            return

        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            return  # Skip non-JSON lines gracefully

        if not isinstance(raw, dict):
            return

        event = cast(dict[str, Any], raw)
        event_type: str = str(event.get("type", ""))

        if event_type == "system":
            self._handle_system(event)
        elif event_type == "assistant":
            self._handle_assistant(event)
        elif event_type == "user":
            self._handle_user(event)
        elif event_type == "result":
            self._handle_result(event)
        elif event_type == "error":
            self._handle_error(event)
        # Skip unknown event types gracefully

    def finalize(self) -> ActionLog:
        """Return the completed ActionLog."""
        num_turns = self._num_turns or sum(
            1 for e in self._entries if e.kind == ActionEntryKind.ASSISTANT_TEXT
        )
        return ActionLog(
            entries=self._entries,
            session_id=self._session_id,
            agent_model=self._model,
            tools_available=self._tools,
            total_turns=num_turns,
            total_cost_usd=self._total_cost,
            total_duration_ms=self._total_duration_ms,
            total_input_tokens=self._total_input_tokens,
            total_output_tokens=self._total_output_tokens,
            total_cache_read_tokens=self._total_cache_read,
            total_cache_creation_tokens=self._total_cache_creation,
            rate_limit_hit=self._rate_limit_hit,
            rate_limit_resets_at=self._rate_limit_resets_at,
        )

    def get_readable_text(self) -> str:
        """Extract human-readable text from parsed entries."""
        return "\n".join(self._readable_parts)

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _handle_system(self, event: dict[str, Any]) -> None:
        subtype = event.get("subtype", "")
        if subtype == "init":
            self._session_id = event.get("session_id")
            self._model = event.get("model")
            self._tools = event.get("tools", [])
            self._entries.append(
                ActionLogEntry(
                    sequence_num=self._next_seq(),
                    kind=ActionEntryKind.SYSTEM_INIT,
                    timestamp=datetime.now(timezone.utc),
                    text=f"Session started (model={self._model})",
                    raw_type="system.init",
                )
            )

    def _handle_assistant(self, event: dict[str, Any]) -> None:
        # Content and usage are nested inside event["message"], not at the top level
        message = event.get("message", event)
        content_blocks = message.get("content", [])
        # Extract per-message usage if present
        usage = message.get("usage")
        turn_metrics = None
        if usage:
            turn_metrics = TurnMetrics(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
            )
            self._total_input_tokens += turn_metrics.input_tokens
            self._total_output_tokens += turn_metrics.output_tokens
            self._total_cache_read += turn_metrics.cache_read_tokens
            self._total_cache_creation += turn_metrics.cache_creation_tokens

        for block in content_blocks:
            block_type = block.get("type", "")

            if block_type == "text":
                text = block.get("text", "")
                self._entries.append(
                    ActionLogEntry(
                        sequence_num=self._next_seq(),
                        kind=ActionEntryKind.ASSISTANT_TEXT,
                        timestamp=datetime.now(timezone.utc),
                        text=text,
                        metrics=turn_metrics,
                        raw_type="assistant.text",
                    )
                )
                if text.strip():
                    self._readable_parts.append(text)

                # Detect rate-limit message from Claude CLI
                if not self._rate_limit_hit and RATE_LIMIT_PATTERN.search(text):
                    self._rate_limit_hit = True
                    reset_match = RATE_LIMIT_RESET_PATTERN.search(text)
                    if reset_match:
                        self._rate_limit_resets_at = parse_reset_time(
                            reset_match.group(1), reset_match.group(2)
                        )
                    logger.warning(
                        "Rate-limit message detected in Claude CLI output: %s", text.strip()
                    )

                # Only attach metrics to the first content block
                turn_metrics = None

            elif block_type == "thinking":
                text = block.get("thinking", "")
                self._entries.append(
                    ActionLogEntry(
                        sequence_num=self._next_seq(),
                        kind=ActionEntryKind.THINKING,
                        timestamp=datetime.now(timezone.utc),
                        text=text,
                        metrics=turn_metrics,
                        raw_type="assistant.thinking",
                    )
                )
                turn_metrics = None

            elif block_type == "tool_use":
                tool_name = block.get("name", "")
                tool_id = block.get("id", "")
                arguments = block.get("input", {})
                summary = tool_summary(tool_name, arguments)
                self._entries.append(
                    ActionLogEntry(
                        sequence_num=self._next_seq(),
                        kind=ActionEntryKind.TOOL_USE,
                        timestamp=datetime.now(timezone.utc),
                        tool_use=ToolUseDetail(
                            tool_use_id=tool_id,
                            tool_name=tool_name,
                            arguments=arguments,
                            summary=summary,
                        ),
                        metrics=turn_metrics,
                        raw_type="assistant.tool_use",
                    )
                )
                turn_metrics = None

    def _handle_user(self, event: dict[str, Any]) -> None:
        """Handle user-role events, which carry tool results from the previous turn."""
        message = event.get("message", {})
        content_blocks = message.get("content", [])
        for block in cast(list[Any], content_blocks):
            if isinstance(block, dict):
                typed_block = cast(dict[str, Any], block)
                if typed_block.get("type") == "tool_result":
                    self._handle_tool_result_block(typed_block)

    def _handle_tool_result_block(self, block: dict[str, Any]) -> None:
        tool_use_id = block.get("tool_use_id", "")
        content = block.get("content", "")
        # Content can be a string or a list of content blocks
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in cast(list[Any], content):
                if isinstance(item, dict):
                    b = cast(dict[str, Any], item)
                    if b.get("type") == "text":
                        text_parts.append(str(b.get("text", "")))
                elif isinstance(item, str):
                    text_parts.append(item)
            output: str = "\n".join(text_parts)
        else:
            output = str(content)

        original_length = len(output)
        if len(output) > MAX_TOOL_OUTPUT_SIZE:
            output = output[:MAX_TOOL_OUTPUT_SIZE] + "\n... (truncated)"

        is_error: bool = bool(block.get("is_error", False))

        self._entries.append(
            ActionLogEntry(
                sequence_num=self._next_seq(),
                kind=ActionEntryKind.TOOL_RESULT,
                timestamp=datetime.now(timezone.utc),
                tool_result=ToolResultDetail(
                    tool_use_id=tool_use_id,
                    output=output,
                    success=not is_error,
                    output_length=original_length,
                ),
                raw_type="tool_result",
            )
        )

    def _handle_result(self, event: dict[str, Any]) -> None:
        # The result event carries the final summary text in the "result" field
        # and session-level totals in "usage" / "total_cost_usd".
        text: str = str(event.get("result", ""))

        # Extract session-level usage totals
        usage = event.get("usage")
        cost: float = float(event.get("total_cost_usd", event.get("cost_usd", 0.0)))
        turn_metrics = None
        if usage:
            turn_metrics = TurnMetrics(
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
                cache_read_tokens=int(usage.get("cache_read_input_tokens", 0)),
                cache_creation_tokens=int(usage.get("cache_creation_input_tokens", 0)),
                cost_usd=cost,
            )
            # Update totals from result event (these are session totals)
            self._total_input_tokens = turn_metrics.input_tokens
            self._total_output_tokens = turn_metrics.output_tokens
            self._total_cache_read = turn_metrics.cache_read_tokens
            self._total_cache_creation = turn_metrics.cache_creation_tokens
        self._total_cost = cost
        self._total_duration_ms = int(event.get("duration_ms", 0))
        self._num_turns = int(event.get("num_turns", 0))

        self._entries.append(
            ActionLogEntry(
                sequence_num=self._next_seq(),
                kind=ActionEntryKind.RESULT,
                timestamp=datetime.now(timezone.utc),
                text=text,
                metrics=turn_metrics,
                raw_type="result",
            )
        )
        if text.strip():
            self._readable_parts.append(text)

    def _handle_error(self, event: dict[str, Any]) -> None:
        error_msg: Any = event.get("error", {})
        if isinstance(error_msg, dict):
            err_dict = cast(dict[str, Any], error_msg)
            text: str = str(err_dict.get("message", str(err_dict)))
        else:
            text = str(error_msg)

        self._entries.append(
            ActionLogEntry(
                sequence_num=self._next_seq(),
                kind=ActionEntryKind.ERROR,
                timestamp=datetime.now(timezone.utc),
                text=text,
                raw_type="error",
            )
        )


def parse_reset_time(time_str: str, tz_name: str) -> datetime | None:
    """Best-effort parse of the reset time from a rate-limit message.

    Claude CLI emits times like "6pm", "9am", "Jan 7, 9am" with an IANA
    timezone like "America/New_York".  We try ``dateutil.parser.parse`` first,
    then fall back to a simple am/pm parser.  Returns ``None`` if parsing
    fails — callers should still pause the run even without a precise time.
    """
    import zoneinfo

    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except (KeyError, zoneinfo.ZoneInfoNotFoundError):
        logger.warning("Unknown timezone in rate-limit message: %s", tz_name)
        return None

    # Try dateutil first (handles "Jan 7, 9am" etc.)
    try:
        from dateutil import parser as dateutil_parser

        naive = dateutil_parser.parse(time_str, fuzzy=True)
        return naive.replace(tzinfo=tz)
    except Exception:
        pass

    # Simple fallback: "6pm", "9am"
    time_str = time_str.strip().lower()
    try:
        naive = datetime.strptime(time_str, "%I%p")
        now = datetime.now(tz)
        result = now.replace(hour=naive.hour, minute=0, second=0, microsecond=0)
        # If the time is in the past today, assume tomorrow
        if result <= now:
            from datetime import timedelta

            result += timedelta(days=1)
        return result
    except ValueError:
        pass

    logger.warning("Could not parse reset time from rate-limit message: %r", time_str)
    return None
