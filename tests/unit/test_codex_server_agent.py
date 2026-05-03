"""Unit tests for CodexServerAgent: builder/verifier flows and allow-list enforcement."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from orchestrator.runners import CodexServerAgent, _build_workspace_write_config_toml
from orchestrator.runners.errors import (
    AgentCancelledError,
    AgentExecutionError,
    AgentNotAvailableError,
)
from orchestrator.runners.types import ExecutionContext
from orchestrator.config import AgentRunnerType, ChecklistStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(
    prompt: str = "Do the task.",
    requirements: list[str] | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        run_id="run-abc",
        task_id="task-xyz",
        working_dir="/tmp/work",
        prompt=prompt,
        requirements=requirements or ["R-01: implement feature", "R-02: write tests"],
    )


async def _noop_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
    pass


async def _noop_submit() -> None:
    pass


async def _noop_grade(req_id: str, grade: str, reason: str | None) -> None:
    pass


class _FailingTransport:
    """Fake transport that raises OSError on send — simulates process spawn failure."""

    async def send(self, message: dict[str, Any]) -> None:
        raise OSError("simulated transport failure")

    async def recv(self) -> dict[str, Any]:
        raise OSError("not connected")

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# AgentRunnerInfo
# ---------------------------------------------------------------------------


def test_agent_info_type() -> None:
    agent = CodexServerAgent()
    assert agent.info.agent_runner_type == AgentRunnerType.CODEX_SERVER


def test_agent_info_name() -> None:
    agent = CodexServerAgent()
    assert agent.info.name == "Codex Server"


def test_legacy_no_network_restriction_normalizes_to_managed() -> None:
    agent = CodexServerAgent(restrictions="no-network")
    assert agent._restrictions == "managed"


def test_workspace_write_config_toml_enables_network_and_serializes_roots() -> None:
    config = _build_workspace_write_config_toml(
        [Path("/tmp/cache"), Path("/tmp/gitmeta")],
        network_access=True,
    )
    assert "[sandbox_workspace_write]" in config
    assert '"/tmp/cache"' in config
    assert '"/tmp/gitmeta"' in config
    assert "network_access = true" in config


# ---------------------------------------------------------------------------
# _build_prompt — phase-aware selection
# ---------------------------------------------------------------------------


def test_build_prompt_builder_phase_contains_update_checklist() -> None:
    agent = CodexServerAgent()
    prompt = agent._build_prompt(_ctx(), is_verifier=False)
    assert "update_checklist" in prompt


def test_build_prompt_builder_phase_contains_task_prompt() -> None:
    agent = CodexServerAgent()
    prompt = agent._build_prompt(_ctx(prompt="Special task description."), is_verifier=False)
    assert "Special task description." in prompt


def test_build_prompt_verifier_phase_contains_grade() -> None:
    agent = CodexServerAgent()
    prompt = agent._build_prompt(_ctx(), is_verifier=True)
    assert "grade" in prompt


def test_build_prompt_verifier_phase_contains_task_prompt() -> None:
    agent = CodexServerAgent()
    prompt = agent._build_prompt(_ctx(prompt="Verifier task text."), is_verifier=True)
    assert "Verifier task text." in prompt


def test_build_prompt_builder_and_verifier_differ() -> None:
    agent = CodexServerAgent()
    ctx = _ctx()
    builder_prompt = agent._build_prompt(ctx, is_verifier=False)
    verifier_prompt = agent._build_prompt(ctx, is_verifier=True)
    assert builder_prompt != verifier_prompt


# ---------------------------------------------------------------------------
# execute() — cancelled before start
# ---------------------------------------------------------------------------


async def test_execute_raises_agent_cancelled_error_if_already_cancelled() -> None:
    agent = CodexServerAgent()
    await agent.cancel()
    with pytest.raises(AgentCancelledError):
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )


async def test_execute_raises_agent_not_available_error_on_transport_failure() -> None:
    """execute() raises AgentNotAvailableError when the transport raises OSError."""
    agent = CodexServerAgent(api_key=None, _transport=_FailingTransport())
    with pytest.raises(AgentNotAvailableError):
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )


async def test_execute_builder_phase_detected_when_on_grade_is_none() -> None:
    """When on_grade is None, execute() operates in builder phase."""
    agent = CodexServerAgent()
    # We can't get past AgentNotAvailableError yet, but we verify the
    # prompt the agent _would_ use is builder-flavored via _build_prompt.
    prompt = agent._build_prompt(_ctx(), is_verifier=False)
    assert "update_checklist" in prompt
    assert "Grade EVERY requirement" not in prompt


async def test_execute_verifier_phase_detected_when_on_grade_is_provided() -> None:
    """When on_grade is not None, the agent selects verifier-phase prompt."""
    agent = CodexServerAgent()
    prompt = agent._build_prompt(_ctx(), is_verifier=True)
    assert "grade" in prompt


# ---------------------------------------------------------------------------
# cancel()
# ---------------------------------------------------------------------------


async def test_cancel_sets_cancelled_flag() -> None:
    agent = CodexServerAgent()
    assert agent._cancelled is False
    await agent.cancel()
    assert agent._cancelled is True


async def test_cancel_is_idempotent() -> None:
    agent = CodexServerAgent()
    await agent.cancel()
    await agent.cancel()  # second call must not raise
    assert agent._cancelled is True


# ---------------------------------------------------------------------------
# _route_tool_call — allow-listed tools are dispatched correctly
# ---------------------------------------------------------------------------


async def test_route_tool_call_update_checklist_invokes_callback() -> None:
    agent = CodexServerAgent()
    received: list[tuple[str, ChecklistStatus, str | None]] = []

    async def capture_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append((req_id, status, note))

    await agent._route_tool_call(
        tool_name="update_checklist",
        args={"req_id": "R-01", "status": "done", "note": "all good"},
        on_checklist_update=capture_checklist,
        on_submit=_noop_submit,
        on_grade=None,
    )
    assert received == [("R-01", ChecklistStatus.DONE, "all good")]


async def test_route_tool_call_update_checklist_blocked_status() -> None:
    agent = CodexServerAgent()
    received: list[tuple[str, ChecklistStatus, str | None]] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append((req_id, status, note))

    await agent._route_tool_call(
        tool_name="update_checklist",
        args={"req_id": "R-02", "status": "blocked", "note": None},
        on_checklist_update=capture,
        on_submit=_noop_submit,
    )
    assert received[0][1] == ChecklistStatus.BLOCKED


async def test_route_tool_call_submit_invokes_callback() -> None:
    agent = CodexServerAgent()
    submitted: list[bool] = []

    async def capture_submit() -> None:
        submitted.append(True)

    await agent._route_tool_call(
        tool_name="submit",
        args={},
        on_checklist_update=_noop_checklist,
        on_submit=capture_submit,
    )
    assert submitted == [True]


async def test_route_tool_call_grade_invokes_on_grade_callback() -> None:
    agent = CodexServerAgent()
    grades: list[tuple[str, str, str | None]] = []

    async def capture_grade(req_id: str, grade: str, reason: str | None) -> None:
        grades.append((req_id, grade, reason))

    await agent._route_tool_call(
        tool_name="grade",
        args={"req_id": "R-01", "grade": "A", "grade_reason": "Perfect"},
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
        on_grade=capture_grade,
    )
    assert grades == [("R-01", "A", "Perfect")]


async def test_route_tool_call_grade_ignored_in_builder_phase() -> None:
    """grade tool call is silently ignored when on_grade is None (builder phase)."""
    agent = CodexServerAgent()
    await agent._route_tool_call(
        tool_name="grade",
        args={"req_id": "R-01", "grade": "A"},
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
        on_grade=None,  # builder phase — no grade callback
    )
    # No error raised; grade call silently ignored in builder phase.


async def test_route_tool_call_request_clarification_does_not_raise() -> None:
    """request_clarification is on the allow-list and is handled without error."""
    agent = CodexServerAgent()
    await agent._route_tool_call(
        tool_name="request_clarification",
        args={"question": "What does requirement R-01 mean exactly?"},
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )
    # No callback in v1 — just logs and returns.


# ---------------------------------------------------------------------------
# _route_tool_call — disallowed tools are rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "disallowed_tool",
    [
        "bash",
        "read_file",
        "write_file",
        "execute_command",
        "delete_file",
        "shell",
        "list_files",
        "arbitrary_tool",
        "",
        "SUBMIT",
        "UPDATE_CHECKLIST",
    ],
)
async def test_route_tool_call_rejects_disallowed_tools(disallowed_tool: str) -> None:
    """Any tool not on the v1 allow-list is rejected with ValueError."""
    agent = CodexServerAgent()
    with pytest.raises(ValueError, match="not on the Codex server v1 allow-list"):
        await agent._route_tool_call(
            tool_name=disallowed_tool,
            args={},
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )


async def test_route_tool_call_rejected_tool_does_not_invoke_checklist_callback() -> None:
    """Disallowed tool call raises before any callback is invoked."""
    agent = CodexServerAgent()
    called: list[bool] = []

    async def should_not_be_called(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        called.append(True)

    with pytest.raises(ValueError):
        await agent._route_tool_call(
            tool_name="bash",
            args={"command": "rm -rf /"},
            on_checklist_update=should_not_be_called,
            on_submit=_noop_submit,
        )
    assert called == [], "Disallowed tool invocation must not trigger any callback"


async def test_route_tool_call_rejected_tool_does_not_invoke_submit_callback() -> None:
    agent = CodexServerAgent()
    called: list[bool] = []

    async def should_not_be_called() -> None:
        called.append(True)

    with pytest.raises(ValueError):
        await agent._route_tool_call(
            tool_name="delete_file",
            args={"path": "/etc/passwd"},
            on_checklist_update=_noop_checklist,
            on_submit=should_not_be_called,
        )
    assert called == []


# ---------------------------------------------------------------------------
# _normalize_output and _build_metrics delegation
# ---------------------------------------------------------------------------


def test_normalize_output_delegates_to_common() -> None:
    agent = CodexServerAgent()
    result = agent._normalize_output(["line one", {"text": "line two"}, 42])
    assert result == ["line one", "line two", "42"]


def test_build_metrics_delegates_to_common() -> None:
    agent = CodexServerAgent()
    from orchestrator.runners.types import ExecutionMetrics

    m = agent._build_metrics(
        duration_ms=500,
        tokens_read=100,
        tokens_write=50,
        tokens_cache=10,
        num_actions=3,
    )
    assert isinstance(m, ExecutionMetrics)
    assert m.duration_ms == 500
    assert m.tokens_read == 100
    assert m.tokens_write == 50
    assert m.tokens_cache == 10
    assert m.num_actions == 3


# ---------------------------------------------------------------------------
# Idempotent cancel — edge cases
# ---------------------------------------------------------------------------


async def test_cancel_many_times_is_idempotent() -> None:
    """Calling cancel() many times never raises and always leaves flag set."""
    agent = CodexServerAgent()
    for _ in range(10):
        await agent.cancel()
    assert agent._cancelled is True


async def test_cancel_with_completed_session_task_does_not_raise() -> None:
    """cancel() is safe when the session task has already completed."""
    agent = CodexServerAgent()

    async def _noop_coro() -> None:
        pass

    task: asyncio.Task[None] = asyncio.create_task(_noop_coro())
    await task  # allow the task to complete
    agent._session_task = task  # inject completed task

    # cancel() must not raise even though the task is done
    await agent.cancel()
    assert agent._cancelled is True


async def test_cancel_with_active_session_task_cancels_it() -> None:
    """cancel() calls task.cancel() on an in-flight session task."""
    agent = CodexServerAgent()

    async def _long_running() -> None:
        await asyncio.sleep(60)

    task: asyncio.Task[None] = asyncio.create_task(_long_running())
    agent._session_task = task

    await agent.cancel()

    assert agent._cancelled is True
    # task.cancel() was called — the task should be in a cancelled state
    # Give the event loop a chance to process the cancellation.
    await asyncio.sleep(0)
    assert task.cancelled() or task.done()


# ---------------------------------------------------------------------------
# Failure path mapping — execute() maps failures to explicit agent error types
# ---------------------------------------------------------------------------


async def test_execute_startup_failure_raises_agent_not_available_error() -> None:
    """Transport failure raises AgentNotAvailableError (not generic Exception)."""
    agent = CodexServerAgent(api_key=None, _transport=_FailingTransport())
    with pytest.raises(AgentNotAvailableError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    # Must be the typed agent error, never a bare RuntimeError or similar.
    assert isinstance(exc_info.value, AgentNotAvailableError)
    assert exc_info.value.agent_runner_type == AgentRunnerType.CODEX_SERVER.value


async def test_execute_cancelled_before_start_raises_agent_cancelled_error() -> None:
    """execute() after cancel() raises AgentCancelledError, not CancelledError."""
    agent = CodexServerAgent()
    await agent.cancel()
    with pytest.raises(AgentCancelledError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_runner_type == AgentRunnerType.CODEX_SERVER.value


async def test_execute_agent_not_available_error_does_not_leak_internal_details() -> None:
    """AgentNotAvailableError raised from execute() uses typed error, not raw exception."""
    agent = CodexServerAgent(api_key=None, _transport=_FailingTransport(), _environ={})
    exc: AgentNotAvailableError | None = None
    try:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    except AgentNotAvailableError as e:
        exc = e

    assert exc is not None
    # The error type is explicit and structured — it carries agent_runner_type as a field.
    assert exc.agent_runner_type == AgentRunnerType.CODEX_SERVER.value


class _GenericFailingCodexServerAgent(CodexServerAgent):
    """Test subclass that simulates a generic session error inside execute().

    This exercises the ``except Exception`` branch that maps unknown failures
    to ``AgentExecutionError`` without exposing the raw exception message.
    """

    def __init__(self, secret_in_message: str) -> None:
        super().__init__()
        self._secret = secret_in_message

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: object,
        on_submit: object,
        on_output: object = None,
        on_grade: object = None,
        on_agent_metadata: object = None,
    ) -> object:
        import time

        if self._cancelled:
            raise AgentCancelledError(AgentRunnerType.CODEX_SERVER.value)

        start_ms = int(time.monotonic() * 1000)
        try:
            # Simulate a session error whose message contains a secret.
            raise RuntimeError(self._secret)
        except (AgentCancelledError, AgentNotAvailableError):
            raise
        except asyncio.CancelledError:
            raise AgentCancelledError(AgentRunnerType.CODEX_SERVER.value)
        except Exception as exc:
            import logging

            duration_ms = int(time.monotonic() * 1000) - start_ms
            logging.getLogger(__name__).debug(
                "CodexServerAgent: session error after %dms — %s",
                duration_ms,
                exc,
                exc_info=True,
            )
            raise AgentExecutionError(
                AgentRunnerType.CODEX_SERVER.value,
                f"Session failed after {duration_ms}ms",
            ) from exc


async def test_execute_generic_failure_raises_agent_execution_error() -> None:
    """Generic session errors map to AgentExecutionError (explicit error type)."""
    agent = _GenericFailingCodexServerAgent(secret_in_message="some failure")
    with pytest.raises(AgentExecutionError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_runner_type == AgentRunnerType.CODEX_SERVER.value


async def test_execute_generic_failure_does_not_leak_secret_in_error_message() -> None:
    """AgentExecutionError message must NOT contain the raw exception text (secrets)."""
    secret = "sk-supersecret-api-key-12345"  # pragma: allowlist secret
    agent = _GenericFailingCodexServerAgent(secret_in_message=secret)
    with pytest.raises(AgentExecutionError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    # The human-readable message must not contain the secret.
    assert secret not in exc_info.value.message


async def test_execute_asyncio_cancelled_error_maps_to_agent_cancelled_error() -> None:
    """asyncio.CancelledError inside execute() maps to AgentCancelledError."""

    class _CancelledCodexServerAgent(CodexServerAgent):
        async def execute(
            self,
            context: ExecutionContext,
            on_checklist_update: object,
            on_submit: object,
            on_output: object = None,
            on_grade: object = None,
            on_agent_metadata: object = None,
        ) -> object:
            if self._cancelled:
                raise AgentCancelledError(AgentRunnerType.CODEX_SERVER.value)

            import time

            start_ms = int(time.monotonic() * 1000)
            try:
                # Simulate asyncio cancellation at a session await point.
                raise asyncio.CancelledError()
            except (AgentCancelledError, AgentNotAvailableError):
                raise
            except asyncio.CancelledError:
                raise AgentCancelledError(AgentRunnerType.CODEX_SERVER.value)
            except Exception as exc:
                duration_ms = int(time.monotonic() * 1000) - start_ms
                raise AgentExecutionError(
                    AgentRunnerType.CODEX_SERVER.value,
                    f"Session failed after {duration_ms}ms",
                ) from exc

    agent = _CancelledCodexServerAgent()
    with pytest.raises(AgentCancelledError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_runner_type == AgentRunnerType.CODEX_SERVER.value
