"""Parser for Codex ``--json`` NDJSON output.

Codex --json event mapping:
| Codex event                      | ActionEntryKind |
|----------------------------------|-----------------|
| {"type":"thread.started"}        | system_init     |
| message.created role=assistant   | assistant_text  |
| tool_call                        | tool_use        |
| tool_output                      | tool_result     |
| turn.completed / result          | result          |
| error / turn.failed              | error           |
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, cast

from orchestrator.runners.action_log import (
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


class CodexStreamParser:
    """Parses Codex --json NDJSON output into an ActionLog."""

    def __init__(self) -> None:
        self._entries: list[ActionLogEntry] = []
        self._seq = 0
        self._readable_parts: list[str] = []
        self._total_input_tokens = 0
        self._total_output_tokens = 0

    def parse_line(self, line: str) -> None:
        """Parse a single NDJSON line from Codex --json output."""
        line = line.strip()
        if not line:
            return

        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            return

        if not isinstance(raw, dict):
            return

        event = cast(dict[str, Any], raw)
        event_type: str = str(event.get("type", ""))

        if event_type == "thread.started":
            self._handle_thread_started(event)
        elif event_type == "message.created":
            self._handle_message_created(event)
        elif event_type == "item.completed":
            self._handle_item_completed(event)
        elif event_type == "tool_call":
            self._handle_tool_call(event)
        elif event_type == "tool_output":
            self._handle_tool_output(event)
        elif event_type in ("turn.completed", "result"):
            self._handle_result(event)
        elif event_type in ("error", "turn.failed"):
            self._handle_error(event)

    def finalize(self) -> ActionLog:
        """Return the completed ActionLog."""
        return ActionLog(
            entries=self._entries,
            total_turns=sum(1 for e in self._entries if e.kind == ActionEntryKind.ASSISTANT_TEXT),
            total_input_tokens=self._total_input_tokens,
            total_output_tokens=self._total_output_tokens,
        )

    def get_readable_text(self) -> str:
        """Extract human-readable text from parsed entries."""
        return "\n".join(self._readable_parts)

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _handle_thread_started(self, event: dict[str, Any]) -> None:
        self._entries.append(
            ActionLogEntry(
                sequence_num=self._next_seq(),
                kind=ActionEntryKind.SYSTEM_INIT,
                timestamp=datetime.now(timezone.utc),
                text="Codex thread started",
                raw_type="thread.started",
            )
        )

    def _handle_message_created(self, event: dict[str, Any]) -> None:
        role = event.get("role", "")
        if role != "assistant":
            return

        text: Any = event.get("content", "")
        if isinstance(text, list):
            # Content may be a list of blocks
            parts: list[str] = []
            for block in cast(list[Any], text):
                if isinstance(block, dict):
                    parts.append(str(cast(dict[str, Any], block).get("text", "")))
                elif isinstance(block, str):
                    parts.append(block)
            text = "\n".join(parts)

        usage = event.get("usage")
        turn_metrics = None
        if usage:
            turn_metrics = TurnMetrics(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )
            self._total_input_tokens += turn_metrics.input_tokens
            self._total_output_tokens += turn_metrics.output_tokens

        self._entries.append(
            ActionLogEntry(
                sequence_num=self._next_seq(),
                kind=ActionEntryKind.ASSISTANT_TEXT,
                timestamp=datetime.now(timezone.utc),
                text=text,
                metrics=turn_metrics,
                raw_type="message.created",
            )
        )
        if text and text.strip():
            self._readable_parts.append(text)

    def _handle_item_completed(self, event: dict[str, Any]) -> None:
        """Handle Codex item.completed events (modern stream format)."""
        item_raw = event.get("item")
        if not isinstance(item_raw, dict):
            return

        item = cast(dict[str, Any], item_raw)
        item_type = str(item.get("type", ""))

        if item_type in ("agent_message", "message"):
            text = str(item.get("text", "")).strip()
            if not text:
                return
            self._entries.append(
                ActionLogEntry(
                    sequence_num=self._next_seq(),
                    kind=ActionEntryKind.ASSISTANT_TEXT,
                    timestamp=datetime.now(timezone.utc),
                    text=text,
                    raw_type="item.completed",
                )
            )
            self._readable_parts.append(text)
            return

        if item_type == "reasoning":
            text = str(item.get("text", "")).strip()
            if not text:
                return
            self._entries.append(
                ActionLogEntry(
                    sequence_num=self._next_seq(),
                    kind=ActionEntryKind.THINKING,
                    timestamp=datetime.now(timezone.utc),
                    text=text,
                    raw_type="item.completed",
                )
            )
            return

        if item_type in ("command_execution", "tool_call", "tool_use"):
            tool_use_id = str(item.get("id") or event.get("id") or "")
            command = str(item.get("command", "")).strip()
            status = str(item.get("status", "")).strip().lower()
            success = status in ("completed", "ok", "success", "succeeded")

            self._entries.append(
                ActionLogEntry(
                    sequence_num=self._next_seq(),
                    kind=ActionEntryKind.TOOL_USE,
                    timestamp=datetime.now(timezone.utc),
                    tool_use=ToolUseDetail(
                        tool_use_id=tool_use_id,
                        tool_name="bash",
                        arguments={"command": command} if command else {},
                        summary=f"bash: {command}" if command else "command execution",
                    ),
                    raw_type="item.completed",
                )
            )

            output = str(item.get("aggregated_output") or item.get("output") or "")
            if output:
                exit_code_raw = item.get("exit_code")
                exit_code = exit_code_raw if isinstance(exit_code_raw, int) else None
                self._entries.append(
                    ActionLogEntry(
                        sequence_num=self._next_seq(),
                        kind=ActionEntryKind.TOOL_RESULT,
                        timestamp=datetime.now(timezone.utc),
                        tool_result=ToolResultDetail(
                            tool_use_id=tool_use_id,
                            output=output,
                            exit_code=exit_code,
                            success=success if exit_code is None else exit_code == 0,
                            output_length=len(output),
                        ),
                        raw_type="item.completed",
                    )
                )

    def _handle_tool_call(self, event: dict[str, Any]) -> None:
        tool_name = event.get("name", event.get("function", {}).get("name", ""))
        tool_id = event.get("id", event.get("call_id", ""))
        arguments = event.get("arguments", event.get("function", {}).get("arguments", {}))
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"raw": arguments}

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
                raw_type="tool_call",
            )
        )

    def _handle_tool_output(self, event: dict[str, Any]) -> None:
        tool_use_id = event.get("call_id", event.get("tool_call_id", ""))
        output = event.get("output", event.get("content", ""))
        if not isinstance(output, str):
            output = str(output)

        original_length = len(output)
        if len(output) > MAX_TOOL_OUTPUT_SIZE:
            output = output[:MAX_TOOL_OUTPUT_SIZE] + "\n... (truncated)"

        exit_code = event.get("exit_code")
        success = event.get("success", exit_code is None or exit_code == 0)

        self._entries.append(
            ActionLogEntry(
                sequence_num=self._next_seq(),
                kind=ActionEntryKind.TOOL_RESULT,
                timestamp=datetime.now(timezone.utc),
                tool_result=ToolResultDetail(
                    tool_use_id=tool_use_id,
                    output=output,
                    exit_code=exit_code,
                    success=success,
                    output_length=original_length,
                ),
                raw_type="tool_output",
            )
        )

    def _handle_result(self, event: dict[str, Any]) -> None:
        text: Any = event.get("content", event.get("message", ""))
        if isinstance(text, list):
            parts: list[str] = []
            for block in cast(list[Any], text):
                if isinstance(block, dict):
                    parts.append(str(cast(dict[str, Any], block).get("text", "")))
                elif isinstance(block, str):
                    parts.append(block)
            text = "\n".join(parts)

        usage = event.get("usage")
        turn_metrics = None
        if usage:
            turn_metrics = TurnMetrics(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )

        self._entries.append(
            ActionLogEntry(
                sequence_num=self._next_seq(),
                kind=ActionEntryKind.RESULT,
                timestamp=datetime.now(timezone.utc),
                text=text,
                metrics=turn_metrics,
                raw_type=event.get("type", "result"),
            )
        )
        if text and text.strip():
            self._readable_parts.append(text)

    def _handle_error(self, event: dict[str, Any]) -> None:
        text: Any = event.get("message", event.get("error", str(event)))
        if isinstance(text, dict):
            err_dict = cast(dict[str, Any], text)
            text = str(err_dict.get("message", str(err_dict)))

        self._entries.append(
            ActionLogEntry(
                sequence_num=self._next_seq(),
                kind=ActionEntryKind.ERROR,
                timestamp=datetime.now(timezone.utc),
                text=str(text),
                raw_type=event.get("type", "error"),
            )
        )
