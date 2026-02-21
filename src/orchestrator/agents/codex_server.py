"""Codex Server agent — local managed-process variant.

Implements ``CodexServerAgent`` which manages a local ``codex app-server``
process and communicates via the Codex app server HTTP API (JSON over HTTP).

This module provides a protocol-compliant skeleton that satisfies the full
agent interface surface (``info``, ``execute``, ``cancel``).  Shared helpers
for prompt assembly, tool-allow-list enforcement, and output normalization are
factored into ``codex_server_common`` to minimise duplication with the remote
variant (``codex_server_remote``).

Integration contract reference: docs/codex-server/context/contract-matrix.md
  - §1: Local variant uses loopback/stdio transport; no bearer auth required.
  - §4: Tool allow-list strictly enforced — only allow-listed tools are
        passed to the Codex session.
  - §3: Both REST and MCP callback channels are supported.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from orchestrator.agents.codex_server_common import (
    CODEX_SERVER_TOOL_ALLOWLIST,
    build_codex_server_prompt,
    enforce_tool_allowlist,
    normalize_codex_metrics,
    normalize_codex_output_lines,
)
from orchestrator.agents.errors import (
    AgentCancelledError,
    AgentExecutionError,
    AgentNotAvailableError,
)
from orchestrator.agents.types import (
    AgentInfo,
    AgentMetadataCallback,
    ChecklistUpdateCallback,
    ExecutionContext,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
    SubmitCallback,
)
from orchestrator.config.enums import AgentType, ChecklistStatus

logger = logging.getLogger(__name__)


class CodexServerAgent:
    """Agent that manages a local Codex app server process.

    Spawns ``codex app-server`` as a local process and communicates using
    the Codex app server HTTP API.  Callback tool invocations are restricted
    to the v1 allow-list: ``update_checklist``, ``grade``, ``submit``, and
    ``request_clarification``.  Any out-of-allow-list tool call is rejected
    and logged as a warning.

    Per the integration contract (contract-matrix.md):
    - Local variant uses loopback transport; no bearer auth required.
    - Tool allow-list is strictly enforced at the adapter layer.
    - Both REST and MCP callback channels are supported.

    Configuration:
        endpoint: Local Codex server endpoint URL.  Defaults to the
            conventional loopback URL ``http://localhost:9000``.
        model: Model name forwarded to the Codex server session.
        callback_channel: ``"rest"`` or ``"mcp"`` — determines how the
            prompt instructs the Codex agent to call back.
        api_key: Optional bearer token; present for interface parity with
            the remote variant but unused for local loopback sessions.
    """

    #: v1 tool allow-list surfaced as a class attribute for inspection/testing.
    TOOL_ALLOWLIST: frozenset[str] = CODEX_SERVER_TOOL_ALLOWLIST

    def __init__(
        self,
        endpoint: str = "http://localhost:9000",
        model: str | None = None,
        callback_channel: str = "rest",
        api_key: str | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._model = model
        self._callback_channel = callback_channel
        self._api_key = api_key  # Unused for local; kept for interface parity.
        self._cancelled = False
        self._session_task: asyncio.Task[Any] | None = None

    # ------------------------------------------------------------------
    # Agent protocol
    # ------------------------------------------------------------------

    @property
    def info(self) -> AgentInfo:
        """Return static metadata for this agent instance."""
        return AgentInfo(
            agent_type=AgentType.CODEX_SERVER,
            name="Codex Server",
            version=None,
        )

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
    ) -> ExecutionResult:
        """Execute a task via a local Codex app server session.

        Assembles the phase-aware prompt using ``build_codex_server_prompt``,
        then delegates to the Codex server session lifecycle.  Callback tool
        invocations received from the Codex server are routed to the
        appropriate orchestrator callbacks after allow-list enforcement.

        Args:
            context: Execution context (run/task IDs, prompt, requirements,
                callback metadata).
            on_checklist_update: Callback invoked when the Codex session calls
                ``update_checklist``.
            on_submit: Callback invoked when the Codex session calls
                ``submit``.
            on_output: Optional callback for streaming output lines.
            on_grade: Optional callback invoked when the Codex session calls
                ``grade`` (verifier phase only).
            on_agent_metadata: Optional callback for runtime metadata (e.g.
                server process PID).

        Returns:
            ``ExecutionResult`` describing success, metrics, and output lines.

        Raises:
            AgentNotAvailableError: If the local Codex server cannot be
                started or contacted.
            AgentCancelledError: If ``cancel()`` was called before or during
                execution.
            AgentExecutionError: For any other session-level failure.
        """
        if self._cancelled:
            raise AgentCancelledError(AgentType.CODEX_SERVER.value)

        start_ms = int(time.monotonic() * 1000)
        is_verifier = on_grade is not None

        try:
            logger.debug(
                "CodexServerAgent: starting session — run=%s task=%s phase=%s endpoint=%s",
                context.run_id,
                context.task_id,
                "verifier" if is_verifier else "builder",
                self._endpoint,
            )
            # Build the phase-aware prompt (used by the session layer below).
            _full_prompt = build_codex_server_prompt(context, is_verifier=is_verifier)

            # --- Session lifecycle placeholder ---
            # A complete implementation would:
            #   1. Ensure the local `codex app-server` process is running
            #      (spawn if needed; track PID via on_agent_metadata).
            #   2. POST /sessions to open a new session with full_prompt and
            #      model; record session_id.
            #   3. Stream or poll session events.
            #   4. For each callback-tool event:
            #      a. Call enforce_tool_allowlist(tool_name) — reject if not
            #         in TOOL_ALLOWLIST.
            #      b. Route to on_checklist_update / on_submit / on_grade /
            #         request-clarification handler as appropriate.
            #   5. Collect all output text into output_lines.
            #   6. Return when the session reaches a terminal state or
            #      self._cancelled is set.
            #
            # Until the HTTP transport layer is implemented, raise
            # AgentNotAvailableError so callers receive a clear, actionable
            # error rather than a silent no-op.
            raise AgentNotAvailableError(
                AgentType.CODEX_SERVER.value,
                "Codex server HTTP transport not yet implemented. "
                "The agent protocol surface (info/execute/cancel) is complete; "
                "the session I/O layer will be added in a subsequent step.",
            )

        except (AgentCancelledError, AgentNotAvailableError):
            raise
        except asyncio.CancelledError:
            # asyncio task cancellation is mapped to AgentCancelledError so
            # callers receive a typed, actionable error rather than a raw
            # CancelledError propagating out of the agent boundary.
            logger.debug(
                "CodexServerAgent: asyncio task cancelled — treating as AgentCancelledError"
            )
            raise AgentCancelledError(AgentType.CODEX_SERVER.value)
        except Exception as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            # Log full exception details at debug level only — the error
            # message surfaced to the orchestrator must NOT include the raw
            # exception string because it may contain secrets (API keys,
            # endpoint URLs with credentials, etc.).
            logger.debug(
                "CodexServerAgent: session error after %dms — %s",
                duration_ms,
                exc,
                exc_info=True,
            )
            raise AgentExecutionError(
                AgentType.CODEX_SERVER.value,
                f"Session failed after {duration_ms}ms",
            ) from exc

    async def cancel(self) -> None:
        """Request cancellation of the active Codex server session.

        Sets the cancellation flag and cancels the session asyncio task if
        one is running.  Safe to call multiple times — subsequent calls are
        no-ops once the flag is set and the task is already cancelled or done.

        The ``execute`` coroutine checks ``self._cancelled`` at startup and
        after each blocking operation so that cancellation takes effect at
        the next yield point even if the asyncio task cancel is not delivered
        immediately.
        """
        self._cancelled = True
        if self._session_task is not None and not self._session_task.done():
            self._session_task.cancel()
            logger.info("CodexServerAgent: cancelled active session task")

    # ------------------------------------------------------------------
    # Internal helpers (public for testing)
    # ------------------------------------------------------------------

    def _build_prompt(self, context: ExecutionContext, is_verifier: bool) -> str:
        """Return the fully assembled prompt for the Codex server session."""
        return build_codex_server_prompt(context, is_verifier=is_verifier)

    def _normalize_output(self, raw_output: list[Any]) -> list[str]:
        """Normalize raw Codex session output to a list of text lines."""
        return normalize_codex_output_lines(raw_output)

    def _build_metrics(
        self,
        duration_ms: int,
        tokens_read: int = 0,
        tokens_write: int = 0,
        tokens_cache: int = 0,
        num_actions: int = 0,
    ) -> object:
        """Build normalized ``ExecutionMetrics`` from raw session counters."""
        return normalize_codex_metrics(
            duration_ms=duration_ms,
            tokens_read=tokens_read,
            tokens_write=tokens_write,
            tokens_cache=tokens_cache,
            num_actions=num_actions,
        )

    async def _route_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_grade: GradeCallback | None = None,
    ) -> None:
        """Route an allow-listed callback tool call to the appropriate callback.

        Enforces the v1 allow-list (``TOOL_ALLOWLIST``) before dispatching.
        Disallowed tool names raise ``ValueError`` (via ``enforce_tool_allowlist``).

        Tool routing:
        - ``update_checklist`` → ``on_checklist_update(req_id, status, note)``
        - ``submit``           → ``on_submit()``
        - ``grade``            → ``on_grade(req_id, grade, grade_reason)`` (verifier only)
        - ``request_clarification`` → logged; no callback in v1

        Args:
            tool_name: Name of the callback tool the Codex session invoked.
            args: Tool argument dict from the Codex server event payload.
            on_checklist_update: Bound checklist-update callback.
            on_submit: Bound submit callback.
            on_grade: Bound grade callback (``None`` in builder phase).

        Raises:
            ValueError: If ``tool_name`` is not on the v1 allow-list.
        """
        # Raises ValueError for disallowed tools — logged by enforce_tool_allowlist.
        enforce_tool_allowlist(tool_name)

        if tool_name == "update_checklist":
            req_id: str = str(args.get("req_id", ""))
            raw_status: str = str(args.get("status", "done"))
            note: str | None = args.get("note")
            status = ChecklistStatus(raw_status)
            await on_checklist_update(req_id, status, note)

        elif tool_name == "submit":
            await on_submit()

        elif tool_name == "grade":
            if on_grade is not None:
                req_id = str(args.get("req_id", ""))
                grade: str = str(args.get("grade", ""))
                grade_reason: str | None = args.get("grade_reason")
                await on_grade(req_id, grade, grade_reason)
            else:
                logger.warning("CodexServerAgent: 'grade' tool called in builder phase — ignoring")

        elif tool_name == "request_clarification":
            question: str = str(args.get("question", ""))
            logger.info("CodexServerAgent: request_clarification received — question=%r", question)
