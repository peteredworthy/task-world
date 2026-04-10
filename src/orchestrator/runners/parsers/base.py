"""Base protocols for agent output parsers."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from orchestrator.state.models import ActionLog


@runtime_checkable
class StreamParser(Protocol):
    """Line-by-line stream parser for CLI agent NDJSON output."""

    def parse_line(self, line: str) -> None:
        """Parse a single line of output from the agent stream."""
        ...

    def finalize(self) -> ActionLog:
        """Finalize parsing and return the complete action log."""
        ...

    def get_readable_text(self) -> str:
        """Extract human-readable text from parsed entries.

        Concatenates assistant_text and result entries to produce readable
        output for the agent_output field, so the raw text view remains
        useful even when stdout is NDJSON.
        """
        ...


@runtime_checkable
class BatchParser(Protocol):
    """Batch parser for non-streaming agent output (e.g. OpenHands SDK events)."""

    def parse_events(self, events: list[Any]) -> ActionLog:
        """Parse a batch of events and return the complete action log."""
        ...


def tool_summary(name: str, args: dict[str, Any]) -> str:
    """Produce a human-readable one-liner summary for a tool call."""
    if name in ("bash", "Bash"):
        cmd = args.get("command", "")
        if len(cmd) > 80:
            cmd = cmd[:77] + "..."
        return f"bash: {cmd}"
    if name in ("read", "Read"):
        return f"read: {args.get('file_path', args.get('path', ''))}"
    if name in ("write", "Write"):
        return f"write: {args.get('file_path', args.get('path', ''))}"
    if name in ("edit", "Edit"):
        return f"edit: {args.get('file_path', args.get('path', ''))}"
    if name in ("glob", "Glob"):
        return f"glob: {args.get('pattern', '')}"
    if name in ("grep", "Grep"):
        return f"grep: {args.get('pattern', '')}"
    if name in ("WebSearch", "web_search"):
        return f"search: {args.get('query', '')}"
    if name in ("WebFetch", "web_fetch"):
        return f"fetch: {args.get('url', '')}"
    if name in ("Task", "task"):
        return f"task: {args.get('description', args.get('prompt', '')[:40])}"
    # Generic fallback
    arg_summary = ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:2])
    if len(arg_summary) > 60:
        arg_summary = arg_summary[:57] + "..."
    return f"{name}({arg_summary})" if arg_summary else name
