"""Claude SDK agent — direct Anthropic API integration.

Uses the ``anthropic`` Python SDK to run tasks in-process via the Messages API
with tool use.  No subprocess is spawned; the agent communicates directly with
the Anthropic API over HTTPS.

Orchestrator callback tools (update_checklist, grade, submit,
request_clarification) are defined as Anthropic tool schemas and dispatched
when Claude invokes them in the agentic loop.

The SDK import is deferred to a module-level ``try/except`` so that the rest
of the orchestrator works even when ``anthropic`` is not installed.

Test injection:
    _client: Inject a fake Anthropic client to replace the real one.  When
        set, no real API calls are made.  Leading underscore signals test-only
        use.
    _environ: Inject a controlled environment dict for credential resolution in
        tests.  When provided, real os.environ and keychain lookups are skipped.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from typing import Any

from orchestrator.runners.errors import (
    AgentCancelledError,
    AgentExecutionError,
    AgentNotAvailableError,
)
from orchestrator.runners.types import (
    AgentRunnerInfo,
    AgentMetadataCallback,
    AgentQuota,
    ChecklistUpdateCallback,
    EscalationCallback,
    ExecutionContext,
    ExecutionMetrics,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
    SubmitCallback,
)
from orchestrator.config.enums import AgentRunnerType, ChecklistStatus
from orchestrator.workflow.errors import GateBlockedError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Claude CLI keychain auth helper
# ---------------------------------------------------------------------------


def _read_claude_cli_oauth_token() -> str | None:
    """Read the Claude CLI OAuth access token from the macOS keychain.

    Uses the same mechanism as ``ClaudeCliQuotaAgent`` in ``cli.py``.
    Returns ``None`` on non-macOS platforms, when ``claude`` is not installed,
    the user is not logged in, or on any error.

    The returned ``sk-ant-oat01-...`` token works with the Anthropic API when
    paired with the ``anthropic-beta: oauth-2025-04-20`` header.
    """
    if sys.platform != "darwin" or shutil.which("security") is None:
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-g"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        # The password JSON appears in stderr as: password: "...json..."
        combined = result.stdout + result.stderr
        password_line = next(
            (line for line in combined.splitlines() if line.startswith("password:")),
            None,
        )
        if not password_line:
            return None
        raw_json = password_line[len('password: "') : -1]
        creds = json.loads(raw_json)
        token: str | None = creds.get("claudeAiOauth", {}).get("accessToken")
        return token or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Model discovery
# ---------------------------------------------------------------------------


def fetch_claude_models(
    api_key: str | None = None,
    auth_token: str | None = None,
) -> list[str]:
    """Fetch available Claude model IDs from the Anthropic API.

    Uses the same credential resolution chain as ClaudeSDKAgent:
    1. api_key argument or ANTHROPIC_API_KEY env var
    2. auth_token argument or ANTHROPIC_AUTH_TOKEN env var
    3. Claude CLI OAuth token from the macOS keychain

    Returns an empty list on any error (SDK not installed, no credentials,
    API unreachable, etc.). All exceptions are swallowed so callers are
    never interrupted by model-discovery failures.

    Args:
        api_key: Optional explicit Anthropic API key.
        auth_token: Optional explicit bearer token.

    Returns:
        Ordered list of model ID strings, or [] on failure.
    """
    try:
        import anthropic
    except ImportError:
        return []

    try:
        resolved_api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        resolved_auth_token = (
            auth_token or os.environ.get("ANTHROPIC_AUTH_TOKEN") or _read_claude_cli_oauth_token()
        )

        if not resolved_api_key and not resolved_auth_token:
            return []

        client: anthropic.Anthropic
        if resolved_api_key:
            client = anthropic.Anthropic(api_key=resolved_api_key)
        else:
            client = anthropic.Anthropic(
                auth_token=resolved_auth_token,
                default_headers={"anthropic-beta": "oauth-2025-04-20"},
            )

        page = client.models.list()
        return [model.id for model in page.data]

    except Exception:
        return []


# ---------------------------------------------------------------------------
# Optional SDK availability guard
# ---------------------------------------------------------------------------

try:
    import anthropic  # noqa: F401  # pyright: ignore[reportUnusedImport]

    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False  # pyright: ignore[reportConstantRedefinition]


# ---------------------------------------------------------------------------
# Tool schema definitions
# ---------------------------------------------------------------------------

#: Orchestrator callback tools for builder phase (no grade tool).
_BUILDER_TOOLS: list[dict[str, Any]] = [
    {
        "name": "update_checklist",
        "description": (
            "Mark a requirement as done, blocked, or not_applicable. "
            "Call this after completing each requirement."
        ),
        "input_schema": {
            "type": "object",
            "required": ["req_id", "status"],
            "properties": {
                "req_id": {
                    "type": "string",
                    "description": "Requirement ID (e.g. 'R-01', 'R-02')",
                },
                "status": {
                    "type": "string",
                    "enum": ["done", "blocked", "not_applicable"],
                    "description": "New status for the requirement",
                },
                "note": {
                    "type": "string",
                    "description": "Optional explanation for the status change",
                },
            },
        },
    },
    {
        "name": "submit",
        "description": (
            "Submit your completed work for verification. "
            "Call this after addressing all requirements."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "request_clarification",
        "description": "Request clarification on ambiguous requirements.",
        "input_schema": {
            "type": "object",
            "required": ["question"],
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The clarification question to ask",
                },
            },
        },
    },
]

#: Orchestrator callback tools for verifier phase (includes grade tool).
_VERIFIER_TOOLS: list[dict[str, Any]] = [
    {
        "name": "grade",
        "description": (
            "Set a grade on a requirement after reviewing the builder's work. "
            "Grade every requirement before calling submit."
        ),
        "input_schema": {
            "type": "object",
            "required": ["req_id", "grade"],
            "properties": {
                "req_id": {
                    "type": "string",
                    "description": "Requirement ID (e.g. 'R-01', 'R-02')",
                },
                "grade": {
                    "type": "string",
                    "enum": ["A", "B", "C", "D", "F"],
                    "description": "Grade: A (excellent), B (good), C (adequate), D (poor), F (failing)",
                },
                "grade_reason": {
                    "type": "string",
                    "description": "Optional explanation for the grade",
                },
            },
        },
    },
    {
        "name": "update_checklist",
        "description": "Mark a requirement as done, blocked, or not_applicable.",
        "input_schema": {
            "type": "object",
            "required": ["req_id", "status"],
            "properties": {
                "req_id": {
                    "type": "string",
                    "description": "Requirement ID (e.g. 'R-01', 'R-02')",
                },
                "status": {
                    "type": "string",
                    "enum": ["done", "blocked", "not_applicable"],
                },
                "note": {"type": "string"},
            },
        },
    },
    {
        "name": "submit",
        "description": ("Complete the verification after grading all requirements."),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "request_clarification",
        "description": "Request clarification on ambiguous requirements or grading criteria.",
        "input_schema": {
            "type": "object",
            "required": ["question"],
            "properties": {
                "question": {"type": "string"},
            },
        },
    },
]


# ---------------------------------------------------------------------------
# MCP Connector beta API wiring
# ---------------------------------------------------------------------------


def _build_mcp_params(
    mcp_servers: list[Any] | None,
) -> dict[str, Any]:
    """Convert MCPServerConfig list to MCP Connector beta parameters.

    Only HTTPS URL-based servers are supported. STDIO servers are skipped with a warning.
    Returns empty dict if no servers or all filtered out.

    Args:
        mcp_servers: List of MCPServerConfig objects (or None).

    Returns:
        Dict with "mcp_servers" key if any valid servers exist, otherwise empty dict.
    """
    if not mcp_servers:
        return {}

    api_servers: list[dict[str, Any]] = []
    for mcp in mcp_servers:
        if mcp.command:
            logger.warning(
                "MCP server '%s' uses STDIO transport (command='%s') — "
                "not supported by Claude MCP Connector beta, skipping. "
                "To use this server, either run it as an SSE proxy "
                "(e.g. `npx @anthropic/mcp-proxy`) and use url: instead, "
                "or switch to CLI/OpenHands agent which supports stdio MCP.",
                mcp.name,
                mcp.command,
            )
            continue

        server_config: dict[str, Any] = {
            "type": "url",
            "url": mcp.url,
            "name": mcp.name,
        }
        if mcp.auth_token_env:
            token = os.environ.get(mcp.auth_token_env)
            if token:
                server_config["authorization_token"] = token
            else:
                logger.warning(
                    "Auth token env var '%s' for MCP server '%s' not set",
                    mcp.auth_token_env,
                    mcp.name,
                )
        api_servers.append(server_config)

    if not api_servers:
        return {}

    return {"mcp_servers": api_servers}


# ---------------------------------------------------------------------------
# Tool list construction
# ---------------------------------------------------------------------------


def _build_tool_list(
    is_verifier: bool,
    available_tools: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build tool list: phase tools + additive step tools.

    Step-level available_tools adds to (never restricts) phase tools.
    Unknown tool names are logged as warnings and skipped.

    Args:
        is_verifier: If True, include verifier tools; otherwise include builder tools.
        available_tools: Optional list of additional tool names to add (additive).

    Returns:
        List of tool schema dicts, starting with phase tools plus any known additional tools.
    """
    base_tools = copy.deepcopy(_VERIFIER_TOOLS if is_verifier else _BUILDER_TOOLS)

    if not available_tools:
        return base_tools

    # Collect names already in base tools
    existing_names = {t["name"] for t in base_tools}

    # Known additional tools that can be added via available_tools
    # (This registry can be expanded as new tools are supported)
    known_additional_tools: dict[str, dict[str, Any]] = {}

    for tool_name in available_tools:
        if tool_name in existing_names:
            continue  # Already in phase tools
        if tool_name in known_additional_tools:
            base_tools.append(known_additional_tools[tool_name])
        else:
            logger.warning(
                "Unknown tool '%s' in available_tools — skipping (not in Claude SDK tool registry)",
                tool_name,
            )

    return base_tools


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def build_claude_sdk_prompt(context: ExecutionContext, is_verifier: bool = False) -> str:
    """Build the full prompt for a Claude SDK session.

    Args:
        context: Execution context with prompt, requirements, and optional
            callback metadata.
        is_verifier: If True, produces verifier-phase instructions; otherwise
            builds builder-phase instructions.

    Returns:
        The fully assembled prompt string.
    """
    requirements_text = "\n".join(f"- {req}" for req in context.requirements)

    if is_verifier:
        phase_section = (
            "## Your Role: Verifier\n"
            "You are reviewing code changes made by a builder agent.\n\n"
            "### Required Workflow\n"
            "1. Examine the code changes in the working directory.\n"
            "2. Grade EVERY requirement using the **grade** tool.\n"
            "   - Grades: A (excellent), B (good), C (adequate), D (poor), F (failing)\n"
            "3. After grading ALL requirements, call **submit** to complete verification.\n\n"
            "### Available Tools\n"
            "- **grade**(req_id, grade, grade_reason?) — Grade a requirement\n"
            "- **update_checklist**(req_id, status, note?) — Mark a requirement's status\n"
            "- **submit**() — Complete verification after grading all requirements\n"
            "- **request_clarification**(question) — Ask for clarification if needed\n"
        )
    else:
        phase_section = (
            "## Orchestrator Integration\n"
            "You are connected to an orchestrator that tracks your progress.\n\n"
            "### Required Workflow\n"
            "1. Read the requirements carefully.\n"
            "2. Implement each requirement.\n"
            "3. After completing each requirement, call **update_checklist** to mark it 'done'.\n"
            "4. Once ALL requirements are addressed, call **submit** to submit your work.\n"
            "5. All CRITICAL requirements must be 'done' before submission succeeds.\n\n"
            "### Available Tools\n"
            "- **update_checklist**(req_id, status, note?) — Mark a requirement as done/blocked/not_applicable\n"
            "- **submit**() — Submit your work for verification\n"
            "- **request_clarification**(question) — Ask for clarification on ambiguous requirements\n\n"
            "## Git Workflow\n"
            "Before submitting, commit your changes to git:\n"
            "- Stage changes: `git add <files>`\n"
            "- Commit with a descriptive message: `git commit -m 'Description of changes'`\n"
            "- Always use `git --no-pager` for git commands.\n\n"
            "## Tool Usage Patterns\n"
            "- Call **update_checklist** immediately after completing each requirement — don't batch updates.\n"
            "- Mark each item 'done' as you finish it, before moving to the next requirement.\n"
            "- Call **submit** only after ALL requirements are marked done or not_applicable.\n"
            "- Use **request_clarification** for ambiguous requirements before starting implementation.\n\n"
            "## Sub-Agent Guidance\n"
            "- You may spawn sub-agents (via the Task tool) for complex or parallelizable subtasks.\n"
            "- Each sub-agent gets a fresh context — provide complete, self-contained task descriptions.\n"
            "- Collect and integrate sub-agent results before marking requirements done.\n"
        )

    return f"{context.prompt}\n\n## Requirements\n{requirements_text}\n\n{phase_section}"


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


async def _dispatch_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    on_checklist_update: ChecklistUpdateCallback,
    on_submit: SubmitCallback,
    on_grade: GradeCallback | None,
) -> str:
    """Dispatch a tool call to the appropriate orchestrator callback.

    Args:
        tool_name: Name of the tool Claude invoked.
        tool_input: Tool arguments dict.
        on_checklist_update: Bound checklist-update callback.
        on_submit: Bound submit callback.
        on_grade: Bound grade callback (None in builder phase).

    Returns:
        A plain text result string to return to Claude as the tool result.
    """
    if tool_name == "update_checklist":
        req_id = str(tool_input.get("req_id", "")).strip()
        if not req_id:
            return "Error: 'req_id' is required and cannot be empty."
        raw_status = str(tool_input.get("status", "done"))
        note: str | None = tool_input.get("note")
        status = ChecklistStatus(raw_status)
        await on_checklist_update(req_id, status, note)
        return f"Requirement {req_id} marked as {raw_status}."

    elif tool_name == "submit":
        await on_submit()
        return "Work submitted for verification."

    elif tool_name == "grade":
        if on_grade is not None:
            req_id = str(tool_input.get("req_id", "")).strip()
            grade = str(tool_input.get("grade", "")).strip()
            if not req_id:
                return "Error: 'req_id' is required and cannot be empty."
            if not grade:
                return "Error: 'grade' is required and cannot be empty."
            grade_reason: str | None = tool_input.get("grade_reason")
            await on_grade(req_id, grade, grade_reason)
            return f"Grade {grade} set for requirement {req_id}."
        else:
            logger.warning("ClaudeSDKAgent: 'grade' tool called in builder phase — ignoring")
            return "Grade tool is only available in verifier phase."

    elif tool_name == "request_clarification":
        question = str(tool_input.get("question", ""))
        logger.info("ClaudeSDKAgent: request_clarification — question=%r", question)
        return f"Clarification requested: {question}"

    else:
        logger.warning("ClaudeSDKAgent: unknown tool '%s' — ignoring", tool_name)
        return f"Unknown tool: {tool_name}"


# ---------------------------------------------------------------------------
# Claude SDK Agent
# ---------------------------------------------------------------------------


class ClaudeSDKAgent:
    """Agent that executes via the Anthropic Claude SDK's Messages API.

    Runs entirely in-process — no subprocess is spawned.  Uses the tool use
    feature to expose orchestrator callback tools (update_checklist, grade,
    submit, request_clarification) as Claude tool calls.

    Requires:
    - anthropic package installed (``pip install anthropic``)
    - Authentication via one of (in priority order):
        1. ``api_key`` argument or ``ANTHROPIC_API_KEY`` env var
        2. ``auth_token`` argument or ``ANTHROPIC_AUTH_TOKEN`` env var
        3. Claude CLI OAuth token from the macOS keychain (``claude auth login``)
           — same credential used by the sidebar quota display

    The OAuth path uses ``anthropic-beta: oauth-2025-04-20`` so the standard
    Anthropic API accepts the Claude Max subscription token.

    Configuration:
        model: Claude model to use (default: claude-sonnet-4-5).
        api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
        auth_token: Bearer token. Falls back to ANTHROPIC_AUTH_TOKEN env var,
            then the Claude CLI OAuth token from the macOS keychain.
        max_tokens: Maximum tokens per response turn (default: 4096).
        max_iterations: Maximum agentic loop iterations (default: 50).

    Test injection:
        _client: Inject a fake Anthropic client for unit testing.
        _environ: Inject a controlled environment dict for credential resolution.
            When provided, real os.environ and keychain lookups are skipped.
    """

    #: Matches AgentOption.name produced by ToolDetector._detect_claude_sdk().
    name = "Claude SDK"

    def __init__(
        self,
        model: str = "claude-sonnet-4-5",
        api_key: str | None = None,
        auth_token: str | None = None,
        max_tokens: int = 4096,
        max_iterations: int = 50,
        *,
        _client: Any | None = None,
        _environ: dict[str, str] | None = None,
    ) -> None:
        self._model = model
        # When _environ is provided (test injection), use it exclusively — skip
        # real os.environ and the macOS keychain so tests stay deterministic.
        test_mode = _environ is not None
        env = _environ if test_mode else os.environ

        self._api_key: str | None = api_key or env.get("ANTHROPIC_API_KEY")
        self._auth_token: str | None = (
            auth_token
            or env.get("ANTHROPIC_AUTH_TOKEN")
            # Keychain fallback: only in production mode (not in tests).
            or (None if test_mode else _read_claude_cli_oauth_token())
        )
        self._max_tokens = max_tokens
        self._max_iterations = max_iterations
        self._cancelled = False
        self._client = _client  # injected test client; None → create real client

    @property
    def info(self) -> AgentRunnerInfo:
        """Return static metadata for this agent instance."""
        return AgentRunnerInfo(
            agent_type=AgentRunnerType.CLAUDE_SDK,
            name="Claude SDK",
            version=None,
        )

    def get_quota(self, fetcher: Any | None = None) -> AgentQuota | None:
        """Quota support is not currently implemented for the Claude SDK agent.

        Returns None — the Claude SDK agent does not report quota information.
        """
        return None

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        """Execute a task via the Anthropic Claude SDK.

        Runs an agentic loop using the Messages API with tool use.  Claude
        receives the full prompt and can invoke orchestrator callback tools
        (update_checklist, grade, submit, request_clarification).  The loop
        continues until Claude calls submit, reaches max_iterations, or
        returns an end_turn stop reason with no pending tool calls.

        Args:
            context: Execution context (run/task IDs, prompt, requirements).
            on_checklist_update: Callback for update_checklist tool calls.
            on_submit: Callback for submit tool calls.
            on_output: Optional callback for streaming output lines.
            on_grade: Optional callback for grade tool calls (verifier phase).
            on_agent_metadata: Optional callback for runtime metadata.

        Returns:
            ExecutionResult with success=True on normal completion.

        Raises:
            AgentNotAvailableError: If the anthropic SDK is not installed or
                no credentials are configured.
            AgentCancelledError: If cancel() was called before or during
                execution, or asyncio task is cancelled.
            AgentExecutionError: For API-level failures or session errors.
        """
        if not _SDK_AVAILABLE:
            raise AgentNotAvailableError(
                AgentRunnerType.CLAUDE_SDK.value,
                "anthropic package not installed. Install with: pip install anthropic",
            )

        if not self._api_key and not self._auth_token:
            raise AgentNotAvailableError(
                AgentRunnerType.CLAUDE_SDK.value,
                "No Anthropic credentials found. Either set ANTHROPIC_API_KEY, "
                "set ANTHROPIC_AUTH_TOKEN, or log in with the Claude CLI "
                "(`claude auth login`) so the keychain token can be used.",
            )

        if self._cancelled:
            raise AgentCancelledError(AgentRunnerType.CLAUDE_SDK.value)

        start_ms = int(time.monotonic() * 1000)
        is_verifier = on_grade is not None

        try:
            import anthropic

            # Use injected test client or create a real one.
            client: Any
            if self._client is not None:
                client = self._client
            elif self._api_key:
                client = anthropic.Anthropic(api_key=self._api_key)
            else:
                # OAuth path: same credential used by the sidebar quota display.
                # Requires the oauth-2025-04-20 beta header for the API to accept
                # the sk-ant-oat01-... token from the Claude CLI keychain.
                client = anthropic.Anthropic(
                    auth_token=self._auth_token,
                    default_headers={"anthropic-beta": "oauth-2025-04-20"},
                )

            tools = _build_tool_list(is_verifier, context.available_tools)
            mcp_params = _build_mcp_params(context.mcp_servers)
            full_prompt = build_claude_sdk_prompt(context, is_verifier=is_verifier)

            messages: list[dict[str, Any]] = [{"role": "user", "content": full_prompt}]
            output_lines: list[str] = []
            tokens_read = 0
            tokens_write = 0
            num_actions = 0
            submitted = False

            for _iteration in range(self._max_iterations):
                if self._cancelled:
                    raise AgentCancelledError(AgentRunnerType.CLAUDE_SDK.value)

                # Call the API in a thread to avoid blocking the event loop.
                if mcp_params:
                    # Use beta API with MCP Connector when servers are configured
                    response = await asyncio.to_thread(
                        client.beta.messages.create,
                        model=self._model,
                        max_tokens=self._max_tokens,
                        tools=tools,
                        messages=messages,
                        betas=["mcp-client-2025-11-20"],
                        **mcp_params,
                    )
                else:
                    # Use standard API when no MCP servers
                    response = await asyncio.to_thread(
                        client.messages.create,
                        model=self._model,
                        max_tokens=self._max_tokens,
                        tools=tools,
                        messages=messages,
                    )

                # Accumulate token usage.
                if hasattr(response, "usage") and response.usage is not None:
                    tokens_read += getattr(response.usage, "input_tokens", 0)
                    tokens_write += getattr(response.usage, "output_tokens", 0)

                # Collect text content from the response.
                assistant_content: list[Any] = list(response.content)
                for block in assistant_content:
                    if hasattr(block, "type") and block.type == "text":
                        text = str(block.text)
                        if text:
                            output_lines.append(text)
                            if on_output is not None:
                                await on_output([text])

                # Append the assistant turn to the conversation.
                messages.append({"role": "assistant", "content": assistant_content})

                stop_reason = str(getattr(response, "stop_reason", ""))

                if stop_reason == "end_turn":
                    # Claude finished naturally — auto-submit if not already done.
                    if not submitted:
                        await on_submit()
                    break

                if stop_reason == "tool_use":
                    # Process all tool calls in this turn.
                    tool_results: list[dict[str, Any]] = []
                    for block in assistant_content:
                        if not (hasattr(block, "type") and block.type == "tool_use"):
                            continue

                        num_actions += 1
                        tool_name = str(block.name)
                        tool_input: dict[str, Any] = (
                            dict(block.input) if hasattr(block, "input") else {}
                        )
                        tool_use_id = str(block.id)

                        result_text = await _dispatch_tool(
                            tool_name,
                            tool_input,
                            on_checklist_update,
                            on_submit,
                            on_grade,
                        )

                        if tool_name == "submit":
                            submitted = True

                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": result_text,
                            }
                        )

                    messages.append({"role": "user", "content": tool_results})

                    if submitted:
                        # Submit was called — exit the loop.
                        break
                else:
                    # Unexpected stop reason — treat as natural completion.
                    logger.warning(
                        "ClaudeSDKAgent: unexpected stop_reason=%r — treating as end_turn",
                        stop_reason,
                    )
                    if not submitted:
                        await on_submit()
                    break

            else:
                # Loop exhausted without submit — submit anyway.
                logger.warning(
                    "ClaudeSDKAgent: max_iterations=%d reached without submit — auto-submitting",
                    self._max_iterations,
                )
                if not submitted:
                    await on_submit()

        except AgentCancelledError:
            raise
        except AgentNotAvailableError:
            raise
        except GateBlockedError:
            raise
        except asyncio.CancelledError:
            raise AgentCancelledError(AgentRunnerType.CLAUDE_SDK.value)
        except Exception as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            logger.debug(
                "ClaudeSDKAgent: session error after %dms — %s",
                duration_ms,
                exc,
                exc_info=True,
            )
            # Sanitize exception message to avoid leaking secrets
            exc_msg = str(exc)
            for secret in (self._api_key, self._auth_token):
                if secret and secret in exc_msg:
                    exc_msg = exc_msg.replace(secret, "***")
            raise AgentExecutionError(
                AgentRunnerType.CLAUDE_SDK.value,
                f"Claude SDK session failed after {duration_ms}ms: {exc_msg}",
            ) from exc

        duration_ms = int(time.monotonic() * 1000) - start_ms
        return ExecutionResult(
            success=True,
            metrics=ExecutionMetrics(
                tokens_read=tokens_read,
                tokens_write=tokens_write,
                duration_ms=duration_ms,
                num_actions=num_actions,
            ),
            output_lines=output_lines,
        )

    async def cancel(self) -> None:
        """Request cancellation of the active Claude SDK session.

        Sets the cancellation flag.  The agentic loop checks this flag
        between API calls and raises AgentCancelledError when detected.
        Safe to call multiple times.
        """
        self._cancelled = True
        logger.info("ClaudeSDKAgent: cancelled")


# Alias for backwards-compatible import (camelCase variant)
ClaudeSdkAgent = ClaudeSDKAgent
