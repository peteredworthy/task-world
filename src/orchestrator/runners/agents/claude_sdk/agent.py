"""Claude Agent SDK runner — uses the ``claude-agent-sdk`` package.

Uses the ``claude_agent_sdk`` Python package to run tasks via the Claude Agent
SDK.  Orchestrator callback tools (update_checklist, grade, submit,
request_clarification) are exposed as an in-process MCP server that the SDK
connects to automatically.

The SDK import is deferred to a module-level ``try/except`` so that the rest
of the orchestrator works even when ``claude-agent-sdk`` is not installed.

Test injection:
    _query_fn: Inject a fake query function to replace the real SDK query().
        When set, no real API calls are made.  Leading underscore signals
        test-only use.
    _environ: Inject a controlled environment dict for credential resolution in
        tests.  When provided, real os.environ and keychain lookups are skipped.
"""

from __future__ import annotations

import asyncio
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
    import claude_agent_sdk  # noqa: F401  # pyright: ignore[reportUnusedImport]

    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False  # pyright: ignore[reportConstantRedefinition]


# ---------------------------------------------------------------------------
# Orchestrator MCP server builder
# ---------------------------------------------------------------------------


def _build_orchestrator_mcp_server(
    on_checklist_update: ChecklistUpdateCallback,
    on_submit: SubmitCallback,
    on_grade: GradeCallback | None,
) -> Any:
    """Build an in-process MCP server with orchestrator callback tools."""
    from claude_agent_sdk import tool, create_sdk_mcp_server

    @tool(
        "update_checklist",
        "Mark a requirement as done, blocked, or not_applicable.",
        {"req_id": str, "status": str, "note": str},
    )
    async def update_checklist(args: dict[str, Any]) -> dict[str, Any]:
        req_id = str(args.get("req_id", "")).strip()
        if not req_id:
            return {"content": [{"type": "text", "text": "Error: 'req_id' is required."}]}
        raw_status = str(args.get("status", "done"))
        note = args.get("note")
        status = ChecklistStatus(raw_status)
        await on_checklist_update(req_id, status, note)
        return {
            "content": [{"type": "text", "text": f"Requirement {req_id} marked as {raw_status}."}]
        }

    @tool("submit", "Submit your completed work for verification.", {})
    async def submit(args: dict[str, Any]) -> dict[str, Any]:
        await on_submit()
        return {"content": [{"type": "text", "text": "Work submitted for verification."}]}

    @tool(
        "request_clarification",
        "Request clarification on ambiguous requirements.",
        {"question": str},
    )
    async def request_clarification(args: dict[str, Any]) -> dict[str, Any]:
        question = str(args.get("question", ""))
        logger.info("ClaudeSDKAgent: request_clarification — question=%r", question)
        return {"content": [{"type": "text", "text": f"Clarification requested: {question}"}]}

    tools_list = [update_checklist, submit, request_clarification]

    if on_grade is not None:

        @tool(
            "grade",
            "Set a grade on a requirement after reviewing the builder's work.",
            {"req_id": str, "grade": str, "grade_reason": str},
        )
        async def grade(args: dict[str, Any]) -> dict[str, Any]:
            req_id = str(args.get("req_id", "")).strip()
            grade_val = str(args.get("grade", "")).strip()
            if not req_id:
                return {"content": [{"type": "text", "text": "Error: 'req_id' is required."}]}
            if not grade_val:
                return {"content": [{"type": "text", "text": "Error: 'grade' is required."}]}
            grade_reason = args.get("grade_reason")
            await on_grade(req_id, grade_val, grade_reason)
            return {
                "content": [
                    {"type": "text", "text": f"Grade {grade_val} set for requirement {req_id}."}
                ]
            }

        tools_list.append(grade)

    return create_sdk_mcp_server("orchestrator", tools=tools_list)


# ---------------------------------------------------------------------------
# MCP servers dict builder
# ---------------------------------------------------------------------------


def _build_mcp_servers(
    orchestrator_server: Any,
    mcp_servers: list[Any] | None,
) -> dict[str, Any]:
    """Build MCP servers dict for ClaudeAgentOptions."""
    servers: dict[str, Any] = {"orchestrator": orchestrator_server}

    if not mcp_servers:
        return servers

    for mcp in mcp_servers:
        if mcp.command:
            # stdio transport
            server_config: dict[str, Any] = {"command": mcp.command}
            if mcp.args:
                server_config["args"] = mcp.args
            env: dict[str, str] = {}
            if mcp.auth_token_env:
                token = os.environ.get(mcp.auth_token_env)
                if token:
                    env[mcp.auth_token_env] = token
            if env:
                server_config["env"] = env
            servers[mcp.name] = server_config
        elif mcp.url:
            # URL-based (SSE/HTTP)
            server_config = {"type": "sse", "url": mcp.url}
            headers: dict[str, str] = {}
            if mcp.auth_token_env:
                token = os.environ.get(mcp.auth_token_env)
                if token:
                    headers["Authorization"] = f"Bearer {token}"
            if headers:
                server_config["headers"] = headers
            servers[mcp.name] = server_config
        else:
            logger.warning("MCP server '%s' has no command or url — skipping", mcp.name)

    return servers


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
# Claude SDK Agent
# ---------------------------------------------------------------------------


class ClaudeSDKAgent:
    """Agent that executes via the Claude Agent SDK.

    Uses the ``claude-agent-sdk`` package to run an agentic session.
    Orchestrator callback tools are exposed as an in-process MCP server.

    Requires:
    - claude-agent-sdk package installed (``pip install claude-agent-sdk``)
    - Authentication via one of (in priority order):
        1. ``api_key`` argument or ``ANTHROPIC_API_KEY`` env var
        2. ``auth_token`` argument or ``ANTHROPIC_AUTH_TOKEN`` env var
        3. Claude CLI OAuth token from the macOS keychain (``claude auth login``)
           — same credential used by the sidebar quota display

    Configuration:
        model: Claude model to use (default: claude-sonnet-4-5).
        api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
        auth_token: Bearer token. Falls back to ANTHROPIC_AUTH_TOKEN env var,
            then the Claude CLI OAuth token from the macOS keychain.
        max_turns: Maximum agentic turns (default: 50).

    Test injection:
        _query_fn: Inject a fake query function for unit testing.
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
        max_turns: int = 50,
        *,
        _query_fn: Any | None = None,
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
        self._max_turns = max_turns
        self._cancelled = False
        self._query_fn = _query_fn  # injected test query fn; None → use real SDK

    @property
    def info(self) -> AgentRunnerInfo:
        """Return static metadata for this agent instance."""
        return AgentRunnerInfo(
            agent_type=AgentRunnerType.CLAUDE_SDK,
            name="Claude SDK",
            version=None,
        )

    def get_quota(self, fetcher: Any | None = None) -> AgentQuota | None:
        """Quota is not supported for the Claude SDK agent.

        The Claude CLI agent handles quota display for the shared subscription.
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
        """Execute a task via the Claude Agent SDK.

        Runs an agentic session using the ``claude-agent-sdk`` package.
        Orchestrator callback tools are exposed as an in-process MCP server
        that the SDK connects to automatically.

        Args:
            context: Execution context (run/task IDs, prompt, requirements).
            on_checklist_update: Callback for update_checklist tool calls.
            on_submit: Callback for submit tool calls.
            on_output: Optional callback for streaming output lines.
            on_grade: Optional callback for grade tool calls (verifier phase).
            on_agent_metadata: Optional callback for runtime metadata.
            on_escalation: Optional callback for escalation events.

        Returns:
            ExecutionResult with success=True on normal completion.

        Raises:
            AgentNotAvailableError: If claude-agent-sdk is not installed or
                no credentials are configured.
            AgentCancelledError: If cancel() was called before or during
                execution, or asyncio task is cancelled.
            AgentExecutionError: For API-level failures or session errors.
        """
        if not _SDK_AVAILABLE:
            raise AgentNotAvailableError(
                AgentRunnerType.CLAUDE_SDK.value,
                "claude-agent-sdk package not installed. Install with: pip install claude-agent-sdk",
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
            from claude_agent_sdk import (
                query as sdk_query,
                ClaudeAgentOptions,
                AssistantMessage,
                ResultMessage,
            )
            from claude_agent_sdk.types import TextBlock, ToolUseBlock

            # Build orchestrator MCP server with callback tools
            orchestrator_server = _build_orchestrator_mcp_server(
                on_checklist_update, on_submit, on_grade
            )
            mcp_servers = _build_mcp_servers(orchestrator_server, context.mcp_servers)

            full_prompt = build_claude_sdk_prompt(context, is_verifier=is_verifier)

            # Build environment for SDK (pass credentials)
            sdk_env: dict[str, str] = {}
            if self._api_key:
                sdk_env["ANTHROPIC_API_KEY"] = self._api_key
            elif self._auth_token:
                sdk_env["ANTHROPIC_AUTH_TOKEN"] = self._auth_token

            options = ClaudeAgentOptions(
                model=self._model,
                max_turns=self._max_turns,
                permission_mode="bypassPermissions",
                cwd=context.working_dir,
                mcp_servers=mcp_servers,
                env=sdk_env,
            )

            query_fn = self._query_fn or sdk_query
            output_lines: list[str] = []
            tokens_read = 0
            tokens_write = 0
            num_actions = 0

            async for msg in query_fn(prompt=full_prompt, options=options):
                if self._cancelled:
                    raise AgentCancelledError(AgentRunnerType.CLAUDE_SDK.value)

                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            if block.text:
                                output_lines.append(block.text)
                                if on_output is not None:
                                    await on_output([block.text])
                        elif isinstance(block, ToolUseBlock):
                            num_actions += 1

                elif isinstance(msg, ResultMessage):
                    if msg.usage:
                        tokens_read = msg.usage.get("input_tokens", 0)
                        tokens_write = msg.usage.get("output_tokens", 0)
                    num_actions = max(num_actions, msg.num_turns)

                    if msg.is_error:
                        raise AgentExecutionError(
                            AgentRunnerType.CLAUDE_SDK.value,
                            f"Claude Agent SDK session failed: {msg.result or 'unknown error'}",
                        )

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
                f"Claude Agent SDK session failed after {duration_ms}ms: {exc_msg}",
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

        Sets the cancellation flag.  The streaming loop checks this flag
        between messages and raises AgentCancelledError when detected.
        Safe to call multiple times.
        """
        self._cancelled = True
        logger.info("ClaudeSDKAgent: cancelled")


# Alias for backwards-compatible import (camelCase variant)
ClaudeSdkAgent = ClaudeSDKAgent
