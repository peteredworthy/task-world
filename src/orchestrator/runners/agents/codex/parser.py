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


class CodexStreamParser:
    """Parses Codex --json NDJSON output into an ActionLog."""

    def __init__(self) -> None:
        self._entries: list[ActionLogEntry] = []
        self._seq = 0
        self._readable_parts: list[str] = []
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._pending_assistant_parts: list[str] = []

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
        self._flush_pending_assistant_text()
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
        self._flush_pending_assistant_text()
        return ActionLog(
            entries=self._entries,
            total_turns=sum(1 for e in self._entries if e.kind == ActionEntryKind.ASSISTANT_TEXT),
            total_input_tokens=self._total_input_tokens,
            total_output_tokens=self._total_output_tokens,
        )

    def parse_jsonrpc_message(self, message: dict[str, Any]) -> None:
        """Parse one Codex app-server JSON-RPC message into action-log entries."""
        method = str(message.get("method", "")).strip()
        if not method:
            return

        if method == "item/agentMessage/delta":
            delta = message.get("params", {}).get("delta")
            if isinstance(delta, str) and delta:
                self._pending_assistant_parts.append(delta)
            return

        self._flush_pending_assistant_text()

        if method == "item/completed":
            item = message.get("params", {}).get("item")
            if isinstance(item, dict):
                self._handle_item_completed({"type": "item.completed", "item": item})
            return

        if method == "item/tool/call":
            params = message.get("params", {})
            self._handle_tool_call(
                {
                    "type": "tool_call",
                    "id": message.get("id", ""),
                    "name": params.get("tool", ""),
                    "arguments": params.get("arguments", {}),
                }
            )
            return

        if method == "turn/completed":
            turn = message.get("params", {}).get("turn", {})
            usage = self._normalize_turn_usage(turn.get("tokenUsage") or turn.get("usage"))
            self._handle_result(
                {
                    "type": "turn.completed",
                    "message": turn.get("summary", ""),
                    "usage": usage,
                }
            )
            return

    def record_dynamic_tool_result(
        self,
        tool_use_id: str,
        *,
        success: bool,
        output: str | None = None,
    ) -> None:
        """Record the result of an app-server dynamic tool invocation."""
        self._flush_pending_assistant_text()
        self._handle_tool_output(
            {
                "type": "tool_output",
                "call_id": tool_use_id,
                "output": output
                if output is not None
                else ("Tool executed successfully." if success else "Tool execution failed."),
                "success": success,
                "exit_code": 0 if success else 1,
            }
        )

    def get_readable_text(self) -> str:
        """Extract human-readable text from parsed entries."""
        return "\n".join(self._readable_parts)

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _flush_pending_assistant_text(self) -> None:
        if not self._pending_assistant_parts:
            return
        text = "".join(self._pending_assistant_parts).strip()
        self._pending_assistant_parts.clear()
        if not text:
            return
        self._entries.append(
            ActionLogEntry(
                sequence_num=self._next_seq(),
                kind=ActionEntryKind.ASSISTANT_TEXT,
                timestamp=datetime.now(timezone.utc),
                text=text,
                raw_type="item/agentMessage/delta",
            )
        )
        self._readable_parts.append(text)

    @staticmethod
    def _normalize_turn_usage(usage: Any) -> dict[str, int] | None:
        if not isinstance(usage, dict):
            return None
        usage_dict = cast(dict[str, Any], usage)
        return {
            "input_tokens": int(
                usage_dict.get("inputTokens")
                or usage_dict.get("input_tokens")
                or usage_dict.get("prompt_tokens")
                or 0
            ),
            "output_tokens": int(
                usage_dict.get("outputTokens")
                or usage_dict.get("output_tokens")
                or usage_dict.get("completion_tokens")
                or 0
            ),
        }

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
        item_type_normalized = item_type.replace("_", "").lower()

        if item_type in ("agent_message", "agentMessage", "message"):
            text = str(item.get("text", ""))
            if not text:
                content = item.get("content")
                if isinstance(content, list):
                    content_parts = cast(list[Any], content)
                    text = "\n".join(str(part) for part in content_parts if str(part).strip())
            text = text.strip()
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
                summary = item.get("summary")
                if isinstance(summary, list):
                    summary_parts = cast(list[Any], summary)
                    text = "\n".join(
                        str(part) for part in summary_parts if str(part).strip()
                    ).strip()
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

        if item_type_normalized in (
            "commandexecution",
            "toolcall",
            "tooluse",
            "dynamictoolcall",
            "mcptoolcall",
            "filechange",
        ):
            tool_use_id = str(item.get("id") or event.get("id") or "")
            status = str(item.get("status", "")).strip().lower()
            success = status in ("completed", "ok", "success", "succeeded")

            if item_type_normalized == "commandexecution":
                command = str(item.get("command", "")).strip()
                tool_name = "bash"
                arguments = {"command": command} if command else {}
                summary = f"bash: {command}" if command else "command execution"
                output = str(item.get("aggregated_output") or item.get("aggregatedOutput") or "")
                exit_code_raw = item.get("exit_code", item.get("exitCode"))
                exit_code = exit_code_raw if isinstance(exit_code_raw, int) else None
            elif item_type_normalized == "filechange":
                changes = item.get("changes")
                change_list: list[Any] = (
                    cast(list[Any], changes) if isinstance(changes, list) else []
                )
                tool_name = "file_change"
                arguments: dict[str, Any] = {"changes": change_list}
                summary = f"file change: {len(change_list)} update(s)"
                output = ""
                exit_code = None
            else:
                tool_name = str(item.get("tool", "")).strip() or item_type
                arguments_raw = item.get("arguments")
                arguments = (
                    cast(dict[str, Any], arguments_raw) if isinstance(arguments_raw, dict) else {}
                )
                summary = tool_summary(tool_name, arguments)
                content_items = item.get("contentItems")
                if isinstance(content_items, list):
                    content_list = cast(list[Any], content_items)
                    output = "\n".join(
                        str(content_dict.get("text", ""))
                        for content in content_list
                        if isinstance(content, dict)
                        and str(
                            (content_dict := cast(dict[str, Any], content)).get("text", "")
                        ).strip()
                    )
                else:
                    output = ""
                success_value = item.get("success")
                if isinstance(success_value, bool):
                    success = success_value
                exit_code = None

            self._entries.append(
                ActionLogEntry(
                    sequence_num=self._next_seq(),
                    kind=ActionEntryKind.TOOL_USE,
                    timestamp=datetime.now(timezone.utc),
                    tool_use=ToolUseDetail(
                        tool_use_id=tool_use_id,
                        tool_name=tool_name,
                        arguments=arguments,
                        summary=summary,
                    ),
                    raw_type="item.completed",
                )
            )

            if output:
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
        tool_id = str(event.get("id", event.get("call_id", "")))
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
        tool_use_id = str(event.get("call_id", event.get("tool_call_id", "")))
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
