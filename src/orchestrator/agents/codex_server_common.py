"""Shared code for Codex Server agent variants.

Contains prompt assembly, tool allow-list enforcement, and output
normalization used by both the local (``codex_server``) and remote
(``codex_server_remote``) Codex Server agents.

Per the integration contract (docs/codex-server/context/contract-matrix.md §4):
  - The v1 experimental tool allow-list is limited to exactly four
    orchestrator callback tools: ``update_checklist``, ``grade``,
    ``submit``, and ``request_clarification``.
  - Any tool invocation outside this list MUST be rejected and logged.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from orchestrator.agents.types import (
    ExecutionContext,
    ExecutionMetrics,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool allow-list
# ---------------------------------------------------------------------------

#: v1 Codex callback tool allow-list — contract-matrix.md §4.
CODEX_SERVER_TOOL_ALLOWLIST: frozenset[str] = frozenset(
    {
        "update_checklist",
        "grade",
        "submit",
        "request_clarification",
    }
)


def is_allowed_tool(tool_name: str) -> bool:
    """Return True if *tool_name* is on the v1 Codex callback allow-list."""
    return tool_name in CODEX_SERVER_TOOL_ALLOWLIST


def enforce_tool_allowlist(tool_name: str) -> None:
    """Raise ``ValueError`` and log a warning for out-of-allow-list tools.

    Per contract-matrix.md §4: the adapter MUST reject or ignore any tool
    invocation outside the v1 allow-list and log a warning to the action log.

    Args:
        tool_name: Name of the tool being invoked.

    Raises:
        ValueError: If *tool_name* is not on the v1 allow-list.
    """
    if not is_allowed_tool(tool_name):
        allowed = sorted(CODEX_SERVER_TOOL_ALLOWLIST)
        logger.warning(
            "Codex server tool invocation rejected: '%s' is not on the v1 allow-list %r",
            tool_name,
            allowed,
        )
        raise ValueError(
            f"Tool '{tool_name}' is not on the Codex server v1 allow-list. Allowed tools: {allowed}"
        )


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def build_codex_server_prompt(context: ExecutionContext, is_verifier: bool = False) -> str:
    """Build the full prompt for a Codex server session with phase-aware tool instructions.

    Produces a prompt that includes the task description, requirements, and
    instructions for the Codex agent on how to use the v1 callback tools.

    Args:
        context: Execution context with prompt, requirements, and optional
            callback metadata (``api_base_url``).
        is_verifier: If ``True``, includes verifier-phase grading instructions
            (``grade``); otherwise builds builder-phase instructions.

    Returns:
        The fully assembled prompt string.
    """
    requirements_text = "\n".join(f"- {req}" for req in context.requirements)

    if is_verifier:
        tool_section = (
            "## Orchestrator Integration (Verifier)\n"
            "You are connected to an orchestrator. Your role is to VERIFY the builder's work.\n\n"
            "### Required Workflow\n"
            "1. Review the code changes made by the builder.\n"
            "2. Grade EVERY requirement using **grade**.\n"
            "3. After grading all requirements, call **submit** to complete verification.\n"
            "4. Grades: A (excellent), B (good), C (adequate), D (poor), F (failing)\n\n"
            "### Available Callback Tools\n"
            "- **update_checklist**(req_id, status, note?)\n"
            "  Mark a requirement as done, blocked, or not_applicable.\n\n"
            "- **grade**(req_id, grade, grade_reason?)\n"
            "  Set a grade on a requirement.\n"
            "  - req_id: The requirement ID (e.g. 'R-01', 'R-02')\n"
            "  - grade: One of 'A', 'B', 'C', 'D', 'F'\n"
            "  - grade_reason: Optional explanation for the grade\n\n"
            "- **submit**()\n"
            "  Complete the verification after grading all requirements.\n\n"
            "- **request_clarification**(question)\n"
            "  Request clarification on ambiguous requirements or grading criteria."
        )
    else:
        tool_section = (
            "## Orchestrator Integration\n"
            "You are connected to an orchestrator that tracks your progress. "
            "Use the callback tools below to report your work.\n\n"
            "### Required Workflow\n"
            "1. Read the requirements above carefully.\n"
            "2. Implement each requirement.\n"
            "3. After completing each requirement, call **update_checklist** "
            "to mark it 'done'.\n"
            "4. Once ALL requirements are addressed, call **submit** to submit.\n"
            "5. All CRITICAL requirements must be 'done' before submission succeeds.\n\n"
            "### Available Callback Tools\n"
            "- **update_checklist**(req_id, status, note?)\n"
            "  Mark a requirement as done, blocked, or not_applicable.\n"
            "  - req_id: The requirement ID (e.g. 'R-01', 'R-02')\n"
            "  - status: 'done', 'blocked', or 'not_applicable'\n"
            "  - note: Optional explanation\n"
            "  Example: update_checklist('R-01', 'done')\n\n"
            "- **submit**()\n"
            "  Submit your work for verification by a reviewer.\n"
            "  Only call this after addressing all requirements.\n"
            "  Submission will fail if any CRITICAL requirement is not 'done'.\n\n"
            "- **request_clarification**(question)\n"
            "  Request clarification on ambiguous requirements."
        )

    channel_hint = ""
    if context.api_base_url:
        channel_hint = f"\n\nOrchestrator API base URL: {context.api_base_url}"

    return (
        f"{context.prompt}\n\n## Requirements\n{requirements_text}\n\n{tool_section}{channel_hint}"
    )


# ---------------------------------------------------------------------------
# Output normalization
# ---------------------------------------------------------------------------


def normalize_codex_metrics(
    duration_ms: int = 0,
    tokens_read: int = 0,
    tokens_write: int = 0,
    tokens_cache: int = 0,
    num_actions: int = 0,
) -> ExecutionMetrics:
    """Build a normalized ``ExecutionMetrics`` from Codex server session data.

    Args:
        duration_ms: Wall-clock session duration in milliseconds.
        tokens_read: Prompt/input tokens consumed.
        tokens_write: Completion/output tokens produced.
        tokens_cache: Cache-read tokens (if reported by the server).
        num_actions: Number of tool invocations made during the session.

    Returns:
        Populated ``ExecutionMetrics`` instance.
    """
    return ExecutionMetrics(
        tokens_read=tokens_read,
        tokens_write=tokens_write,
        tokens_cache=tokens_cache,
        duration_ms=duration_ms,
        num_actions=num_actions,
    )


def normalize_codex_output_lines(raw_output: list[Any]) -> list[str]:
    """Normalize raw Codex server output items to a flat list of text lines.

    Accepts the heterogeneous output stream produced by a Codex server session
    (strings, dicts, or other objects) and returns a list of plain strings
    suitable for ``ExecutionResult.output_lines``.

    For dict items, the following keys are tried in priority order:
    ``"text"``, ``"content"``, ``"message"``, ``"output"``.  If none match,
    the dict is JSON-serialized as a fallback.

    Args:
        raw_output: List of raw output items from the Codex server session.

    Returns:
        List of normalized string lines.
    """
    lines: list[str] = []
    for item in raw_output:
        if isinstance(item, str):
            lines.append(item)
        elif isinstance(item, dict):
            # Prefer structured text fields in priority order.
            d: dict[str, Any] = item  # pyright: ignore[reportUnknownVariableType]
            matched = False
            for key in ("text", "content", "message", "output"):
                value: Any = d.get(key)
                if value is not None:
                    lines.append(str(value))
                    matched = True
                    break
            if not matched:
                # Fallback: serialize to JSON for transparency.
                try:
                    lines.append(json.dumps(d))
                except (TypeError, ValueError):
                    lines.append(repr(d))
        else:
            lines.append(str(item))
    return lines
