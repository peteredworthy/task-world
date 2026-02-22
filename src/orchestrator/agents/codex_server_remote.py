"""Codex Server agent — remote bearer-authenticated variant.

Implements ``CodexServerRemoteAgent`` which connects to a pre-existing remote
``codex app-server`` instance over WebSocket with a bearer token for
authentication.  Shared helpers for prompt assembly, tool allow-list
enforcement, and output normalization are imported from
``codex_server_common`` — the same module used by the local variant
(``codex_server``).

Protocol summary (see docs/codex-server-transport/api-contract.md §5):
  - Remote variant connects via WebSocket (``wss://`` or ``ws://``).
  - Bearer token is sent in the WebSocket upgrade ``Authorization`` header.
  - No ``account/login/start`` step (auth is in the handshake).
  - ``initialize`` handshake is required before any other request.
  - Otherwise identical JSON-RPC protocol: ``initialize`` → ``thread/start``
    → ``turn/start`` → notification stream → ``turn/completed``.

## Token resolution (deterministic precedence)

Tokens are resolved in the following order at *construction* time:

1. ``api_key`` constructor argument — if non-empty, use it directly.
2. Environment variable named by ``token_env_var`` (default
   ``CODEX_SERVER_API_KEY``) — resolved via ``os.environ``.
3. ``OPENAI_API_KEY`` environment variable — fallback for operators that
   already export this key.

If none of the above yields a non-empty string, ``AgentConfigError`` is
raised immediately — no network I/O is performed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import websockets
import websockets.exceptions

from orchestrator.agents.codex_server_common import (
    CODEX_SERVER_TOOL_ALLOWLIST,
    JsonRpcTransport,
    build_codex_server_prompt,
    build_dynamic_tool_call_response,
    build_dynamic_tool_specs,
    build_execution_result,
    build_jsonrpc_request,
    extract_agent_message_delta,
    extract_dynamic_tool_call,
    extract_tool_call_from_notification,
    is_terminal_notification,
    normalize_codex_metrics,
    normalize_codex_output_lines,
    route_tool_call,
)
from orchestrator.agents.errors import (
    AgentCancelledError,
    AgentConfigError,
    AgentError,
    AgentExecutionError,
    AgentNotAvailableError,
    AgentTimeoutError,
)
from orchestrator.agents.quota import HttpQuotaFetcher, QuotaFetcher
from orchestrator.agents.types import (
    AgentInfo,
    AgentMetadataCallback,
    AgentQuota,
    ChecklistUpdateCallback,
    ExecutionContext,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
    SubmitCallback,
)
from orchestrator.config.enums import AgentType

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
    """Map WebSocket/transport exceptions to typed orchestrator agent errors.

    Converts WebSocket and OS-level exceptions to the appropriate orchestrator
    error type with redacted diagnostics.  Raw exception text, bearer tokens,
    and credentials are never included in the returned error's message.

    Mapping:
    - ``OSError`` (connection refused, DNS fail)  → ``AgentNotAvailableError``
    - ``websockets.exceptions.InvalidHandshake``  → ``AgentExecutionError``
      (includes 401/403 — no token in message)
    - ``websockets.exceptions.ConnectionClosed``  → ``AgentNotAvailableError``
    - ``asyncio.TimeoutError``                    → ``AgentTimeoutError``
    - Any other ``Exception``                     → ``AgentExecutionError``

    Args:
        exc: The exception to map.
        agent_type: Agent type string for the error constructor.
        duration_ms: Elapsed time in milliseconds.

    Returns:
        A typed ``AgentError`` subclass ready to raise.
    """
    if isinstance(exc, asyncio.TimeoutError):
        return AgentTimeoutError(
            agent_type,
            f"WebSocket connection timed out after {duration_ms}ms",
        )

    if isinstance(exc, OSError):
        return AgentNotAvailableError(
            agent_type,
            "Remote endpoint is unreachable",
        )

    if isinstance(exc, websockets.exceptions.ConnectionClosed):
        return AgentNotAvailableError(
            agent_type,
            "WebSocket connection was closed unexpectedly",
        )

    if isinstance(exc, websockets.exceptions.InvalidHandshake):
        # Includes HTTP 401/403 during WebSocket upgrade — never log the token.
        return AgentExecutionError(
            agent_type,
            "WebSocket handshake failed; check bearer token and endpoint URL",
        )

    # Generic fallback — secret-safe, no raw exception text.
    return AgentExecutionError(
        agent_type,
        f"Session failed after {duration_ms}ms",
    )


# ---------------------------------------------------------------------------
# WebSocket transport
# ---------------------------------------------------------------------------


class RealWebSocketTransport:
    """JSON-RPC 2.0 transport backed by a WebSocket connection.

    Connects to a remote ``codex app-server`` via WebSocket with optional
    bearer authentication in the upgrade headers.

    Args:
        ws_url: WebSocket URL (``ws://`` or ``wss://``).
        token: Optional bearer token included in the ``Authorization`` header
            on the WebSocket upgrade request.
    """

    def __init__(self, ws_url: str, token: str | None = None) -> None:
        self._ws_url = ws_url
        self._token = token
        self._ws: Any = None

    async def connect(self) -> None:
        """Establish the WebSocket connection."""
        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        self._ws = await websockets.connect(self._ws_url, additional_headers=headers)

    async def send(self, message: dict[str, Any]) -> None:
        """Send one JSON-RPC message as a WebSocket text frame."""
        if self._ws is None:
            raise OSError("WebSocket transport is not connected")
        await self._ws.send(json.dumps(message))

    async def recv(self) -> dict[str, Any]:
        """Receive and parse the next WebSocket text frame as a JSON-RPC message.

        Raises:
            EOFError: If the WebSocket is closed.
            json.JSONDecodeError: If the frame is not valid JSON.
        """
        if self._ws is None:
            raise OSError("WebSocket transport is not connected")
        raw = await self._ws.recv()
        return json.loads(raw)  # type: ignore[arg-type]

    async def close(self) -> None:
        """Close the WebSocket connection."""
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None


# ---------------------------------------------------------------------------
# URL normalization helper
# ---------------------------------------------------------------------------


def _normalize_to_ws_url(url: str) -> str:
    """Convert an http/https URL to ws/wss for WebSocket connection.

    ``https://`` → ``wss://``
    ``http://``  → ``ws://``
    ``ws://`` / ``wss://`` → unchanged
    """
    if url.startswith("https://"):
        return "wss://" + url[len("https://") :]
    if url.startswith("http://"):
        return "ws://" + url[len("http://") :]
    return url


# ---------------------------------------------------------------------------
# Remote agent
# ---------------------------------------------------------------------------


class CodexServerRemoteAgent:
    """Agent that connects to a remote Codex app server with bearer authentication.

    Validates all required configuration at construction time and resolves
    the API token using a deterministic precedence chain:
    ``api_key`` → ``token_env_var`` env var → ``OPENAI_API_KEY`` env var.

    Raises ``AgentConfigError`` immediately if:
    - ``base_url`` is missing or not a valid URL.
    - No token can be resolved from any source in the precedence chain.

    Per the integration contract (contract-matrix.md):
    - Remote variant uses bearer-authenticated WebSocket transport.
    - Tool allow-list is strictly enforced at the adapter layer.
    - Both REST and MCP callback channels are supported.

    Configuration:
        base_url: URL of the remote Codex server.  Accepts ``http://``,
            ``https://``, ``ws://``, or ``wss://``.  HTTP/HTTPS URLs are
            normalized to WebSocket equivalents internally.
        model: Model name forwarded to the Codex server session.  Optional.
        session_id: Optional pre-existing thread ID to resume.
        callback_channel: ``"rest"`` or ``"mcp"`` — determines how the
            prompt instructs the Codex agent to call back.
        api_key: Explicit bearer token.  Takes precedence over env vars.
        token_env_var: Name of the environment variable to check when
            ``api_key`` is not provided.  Defaults to
            ``CODEX_SERVER_API_KEY``.

    Test injection:
        _transport: Inject a fake ``JsonRpcTransport`` to replace the real
            WebSocket transport.  When set, no WebSocket connection is made.
    """

    #: Matches AgentOption.name produced by ToolDetector._detect_codex_server_remote().
    name = "Codex Server Remote"

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
        *,
        _environ: dict[str, str] | None = None,
        _transport: JsonRpcTransport | None = None,
    ) -> None:
        # --- Config validation ---
        if not base_url or not base_url.startswith(("http://", "https://", "ws://", "wss://")):
            raise AgentConfigError(
                AgentType.CODEX_SERVER_REMOTE.value,
                f"base_url must be a valid HTTP, HTTPS, ws, or wss URL, got: {base_url!r}",
            )

        if callback_channel not in ("rest", "mcp"):
            raise AgentConfigError(
                AgentType.CODEX_SERVER_REMOTE.value,
                f"callback_channel must be 'rest' or 'mcp', got: {callback_channel!r}",
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
        self._ws_url = _normalize_to_ws_url(self._base_url)
        self._model = model
        self._session_id = session_id
        self._callback_channel = callback_channel
        self._token = resolved
        self._token_env_var = token_env_var
        self._cancelled = False
        self._active_thread_id: str | None = None
        self._session_task: asyncio.Task[object] | None = None
        # For testing: inject a fake transport to replace real WebSocket.
        self._transport = _transport

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

    def get_quota(self, fetcher: QuotaFetcher | None = None) -> AgentQuota | None:
        """Fetch the OpenAI credit balance for the resolved API token.

        Uses the injected fetcher if provided; otherwise constructs an
        HttpQuotaFetcher.  All exceptions are swallowed and result in None.
        The api_key is never logged at any log level.

        Returns:
            AgentQuota with balance_usd, max_balance_usd, and label when the
            key is present and the fetch succeeds; None otherwise.
        """
        api_key = self._token
        if not api_key:
            return None
        try:
            quota_fetcher: QuotaFetcher = fetcher if fetcher is not None else HttpQuotaFetcher()
            data = quota_fetcher.fetch_openai_credits(api_key)
            total_granted: float = data["total_granted"]
            total_used: float = data["total_used"]
            balance_usd = total_granted - total_used
            return AgentQuota(
                balance_usd=balance_usd,
                max_balance_usd=total_granted,
                balance_pct=None,
                label="OpenAI credit balance",
            )
        except Exception:
            return None

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

        Connects via WebSocket (bearer token in the upgrade header), sends
        ``thread/start`` → ``turn/start``, then reads notifications until
        ``turn/completed``.

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
            on_agent_metadata: Optional callback for runtime metadata.

        Returns:
            ``ExecutionResult`` describing success, metrics, and output lines.

        Raises:
            AgentCancelledError: If ``cancel()`` was called before or during
                execution.
            AgentNotAvailableError: If the remote Codex server cannot be
                contacted.
            AgentExecutionError: For session-level failures.
        """
        if self._cancelled:
            raise AgentCancelledError(AgentType.CODEX_SERVER_REMOTE.value)

        start_ms = int(time.monotonic() * 1000)
        is_verifier = on_grade is not None
        full_prompt = build_codex_server_prompt(context, is_verifier=is_verifier)

        transport: JsonRpcTransport | None = self._transport
        connected = False

        try:
            if transport is None:
                ws_transport = RealWebSocketTransport(self._ws_url, self._token)
                try:
                    await ws_transport.connect()
                except OSError as exc:
                    raise AgentNotAvailableError(
                        AgentType.CODEX_SERVER_REMOTE.value,
                        "Remote endpoint is unreachable",
                    ) from exc
                except websockets.exceptions.InvalidHandshake as exc:
                    # Never include the token in the error message (risk R-05).
                    raise AgentExecutionError(
                        AgentType.CODEX_SERVER_REMOTE.value,
                        "WebSocket handshake failed; check bearer token and endpoint URL",
                    ) from exc
                transport = ws_transport
                connected = True

            logger.debug(
                "CodexServerRemoteAgent: starting session — run=%s task=%s phase=%s",
                context.run_id,
                context.task_id,
                "verifier" if is_verifier else "builder",
            )

            output_lines: list[str] = []
            notification_buffer: list[dict[str, Any]] = []
            next_id = 1

            async def _send_and_wait(method: str, params: dict[str, Any]) -> dict[str, Any]:
                nonlocal next_id
                req_id = next_id
                next_id += 1
                await transport.send(build_jsonrpc_request(req_id, method, params))
                while True:
                    msg = await transport.recv()
                    if msg.get("id") == req_id:
                        return msg
                    if "method" in msg and "id" not in msg:
                        notification_buffer.append(msg)

            # --- Step 0: Initialize (required JSON-RPC handshake) ---
            # experimentalApi enables dynamicTools in thread/start.
            await _send_and_wait(
                "initialize",
                {
                    "clientInfo": {"name": "orchestrator", "version": "1.0.0"},
                    "capabilities": {"experimentalApi": True},
                },
            )

            # --- Step 1: Create or resume thread ---
            model = self._model
            thread_params: dict[str, Any] = {
                "cwd": context.working_dir,
                "approvalPolicy": "never",
                "dynamicTools": build_dynamic_tool_specs(),
            }
            if model:
                thread_params["model"] = model

            if self._session_id:
                # Resume an existing thread.
                thread_resp = await _send_and_wait("thread/resume", {"threadId": self._session_id})
            else:
                thread_resp = await _send_and_wait("thread/start", thread_params)

            if "error" in thread_resp:
                raise AgentExecutionError(
                    AgentType.CODEX_SERVER_REMOTE.value,
                    "thread/start failed",
                )

            thread_id: str = thread_resp["result"]["thread"]["id"]
            self._active_thread_id = thread_id

            if on_agent_metadata is not None:
                await on_agent_metadata({"thread_id": thread_id})

            logger.debug("CodexServerRemoteAgent: thread ready — thread_id=%s", thread_id)

            # --- Step 2: Start turn ---
            turn_params: dict[str, Any] = {
                "threadId": thread_id,
                "input": [{"type": "text", "text": full_prompt}],
                "cwd": context.working_dir,
                "approvalPolicy": "never",
                "effort": "medium",
            }
            if model:
                turn_params["model"] = model

            turn_resp = await _send_and_wait("turn/start", turn_params)
            if "error" in turn_resp:
                raise AgentExecutionError(
                    AgentType.CODEX_SERVER_REMOTE.value,
                    "turn/start failed",
                )

            # --- Step 3: Process notification stream ---
            done = False

            async def _dispatch_tool_call(tool_msg: dict[str, Any]) -> None:
                """Respond to an ``item/tool/call`` server request and fire callbacks."""
                tool_result = extract_dynamic_tool_call(tool_msg)
                if tool_result is None:
                    return
                req_id, tool_name, tool_args = tool_result
                try:
                    await route_tool_call(
                        tool_name,
                        tool_args,
                        on_checklist_update,
                        on_submit,
                        on_grade=on_grade,
                        agent_label="CodexServerRemoteAgent",
                    )
                    await transport.send(build_dynamic_tool_call_response(req_id, success=True))
                except ValueError:
                    # Disallowed tool — respond with failure to unblock the server.
                    await transport.send(build_dynamic_tool_call_response(req_id, success=False))

            async def _process_msg(msg: dict[str, Any]) -> bool:
                """Process one message; return True if it is a terminal notification."""
                # Dynamic tool call request from the server (has id AND method).
                if msg.get("method") == "item/tool/call" and "id" in msg:
                    await _dispatch_tool_call(msg)
                    return False
                # Skip stray response messages (no method field).
                if "id" in msg and "method" not in msg:
                    return False
                return await self._handle_notification(
                    msg, output_lines, on_output, on_checklist_update, on_submit, on_grade
                )

            # First drain any notifications buffered during the request-response phase.
            for msg in notification_buffer:
                if self._cancelled:
                    raise AgentCancelledError(AgentType.CODEX_SERVER_REMOTE.value)
                if await _process_msg(msg):
                    done = True
                    break

            # Then continue reading live notifications until terminal.
            while not done and not self._cancelled:
                msg = await transport.recv()
                if await _process_msg(msg):
                    done = True

            if self._cancelled:
                raise AgentCancelledError(AgentType.CODEX_SERVER_REMOTE.value)

        except (
            AgentCancelledError,
            AgentNotAvailableError,
            AgentTimeoutError,
            AgentExecutionError,
        ):
            raise
        except asyncio.CancelledError:
            raise AgentCancelledError(AgentType.CODEX_SERVER_REMOTE.value)
        except OSError as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            raise map_transport_error(
                exc, AgentType.CODEX_SERVER_REMOTE.value, duration_ms
            ) from exc
        except websockets.exceptions.ConnectionClosed as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            logger.debug("CodexServerRemoteAgent: WebSocket closed after %dms", duration_ms)
            raise map_transport_error(
                exc, AgentType.CODEX_SERVER_REMOTE.value, duration_ms
            ) from exc
        except Exception as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            logger.debug(
                "CodexServerRemoteAgent: session error after %dms — %s",
                duration_ms,
                exc,
                exc_info=True,
            )
            raise AgentExecutionError(
                AgentType.CODEX_SERVER_REMOTE.value,
                f"Session failed after {duration_ms}ms",
            ) from exc
        finally:
            if connected and transport is not None:
                try:
                    await transport.close()
                except Exception:
                    pass

        duration_ms = int(time.monotonic() * 1000) - start_ms
        return build_execution_result(output_lines, duration_ms)

    async def cancel(self) -> None:
        """Request cancellation of the active Codex server session."""
        self._cancelled = True
        task = self._session_task
        if task is not None and not task.done():
            task.cancel()
        thread_id = self._active_thread_id
        transport = self._transport
        if thread_id is not None and transport is not None:
            try:
                await transport.send(
                    build_jsonrpc_request(99, "turn/interrupt", {"threadId": thread_id})
                )
            except Exception:
                pass
        logger.info("CodexServerRemoteAgent: cancelled")

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
        """Route an allow-listed callback tool call to the appropriate callback."""
        await route_tool_call(
            tool_name,
            args,
            on_checklist_update,
            on_submit,
            on_grade=on_grade,
            agent_label="CodexServerRemoteAgent",
        )

    async def _handle_notification(
        self,
        msg: dict[str, Any],
        output_lines: list[str],
        on_output: LogLineCallback | None,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_grade: GradeCallback | None,
    ) -> bool:
        """Process one JSON-RPC notification. Returns True if terminal."""
        terminal, status = is_terminal_notification(msg)
        if terminal:
            if status == "interrupted":
                raise AgentCancelledError(AgentType.CODEX_SERVER_REMOTE.value)
            if status in ("systemError", "failed"):
                raise AgentExecutionError(
                    AgentType.CODEX_SERVER_REMOTE.value,
                    f"Codex session ended with status: {status}",
                )
            return True

        tool_call = extract_tool_call_from_notification(msg)
        if tool_call is not None:
            tool_name, tool_args = tool_call
            try:
                await route_tool_call(
                    tool_name,
                    tool_args,
                    on_checklist_update,
                    on_submit,
                    on_grade=on_grade,
                    agent_label="CodexServerRemoteAgent",
                )
            except ValueError:
                pass

        delta = extract_agent_message_delta(msg)
        if delta:
            output_lines.append(delta)
            if on_output is not None:
                await on_output([delta])

        return False
