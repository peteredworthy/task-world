"""Codex Server agent — local managed-process variant.

Implements ``CodexServerAgent`` which spawns a local ``codex app-server``
process and communicates via JSON-RPC 2.0 over stdio (newline-delimited JSON
on stdin/stdout).

Protocol summary (see docs/codex-server-transport/api-contract.md):
  1. Spawn ``codex app-server`` with stdin/stdout pipes.
  2. Send ``initialize`` with clientInfo (required handshake).
  3. Optionally send ``account/login/start`` with the OpenAI API key.
  4. Send ``thread/start`` → receive ``thread.id``.
  5. Send ``turn/start`` with the full prompt.
  6. Read JSON-RPC notifications until ``turn/completed``.
  7. Route ``item/started`` mcpToolCall notifications to orchestrator callbacks.
  8. Accumulate ``item/agentMessage/delta`` notifications as output lines.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from orchestrator.runners.agents.codex.common import (
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
    extract_turn_usage,
    is_terminal_notification,
    normalize_codex_metrics,
    normalize_codex_output_lines,
    route_tool_call,
)
from orchestrator.runners.errors import (
    AgentCancelledError,
    AgentExecutionError,
    AgentNotAvailableError,
    AgentTimeoutError,
)
from orchestrator.workflow import GateBlockedError
from orchestrator.runners.types import (
    AgentRunnerInfo,
    AgentMetadataCallback,
    AgentQuota,
    ChecklistUpdateCallback,
    CompleteRecoveryCallback,
    EscalationCallback,
    ExecutionContext,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
    QuotaBucket,
    SubmitCallback,
)
from orchestrator.config.enums import AgentRunnerType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stdio transport
# ---------------------------------------------------------------------------


class RealStdioTransport:
    """JSON-RPC 2.0 transport backed by a ``codex app-server`` subprocess stdio.

    Writes newline-delimited JSON to the process stdin and reads
    newline-delimited JSON from the process stdout.  Non-JSON lines (such as
    startup banners) are silently skipped.

    Args:
        proc: A running asyncio subprocess with ``stdin`` and ``stdout`` pipes.
    """

    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self._proc = proc

    async def send(self, message: dict[str, Any]) -> None:
        """Write one JSON-RPC message to the subprocess stdin."""
        assert self._proc.stdin is not None
        line = json.dumps(message) + "\n"
        self._proc.stdin.write(line.encode())
        await self._proc.stdin.drain()

    async def recv(self) -> dict[str, Any]:
        """Read and return the next valid JSON-RPC message from subprocess stdout.

        Skips empty lines and non-JSON lines (e.g. startup banners).

        Raises:
            EOFError: If stdout closes before a valid message is received.
        """
        assert self._proc.stdout is not None
        while True:
            line_bytes = await self._proc.stdout.readline()
            if not line_bytes:
                raise EOFError("codex app-server process stdout closed unexpectedly")
            line = line_bytes.decode().strip()
            if not line:
                continue  # skip blank lines
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                logger.debug("CodexServerAgent: skipping non-JSON line: %r", line[:120])

    async def close(self) -> None:
        """Terminate the subprocess and close its stdin."""
        try:
            if self._proc.stdin and not self._proc.stdin.is_closing():
                self._proc.stdin.close()
        except Exception:
            pass
        try:
            self._proc.terminate()
        except ProcessLookupError:
            pass


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class CodexServerAgent:
    """Agent that manages a local Codex app server process via JSON-RPC stdio.

    Spawns ``codex app-server`` as a subprocess and communicates using
    JSON-RPC 2.0 over stdio.  Callback tool invocations (``update_checklist``,
    ``grade``, ``submit``, ``request_clarification``) received as
    ``item/started`` notifications are dispatched to the orchestrator
    callbacks after allow-list enforcement.

    Configuration:
        model: Model name forwarded to the Codex session.  Defaults to the
            server's configured default when omitted.
        callback_channel: ``"rest"`` or ``"mcp"`` — determines how the
            prompt instructs the Codex agent to call back.
        api_key: OpenAI API key sent via ``account/login/start``.  Falls back
            to ``OPENAI_API_KEY`` from the environment.  If neither is present,
            the login step is skipped (the server must be pre-configured).

    Test injection:
        _transport: Inject a fake ``JsonRpcTransport`` to replace the real
            subprocess transport.  When set, no subprocess is spawned and the
            injected transport is used directly.  Leading underscore signals
            test-only use.
    """

    #: Matches AgentOption.name produced by ToolDetector._detect_codex_server().
    name = "Codex Server"

    #: v1 tool allow-list surfaced as a class attribute for inspection/testing.
    TOOL_ALLOWLIST: frozenset[str] = CODEX_SERVER_TOOL_ALLOWLIST

    def __init__(
        self,
        model: str | None = None,
        callback_channel: str = "rest",
        api_key: str | None = None,
        restrictions: str = "no-network",
        *,
        _transport: JsonRpcTransport | None = None,
        _environ: dict[str, str] | None = None,
    ) -> None:
        self._model = model
        self._callback_channel = callback_channel
        # restrictions controls how aggressively we override Codex sandbox/config behaviour.
        # Supported values:
        # - "none":     Do not override sandbox/network; honour Codex defaults and local config.
        # - "no-network": Force workspace-write sandbox with network disabled (orchestrator default).
        # - "use-local": Delegate entirely to the user's local Codex config.toml, including sandbox.
        self._restrictions = restrictions
        # Resolve API key: explicit arg only (or test-injected _environ).
        # Do NOT fall back to OPENAI_API_KEY from os.environ — doing so causes
        # execute() to call account/login/start with apiKey, which unconditionally
        # overwrites ~/.codex/auth.json and clobbers any ChatGPT subscription auth.
        # _environ is used in tests to inject a controlled environment.
        env = _environ if _environ is not None else {}
        self._api_key: str | None = api_key or env.get("OPENAI_API_KEY")
        self._cancelled = False
        self._transport = _transport
        self._active_thread_id: str | None = None
        self._session_task: asyncio.Task[object] | None = None

    # ------------------------------------------------------------------
    # Agent protocol
    # ------------------------------------------------------------------

    @property
    def info(self) -> AgentRunnerInfo:
        """Return static metadata for this agent instance."""
        return AgentRunnerInfo(
            agent_type=AgentRunnerType.CODEX_SERVER,
            name="Codex Server",
            version=None,
        )

    def get_quota(self, fetcher: Any = None) -> AgentQuota | None:
        """Fetch Codex rate-limit quota via ``account/rateLimits/read`` JSON-RPC.

        Spawns a short-lived ``codex app-server`` subprocess, completes the
        required ``initialize``/``initialized`` handshake, sends
        ``account/rateLimits/read``, reads the response, then terminates the
        process immediately.  The secondary (weekly) rate limit is used as the
        quota signal since it reflects the sustained-use ceiling most relevant
        to long-running orchestration sessions.

        Returns ``None`` on any error (codex not installed, no auth configured,
        subprocess timeout, malformed response, etc.).  All exceptions are
        swallowed so the caller is never interrupted by quota-fetch failures.
        """
        if shutil.which("codex") is None:
            return None

        try:
            import subprocess as _sp

            proc = _sp.Popen(
                ["codex", "app-server"],
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

            _send(
                {
                    "method": "initialize",
                    "id": 1,
                    "params": {
                        "clientInfo": {
                            "name": "orchestrator",
                            "title": "Orchestrator",
                            "version": "0.1.0",
                        }
                    },
                }
            )
            _send({"method": "initialized", "params": {}})
            _send({"method": "account/rateLimits/read", "id": 2})

            result: dict[str, Any] | None = None
            assert proc.stdout is not None
            for _ in range(20):
                line = proc.stdout.readline()
                if not line:
                    break
                try:
                    obj = json.loads(line)
                    if obj.get("id") == 2:
                        result = obj.get("result")
                        break
                except json.JSONDecodeError:
                    pass

            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()

            if result is None:
                return None

            rate_limits = result.get("rateLimits", {})
            secondary = rate_limits.get("secondary", {})
            used_pct: float = float(secondary.get("usedPercent", 0))
            plan_type: str = rate_limits.get("planType", "")
            resets_at: int | None = secondary.get("resetsAt")
            window_mins: int = int(secondary.get("windowDurationMins", 10080))
            window_label = f"{window_mins // 1440}d" if window_mins >= 1440 else f"{window_mins}m"

            from datetime import datetime, timezone

            resets_at_iso: str | None = None
            resets_label = ""
            if resets_at:
                resets_dt = datetime.fromtimestamp(resets_at, tz=timezone.utc)
                resets_at_iso = resets_dt.isoformat()
                resets_label = f"· resets {resets_dt.strftime('%b %d')}"

            label_parts = ["Codex"]
            if plan_type:
                label_parts.append(f"({plan_type})")
            label_parts.append(f"— {window_label} remaining")
            if resets_label:
                label_parts.append(resets_label)

            return AgentQuota(
                balance_pct=float(100 - used_pct),
                label=" ".join(label_parts),
                breakdown=[
                    QuotaBucket(
                        label=f"{window_label} window",
                        remaining_pct=float(100 - used_pct),
                        resets_at=resets_at_iso,
                    )
                ],
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
        on_complete_recovery: CompleteRecoveryCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        """Execute a task via a local Codex app server session over stdio.

        Spawns ``codex app-server`` (unless a transport is injected), sends
        ``account/login/start`` → ``thread/start`` → ``turn/start``, then
        reads notifications until ``turn/completed``.

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
                subprocess PID).

        Returns:
            ``ExecutionResult`` describing success, metrics, and output lines.

        Raises:
            AgentNotAvailableError: If the ``codex`` binary is not found or
                the process cannot be started.
            AgentCancelledError: If ``cancel()`` was called before or during
                execution, or the turn ended with ``status: "interrupted"``.
            AgentExecutionError: For session-level failures including
                ``turn/completed`` with ``status: "systemError"``.
        """
        if self._cancelled:
            raise AgentCancelledError(AgentRunnerType.CODEX_SERVER.value)

        start_ms = int(time.monotonic() * 1000)
        is_verifier = on_grade is not None
        full_prompt = build_codex_server_prompt(context, is_verifier=is_verifier)

        # Use injected transport (test) or spawn a real subprocess.
        transport: JsonRpcTransport | None = self._transport
        spawned = False
        tmp_codex_home: Path | None = None

        try:
            if transport is None:
                transport, spawned, tmp_codex_home = await self._spawn_transport(
                    context, on_agent_metadata
                )

            output_lines: list[str] = []
            notification_buffer: list[dict[str, Any]] = []
            next_id = 1

            async def _send_and_wait(method: str, params: dict[str, Any]) -> dict[str, Any]:
                """Send a request and wait for the matching response, buffering notifications."""
                nonlocal next_id
                req_id = next_id
                next_id += 1
                await transport.send(build_jsonrpc_request(req_id, method, params))
                while True:
                    msg = await transport.recv()
                    if msg.get("id") == req_id:
                        return msg
                    # Buffer any notifications that arrive while we wait.
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

            # --- Step 1: Authenticate (local only, if API key is available) ---
            if self._api_key:
                login_resp = await _send_and_wait(
                    "account/login/start",
                    {"type": "apiKey", "apiKey": self._api_key},
                )
                if "error" in login_resp:
                    logger.warning(
                        "CodexServerAgent: account/login/start returned error — %s",
                        login_resp.get("error"),
                    )

            # --- Step 2: Create thread ---
            model = self._model
            # Map restrictions to the thread-level sandbox mode.
            # The sandbox field in thread/start controls the macOS seatbelt
            # applied to shell commands executed by codex on behalf of the model.
            # It is NOT controlled by CLI flags (those only affect `codex exec`).
            sandbox_mode: str | None
            if self._restrictions == "none":
                sandbox_mode = "danger-full-access"
            elif self._restrictions == "no-network":
                sandbox_mode = "workspace-write"
            else:
                # "use-local": let the config.toml (already copied) decide.
                sandbox_mode = None
            thread_params: dict[str, Any] = {
                "cwd": context.working_dir,
                "approvalPolicy": "never",
                "dynamicTools": build_dynamic_tool_specs(
                    is_verifier=is_verifier,
                    context=context,
                ),
            }
            if sandbox_mode is not None:
                thread_params["sandbox"] = sandbox_mode
            if model:
                thread_params["model"] = model

            # Add external MCP servers to thread params
            if context.mcp_servers:
                mcp_configs: list[dict[str, Any]] = []
                for mcp in context.mcp_servers:
                    mcp_entry: dict[str, Any] = {"name": mcp.name}
                    if mcp.url:
                        mcp_entry["url"] = mcp.url
                    elif mcp.command:
                        mcp_entry["command"] = mcp.command
                        if mcp.args:
                            mcp_entry["args"] = mcp.args
                    if mcp.env:
                        mcp_entry["env"] = mcp.env
                    mcp_configs.append(mcp_entry)
                thread_params["mcpServers"] = mcp_configs

            thread_resp = await _send_and_wait("thread/start", thread_params)
            if "error" in thread_resp:
                raise AgentExecutionError(
                    AgentRunnerType.CODEX_SERVER.value,
                    "thread/start failed",
                )

            thread_id: str = thread_resp["result"]["thread"]["id"]
            self._active_thread_id = thread_id
            logger.debug("CodexServerAgent: thread created — thread_id=%s", thread_id)

            # --- Step 3: Start turn ---
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
                    AgentRunnerType.CODEX_SERVER.value,
                    "turn/start failed",
                )

            logger.debug(
                "CodexServerAgent: turn started — run=%s task=%s phase=%s",
                context.run_id,
                context.task_id,
                "verifier" if is_verifier else "builder",
            )

            # --- Step 4: Process notification stream ---
            done = False
            num_actions = 0
            turn_usage: dict[str, int] = {}

            async def _dispatch_tool_call(tool_msg: dict[str, Any]) -> None:
                """Respond to an ``item/tool/call`` server request and fire callbacks."""
                nonlocal num_actions
                tool_result = extract_dynamic_tool_call(tool_msg)
                if tool_result is None:
                    return
                req_id, tool_name, tool_args = tool_result
                num_actions += 1
                try:
                    await route_tool_call(
                        tool_name,
                        tool_args,
                        on_checklist_update,
                        on_submit,
                        on_grade=on_grade,
                        on_complete_recovery=on_complete_recovery,
                        agent_label="CodexServerAgent",
                    )
                    await transport.send(build_dynamic_tool_call_response(req_id, success=True))
                except ValueError:
                    # Disallowed tool — respond with failure to unblock the server.
                    await transport.send(build_dynamic_tool_call_response(req_id, success=False))
                except Exception as cb_exc:
                    # Callback raised an unexpected error (GateBlockedError, DB error, etc.).
                    # Send failure response to unblock the codex server, then re-raise
                    # so the session terminates with a meaningful error.
                    logger.warning(
                        "CodexServerAgent: callback error for tool %r: %s: %s",
                        tool_name,
                        type(cb_exc).__name__,
                        cb_exc,
                    )
                    await transport.send(build_dynamic_tool_call_response(req_id, success=False))
                    raise

            async def _process_msg(msg: dict[str, Any]) -> bool:
                """Process one message; return True if it is a terminal notification."""
                nonlocal num_actions, turn_usage
                # Dynamic tool call request from the server (has id AND method).
                if msg.get("method") == "item/tool/call" and "id" in msg:
                    await _dispatch_tool_call(msg)
                    return False
                # Skip stray response messages (no method field).
                if "id" in msg and "method" not in msg:
                    return False
                # Count item/completed notifications as actions (these represent
                # the agent's own tool invocations, e.g. shell commands, file edits).
                if msg.get("method") == "item/completed":
                    item = msg.get("params", {}).get("item", {})
                    if item.get("type") not in ("agentMessage", None):
                        num_actions += 1
                terminal, usage = await self._handle_notification(
                    msg,
                    output_lines,
                    on_output,
                    on_checklist_update,
                    on_submit,
                    on_grade,
                    on_complete_recovery,
                )
                if terminal:
                    turn_usage = usage
                return terminal

            # First drain any notifications buffered during the request-response phase.
            for msg in notification_buffer:
                if self._cancelled:
                    raise AgentCancelledError(AgentRunnerType.CODEX_SERVER.value)
                if await _process_msg(msg):
                    done = True
                    break

            # Then continue reading live notifications until terminal.
            while not done and not self._cancelled:
                msg = await transport.recv()
                if await _process_msg(msg):
                    done = True

            if self._cancelled:
                raise AgentCancelledError(AgentRunnerType.CODEX_SERVER.value)

        except (
            AgentCancelledError,
            AgentNotAvailableError,
            AgentTimeoutError,
            AgentExecutionError,
            GateBlockedError,
        ):
            raise
        except asyncio.CancelledError:
            raise AgentCancelledError(AgentRunnerType.CODEX_SERVER.value)
        except OSError as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            logger.debug(
                "CodexServerAgent: OS error after %dms — %s", duration_ms, exc, exc_info=True
            )
            raise AgentNotAvailableError(
                AgentRunnerType.CODEX_SERVER.value,
                "Transport error communicating with codex app-server",
            ) from exc
        except EOFError as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            raise AgentNotAvailableError(
                AgentRunnerType.CODEX_SERVER.value,
                "codex app-server process terminated unexpectedly",
            ) from exc
        except Exception as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            logger.warning(
                "CodexServerAgent: session error after %dms — %s: %s",
                duration_ms,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            raise AgentExecutionError(
                AgentRunnerType.CODEX_SERVER.value,
                f"Session failed after {duration_ms}ms: {type(exc).__name__}: {exc}",
            ) from exc
        finally:
            # Only close the transport if we spawned it (not injected by tests).
            if spawned and transport is not None:
                try:
                    await transport.close()
                except Exception:
                    pass
            # Clean up the isolated CODEX_HOME temp directory.
            if tmp_codex_home is not None:
                shutil.rmtree(tmp_codex_home, ignore_errors=True)

        duration_ms = int(time.monotonic() * 1000) - start_ms
        return build_execution_result(
            output_lines,
            duration_ms,
            tokens_read=turn_usage.get("tokens_read", 0),
            tokens_write=turn_usage.get("tokens_write", 0),
            tokens_cache=turn_usage.get("tokens_cache", 0),
            num_actions=num_actions,
        )

    async def cancel(self) -> None:
        """Request cancellation of the active Codex server session.

        Sets the cancellation flag.  If a turn is active, sends
        ``turn/interrupt`` as a best-effort signal to the server.
        Cancels any in-flight ``_session_task``.  Safe to call multiple times.
        """
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
                pass  # Best-effort — cancellation flag is the primary mechanism.
        logger.info("CodexServerAgent: cancelled")

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
            agent_label="CodexServerAgent",
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _spawn_transport(
        self,
        context: ExecutionContext,
        on_agent_metadata: AgentMetadataCallback | None,
    ) -> tuple[RealStdioTransport, bool, Path]:
        """Spawn a ``codex app-server`` subprocess and return its transport.

        Behaviour is controlled by ``self._restrictions``:

        - ``"no-network"`` (default): Force workspace-write sandbox with network
          disabled. Uses CLI ``--sandbox workspace-write`` and a config override
          ``sandbox_workspace_write.network_access=false``. Does not load the
          user's config.toml (only auth.json is copied).
        - ``"none"``: Do not override sandbox/network; rely on Codex defaults
          and any user config present in ``~/.codex``. We still isolate
          ``CODEX_HOME`` and copy only auth.json to avoid touching the real
          profile on disk.
        - ``"use-local"``: Copy both auth.json and config.toml from the user's
          ``~/.codex`` into the temp CODEX_HOME and launch app-server without
          sandbox/approval overrides so that local configuration fully controls
          behaviour. This may result in read-only workspaces or enabled
          network access, depending on the user's own settings.
        """
        # Create an isolated CODEX_HOME so that the subprocess cannot overwrite
        # the user's ~/.codex/auth.json.  Per codex source code, auth.json is only
        # written when account/login/start is called — but using a private CODEX_HOME
        # means any writes go to a throwaway temp directory, not the user's profile.
        #
        # We copy the user's auth.json into the temp dir so the subprocess starts
        # with the same credentials (ChatGPT subscription tokens). Config
        # propagation is controlled by self._restrictions.
        user_codex_home = Path.home() / ".codex"
        tmp_codex_home = Path(tempfile.mkdtemp(prefix="orchestrator-codex-"))
        if (user_codex_home / "auth.json").exists():
            shutil.copy2(user_codex_home / "auth.json", tmp_codex_home / "auth.json")

        # Optionally propagate the user's config.toml when restrictions is "use-local".
        if self._restrictions == "use-local" and (user_codex_home / "config.toml").exists():
            shutil.copy2(user_codex_home / "config.toml", tmp_codex_home / "config.toml")

        # Strip OPENAI_API_KEY and set isolated CODEX_HOME.  Also run from the
        # worktree (not the orchestrator cwd) to avoid loading a .env file.
        clean_env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        clean_env["CODEX_HOME"] = str(tmp_codex_home)

        # Build argv.  The `--sandbox` and `--ask-for-approval` CLI flags only
        # apply to `codex exec` / interactive mode.  For `codex app-server` the
        # sandbox is controlled per-thread via the `sandbox` field in
        # thread/start (see Step 2 below).  No extra CLI flags are needed here.
        argv: list[str] = ["codex", "app-server"]

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=clean_env,
                cwd=context.working_dir,
                limit=1024 * 1024,  # 1MB readline buffer for large JSON-RPC messages
            )
        except FileNotFoundError as exc:
            shutil.rmtree(tmp_codex_home, ignore_errors=True)
            # create_subprocess_exec raises FileNotFoundError for BOTH
            # a missing executable AND a missing cwd directory.
            # Distinguish between the two to give a useful error message.
            if shutil.which("codex") is None:
                raise AgentNotAvailableError(
                    AgentRunnerType.CODEX_SERVER.value,
                    "codex executable not found; install Codex CLI to use this agent",
                ) from exc
            raise AgentExecutionError(
                agent_type=AgentRunnerType.CODEX_SERVER.value,
                message=f"Working directory does not exist: {context.working_dir}",
            ) from exc
        except OSError as exc:
            shutil.rmtree(tmp_codex_home, ignore_errors=True)
            raise AgentNotAvailableError(
                AgentRunnerType.CODEX_SERVER.value,
                "Failed to spawn codex app-server process",
            ) from exc

        if on_agent_metadata is not None:
            await on_agent_metadata({"pid": proc.pid})

        logger.debug(
            "CodexServerAgent: spawned codex app-server — pid=%d, codex_home=%s",
            proc.pid,
            tmp_codex_home,
        )
        return RealStdioTransport(proc), True, tmp_codex_home

    async def _handle_notification(
        self,
        msg: dict[str, Any],
        output_lines: list[str],
        on_output: LogLineCallback | None,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_grade: GradeCallback | None,
        on_complete_recovery: CompleteRecoveryCallback | None = None,
    ) -> tuple[bool, dict[str, int]]:
        """Process one JSON-RPC notification.

        Returns:
            ``(True, usage)`` if this is a terminal notification
            (``turn/completed``), where *usage* is the token usage dict
            extracted from the turn payload.
            ``(False, {})`` otherwise.

        Raises:
            AgentCancelledError: When ``turn/completed`` has
                ``status: "interrupted"``.
            AgentExecutionError: When ``turn/completed`` has
                ``status: "systemError"``.
        """
        # Check for terminal state first.
        terminal, status = is_terminal_notification(msg)
        if terminal:
            if status == "interrupted":
                raise AgentCancelledError(AgentRunnerType.CODEX_SERVER.value)
            if status in ("systemError", "failed"):
                raise AgentExecutionError(
                    AgentRunnerType.CODEX_SERVER.value,
                    f"Codex session ended with status: {status}",
                )
            # "completed" — normal success; extract usage from the turn payload.
            usage = extract_turn_usage(msg)
            return (True, usage)

        # Route tool calls (fire on item/started so the orchestrator is notified promptly).
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
                    on_complete_recovery=on_complete_recovery,
                    agent_label="CodexServerAgent",
                )
            except ValueError:
                pass  # Disallowed tool — already logged by enforce_tool_allowlist.

        # Accumulate agent message text.
        delta = extract_agent_message_delta(msg)
        if delta:
            output_lines.append(delta)
            if on_output is not None:
                await on_output([delta])

        return (False, {})
