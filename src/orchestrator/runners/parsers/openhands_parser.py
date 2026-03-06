"""Parser for OpenHands SDK events (batch mode).

OpenHands SDK mapping:
| OH event class                              | ActionEntryKind |
|---------------------------------------------|-----------------|
| MessageAction                               | assistant_text  |
| *Action (CmdRunAction, FileWriteAction, ..) | tool_use        |
| *Observation (CmdOutputObservation, ..)     | tool_result     |
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from orchestrator.runners.action_log import (
    MAX_TOOL_OUTPUT_SIZE,
    ActionEntryKind,
    ActionLog,
    ActionLogEntry,
    ToolResultDetail,
    ToolUseDetail,
)

logger = logging.getLogger(__name__)


class OpenHandsEventParser:
    """Parses OpenHands SDK conversation events into an ActionLog (batch mode)."""

    def parse_events(self, events: list[Any]) -> ActionLog:
        """Parse a list of OpenHands SDK events into an ActionLog.

        Events are expected to be instances of openhands Action/Observation classes
        with a ``__class__.__name__`` attribute. The parser gracefully handles
        unknown event types.
        """
        entries: list[ActionLogEntry] = []
        seq = 0
        readable_parts: list[str] = []

        for event in events:
            class_name = type(event).__name__
            seq += 1

            if class_name == "MessageAction":
                text = getattr(event, "content", "") or getattr(event, "message", "")
                entries.append(
                    ActionLogEntry(
                        sequence_num=seq,
                        kind=ActionEntryKind.ASSISTANT_TEXT,
                        timestamp=datetime.now(timezone.utc),
                        text=str(text),
                        raw_type=class_name,
                    )
                )
                if text and str(text).strip():
                    readable_parts.append(str(text))

            elif class_name.endswith("Action"):
                # Generic action -> tool_use
                tool_name = class_name.replace("Action", "")
                arguments = self._extract_action_args(event)
                summary = self._action_summary(class_name, event)

                entries.append(
                    ActionLogEntry(
                        sequence_num=seq,
                        kind=ActionEntryKind.TOOL_USE,
                        timestamp=datetime.now(timezone.utc),
                        tool_use=ToolUseDetail(
                            tool_name=tool_name,
                            arguments=arguments,
                            summary=summary,
                        ),
                        raw_type=class_name,
                    )
                )

            elif class_name.endswith("Observation"):
                # Generic observation -> tool_result
                output = self._extract_observation_output(event)
                original_length = len(output)
                if len(output) > MAX_TOOL_OUTPUT_SIZE:
                    output = output[:MAX_TOOL_OUTPUT_SIZE] + "\n... (truncated)"

                exit_code = getattr(event, "exit_code", None)
                success = True
                if exit_code is not None:
                    success = exit_code == 0

                entries.append(
                    ActionLogEntry(
                        sequence_num=seq,
                        kind=ActionEntryKind.TOOL_RESULT,
                        timestamp=datetime.now(timezone.utc),
                        tool_result=ToolResultDetail(
                            output=output,
                            exit_code=exit_code,
                            success=success,
                            output_length=original_length,
                        ),
                        raw_type=class_name,
                    )
                )

            # Skip unknown event types gracefully

        return ActionLog(
            entries=entries,
            total_turns=sum(1 for e in entries if e.kind == ActionEntryKind.ASSISTANT_TEXT),
        )

    def _extract_action_args(self, event: Any) -> dict[str, str]:
        """Extract arguments from an OpenHands Action event."""
        args: dict[str, str] = {}
        for attr in ("command", "path", "content", "url", "query", "old_str", "new_str"):
            val = getattr(event, attr, None)
            if val is not None:
                args[attr] = str(val)
        return args

    def _extract_observation_output(self, event: Any) -> str:
        """Extract output text from an OpenHands Observation event."""
        for attr in ("content", "output", "text", "message"):
            val = getattr(event, attr, None)
            if val is not None:
                return str(val)
        return str(event)

    def _action_summary(self, class_name: str, event: Any) -> str:
        """Generate a human-readable summary for an action."""
        if class_name == "CmdRunAction":
            cmd = getattr(event, "command", "")
            if len(cmd) > 80:
                cmd = cmd[:77] + "..."
            return f"run: {cmd}"
        if class_name == "FileWriteAction":
            return f"write: {getattr(event, 'path', '')}"
        if class_name == "FileReadAction":
            return f"read: {getattr(event, 'path', '')}"
        if class_name == "FileEditAction":
            return f"edit: {getattr(event, 'path', '')}"
        if class_name == "BrowseURLAction":
            return f"browse: {getattr(event, 'url', '')}"
        return class_name.replace("Action", "").lower()
