"""Reader for Claude Code sub-agent sessions.

When Claude Code's ``Agent`` tool (e.g. ``subagent_type: "Explore"``) is used,
the sub-agent runs as a separate Claude Code process. Its token usage is billed
separately and is NOT reflected in the parent session's ``result`` event totals.

Sub-agent sessions are stored on disk at:
    ~/.claude/projects/{project_slug}/{parent_session_id}/subagents/

Each sub-agent has two files:
    {agent_id}.jsonl       — full conversation in Claude stream-json format
    {agent_id}.meta.json   — {"agentType": "Explore", "description": "..."}

The JSONL format is the same ``assistant``/``user`` event format as the parent
session, but without a final ``result`` event. Token usage is accumulated from
per-turn ``usage`` fields on ``assistant`` messages.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from orchestrator.state.models import (
    MAX_TOOL_OUTPUT_SIZE,
    ActionEntryKind,
    ActionLogEntry,
    SubAgentLog,
    ToolResultDetail,
    ToolUseDetail,
    TurnMetrics,
)
from orchestrator.runners.parsers.base import tool_summary

logger = logging.getLogger(__name__)

# Base directory where Claude Code stores project session data
_CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def _working_dir_to_project_slug(working_dir: str) -> str:
    """Convert an absolute working directory path to a Claude project slug.

    Claude Code stores sessions under ~/.claude/projects/ using a slug derived
    from the working directory by stripping the leading ``/`` and replacing all
    ``/`` with ``-``.

    Example:
        /Users/peter/code/task-world/worktrees/r62
        → -Users-peter-code-task-world-worktrees-r62
    """
    return working_dir.replace("/", "-")


def _parse_subagent_jsonl(
    jsonl_path: Path,
) -> tuple[str | None, list[ActionLogEntry], dict[str, int]]:
    """Parse a sub-agent JSONL file.

    Returns:
        (model, entries, totals) where totals is a dict with keys
        input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens.
    """
    entries: list[ActionLogEntry] = []
    totals: dict[str, int] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
    }
    model: str | None = None
    seq = 0
    # Each API call emits one assistant event per content block, all carrying the
    # same usage data. Track seen message IDs so we accumulate usage only once
    # per API call (sub-agents have no result event to correct overcounting).
    seen_message_ids: set[str] = set()

    try:
        with open(jsonl_path) as f:
            lines = f.readlines()
    except OSError as exc:
        logger.warning("subagents: cannot read %s: %s", jsonl_path, exc)
        return None, [], totals

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(raw, dict):
            continue
        event = cast(dict[str, Any], raw)
        event_type: str = str(event.get("type", ""))

        if event_type == "assistant":
            message = cast(dict[str, Any], event.get("message", event))
            if not model:
                raw_model = message.get("model")
                model = str(raw_model) if raw_model else None

            usage = cast(dict[str, Any], message.get("usage") or {})
            turn_metrics: TurnMetrics | None = None
            if usage:
                turn_metrics = TurnMetrics(
                    input_tokens=int(usage.get("input_tokens") or 0),
                    output_tokens=int(usage.get("output_tokens") or 0),
                    cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
                    cache_creation_tokens=int(usage.get("cache_creation_input_tokens") or 0),
                )
                message_id: str | None = message.get("id")
                if message_id is None or message_id not in seen_message_ids:
                    totals["input_tokens"] += turn_metrics.input_tokens
                    totals["output_tokens"] += turn_metrics.output_tokens
                    totals["cache_read_tokens"] += turn_metrics.cache_read_tokens
                    totals["cache_creation_tokens"] += turn_metrics.cache_creation_tokens
                if message_id:
                    seen_message_ids.add(message_id)

            for block in cast(list[Any], message.get("content") or []):
                if not isinstance(block, dict):
                    continue
                b = cast(dict[str, Any], block)
                block_type: str = str(b.get("type", ""))

                if block_type == "tool_use":
                    tool_name: str = str(b.get("name") or "")
                    tool_id: str = str(b.get("id") or "")
                    arguments: dict[str, Any] = cast(dict[str, Any], b.get("input") or {})
                    seq += 1
                    entries.append(
                        ActionLogEntry(
                            sequence_num=seq,
                            kind=ActionEntryKind.TOOL_USE,
                            timestamp=datetime.now(timezone.utc),
                            tool_use=ToolUseDetail(
                                tool_use_id=tool_id,
                                tool_name=tool_name,
                                arguments=arguments,
                                summary=tool_summary(tool_name, arguments),
                            ),
                            metrics=turn_metrics,
                            raw_type="assistant.tool_use",
                        )
                    )
                    turn_metrics = None  # attach metrics to first block only

                elif block_type == "text" and str(b.get("text") or "").strip():
                    seq += 1
                    entries.append(
                        ActionLogEntry(
                            sequence_num=seq,
                            kind=ActionEntryKind.ASSISTANT_TEXT,
                            timestamp=datetime.now(timezone.utc),
                            text=str(b.get("text") or ""),
                            metrics=turn_metrics,
                            raw_type="assistant.text",
                        )
                    )
                    turn_metrics = None

        elif event_type == "user":
            message = cast(dict[str, Any], event.get("message") or {})
            content = message.get("content", [])
            if not isinstance(content, list):
                continue
            for block in cast(list[Any], content):
                if not isinstance(block, dict):
                    continue
                b = cast(dict[str, Any], block)
                if b.get("type") != "tool_result":
                    continue

                tool_use_id = str(b.get("tool_use_id") or "")
                raw_content = b.get("content", "")
                if isinstance(raw_content, list):
                    text_parts: list[str] = []
                    for item in cast(list[Any], raw_content):
                        if isinstance(item, dict):
                            item_d = cast(dict[str, Any], item)
                            if item_d.get("type") == "text":
                                text_parts.append(str(item_d.get("text") or ""))
                    output = "\n".join(text_parts)
                else:
                    output = str(raw_content)

                original_length = len(output)
                if len(output) > MAX_TOOL_OUTPUT_SIZE:
                    output = output[:MAX_TOOL_OUTPUT_SIZE] + "\n... (truncated)"

                seq += 1
                entries.append(
                    ActionLogEntry(
                        sequence_num=seq,
                        kind=ActionEntryKind.TOOL_RESULT,
                        timestamp=datetime.now(timezone.utc),
                        tool_result=ToolResultDetail(
                            tool_use_id=tool_use_id,
                            output=output,
                            success=not b.get("is_error", False),
                            output_length=original_length,
                        ),
                        raw_type="tool_result",
                    )
                )

    return model, entries, totals


def load_sub_agents(working_dir: str, session_id: str) -> list[SubAgentLog]:
    """Load all sub-agent sessions for a given parent session.

    Args:
        working_dir: The working directory used by the parent agent. Used to
            derive the Claude project slug (path under ~/.claude/projects/).
        session_id: The parent session ID from the ``system.init`` event. The
            sub-agents directory lives at:
            ``~/.claude/projects/{slug}/{session_id}/subagents/``

    Returns:
        List of SubAgentLog instances, one per sub-agent JSONL file found.
        Returns an empty list if the directory doesn't exist or on any error.
    """
    if not session_id:
        return []

    slug = _working_dir_to_project_slug(working_dir)
    subagents_dir = _CLAUDE_PROJECTS_DIR / slug / session_id / "subagents"

    if not subagents_dir.is_dir():
        return []

    results: list[SubAgentLog] = []

    try:
        filenames = sorted(os.listdir(subagents_dir))
    except OSError as exc:
        logger.warning("subagents: cannot list %s: %s", subagents_dir, exc)
        return []

    for fname in filenames:
        if not fname.endswith(".jsonl"):
            continue

        agent_id = fname[: -len(".jsonl")]
        jsonl_path = subagents_dir / fname
        meta_path = subagents_dir / f"{agent_id}.meta.json"

        # Read metadata
        subagent_type = ""
        description = ""
        if meta_path.exists():
            try:
                with open(meta_path) as mf:
                    meta = json.load(mf)
                subagent_type = meta.get("agentType", "")
                description = meta.get("description", "")
            except (OSError, json.JSONDecodeError) as exc:
                logger.debug("subagents: cannot read meta %s: %s", meta_path, exc)

        # Parse the JSONL
        model, entries, totals = _parse_subagent_jsonl(jsonl_path)

        results.append(
            SubAgentLog(
                agent_id=agent_id,
                subagent_type=subagent_type,
                description=description,
                model=model,
                total_input_tokens=totals["input_tokens"],
                total_output_tokens=totals["output_tokens"],
                total_cache_read_tokens=totals["cache_read_tokens"],
                total_cache_creation_tokens=totals["cache_creation_tokens"],
                entries=entries,
            )
        )

    if results:
        logger.debug(
            "subagents: loaded %d sub-agent sessions from %s (session %s)",
            len(results),
            working_dir,
            session_id[:8],
        )

    return results
