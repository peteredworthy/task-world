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
import hashlib
import json
import logging
import os
import re
import select
import shutil
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from orchestrator.git import (
    WorktreeCommitError,
    get_agent_cache_write_paths,
    get_worktree_git_write_paths,
)
from orchestrator.runners.errors import SubmissionRejectedError
from orchestrator.runners.agents.codex.common import (
    CODEX_SERVER_TOOL_ALLOWLIST,
    JsonRpcTransport,
    build_codex_server_prompt,
    build_dynamic_tool_call_response,
    build_dynamic_tool_specs,
    build_execution_result,
    build_jsonrpc_request,
    extract_agent_message_delta,
    extract_item_activity_line,
    extract_turn_error,
    extract_turn_finish_reasons,
    extract_dynamic_tool_call,
    extract_tool_call_from_notification,
    extract_token_usage_update,
    extract_turn_usage,
    is_terminal_notification,
    normalize_codex_metrics,
    normalize_codex_output_lines,
    route_tool_call,
)
from orchestrator.runners.agents.codex.parser import CodexStreamParser
from orchestrator.runners.environment import build_agent_subprocess_env
from orchestrator.runners.errors import (
    AgentCancelledError,
    AgentExecutionError,
    SubmissionRepairExhaustedError,
    AgentNotAvailableError,
    AgentTimeoutError,
)
from orchestrator.runners.mcp_scope import (
    resolve_mcp_server_cwd,
    scope_mcp_servers_to_available_tools,
)
from orchestrator.runners.submission import (
    is_decision_submission,
)
from orchestrator.workflow import GateBlockedError, InvalidTransitionError
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
    RunnerRuntimeObservationCapability,
    QuotaBucket,
    SubmitCallback,
    SubmissionInvocation,
    submission_rejection_requires_stop,
)
from orchestrator.config.enums import AgentRunnerType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CodexCommandExecutionReceipt:
    """Completed shell command observed on one active Codex turn."""

    thread_id: str
    turn_id: str
    item_id: str
    command: str
    cwd: str
    exit_code: int
    status: str
    output_sha256: str
    output_bytes: int


CommandCompletionObserver = Callable[[CodexCommandExecutionReceipt], Awaitable[None]]


_MAX_DYNAMIC_TOOL_RECEIPT_PAYLOAD_BYTES = 96 * 1024


class CodexDynamicToolReceipt(BaseModel):
    """Bounded, immutable evidence for one dynamic-tool request/response pair.

    ``request`` and ``response`` contain canonical JSON strings when their
    individual UTF-8 payload is at most 96 KiB.  Once a payload exceeds that
    boundary, the corresponding string is omitted while its size and SHA-256
    remain available and ``request_response_complete`` is false.  The
    app-server transport exposes parsed JSON objects, so the canonical JSON
    preserves the received data but cannot preserve wire-level whitespace. If
    upstream delivers a non-JSON value or a non-integer request id, no receipt
    is synthesized because the wire arguments cannot be recovered safely.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    thread_id: str
    turn_id: str
    request_id: int
    request_sha256: str
    response_sha256: str
    request_size_bytes: int = Field(ge=0)
    response_size_bytes: int = Field(ge=0)
    request_response_complete: bool
    request: str | None = None
    response: str | None = None

    @property
    def incomplete(self) -> bool:
        """Whether either payload was omitted because it exceeded the bound."""
        return not self.request_response_complete


DynamicToolReceiptObserver = Callable[[CodexDynamicToolReceipt], Awaitable[None]]


class _DynamicToolReceiptObserverError(RuntimeError):
    """Internal boundary preserving fail-closed observer errors."""


def _canonical_json_bytes(value: object) -> bytes:
    """Serialize parsed transport JSON deterministically for receipt hashing."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _dynamic_tool_receipt(
    request_bytes: bytes,
    response: dict[str, Any],
    *,
    thread_id: str,
    turn_id: str,
    request_id: int,
) -> CodexDynamicToolReceipt:
    """Build a truthful bounded receipt without truncating either payload."""
    response_bytes = _canonical_json_bytes(response)
    request_complete = len(request_bytes) <= _MAX_DYNAMIC_TOOL_RECEIPT_PAYLOAD_BYTES
    response_complete = len(response_bytes) <= _MAX_DYNAMIC_TOOL_RECEIPT_PAYLOAD_BYTES
    return CodexDynamicToolReceipt(
        thread_id=thread_id,
        turn_id=turn_id,
        request_id=request_id,
        request_sha256=f"sha256:{hashlib.sha256(request_bytes).hexdigest()}",
        response_sha256=f"sha256:{hashlib.sha256(response_bytes).hexdigest()}",
        request_size_bytes=len(request_bytes),
        response_size_bytes=len(response_bytes),
        request_response_complete=request_complete and response_complete,
        request=(request_bytes.decode("utf-8") if request_complete else None),
        response=(response_bytes.decode("utf-8") if response_complete else None),
    )


def _command_execution_receipt(
    message: dict[str, Any],
    *,
    thread_id: str,
    turn_id: str,
) -> CodexCommandExecutionReceipt | None:
    """Extract a command receipt only when the notification binds to this turn."""

    if message.get("method") != "item/completed":
        return None
    params_raw = message.get("params")
    if not isinstance(params_raw, dict):
        return None
    params = cast(dict[str, Any], params_raw)
    if params.get("threadId") != thread_id or params.get("turnId") != turn_id:
        return None
    item_raw = params.get("item")
    if not isinstance(item_raw, dict):
        return None
    item = cast(dict[str, Any], item_raw)
    item_type = str(item.get("type", "")).replace("_", "").lower()
    if item_type != "commandexecution":
        return None
    item_id = item.get("id")
    command = item.get("command")
    cwd = item.get("cwd")
    exit_code = item.get("exitCode", item.get("exit_code"))
    status = item.get("status")
    output = item.get("aggregatedOutput", item.get("aggregated_output"))
    if not (
        isinstance(item_id, str)
        and item_id
        and isinstance(command, str)
        and command
        and len(command) <= 4096
        and isinstance(cwd, str)
        and cwd
        and len(cwd) <= 4096
        and isinstance(exit_code, int)
        and not isinstance(exit_code, bool)
        and isinstance(status, str)
        and status in {"completed", "failed"}
        and isinstance(output, str)
    ):
        return None
    return CodexCommandExecutionReceipt(
        thread_id=thread_id,
        turn_id=turn_id,
        item_id=item_id,
        command=command,
        cwd=cwd,
        exit_code=exit_code,
        status=status,
        output_sha256=hashlib.sha256(output.encode()).hexdigest(),
        output_bytes=len(output.encode()),
    )


_RECV_CHUNK_SIZE = 64 * 1024  # 64KB per read from process stdout.
_MAX_JSON_RPC_LINE_BYTES = 16 * 1024 * 1024  # 16MB soft cap before dropping an oversized line.
_MAX_STDERR_TAIL_CHARS = 16 * 1024


def _sanitize_transport_diagnostic(text: str, tmp_codex_home: Path | None) -> str:
    """Keep a useful app-server stderr tail without exposing credentials or homes."""
    if tmp_codex_home is not None:
        text = text.replace(str(tmp_codex_home), "<CODEX_HOME>")
    # App-server diagnostics occasionally echo their environment/config.  A
    # tail must never turn the temporary auth profile or a provider key into a
    # persisted run error or journal entry.
    text = re.sub(
        r"(?i)\b(authorization|api[_-]?key|token|password)\b(\s*[:=]\s*)([^\s,;]+)",
        r"\1\2<redacted>",
        text,
    )
    text = re.sub(r"/[^\s'\"]*orchestrator-codex-[^\s/'\"]+(?:/[^\s'\"]*)?", "<CODEX_HOME>", text)
    return text.replace("\x00", "").strip()


def _is_submit_callback_rejection(tool_name: str, exc: Exception) -> bool:
    return tool_name == "submit" and isinstance(exc, SubmissionRejectedError)


def _transport_failure_diagnostic(
    transport: JsonRpcTransport | None,
    thread_id: str | None,
    tmp_codex_home: Path | None,
) -> str:
    """Return diagnostic context for a real app-server transport failure."""
    if isinstance(transport, RealStdioTransport):
        return transport.diagnostic_summary(thread_id, tmp_codex_home)
    return f"thread_id={thread_id or '<none>'}; transport=injected"


def _build_workspace_write_config_toml(
    writable_roots: list[Path],
    *,
    network_access: bool,
) -> str:
    """Build a minimal Codex ``config.toml`` for workspace-write sessions."""
    lines = ["[sandbox_workspace_write]"]
    if writable_roots:
        roots = ", ".join(json.dumps(str(path)) for path in writable_roots)
        lines.append(f"writable_roots = [{roots}]")
    lines.append(f"network_access = {'true' if network_access else 'false'}")
    lines.append("")
    return "\n".join(lines)


def build_codex_app_server_launch(
    local_provider: str,
    api_base_url: str | None,
) -> tuple[list[str], dict[str, str]]:
    """Build the app-server command and provider-specific environment."""
    argv = ["codex", "app-server"]
    if local_provider != "lmstudio":
        return argv, {}

    orchestrator_base = (api_base_url or "http://localhost:8000").rstrip("/")
    # The app-server accepts regular configuration overrides. Selecting its
    # built-in LM Studio provider here preserves dynamic tool injection and
    # callback routing in this existing runner.
    return (
        [*argv, "-c", 'model_provider="lmstudio"'],
        {"CODEX_OSS_BASE_URL": (f"{orchestrator_base}/api/agent-runners/lmstudio-codex")},
    )


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
        self._buffer = bytearray()
        self._stderr_tail = ""
        self._last_rpc_boundary = "spawned"
        stderr = getattr(proc, "stderr", None)
        self._stderr_task: asyncio.Task[None] | None = (
            asyncio.create_task(self._drain_stderr(stderr)) if stderr is not None else None
        )

    async def _drain_stderr(self, stderr: Any) -> None:
        """Drain stderr continuously so diagnostics cannot deadlock the server."""
        try:
            while chunk := await stderr.read(_RECV_CHUNK_SIZE):
                self._stderr_tail = (self._stderr_tail + chunk.decode(errors="replace"))[
                    -_MAX_STDERR_TAIL_CHARS:
                ]
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("CodexServerAgent: stderr drainer stopped: %s", exc)

    def record_rpc_boundary(self, method: str, request_id: int | str | None = None) -> None:
        """Record the last safe protocol boundary, never request params."""
        suffix = f" id={request_id}" if request_id is not None else ""
        self._last_rpc_boundary = f"{method}{suffix}"

    def diagnostic_summary(self, thread_id: str | None, tmp_codex_home: Path | None) -> str:
        """Return a bounded, scrubbed transport state summary for a failure."""
        exit_code = self._proc.returncode
        state = str(exit_code) if exit_code is not None else "running"
        tail = _sanitize_transport_diagnostic(self._stderr_tail, tmp_codex_home)
        tail_summary = tail[-_MAX_STDERR_TAIL_CHARS:] if tail else "<empty>"
        return (
            f"pid={self._proc.pid}; exit_code={state}; thread_id={thread_id or '<none>'}; "
            f"last_rpc={self._last_rpc_boundary}; stderr_tail={tail_summary}"
        )

    async def send(self, message: dict[str, Any]) -> None:
        """Write one JSON-RPC message to the subprocess stdin."""
        assert self._proc.stdin is not None
        method = message.get("method")
        if isinstance(method, str):
            self.record_rpc_boundary(method, message.get("id"))
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
            newline = self._buffer.find(b"\n")
            if newline != -1:
                line_bytes = bytes(self._buffer[:newline])
                del self._buffer[: newline + 1]
                line = line_bytes.decode(errors="replace").strip()
                if not line:
                    continue
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("CodexServerAgent: skipping non-JSON line: %r", line[:120])

            chunk = await self._proc.stdout.read(_RECV_CHUNK_SIZE)
            if not chunk:
                if self._stderr_task is not None:
                    try:
                        await asyncio.wait_for(asyncio.shield(self._stderr_task), timeout=0.2)
                    except TimeoutError:
                        pass
                if self._buffer:
                    line = self._buffer.decode(errors="replace").strip()
                    self._buffer.clear()
                    if line:
                        try:
                            return json.loads(line)
                        except json.JSONDecodeError:
                            logger.debug(
                                "CodexServerAgent: skipping non-JSON final line: %r",
                                line[:120],
                            )
                    raise EOFError(
                        "codex app-server process stdout closed before JSON line completion"
                    )

                raise EOFError("codex app-server process stdout closed unexpectedly")

            self._buffer.extend(chunk)

            if len(self._buffer) > _MAX_JSON_RPC_LINE_BYTES:
                drop_at = self._buffer.find(b"\n")
                if drop_at == -1:
                    logger.warning(
                        "CodexServerAgent: oversized JSON-RPC line (%d bytes) with no delimiter; discarding",
                        len(self._buffer),
                    )
                    self._buffer.clear()
                else:
                    logger.warning(
                        "CodexServerAgent: oversized JSON-RPC line (%d bytes); discarding until newline",
                        len(self._buffer),
                    )
                    del self._buffer[: drop_at + 1]

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
        if self._stderr_task is not None:
            try:
                await asyncio.wait_for(self._stderr_task, timeout=1)
            except TimeoutError:
                self._stderr_task.cancel()
            except (asyncio.CancelledError, Exception):
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

    @staticmethod
    def _normalize_restrictions(restrictions: str) -> str:
        """Map legacy restriction names to the current canonical values."""
        if restrictions == "no-network":
            return "managed"
        return restrictions

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        restrictions: str = "managed",
        reasoning_effort: str = "high",
        local_provider: str = "openai",
        *,
        _transport: JsonRpcTransport | None = None,
        _environ: dict[str, str] | None = None,
        command_completion_observer: CommandCompletionObserver | None = None,
        dynamic_tool_receipt_observer: DynamicToolReceiptObserver | None = None,
    ) -> None:
        self._model = model
        # Reasoning effort for Codex model turns. Falls back to "medium" for any
        # value outside the supported set.
        self._reasoning_effort = (
            reasoning_effort if reasoning_effort in ("low", "medium", "high") else "medium"
        )
        # restrictions controls how aggressively we override Codex sandbox/config behaviour.
        # Supported values:
        # - "none":     Do not override sandbox/network; honour Codex defaults and local config.
        # - "managed":  Use orchestrator-managed workspace-write roots and network policy.
        # - "use-local": Delegate entirely to the user's local Codex config.toml, including sandbox.
        self._restrictions = self._normalize_restrictions(restrictions)
        self._local_provider = (
            local_provider if local_provider in {"openai", "lmstudio"} else "openai"
        )
        # Resolve API key: explicit arg only (or test-injected _environ).
        # Do NOT fall back to OPENAI_API_KEY from os.environ — doing so causes
        # execute() to call account/login/start with apiKey, which unconditionally
        # overwrites ~/.codex/auth.json and clobbers any ChatGPT subscription auth.
        # _environ is used in tests to inject a controlled environment.
        env = _environ if _environ is not None else {}
        self._api_key: str | None = api_key or env.get("OPENAI_API_KEY")
        self._cancelled = False
        self._transport = _transport
        self._command_completion_observer = command_completion_observer
        self._dynamic_tool_receipt_observer = dynamic_tool_receipt_observer
        self._active_thread_id: str | None = None
        self._session_task: asyncio.Task[object] | None = None
        self._terminal_answer_requested = False
        self._terminal_answer_interrupt_sent = False
        self._terminal_answer_completed_observed = False
        self._terminal_answer_stop_deadline: float | None = None

    # ------------------------------------------------------------------
    # Agent protocol
    # ------------------------------------------------------------------

    @property
    def info(self) -> AgentRunnerInfo:
        """Return static metadata for this agent instance."""
        return AgentRunnerInfo(
            agent_runner_type=AgentRunnerType.CODEX_SERVER,
            name="Codex Server",
            version=None,
            runtime_observation=RunnerRuntimeObservationCapability(
                mode=("host_process" if self._transport is None else "unsupported"),
                reason=(
                    "Codex runner reports the exact spawned app-server PID at startup"
                    if self._transport is None
                    else "injected Codex transport does not expose a host process identity"
                ),
            ),
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
                ready, _, _ = select.select([proc.stdout], [], [], 15.0)
                if not ready:
                    break
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
        self._terminal_answer_requested = False
        self._terminal_answer_interrupt_sent = False
        self._terminal_answer_completed_observed = False
        self._terminal_answer_stop_deadline = None

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
            parser = CodexStreamParser()
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
                        parser.parse_jsonrpc_message(msg)

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
            elif self._restrictions == "managed":
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
            scoped_mcp_servers = scope_mcp_servers_to_available_tools(
                context.mcp_servers,
                context.available_tools,
                phase="verifying" if is_verifier else "building",
            )
            if scoped_mcp_servers:
                mcp_configs: list[dict[str, Any]] = []
                for mcp in scoped_mcp_servers:
                    mcp_entry: dict[str, Any] = {"name": mcp.name}
                    if mcp.url:
                        mcp_entry["url"] = mcp.url
                    elif mcp.command:
                        mcp_entry["command"] = mcp.command
                        if mcp.args:
                            mcp_entry["args"] = mcp.args
                        resolved_cwd = resolve_mcp_server_cwd(mcp, context.working_dir)
                        if resolved_cwd:
                            mcp_entry["cwd"] = resolved_cwd
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
            logger.info(
                "CodexServerAgent: thread started — run=%s task=%s thread_id=%s",
                context.run_id,
                context.task_id,
                thread_id,
            )

            # --- Step 3: Start turn ---
            turn_params: dict[str, Any] = {
                "threadId": thread_id,
                "input": [{"type": "text", "text": full_prompt}],
                "cwd": context.working_dir,
                "approvalPolicy": "never",
                "effort": self._reasoning_effort,
            }
            if model:
                turn_params["model"] = model

            turn_resp = await _send_and_wait("turn/start", turn_params)
            if "error" in turn_resp:
                raise AgentExecutionError(
                    AgentRunnerType.CODEX_SERVER.value,
                    "turn/start failed",
                )

            turn_id = str(turn_resp.get("result", {}).get("turn", {}).get("id", ""))
            if not turn_id:
                raise AgentExecutionError(
                    AgentRunnerType.CODEX_SERVER.value,
                    "turn/start response did not include a turn id",
                )

            logger.info(
                "CodexServerAgent: turn started — run=%s task=%s phase=%s thread_id=%s",
                context.run_id,
                context.task_id,
                "verifier" if is_verifier else "builder",
                thread_id,
            )

            # --- Step 4: Process notification stream ---
            done = False
            num_actions = 0
            submit_rejection_causes: list[str] = []
            turn_usage: dict[str, int] = {}
            finish_reasons: list[str] = []

            async def _dispatch_tool_call(tool_msg: dict[str, Any]) -> None:
                """Respond to an ``item/tool/call`` server request and fire callbacks."""
                nonlocal num_actions
                tool_result = extract_dynamic_tool_call(tool_msg)
                if tool_result is None:
                    return
                req_id, tool_name, tool_args = tool_result
                num_actions += 1
                # Freeze the parsed request before routing. Controller
                # callbacks may inspect or transform nested values; receipts
                # must describe what arrived at this transport boundary.
                request_bytes = _canonical_json_bytes(tool_msg)
                parser.parse_jsonrpc_message(tool_msg)

                async def _send_dynamic_tool_response(
                    *,
                    success: bool,
                    output: str | None = None,
                    best_effort: bool = False,
                ) -> None:
                    """Observe a response pair before writing it to app-server."""
                    response = build_dynamic_tool_call_response(
                        req_id,
                        success=success,
                        output=output,
                    )
                    if self._dynamic_tool_receipt_observer is not None:
                        # An opted-in evidence probe fails closed if it cannot
                        # record the exact pair. Do not log its exception here;
                        # the outer session boundary supplies a safe diagnostic
                        # and no response is sent after the failure.
                        try:
                            receipt = _dynamic_tool_receipt(
                                request_bytes,
                                response,
                                thread_id=thread_id,
                                turn_id=turn_id,
                                request_id=req_id,
                            )
                            await self._dynamic_tool_receipt_observer(receipt)
                        except Exception as exc:
                            # Keep receipt construction/observer failures out of
                            # routing handlers: a ValueError from the probe is not
                            # a tool rejection.
                            raise _DynamicToolReceiptObserverError(
                                "dynamic tool receipt observer failed"
                            ) from exc
                    try:
                        await transport.send(response)
                    except Exception:
                        if not best_effort:
                            raise
                        logger.warning(
                            "CodexServerAgent: dynamic tool response delivery failed "
                            "after terminal answer staging; continuing owned stop"
                        )

                terminal_answer_staged = (
                    self._terminal_answer_requested and self._terminal_answer_interrupt_sent
                )
                if terminal_answer_staged:
                    feedback = "tool call refused after terminal answer staging"
                    parser.record_dynamic_tool_result(str(req_id), success=False, output=feedback)
                    await _send_dynamic_tool_response(
                        success=False,
                        output=feedback,
                        best_effort=True,
                    )
                    return

                decision_submission = is_decision_submission(context.submission_contract)
                try:
                    routed_submit_callback: SubmitCallback = on_submit
                    if tool_name == "submit" and decision_submission:
                        invocation = SubmissionInvocation(
                            execution_id=context.execution_id or context.task_id,
                            answer_attempt_id=(
                                "answer-attempt-"
                                + hashlib.sha256(
                                    f"{context.run_id}\x00{thread_id}\x00{turn_id}\x00{req_id}".encode()
                                ).hexdigest()[:24]
                            ),
                            transport_channel="codex_dynamic_tool",
                            transport_session_id=f"{thread_id}:{turn_id}",
                            transport_request_id=str(req_id),
                            arguments=tool_args,
                        )

                        async def decision_submit_callback(
                            _args: dict[str, Any] | None = None,
                        ) -> Any:
                            typed = cast(Any, on_submit)
                            return await typed(invocation)

                        routed_submit_callback = decision_submit_callback

                    feedback = await route_tool_call(
                        tool_name,
                        tool_args,
                        on_checklist_update,
                        routed_submit_callback,
                        on_submit_graph_patch=context.graph_patch_callback,
                        on_grade=on_grade,
                        on_complete_recovery=on_complete_recovery,
                        agent_label="CodexServerAgent",
                    )
                    parser.record_dynamic_tool_result(str(req_id), success=True)
                    await _send_dynamic_tool_response(
                        success=True,
                        output=feedback or None,
                        best_effort=(
                            tool_name == "submit"
                            and self._terminal_answer_requested
                            and self._terminal_answer_interrupt_sent
                        ),
                    )
                except _DynamicToolReceiptObserverError:
                    raise
                except ValueError as exc:
                    if _is_submit_callback_rejection(tool_name, exc):
                        submit_rejection_causes.append(str(exc))
                        parser.record_dynamic_tool_result(
                            str(req_id), success=False, output=str(exc)
                        )
                        await _send_dynamic_tool_response(success=False, output=str(exc))
                        if isinstance(
                            exc, SubmissionRejectedError
                        ) and submission_rejection_requires_stop(exc.acknowledgement):
                            raise
                        rejection_budget = 2 if decision_submission else 3
                        if len(submit_rejection_causes) >= rejection_budget:
                            raise SubmissionRepairExhaustedError(
                                AgentRunnerType.CODEX_SERVER.value,
                                submit_rejection_causes[0],
                                submit_rejection_causes[-1],
                                rejection_budget,
                            )
                        logger.warning(
                            "CodexServerAgent: submit rejected with actionable feedback; "
                            "continuing the same session: %s",
                            exc,
                        )
                        return
                    # Disallowed tool — respond with failure to unblock the server.
                    parser.record_dynamic_tool_result(str(req_id), success=False)
                    await _send_dynamic_tool_response(success=False, output=str(exc))
                except InvalidTransitionError as cb_exc:
                    # Agent called a tool that is invalid in the current task state
                    # (e.g. update_checklist during the verifying phase).  Inform the
                    # agent via a failure response and continue — this must not crash
                    # the session.
                    logger.warning(
                        "CodexServerAgent: tool %r rejected (invalid state): %s — continuing",
                        tool_name,
                        cb_exc,
                    )
                    parser.record_dynamic_tool_result(
                        str(req_id), success=False, output=str(cb_exc)
                    )
                    await _send_dynamic_tool_response(success=False, output=str(cb_exc))
                except WorktreeCommitError as commit_exc:
                    # The agent submitted but the pre-submit commit gate (ruff /
                    # pyright / pytest pre-commit hooks) failed.  This is a
                    # builder-fixable rejection, not an infra failure: feed the
                    # hook output back to the agent as a failed tool result and
                    # CONTINUE the session so it can fix and resubmit — mirroring
                    # the HTTP /submit endpoint's 409 reject-with-feedback. The
                    # run stays ACTIVE; only a RunWorktreeCommitFailed event was
                    # recorded by the service.  This must NOT crash the session.
                    feedback = (
                        "Submission rejected: pre-submit checks failed. Fix the "
                        "following and call submit again:\n" + str(commit_exc)
                    )
                    logger.warning(
                        "CodexServerAgent: submission rejected by commit gate for "
                        "tool %r — feeding back to agent and continuing: %s",
                        tool_name,
                        commit_exc,
                    )
                    parser.record_dynamic_tool_result(str(req_id), success=False, output=feedback)
                    await _send_dynamic_tool_response(success=False, output=feedback)
                    submit_rejection_causes.append(feedback)
                    if len(submit_rejection_causes) >= 3:
                        raise SubmissionRepairExhaustedError(
                            AgentRunnerType.CODEX_SERVER.value,
                            submit_rejection_causes[0],
                            submit_rejection_causes[-1],
                        )
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
                    parser.record_dynamic_tool_result(
                        str(req_id), success=False, output=str(cb_exc)
                    )
                    await _send_dynamic_tool_response(success=False)
                    raise

            async def _process_msg(msg: dict[str, Any]) -> bool:
                """Process one message; return True if it is a terminal notification."""
                nonlocal num_actions, turn_usage, finish_reasons
                # Dynamic tool call request from the server (has id AND method).
                if msg.get("method") == "item/tool/call" and "id" in msg:
                    if isinstance(transport, RealStdioTransport):
                        transport.record_rpc_boundary("item/tool/call", msg.get("id"))
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
                    receipt = _command_execution_receipt(
                        msg,
                        thread_id=thread_id,
                        turn_id=turn_id,
                    )
                    if receipt is not None and self._command_completion_observer is not None:
                        await self._command_completion_observer(receipt)
                terminal, status = is_terminal_notification(msg)
                if (
                    terminal
                    and self._terminal_answer_requested
                    and self._terminal_answer_interrupt_sent
                    and status in {"completed", "interrupted"}
                ):
                    self._terminal_answer_completed_observed = True
                    parser.parse_jsonrpc_message(msg)
                    usage = extract_turn_usage(msg)
                    if usage:
                        turn_usage.update(usage)
                    return True
                parser.parse_jsonrpc_message(msg)
                terminal, usage = await self._handle_notification(
                    msg,
                    output_lines,
                    on_output,
                    on_checklist_update,
                    on_submit,
                    on_grade,
                    context.graph_patch_callback,
                    on_complete_recovery,
                    submit_rejection_causes,
                    decision_submission=is_decision_submission(context.submission_contract),
                )
                finish_reasons.extend(extract_turn_finish_reasons(msg))
                # Accumulate usage: cumulative wins (last value overwrites), or sum per-turn.
                # thread/tokenUsage/updated sends cumulative total_token_usage, so we keep
                # the latest. turn/completed usage is used only if no token updates were seen.
                if usage:
                    if not turn_usage:
                        turn_usage = usage
                    else:
                        # Cumulative update: latest wins for each field.
                        for k, v in usage.items():
                            if v > turn_usage.get(k, 0):
                                turn_usage[k] = v
                if terminal:
                    # If turn/completed has usage but we've already accumulated token updates,
                    # keep the accumulated values (they're more complete).
                    if not turn_usage:
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
                if self._terminal_answer_stop_deadline is None:
                    msg = await transport.recv()
                else:
                    remaining = self._terminal_answer_stop_deadline - time.monotonic()
                    if remaining <= 0:
                        raise AgentTimeoutError(
                            AgentRunnerType.CODEX_SERVER.value,
                            "terminal answer stop was not observed within 180 seconds",
                        )
                    try:
                        msg = await asyncio.wait_for(transport.recv(), timeout=remaining)
                    except TimeoutError as exc:
                        raise AgentTimeoutError(
                            AgentRunnerType.CODEX_SERVER.value,
                            "terminal answer stop was not observed within 180 seconds",
                        ) from exc
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
            SubmissionRejectedError,
        ):
            raise
        except asyncio.CancelledError:
            # Do NOT convert to AgentCancelledError — let it propagate as-is so
            # the runtime's asyncio.CancelledError handler records the pause reason
            # as "server_shutdown" (enabling auto-resume on next startup) rather
            # than the non-recoverable "agent_cancelled".
            raise
        except _DynamicToolReceiptObserverError:
            # The opt-in observer is an evidence boundary. Its failure must
            # stop execution, but its exception text (which may contain probe
            # data) must not enter public diagnostics or logs.
            raise AgentExecutionError(
                AgentRunnerType.CODEX_SERVER.value,
                "Dynamic tool receipt observer failed",
            ) from None
        except OSError as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            diagnostic = _transport_failure_diagnostic(
                transport, self._active_thread_id, tmp_codex_home
            )
            logger.warning(
                "CodexServerAgent: transport OS error after %dms — %s; %s",
                duration_ms,
                exc,
                diagnostic,
                exc_info=True,
            )
            raise AgentNotAvailableError(
                AgentRunnerType.CODEX_SERVER.value,
                f"Transport error communicating with codex app-server; {diagnostic}",
            ) from exc
        except EOFError as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            diagnostic = _transport_failure_diagnostic(
                transport, self._active_thread_id, tmp_codex_home
            )
            logger.warning(
                "CodexServerAgent: app-server EOF after %dms — %s; %s",
                duration_ms,
                exc,
                diagnostic,
            )
            raise AgentNotAvailableError(
                AgentRunnerType.CODEX_SERVER.value,
                f"codex app-server process terminated unexpectedly; {diagnostic}",
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
                logger.info(
                    "CodexServerAgent: closing app-server transport — run=%s task=%s thread_id=%s",
                    context.run_id,
                    context.task_id,
                    self._active_thread_id or "<none>",
                )
                try:
                    await transport.close()
                except Exception:
                    pass
            # Clean up the isolated CODEX_HOME temp directory.
            if tmp_codex_home is not None:
                shutil.rmtree(tmp_codex_home, ignore_errors=True)

        duration_ms = int(time.monotonic() * 1000) - start_ms
        result = build_execution_result(
            output_lines,
            duration_ms,
            gen_ai_usage_input_tokens=turn_usage.get("gen_ai_usage_input_tokens", 0),
            gen_ai_usage_output_tokens=turn_usage.get("gen_ai_usage_output_tokens", 0),
            gen_ai_usage_cache_read_input_tokens=turn_usage.get(
                "gen_ai_usage_cache_read_input_tokens", 0
            ),
            num_actions=num_actions,
            agent_model=model,
            gen_ai_response_finish_reasons=finish_reasons,
            gen_ai_usage_reasoning_output_tokens=turn_usage.get(
                "gen_ai_usage_reasoning_output_tokens", 0
            ),
        )
        if self._terminal_answer_completed_observed:
            result.completion_cause = "terminal_answer_completed"
        action_log = parser.finalize()
        action_log.agent_model = model
        action_log.total_duration_ms = duration_ms
        action_log.gen_ai_usage_input_tokens = turn_usage.get("gen_ai_usage_input_tokens", 0)
        action_log.gen_ai_usage_output_tokens = turn_usage.get("gen_ai_usage_output_tokens", 0)
        action_log.gen_ai_usage_cache_read_input_tokens = turn_usage.get(
            "gen_ai_usage_cache_read_input_tokens", 0
        )
        result.action_log = action_log
        return result

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
        logger.info(
            "CodexServerAgent: cancellation requested — thread_id=%s", thread_id or "<none>"
        )

    async def request_terminal_answer_completion(self) -> None:
        """Stop the active turn after a durable answer without classifying cancellation."""
        self._terminal_answer_requested = True
        thread_id = self._active_thread_id
        transport = self._transport
        if thread_id is not None and transport is not None:
            await transport.send(
                build_jsonrpc_request(98, "turn/interrupt", {"threadId": thread_id})
            )
            self._terminal_answer_interrupt_sent = True
            self._terminal_answer_stop_deadline = time.monotonic() + 180.0

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
        gen_ai_usage_input_tokens: int = 0,
        gen_ai_usage_output_tokens: int = 0,
        gen_ai_usage_cache_read_input_tokens: int = 0,
        num_actions: int = 0,
    ) -> object:
        """Build normalized ``ExecutionMetrics`` from raw session counters."""
        return normalize_codex_metrics(
            duration_ms=duration_ms,
            gen_ai_usage_input_tokens=gen_ai_usage_input_tokens,
            gen_ai_usage_output_tokens=gen_ai_usage_output_tokens,
            gen_ai_usage_cache_read_input_tokens=gen_ai_usage_cache_read_input_tokens,
            num_actions=num_actions,
        )

    async def _route_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_submit_graph_patch: Any | None = None,
        on_grade: GradeCallback | None = None,
    ) -> str:
        """Route an allow-listed callback tool call to the appropriate callback."""
        return await route_tool_call(
            tool_name,
            args,
            on_checklist_update,
            on_submit,
            on_submit_graph_patch=on_submit_graph_patch,
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

        - ``"managed"`` (default): Force workspace-write sandbox using
          orchestrator-managed writable roots. Network access is currently left
          enabled so package-manager caches and hook environments can refresh.
          Does not load the user's config.toml (only auth.json is copied).
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
        elif self._restrictions == "managed":
            writable_roots = [
                *get_worktree_git_write_paths(Path(context.working_dir)),
                *get_agent_cache_write_paths(),
            ]
            config_text = _build_workspace_write_config_toml(
                writable_roots,
                network_access=True,
            )
            (tmp_codex_home / "config.toml").write_text(config_text)

        # Strip OPENAI_API_KEY and set isolated CODEX_HOME.  Also run from the
        # worktree (not the orchestrator cwd) to avoid loading a .env file.
        clean_env = build_agent_subprocess_env(
            base_env={k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"},
            run_worktree=context.working_dir,
            expected_run_branch=context.expected_git_branch,
        )
        clean_env["CODEX_HOME"] = str(tmp_codex_home)

        # Build argv.  The `--sandbox` and `--ask-for-approval` CLI flags only
        # apply to `codex exec` / interactive mode.  For `codex app-server` the
        # sandbox is controlled per-thread via the `sandbox` field in
        # thread/start (see Step 2 below).  No extra CLI flags are needed here.
        argv, provider_env = build_codex_app_server_launch(
            self._local_provider,
            context.api_base_url,
        )
        clean_env.update(provider_env)

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
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
                agent_runner_type=AgentRunnerType.CODEX_SERVER.value,
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

        logger.info(
            "CodexServerAgent: spawned codex app-server — pid=%d, provider=%s, run=%s, task=%s",
            proc.pid,
            self._local_provider,
            context.run_id,
            context.task_id,
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
        on_submit_graph_patch: Any | None = None,
        on_complete_recovery: CompleteRecoveryCallback | None = None,
        submit_rejection_causes: list[str] | None = None,
        *,
        decision_submission: bool = False,
    ) -> tuple[bool, dict[str, int]]:
        """Process one JSON-RPC notification.

        Returns:
            ``(True, usage)`` if this is a terminal notification
            (``turn/completed``), where *usage* is the token usage dict
            extracted from the turn payload.
            ``(False, usage)`` for ``thread/tokenUsage/updated`` notifications,
            where *usage* is the interim token usage dict.
            ``(False, {})`` otherwise.

        Raises:
            AgentCancelledError: When ``turn/completed`` has
                ``status: "interrupted"``.
            AgentExecutionError: When ``turn/completed`` has
                ``status: "systemError"``.
        """
        # Check for token usage updates (cumulative or per-turn).
        usage_update = extract_token_usage_update(msg)
        if usage_update is not None:
            return (False, usage_update)

        # Check for terminal state.
        terminal, status = is_terminal_notification(msg)
        if terminal:
            if status == "interrupted":
                raise AgentCancelledError(AgentRunnerType.CODEX_SERVER.value)
            if status in ("systemError", "failed"):
                error_detail = extract_turn_error(msg)
                message = f"Codex session ended with status: {status}"
                if error_detail:
                    message = f"{message} — {error_detail}"
                raise AgentExecutionError(AgentRunnerType.CODEX_SERVER.value, message)
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
                    on_submit_graph_patch=on_submit_graph_patch,
                    on_grade=on_grade,
                    on_complete_recovery=on_complete_recovery,
                    agent_label="CodexServerAgent",
                )
            except ValueError as exc:
                if _is_submit_callback_rejection(tool_name, exc):
                    causes = submit_rejection_causes if submit_rejection_causes is not None else []
                    causes.append(str(exc))
                    if isinstance(
                        exc, SubmissionRejectedError
                    ) and submission_rejection_requires_stop(exc.acknowledgement):
                        raise
                    rejection_budget = 2 if decision_submission else 3
                    if len(causes) >= rejection_budget:
                        raise SubmissionRepairExhaustedError(
                            AgentRunnerType.CODEX_SERVER.value,
                            causes[0],
                            causes[-1],
                            rejection_budget,
                        )
                    logger.warning(
                        "CodexServerAgent: legacy submit notification rejected; "
                        "continuing the same session: %s",
                        exc,
                    )
                    return (False, {})
                pass  # Disallowed tool — already logged by enforce_tool_allowlist.
            except Exception as exc:
                # Tool call raised an unexpected error (e.g. InvalidTransitionError when
                # the agent calls update_checklist during the verifying phase).  Log and
                # continue — a bad tool call must never crash the whole session.
                logger.warning(
                    "CodexServerAgent: tool call %r raised %s: %s — continuing session",
                    tool_name,
                    type(exc).__name__,
                    exc,
                )

        # Accumulate agent message text.
        delta = extract_agent_message_delta(msg)
        if delta:
            output_lines.append(delta)
            if on_output is not None:
                await on_output([delta])

        # Stream completed work items (commands, file changes, tool calls) so
        # the activity feed shows progress even when the model emits no text.
        activity_line = extract_item_activity_line(msg)
        if activity_line:
            output_lines.append(activity_line)
            if on_output is not None:
                await on_output([activity_line])

        return (False, {})
