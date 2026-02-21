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
from urllib.parse import urlparse

import httpx

from orchestrator.agents.codex_server_common import (
    CODEX_SERVER_TOOL_ALLOWLIST,
    build_codex_server_prompt,
    build_execution_result,
    create_session_payload,
    extract_events,
    normalize_codex_metrics,
    normalize_codex_output_lines,
    route_tool_call,
)
from orchestrator.agents.errors import (
    AgentCancelledError,
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
from orchestrator.config.enums import AgentType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_loopback_endpoint(endpoint: str) -> bool:
    """Return True if *endpoint* points to a loopback address (localhost/127.0.0.1)."""
    try:
        host = urlparse(endpoint).hostname or ""
    except Exception:
        return False
    return host in ("localhost", "127.0.0.1", "::1")


async def _ensure_codex_server(endpoint: str) -> int | None:
    """Ensure a local ``codex app-server`` process is running.

    Checks whether the endpoint is already accepting connections.  If not,
    spawns ``codex app-server`` as a subprocess and returns its PID.  Returns
    ``None`` if the server is already running or if spawning fails.

    Args:
        endpoint: Loopback endpoint URL of the Codex server.

    Returns:
        PID of the newly spawned process, or ``None`` if already running or
        spawn failed.
    """
    parsed = urlparse(endpoint)
    host = parsed.hostname or "localhost"
    port = parsed.port or 9000

    # Quick reachability check — if the server already listens, skip spawning.
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=0.5,
        )
        writer.close()
        await writer.wait_closed()
        logger.debug("CodexServerAgent: server already running at %s", endpoint)
        return None
    except (OSError, asyncio.TimeoutError):
        pass  # Not reachable — attempt to spawn.

    try:
        proc = await asyncio.create_subprocess_exec(
            "codex",
            "app-server",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        logger.info("CodexServerAgent: spawned codex app-server — pid=%d", proc.pid)
        return proc.pid
    except FileNotFoundError:
        raise AgentNotAvailableError(
            AgentType.CODEX_SERVER.value,
            "codex executable not found; install Codex CLI to use this agent",
        )
    except Exception as exc:
        raise AgentNotAvailableError(
            AgentType.CODEX_SERVER.value,
            "Failed to spawn codex app-server process",
        ) from exc


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
        *,
        _http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._model = model
        self._callback_channel = callback_channel
        self._api_key = api_key  # Unused for local; kept for interface parity.
        self._cancelled = False
        self._session_task: asyncio.Task[Any] | None = None
        # For testing only: inject a fake client to intercept HTTP calls without
        # starting a real Codex process.
        self._http_client = _http_client

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
            # Build the phase-aware prompt.
            _full_prompt = build_codex_server_prompt(context, is_verifier=is_verifier)

            # Determine which HTTP client to use.
            # When _http_client is injected (tests), use it directly.
            # Otherwise create a default client (and close it when done).
            injected_client = self._http_client is not None
            client: httpx.AsyncClient = self._http_client or httpx.AsyncClient()

            output_lines: list[str] = []

            try:
                # --- Process spawning ---
                # Only spawn a local process when using a real client (not a test
                # injection) and the endpoint is a loopback address.
                if not injected_client and _is_loopback_endpoint(self._endpoint):
                    pid = await _ensure_codex_server(self._endpoint)
                    if pid is not None and on_agent_metadata is not None:
                        await on_agent_metadata({"pid": pid})

                # --- Session creation: POST {endpoint}/sessions ---
                payload = create_session_payload(_full_prompt, self._model)

                try:
                    response = await client.post(
                        f"{self._endpoint}/sessions",
                        json=payload,
                    )
                    response.raise_for_status()
                except httpx.ConnectError as exc:
                    raise AgentNotAvailableError(
                        AgentType.CODEX_SERVER.value,
                        "Local Codex server is unreachable",
                    ) from exc

                data: dict[str, Any] = response.json()
                session_id: str | None = data.get("session_id") or data.get("id")

                logger.debug(
                    "CodexServerAgent: session created — session_id=%s",
                    session_id,
                )

                # --- Event polling loop ---
                # Poll GET {endpoint}/sessions/{session_id}/events until a
                # terminal event is received or cancellation is requested.
                terminal = False
                while not self._cancelled and not terminal:
                    try:
                        events_resp = await client.get(
                            f"{self._endpoint}/sessions/{session_id}/events",
                        )
                        events_resp.raise_for_status()
                    except httpx.ConnectError as exc:
                        raise AgentNotAvailableError(
                            AgentType.CODEX_SERVER.value,
                            "Local Codex server is unreachable",
                        ) from exc
                    except httpx.TimeoutException as exc:
                        raise AgentTimeoutError(
                            AgentType.CODEX_SERVER.value,
                            "Timed out waiting for session events",
                        ) from exc

                    events_payload: Any = events_resp.json()
                    events = extract_events(events_payload)

                    for event in events:
                        event_type = str(event.get("type", ""))

                        if event_type == "tool_call":
                            tool_name = str(event.get("tool_name", ""))
                            tool_args: dict[str, Any] = event.get("args") or {}
                            try:
                                await self._route_tool_call(
                                    tool_name,
                                    tool_args,
                                    on_checklist_update,
                                    on_submit,
                                    on_grade=on_grade,
                                )
                            except ValueError:
                                # Disallowed tool — already logged by enforce_tool_allowlist.
                                pass

                        elif event_type == "output":
                            text = str(event.get("text", ""))
                            output_lines.append(text)
                            if on_output is not None:
                                await on_output([text])

                        elif event_type in ("complete", "error", "cancelled"):
                            terminal = True
                            break

                    # Yield to allow asyncio cancellation to be processed.
                    await asyncio.sleep(0)

                if self._cancelled:
                    raise AgentCancelledError(AgentType.CODEX_SERVER.value)

            finally:
                if not injected_client:
                    await client.aclose()

            duration_ms = int(time.monotonic() * 1000) - start_ms
            return build_execution_result(output_lines, duration_ms)

        except (AgentCancelledError, AgentNotAvailableError, AgentTimeoutError):
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

        Delegates to the shared ``route_tool_call`` helper in
        ``codex_server_common``.  Disallowed tool names raise ``ValueError``
        (via ``enforce_tool_allowlist``).

        Args:
            tool_name: Name of the callback tool the Codex session invoked.
            args: Tool argument dict from the Codex server event payload.
            on_checklist_update: Bound checklist-update callback.
            on_submit: Bound submit callback.
            on_grade: Bound grade callback (``None`` in builder phase).

        Raises:
            ValueError: If ``tool_name`` is not on the v1 allow-list.
        """
        await route_tool_call(
            tool_name,
            args,
            on_checklist_update,
            on_submit,
            on_grade=on_grade,
            agent_label="CodexServerAgent",
        )
