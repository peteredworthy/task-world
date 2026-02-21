"""Codex Server agent — remote bearer-authenticated variant.

Implements ``CodexServerRemoteAgent`` which connects to a pre-existing remote
``codex app-server`` instance over HTTPS using a bearer token for
authentication.  Shared helpers for prompt assembly, tool allow-list
enforcement, and output normalization are imported from
``codex_server_common`` — the same module used by the local variant
(``codex_server``).

## Token resolution (deterministic precedence)

Tokens are resolved in the following order at *construction* time:

1. ``api_key`` constructor argument — if non-empty, use it directly.
2. Environment variable named by ``token_env_var`` (default
   ``CODEX_SERVER_API_KEY``) — resolved via ``os.environ``.
3. ``OPENAI_API_KEY`` environment variable — fallback for operators that
   already export this key.

If none of the above yields a non-empty string, ``AgentConfigError`` is
raised immediately — no network I/O is performed.

## Integration contract

Integration contract reference: docs/codex-server/context/contract-matrix.md
  - §2: Remote variant uses bearer-authenticated HTTPS transport.
  - §4: Tool allow-list strictly enforced — only allow-listed tools are
        passed to the Codex session.
  - §3: Both REST and MCP callback channels are supported.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

from orchestrator.agents.codex_server_common import (
    CODEX_SERVER_TOOL_ALLOWLIST,
    build_codex_server_prompt,
    enforce_tool_allowlist,
    normalize_codex_metrics,
    normalize_codex_output_lines,
)
from orchestrator.agents.errors import (
    AgentCancelledError,
    AgentConfigError,
    AgentError,
    AgentExecutionError,
    AgentNotAvailableError,
    AgentTimeoutError,
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

#: Default environment variable name to look up when no ``api_key`` is supplied.
DEFAULT_TOKEN_ENV_VAR: str = "CODEX_SERVER_API_KEY"

#: Fallback environment variable used when neither ``api_key`` nor
#: ``token_env_var`` resolves a token.
FALLBACK_TOKEN_ENV_VAR: str = "OPENAI_API_KEY"


# ---------------------------------------------------------------------------
# Token resolution (pure function — testable without I/O)
# ---------------------------------------------------------------------------


def resolve_remote_token(
    api_key: str | None,
    token_env_var: str,
    environ: dict[str, str] | None = None,
) -> str | None:
    """Resolve the API token using the deterministic precedence chain.

    Precedence (first non-empty value wins):
    1. ``api_key`` — explicit constructor argument.
    2. ``environ[token_env_var]`` — named env var (default ``CODEX_SERVER_API_KEY``).
    3. ``environ["OPENAI_API_KEY"]`` — global fallback.

    Args:
        api_key: Explicit token supplied by the caller; ``None`` or empty
            string triggers fall-through to env-var lookup.
        token_env_var: Name of the primary environment variable to check when
            ``api_key`` is not provided.
        environ: Environment mapping to use for lookup.  Defaults to
            ``os.environ`` when ``None``.

    Returns:
        Resolved token string, or ``None`` if no source yielded a value.
    """
    env = environ if environ is not None else dict(os.environ)

    if api_key:
        return api_key

    primary = env.get(token_env_var)
    if primary:
        return primary

    fallback = env.get(FALLBACK_TOKEN_ENV_VAR)
    if fallback:
        return fallback

    return None


# ---------------------------------------------------------------------------
# Transport error mapping (pure function — testable without I/O)
# ---------------------------------------------------------------------------


def map_transport_error(
    exc: Exception,
    agent_type: str,
    duration_ms: int,
) -> AgentError:
    """Map transport-layer exceptions to typed orchestrator agent errors.

    Converts httpx exceptions and other transport failures to the appropriate
    orchestrator error type with redacted diagnostics.  Raw exception text,
    bearer tokens, and URLs with embedded credentials are never included in
    the returned error's message.

    Mapping:
    - ``httpx.TimeoutException``          → ``AgentTimeoutError``
    - ``httpx.ConnectError``              → ``AgentNotAvailableError`` (endpoint unreachable)
    - ``httpx.HTTPStatusError`` 401       → ``AgentExecutionError`` (token-safe message)
    - ``httpx.HTTPStatusError`` 403       → ``AgentExecutionError`` (token-safe message)
    - ``httpx.HTTPStatusError`` other     → ``AgentExecutionError`` (status code only)
    - Any other ``Exception``             → ``AgentExecutionError`` (generic, secret-safe)

    Args:
        exc: The exception to map.
        agent_type: Agent type string for the error constructor.
        duration_ms: Elapsed time in milliseconds for inclusion in the message.

    Returns:
        A typed ``AgentError`` subclass ready to raise.
    """
    if isinstance(exc, httpx.TimeoutException):
        return AgentTimeoutError(
            agent_type,
            f"HTTP request timed out after {duration_ms}ms",
        )

    if isinstance(exc, httpx.ConnectError):
        return AgentNotAvailableError(
            agent_type,
            "Remote endpoint is unreachable",
        )

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 401:
            # 401 Unauthorized — bearer token is invalid or expired.
            # Do NOT include the token value or raw response body in the message.
            return AgentExecutionError(
                agent_type,
                "401 Unauthorized: bearer token is invalid or expired",
            )
        if status == 403:
            # 403 Forbidden — token is valid but lacks required permissions.
            return AgentExecutionError(
                agent_type,
                "403 Forbidden: bearer token lacks required permissions",
            )
        # Other HTTP error — include status code only (no response body).
        return AgentExecutionError(
            agent_type,
            f"HTTP {status} error from remote server after {duration_ms}ms",
        )

    # Generic fallback — secret-safe, no raw exception text.
    return AgentExecutionError(
        agent_type,
        f"Session failed after {duration_ms}ms",
    )


# ---------------------------------------------------------------------------
# Remote agent
# ---------------------------------------------------------------------------


class CodexServerRemoteAgent:
    """Agent that connects to a remote Codex app server with bearer authentication.

    Validates all required configuration at construction time and resolves
    the API token using a deterministic precedence chain:
    ``api_key`` → ``token_env_var`` env var → ``OPENAI_API_KEY`` env var.

    Raises ``AgentConfigError`` immediately if:
    - ``base_url`` is missing or not a valid HTTP/HTTPS URL.
    - No token can be resolved from any source in the precedence chain.

    Per the integration contract (contract-matrix.md):
    - Remote variant uses bearer-authenticated HTTPS transport.
    - Tool allow-list is strictly enforced at the adapter layer.
    - Both REST and MCP callback channels are supported.

    Configuration:
        base_url: HTTPS base URL of the remote Codex server.  Must begin
            with ``http://`` or ``https://``.
        model: Model name forwarded to the Codex server session.  Optional.
        session_id: Optional pre-existing session ID to resume.
        callback_channel: ``"rest"`` or ``"mcp"`` — determines how the
            prompt instructs the Codex agent to call back.
        api_key: Explicit bearer token.  Takes precedence over env vars.
        token_env_var: Name of the environment variable to check when
            ``api_key`` is not provided.  Defaults to
            ``CODEX_SERVER_API_KEY``.
        retry: Maximum number of HTTP request retries on transient failure.
            Defaults to ``3``.
        timeout: HTTP request timeout in seconds.  Defaults to ``300.0``.
    """

    #: v1 tool allow-list surfaced as a class attribute for inspection/testing.
    TOOL_ALLOWLIST: frozenset[str] = CODEX_SERVER_TOOL_ALLOWLIST

    def __init__(
        self,
        base_url: str,
        model: str | None = None,
        session_id: str | None = None,
        callback_channel: str = "rest",
        api_key: str | None = None,
        token_env_var: str = DEFAULT_TOKEN_ENV_VAR,
        retry: int = 3,
        timeout: float = 300.0,
        *,
        _environ: dict[str, str] | None = None,
    ) -> None:
        # --- Config validation ---
        if not base_url or not base_url.startswith(("http://", "https://")):
            raise AgentConfigError(
                AgentType.CODEX_SERVER_REMOTE.value,
                f"base_url must be a valid HTTP or HTTPS URL, got: {base_url!r}",
            )

        if callback_channel not in ("rest", "mcp"):
            raise AgentConfigError(
                AgentType.CODEX_SERVER_REMOTE.value,
                f"callback_channel must be 'rest' or 'mcp', got: {callback_channel!r}",
            )

        if retry < 0:
            raise AgentConfigError(
                AgentType.CODEX_SERVER_REMOTE.value,
                f"retry must be a non-negative integer, got: {retry!r}",
            )

        if timeout <= 0:
            raise AgentConfigError(
                AgentType.CODEX_SERVER_REMOTE.value,
                f"timeout must be a positive number, got: {timeout!r}",
            )

        # --- Token resolution ---
        resolved = resolve_remote_token(
            api_key=api_key,
            token_env_var=token_env_var,
            environ=_environ,
        )
        if not resolved:
            raise AgentConfigError(
                AgentType.CODEX_SERVER_REMOTE.value,
                (
                    f"No API token could be resolved. "
                    f"Provide api_key, set ${token_env_var}, "
                    f"or set ${FALLBACK_TOKEN_ENV_VAR}."
                ),
            )

        self._base_url = base_url.rstrip("/")
        self._model = model
        self._session_id = session_id
        self._callback_channel = callback_channel
        self._token = resolved
        self._token_env_var = token_env_var
        self._retry = retry
        self._timeout = timeout
        self._cancelled = False
        self._session_task: asyncio.Task[Any] | None = None

    # ------------------------------------------------------------------
    # Agent protocol
    # ------------------------------------------------------------------

    @property
    def info(self) -> AgentInfo:
        """Return static metadata for this agent instance."""
        return AgentInfo(
            agent_type=AgentType.CODEX_SERVER_REMOTE,
            name="Codex Server Remote",
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
        """Execute a task via a remote bearer-authenticated Codex server session.

        Assembles the phase-aware prompt using ``build_codex_server_prompt``,
        then delegates to the remote Codex server session lifecycle over HTTPS
        with a bearer token in the ``Authorization`` header.  Callback tool
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
                session ID).

        Returns:
            ``ExecutionResult`` describing success, metrics, and output lines.

        Raises:
            AgentCancelledError: If ``cancel()`` was called before or during
                execution.
            AgentNotAvailableError: If the remote Codex server cannot be
                contacted.
            AgentExecutionError: For any other session-level failure.
        """
        if self._cancelled:
            raise AgentCancelledError(AgentType.CODEX_SERVER_REMOTE.value)

        start_ms = int(time.monotonic() * 1000)
        is_verifier = on_grade is not None

        try:
            logger.debug(
                "CodexServerRemoteAgent: starting session — run=%s task=%s phase=%s base_url=%s",
                context.run_id,
                context.task_id,
                "verifier" if is_verifier else "builder",
                self._base_url,
            )

            # Build the phase-aware prompt (used by the session layer below).
            _full_prompt = build_codex_server_prompt(context, is_verifier=is_verifier)

            # --- Session lifecycle placeholder ---
            # A complete implementation would:
            #   1. POST /sessions to open a new session with full_prompt, model,
            #      and Authorization: Bearer <token> header; record session_id.
            #   2. Stream or poll session events over HTTPS.
            #   3. For each callback-tool event:
            #      a. Call enforce_tool_allowlist(tool_name) — reject if not
            #         in TOOL_ALLOWLIST.
            #      b. Route to on_checklist_update / on_submit / on_grade /
            #         request-clarification handler as appropriate.
            #   4. Collect all output text into output_lines.
            #   5. Retry on transient HTTP errors up to self._retry times.
            #   6. Apply self._timeout to each HTTP request.
            #   7. Return when session reaches a terminal state or
            #      self._cancelled is set.
            #
            # Until the HTTPS transport layer is implemented, raise
            # AgentNotAvailableError so callers receive a clear, actionable
            # error rather than a silent no-op.
            raise AgentNotAvailableError(
                AgentType.CODEX_SERVER_REMOTE.value,
                "Codex remote server HTTPS transport not yet implemented. "
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
                "CodexServerRemoteAgent: asyncio task cancelled — treating as AgentCancelledError"
            )
            raise AgentCancelledError(AgentType.CODEX_SERVER_REMOTE.value)
        except httpx.TimeoutException as exc:
            # Bounded timeout — map to AgentTimeoutError with redacted diagnostics.
            duration_ms = int(time.monotonic() * 1000) - start_ms
            logger.debug(
                "CodexServerRemoteAgent: request timed out after %dms (timeout=%.1fs)",
                duration_ms,
                self._timeout,
            )
            raise map_transport_error(
                exc, AgentType.CODEX_SERVER_REMOTE.value, duration_ms
            ) from exc
        except httpx.ConnectError as exc:
            # Unreachable endpoint — map to AgentNotAvailableError.
            duration_ms = int(time.monotonic() * 1000) - start_ms
            logger.debug(
                "CodexServerRemoteAgent: connection error after %dms — endpoint unreachable",
                duration_ms,
            )
            raise map_transport_error(
                exc, AgentType.CODEX_SERVER_REMOTE.value, duration_ms
            ) from exc
        except httpx.HTTPStatusError as exc:
            # HTTP error responses — explicit 401/403 handling is token-safe;
            # other status codes include only the numeric code, not the body.
            duration_ms = int(time.monotonic() * 1000) - start_ms
            logger.debug(
                "CodexServerRemoteAgent: HTTP %d error after %dms",
                exc.response.status_code,
                duration_ms,
            )
            raise map_transport_error(
                exc, AgentType.CODEX_SERVER_REMOTE.value, duration_ms
            ) from exc
        except Exception as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            # Log full exception details at debug level only — the error
            # message surfaced to the orchestrator must NOT include the raw
            # exception string because it may contain secrets (API keys,
            # endpoint URLs with credentials, etc.).
            logger.debug(
                "CodexServerRemoteAgent: session error after %dms — %s",
                duration_ms,
                exc,
                exc_info=True,
            )
            raise map_transport_error(
                exc, AgentType.CODEX_SERVER_REMOTE.value, duration_ms
            ) from exc

    async def cancel(self) -> None:
        """Request cancellation of the active Codex server session.

        Sets the cancellation flag and cancels the session asyncio task if
        one is running.  Safe to call multiple times — subsequent calls are
        no-ops once the flag is set and the task is already cancelled or done.
        """
        self._cancelled = True
        if self._session_task is not None and not self._session_task.done():
            self._session_task.cancel()
            logger.info("CodexServerRemoteAgent: cancelled active session task")

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
        Disallowed tool names raise ``ValueError`` (via
        ``enforce_tool_allowlist``).

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
        # Raises ValueError for disallowed tools.
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
                logger.warning(
                    "CodexServerRemoteAgent: 'grade' tool called in builder phase — ignoring"
                )

        elif tool_name == "request_clarification":
            question: str = str(args.get("question", ""))
            logger.info(
                "CodexServerRemoteAgent: request_clarification received — question=%r", question
            )
