"""Shared code for Codex Server agent variants.

Contains the ``JsonRpcTransport`` protocol, JSON-RPC helpers, prompt assembly,
tool allow-list enforcement, and output normalization used by the local
Codex Server agent (``codex_server``).

Per the integration contract (docs/codex-server/context/contract-matrix.md §4):
  - The v1 experimental tool allow-list is limited to exactly four
    orchestrator callback tools: ``update_checklist``, ``grade``,
    ``submit``, and ``request_clarification``.
  - Any tool invocation outside this list MUST be rejected and logged.
"""

from __future__ import annotations

import json
import logging
import select
import shutil
import subprocess as _sp
from collections.abc import Callable
from typing import Any, cast

from typing_extensions import Protocol

from orchestrator.state.models import ActionLog
from orchestrator.runners.types import (
    ChecklistUpdateCallback,
    GraphPatchCallback,
    CompleteRecoveryCallback,
    ExecutionContext,
    ExecutionMetrics,
    ExecutionResult,
    GradeCallback,
    SubmitCallback,
)
from orchestrator.config.enums import ChecklistStatus

logger = logging.getLogger(__name__)


GRAPH_MACRO_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "create_work_region",
        "create_corrective_region",
        "attach_verifier",
        "attach_check",
        "create_gap_planner",
        "create_join",
        "request_gate",
        "retire_or_supersede",
    }
)


# ---------------------------------------------------------------------------
# Transport protocol (implemented by both stdio and WebSocket variants)
# ---------------------------------------------------------------------------


class JsonRpcTransport(Protocol):
    """Protocol for JSON-RPC 2.0 message transport.

    Implemented by ``RealStdioTransport`` (local subprocess) and
    ``RealWebSocketTransport`` (remote WebSocket).  Fake implementations
    are used in tests via dependency injection — no mocking required.
    """

    async def send(self, message: dict[str, Any]) -> None:
        """Write one JSON-RPC message to the transport."""
        ...

    async def recv(self) -> dict[str, Any]:
        """Read and return the next JSON-RPC message from the transport.

        Raises:
            EOFError: If the connection has been closed by the remote side.
            OSError: On low-level transport failure.
        """
        ...

    async def close(self) -> None:
        """Close the transport and release resources."""
        ...


# ---------------------------------------------------------------------------
# JSON-RPC helpers (pure functions)
# ---------------------------------------------------------------------------


def build_jsonrpc_request(
    req_id: int,
    method: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 request dict.

    Args:
        req_id: Integer request identifier; matched to the response ``id``.
        method: JSON-RPC method name (e.g. ``"thread/start"``).
        params: Method parameters dict.

    Returns:
        A JSON-RPC 2.0 request dict ready to send over the transport.
    """
    return {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}


def extract_tool_call_from_notification(
    notification: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    """Extract ``(tool_name, args)`` from an ``item/started`` mcpToolCall notification.

    Handles the v2 field names (``tool``, ``arguments``) used by the current
    codex app-server, with fallback to v1 field names (``toolName``, ``input``).

    Returns the tool name and input arguments when the notification is an
    ``item/started`` event for an MCP tool call.  Returns ``None`` for all
    other notification types.

    Args:
        notification: A parsed JSON-RPC notification dict.

    Returns:
        ``(tool_name, args)`` tuple if the notification carries an mcpToolCall,
        otherwise ``None``.
    """
    method = notification.get("method", "")
    if method not in ("item/started", "item/completed"):
        return None
    params = notification.get("params", {})
    item: dict[str, Any] = params.get("item", {})
    if item.get("type") != "mcpToolCall":
        return None
    # v2: "tool" field; v1 fallback: "toolName"
    tool_name = str(item.get("tool") or item.get("toolName", ""))
    # v2: "arguments" field; v1 fallback: "input"
    tool_args: dict[str, Any] = item.get("arguments") or item.get("input") or {}
    return (tool_name, tool_args)


def extract_dynamic_tool_call(
    message: dict[str, Any],
) -> tuple[int, str, dict[str, Any]] | None:
    """Extract ``(req_id, tool_name, args)`` from an ``item/tool/call`` server request.

    The ``item/tool/call`` method is used by codex app-server to invoke dynamic
    tools registered in ``thread/start``.  Unlike notifications, this message
    carries an ``id`` field that the client must echo back in the response.

    Args:
        message: A parsed JSON-RPC message dict.

    Returns:
        ``(req_id, tool_name, args)`` tuple if the message is an ``item/tool/call``
        server request, otherwise ``None``.
    """
    if message.get("method") != "item/tool/call":
        return None
    req_id = message.get("id")
    if req_id is None:
        return None
    params = message.get("params", {})
    tool_name = str(params.get("tool", ""))
    tool_args: dict[str, Any] = params.get("arguments") or {}
    return (int(req_id), tool_name, tool_args)


def build_dynamic_tool_call_response(
    req_id: int, success: bool = True, output: str | None = None
) -> dict[str, Any]:
    """Build the JSON-RPC response for an ``item/tool/call`` server request.

    Args:
        req_id: The request ID from the server's ``item/tool/call`` message.
        success: Whether the tool call succeeded.
        output: Optional detail delivered to the agent as the tool result text.
            When provided it REPLACES the generic message — this is how a
            rejected submission's actionable feedback (failing pre-submit
            checks, invalid-state errors) reaches the agent so it can fix and
            retry within the same session.

    Returns:
        A JSON-RPC 2.0 response dict to send back to the server.
    """
    if output:
        text = output
    else:
        text = "Tool executed successfully." if success else "Tool execution failed."
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "success": success,
            "contentItems": [{"type": "inputText", "text": text}],
        },
    }


def build_dynamic_tool_specs(
    is_verifier: bool = False,
    context: ExecutionContext | None = None,
) -> list[dict[str, Any]]:
    """Return the ``dynamicTools`` list for ``thread/start`` params.

    These are the v1 orchestrator callback tools registered with the
    codex app-server session so the agent can invoke them.

    Requires ``experimentalApi: true`` in the ``initialize`` capabilities.

    Args:
        is_verifier: If ``True``, include the ``grade`` tool (verifier phase).
            If ``False`` (default), exclude the ``grade`` tool (builder phase).
        context: Optional execution context for step-level tool specs from
            available_tools. Unknown tools are logged as warnings and skipped.

    Returns:
        List of tool spec dicts suitable for ``thread/start.dynamicTools``.
    """
    submit_spec: dict[str, Any] = {
        "name": "submit",
        "description": "Submit work for verification or complete the verification.",
        "inputSchema": {"type": "object", "properties": {}},
    }
    update_checklist_spec: dict[str, Any] = {
        "name": "update_checklist",
        "description": "Mark a requirement as done, blocked, or not_applicable.",
        "inputSchema": {
            "type": "object",
            "required": ["req_id", "status"],
            "properties": {
                "req_id": {"type": "string", "description": "Requirement ID (e.g. 'R-01')"},
                "status": {
                    "type": "string",
                    "enum": ["done", "blocked", "not_applicable"],
                },
                "note": {"type": "string", "description": "Optional explanation"},
            },
        },
    }
    request_clarification_spec: dict[str, Any] = {
        "name": "request_clarification",
        "description": "Request clarification on ambiguous requirements.",
        "inputSchema": {
            "type": "object",
            "required": ["question"],
            "properties": {
                "question": {"type": "string", "description": "The clarification question"},
            },
        },
    }
    complete_recovery_spec: dict[str, Any] = {
        "name": "complete_recovery",
        "description": (
            "Finalize recovery for a failed task. "
            "Call this after diagnosing the failure. "
            "outcome='retry' to retry the task, "
            "outcome='skip' to skip it (non-critical tasks only), "
            "outcome='abandon' to permanently fail it."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["outcome"],
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": ["retry", "skip", "abandon"],
                    "description": "Recovery decision: retry, skip, or abandon the task",
                },
                "notes": {
                    "type": "string",
                    "description": "Explanation of the recovery decision",
                },
            },
        },
    }
    submit_graph_patch_spec: dict[str, Any] = {
        "name": "submit_graph_patch",
        "description": (
            "Submit a graph patch envelope. Graph planners must use this to "
            "propose graph mutations or an explicit no-op decision."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "object",
                    "required": ["patch_id", "base_graph_position", "ops"],
                    "properties": {
                        "patch_id": {"type": "string"},
                        "base_graph_position": {"type": "integer", "minimum": 0},
                        "ops": {
                            "type": "array",
                            "items": {"type": "object", "additionalProperties": True},
                            "minItems": 0,
                            "maxItems": 200,
                        },
                        "rationale_record_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "patch_id": {"type": "string"},
                "base_graph_position": {"type": "integer", "minimum": 0},
                "ops": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                    "minItems": 0,
                    "maxItems": 200,
                },
                "rationale_record_id": {"type": "string"},
            },
            "oneOf": [
                {"required": ["patch"]},
                {"required": ["patch_id", "base_graph_position", "ops"]},
            ],
            "additionalProperties": False,
        },
    }
    macro_patch_properties = {
        "patch_id": {"type": "string"},
        "base_graph_position": {"type": "integer", "minimum": 0},
        "rationale_record_id": {"type": "string"},
    }
    attach_verifier_spec: dict[str, Any] = {
        "name": "attach_verifier",
        "description": "Attach a verifier to the current graph region.",
        "inputSchema": {
            "type": "object",
            "required": ["patch_id", "base_graph_position", "region_id", "verifier_id"],
            "properties": {
                **macro_patch_properties,
                "region_id": {"type": "string"},
                "verifier_id": {"type": "string"},
                "candidate_source_node_id": {"type": "string"},
                "candidate_id": {"type": "string"},
            },
            "additionalProperties": False,
        },
    }
    attach_check_spec: dict[str, Any] = {
        "name": "attach_check",
        "description": "Attach a check to the current graph region.",
        "inputSchema": {
            "type": "object",
            "required": ["patch_id", "base_graph_position", "region_id", "check_id"],
            "properties": {
                **macro_patch_properties,
                "region_id": {"type": "string"},
                "check_id": {"type": "string"},
                "evidence_source_node_id": {"type": "string"},
                "command_binding": {"type": "string"},
                "hidden_oracle_command": {"type": "string"},
                "command_definition": {"type": "object", "additionalProperties": True},
            },
            "additionalProperties": False,
        },
    }
    request_gate_spec: dict[str, Any] = {
        "name": "request_gate",
        "description": "Request a gate decision for the current graph node.",
        "inputSchema": {
            "type": "object",
            "required": ["patch_id", "base_graph_position", "node_id"],
            "properties": {
                **macro_patch_properties,
                "node_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "additionalProperties": False,
        },
    }
    planner_macro_specs: dict[str, dict[str, Any]] = {
        "create_work_region": {
            "name": "create_work_region",
            "description": "Create a work region in the graph.",
            "inputSchema": {
                "type": "object",
                "required": ["patch_id", "base_graph_position", "region_id"],
                "properties": {
                    **macro_patch_properties,
                    "region_id": {"type": "string"},
                    "worker_id": {"type": "string"},
                    "verifier_id": {"type": "string"},
                    "candidate_id": {"type": "string"},
                    "checks": {"type": "array", "items": {"type": "object"}},
                },
                "additionalProperties": False,
            },
        },
        "create_gap_planner": {
            "name": "create_gap_planner",
            "description": "Create a gap planner node for the graph.",
            "inputSchema": {
                "type": "object",
                "required": ["patch_id", "base_graph_position", "node_id", "region_id"],
                "properties": {
                    **macro_patch_properties,
                    "node_id": {"type": "string"},
                    "region_id": {"type": "string"},
                    "evidence_source_node_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "create_join": {
            "name": "create_join",
            "description": "Create a join node in the graph.",
            "inputSchema": {
                "type": "object",
                "required": ["patch_id", "base_graph_position", "join_id"],
                "properties": {
                    **macro_patch_properties,
                    "join_id": {"type": "string"},
                    "source_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                    },
                    "sources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["node_id"],
                            "properties": {
                                "node_id": {"type": "string"},
                                "port": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                        "minItems": 1,
                    },
                },
                "additionalProperties": False,
            },
        },
        "retire_or_supersede": {
            "name": "retire_or_supersede",
            "description": "Retire or supersede an existing graph node.",
            "inputSchema": {
                "type": "object",
                "required": ["patch_id", "base_graph_position", "target_id", "action"],
                "properties": {
                    **macro_patch_properties,
                    "target_id": {"type": "string"},
                    "action": {"type": "string", "enum": ["retire", "supersede"]},
                    "replacement_ops": {"type": "array", "items": {"type": "object"}},
                },
                "additionalProperties": False,
            },
        },
        "create_corrective_region": {
            "name": "create_corrective_region",
            "description": "Create a corrective region in the graph.",
            "inputSchema": {
                "type": "object",
                "required": ["patch_id", "base_graph_position", "region_id"],
                "properties": {
                    **macro_patch_properties,
                    "region_id": {"type": "string"},
                    "worker_id": {"type": "string"},
                    "verifier_id": {"type": "string"},
                    "candidate_id": {"type": "string"},
                    "classified_gap_source_node_id": {"type": "string"},
                    "checks": {"type": "array", "items": {"type": "object"}},
                },
                "additionalProperties": False,
            },
        },
    }
    grade_spec: dict[str, Any] = {
        "name": "grade",
        "description": "Set a grade on a requirement (verifier phase only).",
        "inputSchema": {
            "type": "object",
            "required": ["req_id", "grade"],
            "properties": {
                "req_id": {"type": "string"},
                "grade": {
                    "type": "string",
                    "enum": ["A", "B", "C", "D", "F"],
                },
                "grade_reason": {"type": "string", "description": "Optional explanation"},
            },
        },
    }

    specs: list[dict[str, Any]] = (
        [
            submit_spec,
            grade_spec,
            complete_recovery_spec,
        ]
        if is_verifier
        else [
            update_checklist_spec,
            submit_spec,
            request_clarification_spec,
        ]
    )

    if not is_verifier and context is not None and context.node_kind == "planner":
        if context.node_role == "planner":
            specs.extend(
                [
                    planner_macro_specs["create_work_region"],
                    attach_verifier_spec,
                    attach_check_spec,
                    planner_macro_specs["create_gap_planner"],
                    planner_macro_specs["create_join"],
                    request_gate_spec,
                    planner_macro_specs["retire_or_supersede"],
                    submit_graph_patch_spec,
                ]
            )
        elif context.node_role == "gap_planner":
            specs.extend(
                [
                    planner_macro_specs["create_corrective_region"],
                    attach_verifier_spec,
                    attach_check_spec,
                    request_gate_spec,
                    submit_graph_patch_spec,
                ]
            )

    # Add step-level tools from context.available_tools
    if context and context.available_tools:
        existing_names = {s["name"] for s in specs}
        for tool_name in context.available_tools:
            if tool_name in existing_names:
                continue
            # Log warning for unknown tools (Codex Server has no additional built-in tool registry)
            logger.warning(
                "Unknown tool '%s' in available_tools for Codex Server — skipping",
                tool_name,
            )

    return specs


def extract_agent_message_delta(notification: dict[str, Any]) -> str | None:
    """Extract incremental agent text from an ``item/agentMessage/delta`` notification.

    Supports the current protocol format where ``params.delta`` is a plain string
    (``AgentMessageDeltaNotification`` schema).

    Args:
        notification: A parsed JSON-RPC notification dict.

    Returns:
        The delta text string, or ``None`` if the notification is not an
        agent message delta or carries no text.
    """
    if notification.get("method") != "item/agentMessage/delta":
        return None
    params = notification.get("params", {})
    # Current format: params.delta is a plain string.
    delta = params.get("delta")
    if isinstance(delta, str) and delta:
        return delta
    return None


def extract_item_activity_line(notification: dict[str, Any]) -> str | None:
    """Summarize a completed non-message item as a single output line.

    Codex models do most of their work through command executions and file
    changes while emitting little or no agent-message text, so a session can
    run for minutes with nothing reaching the live activity feed. This helper
    turns each completed work item into one human-readable line for streaming
    via ``on_output``.

    Args:
        notification: A parsed JSON-RPC notification dict.

    Returns:
        A one-line summary for command executions, file changes, and tool
        calls. ``None`` for agent messages (already streamed as deltas),
        reasoning items (too noisy), and all other notifications.
    """
    if notification.get("method") != "item/completed":
        return None
    params = notification.get("params", {})
    item: dict[str, Any] = params.get("item", {})
    item_type = str(item.get("type", ""))
    normalized = item_type.replace("_", "").lower()

    if normalized == "commandexecution":
        command = str(item.get("command", "")).strip()
        exit_code = item.get("exit_code", item.get("exitCode"))
        suffix = f" (exit {exit_code})" if isinstance(exit_code, int) else ""
        return f"$ {command}{suffix}" if command else None

    if normalized == "filechange":
        changes_raw = item.get("changes")
        if not isinstance(changes_raw, list):
            return "file change"
        changes = cast(list[Any], changes_raw)
        paths = [
            str(cast(dict[str, Any], change).get("path", ""))
            for change in changes
            if isinstance(change, dict)
        ]
        named = ", ".join(p for p in paths if p)
        return f"file change: {named}" if named else f"file change: {len(changes)} update(s)"

    if normalized in ("mcptoolcall", "toolcall", "tooluse", "dynamictoolcall"):
        tool_name = str(item.get("tool") or item.get("toolName") or item_type)
        status = str(item.get("status", "")).strip().lower()
        suffix = f" ({status})" if status else ""
        return f"tool: {tool_name}{suffix}"

    return None


def extract_turn_error(notification: dict[str, Any]) -> str | None:
    """Extract error detail from a failed ``turn/completed`` notification.

    Args:
        notification: A parsed JSON-RPC notification dict.

    Returns:
        The error message string if the turn payload carries one, else ``None``.
    """
    if notification.get("method") != "turn/completed":
        return None
    params = notification.get("params", {})
    turn: dict[str, Any] = params.get("turn", {})
    error = turn.get("error")
    if isinstance(error, dict):
        error_dict = cast(dict[str, Any], error)
        message: Any = error_dict.get("message") or error_dict.get("detail") or error_dict
        return str(message)
    if isinstance(error, str) and error:
        return error
    return None


def is_terminal_notification(notification: dict[str, Any]) -> tuple[bool, str]:
    """Return ``(True, status)`` for a ``turn/completed`` notification.

    Args:
        notification: A parsed JSON-RPC notification dict.

    Returns:
        ``(True, status_str)`` when the notification is ``turn/completed``,
        where ``status_str`` is one of ``"completed"``, ``"interrupted"``,
        or ``"systemError"``.  Returns ``(False, "")`` for all other messages.
    """
    if notification.get("method") != "turn/completed":
        return (False, "")
    params = notification.get("params", {})
    turn: dict[str, Any] = params.get("turn", {})
    status = str(turn.get("status", ""))
    return (True, status)


def extract_token_usage_update(notification: dict[str, Any]) -> dict[str, int] | None:
    """Extract token usage from a ``thread/tokenUsage/updated`` notification.

    The codex app-server (v0.139.0+) delivers incremental token usage via
    ``thread/tokenUsage/updated`` notifications with a cumulative/per-turn split.
    This function tolerantly locates the usage object regardless of params nesting
    and maps camelCase/snake_case field names to the orchestrator's normalized keys.

    Field mapping (reasoning is folded into write; the billed-output convention):
      - ``inputTokens|input_tokens`` → ``tokens_read``
      - ``cachedInputTokens|cached_input_tokens|cache_read_input_tokens`` → ``tokens_cache``
      - ``outputTokens|output_tokens`` + ``reasoningOutputTokens|reasoning_output_tokens``
        → ``tokens_write`` (reasoning folded into write)
      - ``reasoningOutputTokens|reasoning_output_tokens`` → ``tokens_reasoning``
        (also surfaced separately for observability)

    Args:
        notification: A parsed JSON-RPC notification dict.

    Returns:
        Dict with keys ``tokens_read``, ``tokens_write``, ``tokens_cache``,
        ``tokens_reasoning`` when the notification is ``thread/tokenUsage/updated``,
        otherwise ``None``.
    """
    if notification.get("method") != "thread/tokenUsage/updated":
        return None

    params = notification.get("params", {})

    # Locate the usage object tolerantly: prefer cumulative total_token_usage,
    # else last_token_usage, else recursively find the first dict with inputTokens|input_tokens.
    usage: dict[str, Any] | None = None
    for wrapper_key in ("total_token_usage", "totalTokenUsage"):
        wrapper = params.get(wrapper_key)
        if isinstance(wrapper, dict):
            usage = cast(dict[str, Any], wrapper)
            break

    if usage is None:
        for wrapper_key in ("last_token_usage", "lastTokenUsage"):
            wrapper = params.get(wrapper_key)
            if isinstance(wrapper, dict):
                usage = cast(dict[str, Any], wrapper)
                break

    if usage is None:
        # Recursive search for the first dict with inputTokens|input_tokens.
        def _find_usage(obj: object) -> dict[str, Any] | None:
            if isinstance(obj, dict):
                obj_dict = cast(dict[str, Any], obj)
                if "inputTokens" in obj_dict or "input_tokens" in obj_dict:
                    return obj_dict
                for value in obj_dict.values():
                    found = _find_usage(value)
                    if found is not None:
                        return found
            return None

        usage = _find_usage(params)

    if usage is None:
        return None

    result: dict[str, int] = {
        "tokens_read": 0,
        "tokens_write": 0,
        "tokens_cache": 0,
        "tokens_reasoning": 0,
    }

    # Input tokens
    for key in ("inputTokens", "input_tokens"):
        val = usage.get(key)
        if val is not None:
            result["tokens_read"] = int(val)
            break

    # Cache tokens
    for key in ("cachedInputTokens", "cached_input_tokens", "cache_read_input_tokens"):
        val = usage.get(key)
        if val is not None:
            result["tokens_cache"] = int(val)
            break

    # Output tokens (base)
    output_tokens = 0
    for key in ("outputTokens", "output_tokens"):
        val = usage.get(key)
        if val is not None:
            output_tokens = int(val)
            break

    # Reasoning output tokens (folded into write for billing, but also surfaced separately)
    reasoning_tokens = 0
    for key in ("reasoningOutputTokens", "reasoning_output_tokens"):
        val = usage.get(key)
        if val is not None:
            reasoning_tokens = int(val)
            break

    result["tokens_reasoning"] = reasoning_tokens
    result["tokens_write"] = output_tokens + reasoning_tokens

    return result


def extract_turn_usage(notification: dict[str, Any]) -> dict[str, int]:
    """Extract token usage from a ``turn/completed`` notification.

    Looks for ``params.turn.usage`` and tries multiple field name patterns
    to handle different server versions:

    - ``input_tokens`` / ``prompt_tokens`` → ``tokens_read``
    - ``output_tokens`` / ``completion_tokens`` → ``tokens_write``
    - ``cache_read_tokens`` / ``cached_tokens`` / ``cache_read_input_tokens`` → ``tokens_cache``
    - ``reasoning_output_tokens`` → folded into ``tokens_write``

    Args:
        notification: A parsed JSON-RPC notification dict.

    Returns:
        Dict with keys ``tokens_read``, ``tokens_write``, ``tokens_cache``,
        ``tokens_reasoning``. All values default to 0 when usage data is absent.
    """
    result = {"tokens_read": 0, "tokens_write": 0, "tokens_cache": 0, "tokens_reasoning": 0}

    if notification.get("method") != "turn/completed":
        return result

    params = notification.get("params", {})
    turn: dict[str, Any] = params.get("turn", {})

    logger.debug("extract_turn_usage: turn payload keys=%s", list(turn.keys()))

    # Protocol sends camelCase "tokenUsage"; fall back to snake_case "usage" for
    # older/alternative server versions.
    usage: dict[str, Any] = turn.get("tokenUsage") or turn.get("usage") or {}
    if not usage:
        return result

    logger.debug("extract_turn_usage: usage=%s", usage)

    # Input/prompt tokens — camelCase (protocol) then snake_case (fallback)
    for key in ("inputTokens", "input_tokens", "prompt_tokens"):
        val = usage.get(key)
        if val is not None:
            result["tokens_read"] = int(val)
            break

    # Output/completion tokens — camelCase (protocol) then snake_case (fallback)
    output_tokens = 0
    for key in ("outputTokens", "output_tokens", "completion_tokens"):
        val = usage.get(key)
        if val is not None:
            output_tokens = int(val)
            break

    # Reasoning output tokens (folded into write for billing, but also surfaced separately)
    reasoning_tokens = 0
    for key in ("reasoningOutputTokens", "reasoning_output_tokens"):
        val = usage.get(key)
        if val is not None:
            reasoning_tokens = int(val)
            break

    result["tokens_reasoning"] = reasoning_tokens
    result["tokens_write"] = output_tokens + reasoning_tokens

    # Cache tokens — camelCase (protocol) then snake_case (fallback)
    for key in ("cacheReadTokens", "cache_read_tokens", "cached_tokens", "cache_read_input_tokens"):
        val = usage.get(key)
        if val is not None:
            result["tokens_cache"] = int(val)
            break

    return result


# ---------------------------------------------------------------------------
# Tool allow-list
# ---------------------------------------------------------------------------


#: v1 Codex callback tool allow-list — contract-matrix.md §4.
CODEX_SERVER_TOOL_ALLOWLIST: frozenset[str] = (
    frozenset(
        {
            "update_checklist",
            "grade",
            "submit",
            "submit_graph_patch",
            "request_clarification",
            "complete_recovery",
        }
    )
    | GRAPH_MACRO_TOOL_NAMES
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
    workflow_action = (
        "Perform only oversight/documentation/API operations. Do not implement source or test changes."
        if context.work_mode == "oversight"
        else "Implement each requirement."
    )
    git_section = (
        "## Git Workflow\n"
        "Do not run `git commit` manually; the orchestrator auto-commits allowed changes when you submit.\n"
        "- Leave only task-requested documentation/metadata changed, such as "
        "`docs/super-parent/`\n"
        "- Do not edit source code, tests, dependency files, lockfiles, migrations, or UI files.\n"
        "- Always use `git --no-pager` for git commands.\n"
        if context.work_mode == "oversight"
        else "## Git Workflow\n"
        "Do not run `git commit` manually; the orchestrator auto-commits uncommitted changes when you submit.\n"
        "- Use git status and diff only to inspect your changes before submitting.\n"
        "- Always use `git --no-pager` for git commands.\n"
    )

    if is_verifier:
        verifier_action = (
            "Review the oversight artifacts, orchestrator state updates, and evidence decisions "
            "made by the builder."
            if context.work_mode == "oversight"
            else "Review the code changes made by the builder."
        )
        tool_section = (
            "## Orchestrator Integration (Verifier)\n"
            "You are connected to an orchestrator. Your role is to VERIFY the builder's work.\n\n"
            "### Required Workflow\n"
            f"1. {verifier_action}\n"
            "2. Grade EVERY requirement using **grade**.\n"
            "3. After grading all requirements, call **submit** to complete verification.\n"
            "4. Grades: A (excellent), B (good), C (adequate), D (poor), F (failing)\n\n"
            "### Available Callback Tools\n"
            "- **grade**(req_id, grade, grade_reason?)\n"
            "  Set a grade on a requirement.\n"
            "  - req_id: The requirement ID (e.g. 'R-01', 'R-02')\n"
            "  - grade: One of 'A', 'B', 'C', 'D', 'F'\n"
            "  - grade_reason: Optional explanation for the grade\n\n"
            "- **submit**()\n"
            "  Complete the verification after grading all requirements.\n\n"
            "- **complete_recovery**(outcome, notes?)\n"
            "  Finalize recovery for a failed task only when this verifier phase is handling recovery."
        )
    else:
        planner_tool_section = ""
        if context.node_kind == "planner" and context.node_role in {"planner", "gap_planner"}:
            planner_tool_section = (
                "\n### Planner Graph-Mutation Tool\n"
                "- Prefer graph macros: **create_work_region**, **attach_verifier**, "
                "**attach_check**, **create_gap_planner**, **create_join**, "
                "**request_gate**, and **retire_or_supersede**. Gap planners use "
                "**create_corrective_region**, **attach_verifier**, **attach_check**, "
                "and **request_gate**.\n"
                "  Macro tools submit macro-backed patch envelopes and return accepted or rejected feedback.\n"
                "- **submit_graph_patch**(patch) or **submit_graph_patch**(patch_id, base_graph_position, ops, rationale_record_id?)\n"
                "  Submit an explicit graph patch envelope only when a macro cannot express the mutation.\n"
                "  - patch_id: Stable id for this attempt.\n"
                "  - base_graph_position: Use current_graph_position from the planner packet.\n"
                "  - ops: Raw fallback list using only allowed_patch_operations; gap planners may use [] for an explicit no-op decision.\n"
                "  - rationale_record_id: Optional accepted evidence record supporting the patch.\n"
                "  If feedback says stale, malformed, or rejected, submit a corrected macro or patch instead of editing graph events directly.\n"
                "  Plain submit is only for finishing after at least one submit_graph_patch attempt."
            )

        tool_section = (
            "## Orchestrator Integration\n"
            "You are connected to an orchestrator that tracks your progress. "
            "Use the callback tools below to report your work.\n\n"
            "### Required Workflow\n"
            "1. Read the requirements above carefully.\n"
            f"2. {workflow_action}\n"
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
            "  Request clarification on ambiguous requirements.\n\n"
            f"{planner_tool_section}\n"
            f"{git_section}\n"
            "## Sandbox Constraints\n"
            "- You run in a workspace-write sandbox with network access disabled.\n"
            "- File operations are restricted to the working directory.\n"
            "- Do not attempt to install packages or fetch resources from the internet.\n\n"
            "## Response Style\n"
            "- Keep responses concise. Focus on actions, not verbose explanations.\n"
            "- Prefer targeted, focused changes over large sweeping edits.\n"
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


# ---------------------------------------------------------------------------
# Execution result construction
# ---------------------------------------------------------------------------


def build_execution_result(
    output_lines: list[str],
    duration_ms: int,
    tokens_read: int = 0,
    tokens_write: int = 0,
    tokens_cache: int = 0,
    num_actions: int = 0,
    agent_model: str | None = None,
) -> ExecutionResult:
    """Build an ``ExecutionResult`` from collected output lines and elapsed time.

    The codex app-server sends text as character-level delta fragments via
    ``item/agentMessage/delta`` notifications.  Concatenate them into a single
    string and then split on real newlines so the stored output is readable.

    Args:
        output_lines: Text fragments collected from agent message delta events.
        duration_ms: Wall-clock duration of the session in milliseconds.
        tokens_read: Prompt/input tokens consumed.
        tokens_write: Completion/output tokens produced.
        tokens_cache: Cache-read tokens (if reported by the server).
        num_actions: Number of tool invocations made during the session.
        agent_model: Model name used for the session when known.

    Returns:
        Populated ``ExecutionResult`` with ``success=True``.
    """
    # Join char-level deltas without separator, then split on real newlines.
    combined = "".join(output_lines)
    final_lines = combined.splitlines() if combined else []
    return ExecutionResult(
        success=True,
        metrics=normalize_codex_metrics(
            duration_ms=duration_ms,
            tokens_read=tokens_read,
            tokens_write=tokens_write,
            tokens_cache=tokens_cache,
            num_actions=num_actions,
        ),
        output_lines=final_lines,
        action_log=ActionLog(
            agent_model=agent_model,
            total_duration_ms=duration_ms,
            total_input_tokens=tokens_read,
            total_output_tokens=tokens_write,
            total_cache_read_tokens=tokens_cache,
        ),
    )


# ---------------------------------------------------------------------------
# Shared tool-call routing
# ---------------------------------------------------------------------------


async def route_tool_call(
    tool_name: str,
    args: dict[str, Any],
    on_checklist_update: ChecklistUpdateCallback,
    on_submit: SubmitCallback,
    on_submit_graph_patch: GraphPatchCallback | None = None,
    on_grade: GradeCallback | None = None,
    on_complete_recovery: CompleteRecoveryCallback | None = None,
    *,
    agent_label: str = "CodexServer",
) -> str:
    """Route an allow-listed callback tool call to the appropriate callback.

    Enforces the v1 allow-list (``CODEX_SERVER_TOOL_ALLOWLIST``) before
    dispatching.  Disallowed tool names raise ``ValueError`` via
    ``enforce_tool_allowlist``.

    Tool routing:
    - ``update_checklist`` → ``on_checklist_update(req_id, status, note)``
    - ``submit``           → ``on_submit()``
    - ``submit_graph_patch`` → ``on_submit_graph_patch(payload)``
    - ``grade``            → ``on_grade(req_id, grade, grade_reason)`` (verifier only)
    - ``request_clarification`` → logged; no callback in v1

    Args:
        tool_name: Name of the callback tool the Codex session invoked.
        args: Tool argument dict from the Codex server event payload.
        on_checklist_update: Bound checklist-update callback.
        on_submit: Bound submit callback.
        on_submit_graph_patch: Bound graph patch callback.
        on_grade: Bound grade callback (``None`` in builder phase).
        agent_label: Label used in log messages (e.g. ``"CodexServerAgent"``).

    Raises:
        ValueError: If ``tool_name`` is not on the v1 allow-list.
    """
    enforce_tool_allowlist(tool_name)

    if tool_name == "update_checklist":
        req_id: str = str(args.get("req_id", "")).strip()
        if not req_id:
            raise ValueError("update_checklist requires a non-empty 'req_id'")
        raw_status: str = str(args.get("status", "done"))
        note: str | None = args.get("note")
        status = ChecklistStatus(raw_status)
        await on_checklist_update(req_id, status, note)

    elif tool_name == "submit":
        await on_submit()

    elif tool_name == "submit_graph_patch":
        if on_submit_graph_patch is None:
            raise ValueError("submit_graph_patch is not registered for this session")
        payload = _normalize_patch_payload(args)
        return await on_submit_graph_patch(payload)

    elif tool_name in GRAPH_MACRO_TOOL_NAMES:
        if on_submit_graph_patch is None:
            raise ValueError(f"{tool_name} is not registered for this session")
        payload = _normalize_macro_tool_payload(tool_name, args)
        return await on_submit_graph_patch(payload)

    elif tool_name == "grade":
        if on_grade is not None:
            req_id = str(args.get("req_id", "")).strip()
            grade: str = str(args.get("grade", "")).strip()
            if not req_id:
                raise ValueError("grade requires a non-empty 'req_id'")
            if not grade:
                raise ValueError("grade requires a non-empty 'grade'")
            grade_reason: str | None = args.get("grade_reason")
            await on_grade(req_id, grade, grade_reason)
        else:
            logger.warning("%s: 'grade' tool called in builder phase — ignoring", agent_label)

    elif tool_name == "request_clarification":
        question: str = str(args.get("question", ""))
        logger.info("%s: request_clarification received — question=%r", agent_label, question)

    elif tool_name == "complete_recovery":
        outcome: str = str(args.get("outcome", "retry"))
        notes: str | None = args.get("notes")
        if on_complete_recovery is not None:
            await on_complete_recovery(outcome, notes)
        else:
            logger.info(
                "%s: complete_recovery called (outcome=%r) but no callback registered — ignoring",
                agent_label,
                outcome,
            )
    return ""


def _normalize_macro_tool_payload(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    patch_id = args.get("patch_id")
    base_graph_position = args.get("base_graph_position")
    if not isinstance(patch_id, str) or not patch_id.strip():
        raise ValueError(f"{tool_name} requires a non-empty patch_id")
    if not isinstance(base_graph_position, int):
        raise ValueError(f"{tool_name} requires integer base_graph_position")

    macro_args = {
        key: value
        for key, value in args.items()
        if key not in {"patch_id", "base_graph_position", "rationale_record_id"}
    }
    payload: dict[str, Any] = {
        "patch_id": patch_id,
        "base_graph_position": base_graph_position,
        "macro_invocations": [{"macro": tool_name, "args": macro_args}],
    }
    rationale_record_id = args.get("rationale_record_id")
    if isinstance(rationale_record_id, str):
        payload["rationale_record_id"] = rationale_record_id
    return payload


def _normalize_patch_payload(args: dict[str, Any]) -> dict[str, Any]:
    """Normalize planner patch arguments into a top-level PatchEnvelope payload."""
    if "patch" in args:
        if len(args) != 1:
            raise ValueError("submit_graph_patch accepts either `patch` or patch fields, not both")
        raw_patch = args.get("patch")
        if not isinstance(raw_patch, dict):
            raise ValueError("submit_graph_patch requires `patch` to be an object")
        patch = cast(dict[str, Any], raw_patch)
        patch_id = patch.get("patch_id")
        base_graph_position = patch.get("base_graph_position")
        ops = patch.get("ops")
        rationale_record_id = patch.get("rationale_record_id")
    else:
        patch_id = args.get("patch_id")
        base_graph_position = args.get("base_graph_position")
        ops = args.get("ops")
        rationale_record_id = args.get("rationale_record_id")

    if not isinstance(patch_id, str) or not patch_id.strip():
        raise ValueError("submit_graph_patch requires a non-empty patch_id")
    if not isinstance(base_graph_position, int):
        raise ValueError("submit_graph_patch requires integer base_graph_position")
    if not isinstance(ops, list):
        raise ValueError("submit_graph_patch requires an ops list")

    payload: dict[str, Any] = {
        "patch_id": patch_id,
        "base_graph_position": base_graph_position,
        "ops": ops,
    }
    if isinstance(rationale_record_id, str):
        payload["rationale_record_id"] = rationale_record_id
    return payload


# ---------------------------------------------------------------------------
# Output normalization (kept for backwards compatibility)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Model discovery
# ---------------------------------------------------------------------------


# Historical reference of known Codex model IDs (not used as a runtime fallback).
# Kept for reference only — do not use as a default when model discovery fails,
# as these models may be deprecated or unavailable at any time.
_CODEX_FALLBACK_MODELS: list[str] = [
    "gpt-5.3-codex",
    "gpt-5.2-codex",
    "gpt-5.1-codex-max",
    "gpt-5.2",
    "gpt-5.1-codex-mini",
]

# Preferred Codex models in descending priority order.
# When multiple models are discovered, the first match here is used as the default.
# Excludes known-deprecated models (e.g. gpt-5.2-codex) that the Codex server may
# list but cannot actually execute.
_PREFERRED_CODEX_MODELS: tuple[str, ...] = (
    "gpt-5.3-codex",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini",
)

# Models known to be listed by the Codex API but not actually executable.
# These are never used as defaults and are always rejected at run-creation time.
_KNOWN_UNSUPPORTED_CODEX_MODELS: frozenset[str] = frozenset({"gpt-5.2-codex"})


def select_preferred_codex_model(available_models: list[str]) -> str | None:
    """Pick the best default model from a list of discovered Codex model IDs.

    Iterates through ``_PREFERRED_CODEX_MODELS`` in priority order and returns
    the first one present in *available_models*.  Falls back to the first entry
    in *available_models* that is not in ``_KNOWN_UNSUPPORTED_CODEX_MODELS``.
    Returns ``None`` when the list is empty or all available models are known
    to be unsupported, so that the model field keeps no default.

    Args:
        available_models: Model IDs returned by ``fetch_codex_models()``.

    Returns:
        Preferred model ID to use as the default, or ``None`` if no safe
        default can be determined.
    """
    if not available_models:
        return None
    for preferred in _PREFERRED_CODEX_MODELS:
        if preferred in available_models:
            return preferred
    # Fallback: first model that is not known-unsupported
    for model in available_models:
        if model not in _KNOWN_UNSUPPORTED_CODEX_MODELS:
            return model
    # All available models are known-unsupported; signal no safe default
    return None


class CodexModelProcess(Protocol):
    """Minimal process protocol used by Codex model discovery."""

    stdin: Any | None
    stdout: Any | None

    def terminate(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def kill(self) -> None: ...


CodexModelProcessFactory = Callable[..., CodexModelProcess]


def extract_codex_model_ids(model_resp: dict[str, Any] | None) -> list[str]:
    """Extract visible Codex model IDs from a ``model/list`` JSON-RPC response."""
    if model_resp is None:
        return []

    result: Any = model_resp.get("result")
    if result is None:
        return []

    def _to_model_dicts(src: Any) -> list[dict[str, Any]]:
        if not isinstance(src, list):
            return []
        out: list[dict[str, Any]] = []
        for item in src:  # type: ignore[reportUnknownVariableType]
            if isinstance(item, dict):
                out.append(dict(item))  # type: ignore[arg-type]
        return out

    if isinstance(result, list):
        models_raw = _to_model_dicts(result)
    elif isinstance(result, dict):
        result_dict = cast(dict[str, Any], result)
        raw: Any = result_dict.get("data") or result_dict.get("models") or []
        models_raw = _to_model_dicts(raw)
    else:
        models_raw = []

    if not models_raw:
        return []

    visible = [m for m in models_raw if not m.get("hidden", False)]
    chosen = visible if visible else models_raw
    discovered = [str(m["id"]) for m in chosen if "id" in m]
    return discovered


def _default_codex_model_process_factory(*args: Any, **kwargs: Any) -> CodexModelProcess:
    return _sp.Popen(*args, **kwargs)


def fetch_codex_models(
    *,
    codex_path: str | None = "auto",
    process_factory: CodexModelProcessFactory = _default_codex_model_process_factory,
) -> list[str]:
    """Fetch the list of available model IDs from a local Codex app server.

    Spawns a short-lived ``codex app-server`` subprocess, performs the
    required ``initialize``/``initialized`` handshake, sends ``model/list``,
    reads the response, then terminates the process immediately.

    Only non-hidden models are returned.  If all models are hidden (or the
    ``hidden`` field is absent), all models are returned.

    Returns an empty list when the binary is present but the API returns no
    models (e.g. older CLI versions that don't implement ``model/list``).

    Returns:
        Ordered list of model ID strings, or ``[]`` on failure.
    """
    resolved_codex_path = shutil.which("codex") if codex_path == "auto" else codex_path
    if resolved_codex_path is None:
        return []

    try:
        proc = process_factory(
            [resolved_codex_path, "app-server"],
            stdin=_sp.PIPE,
            stdout=_sp.PIPE,
            stderr=_sp.DEVNULL,
            text=True,
            bufsize=1,
        )

        def _send(msg: dict[str, Any]) -> None:
            assert proc.stdin is not None
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()

        def _read_until_id(
            target_id: int, max_lines: int = 200, timeout_secs: float = 15.0
        ) -> dict[str, Any] | None:
            """Read stdout lines until a JSON-RPC response with the given id is found."""
            assert proc.stdout is not None
            use_select = True
            for _ in range(max_lines):
                if use_select:
                    # Use select to avoid blocking indefinitely when the process
                    # hangs (e.g. sandbox blocks socket.bind).
                    try:
                        ready, _, _ = select.select([proc.stdout], [], [], timeout_secs)
                        if not ready:
                            return None
                    except (ValueError, OSError):
                        # StringIO or non-selectable fd (e.g. in tests) — fall back
                        use_select = False
                line = proc.stdout.readline()
                if not line:
                    return None
                try:
                    obj = json.loads(line)
                    if obj.get("id") == target_id:
                        return obj
                except json.JSONDecodeError:
                    pass
            return None

        # Step 1: Initialize — wait for response before proceeding.
        # (matches what CodexServerAgent.execute() does via _send_and_wait)
        _send(
            {
                "jsonrpc": "2.0",
                "method": "initialize",
                "id": 1,
                "params": {
                    "clientInfo": {
                        "name": "orchestrator",
                        "title": "Orchestrator",
                        "version": "0.1.0",
                    },
                    "capabilities": {"experimentalApi": True},
                },
            }
        )
        init_resp = _read_until_id(1)
        if init_resp is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
            finally:
                if proc.stdin:
                    proc.stdin.close()
                if proc.stdout:
                    proc.stdout.close()
            return []

        # Step 2: Acknowledge initialisation.
        _send({"jsonrpc": "2.0", "method": "initialized", "params": {}})

        # Step 3: Request the model list and wait for the response.
        _send({"jsonrpc": "2.0", "method": "model/list", "id": 2, "params": {}})
        model_resp = _read_until_id(2)

        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
        finally:
            if proc.stdin:
                proc.stdin.close()
            if proc.stdout:
                proc.stdout.close()

        return extract_codex_model_ids(model_resp)

    except Exception:
        return []


def validate_codex_model_selection(
    model: str,
    available_models: list[str],
) -> str | None:
    """Validate a Codex model selection against the discovered available models.

    Models in ``_KNOWN_UNSUPPORTED_CODEX_MODELS`` are always rejected even
    when they appear in *available_models* — they are discoverable but cannot
    execute.  When *available_models* is empty and the model is not known-
    unsupported, validation is skipped (discovery failed or Codex not installed).

    Args:
        model: The model ID the caller intends to use.
        available_models: The list of model IDs returned by
            ``fetch_codex_models()``.  An empty list means discovery did not
            succeed and validation is skipped (unless the model is known-bad).

    Returns:
        ``None`` when the selection is valid (or when validation cannot be
        performed).  An error message string when the model is known-unsupported
        or is not present in *available_models*.
    """
    if model in _KNOWN_UNSUPPORTED_CODEX_MODELS:
        if available_models:
            safe_models = [m for m in available_models if m not in _KNOWN_UNSUPPORTED_CODEX_MODELS]
            suggestion = ", ".join(safe_models) if safe_models else "none available"
        else:
            suggestion = "none discovered — run GET /api/agent-runners to refresh"
        return (
            f"Model '{model}' is not supported by Codex and cannot be used. "
            f"Supported models: {suggestion}. "
            "Use GET /api/agent-runners to discover available models."
        )
    if not available_models:
        return None
    if model in available_models:
        return None
    joined = ", ".join(available_models)
    return (
        f"Model '{model}' is not available for the selected Codex runner. "
        f"Available models: {joined}. "
        "Use GET /api/agent-runners to discover available models."
    )


# Keep extract_events as a deprecated alias so any remaining references don't break
# immediately. It will be removed in a follow-up cleanup.
def extract_events(events_payload: Any) -> list[dict[str, Any]]:  # pragma: no cover
    """Deprecated — HTTP-era event extractor. Do not use."""
    return cast(
        "list[dict[str, Any]]",
        events_payload if isinstance(events_payload, list) else events_payload.get("events", []),
    )
