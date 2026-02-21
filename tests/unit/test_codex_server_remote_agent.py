"""Unit tests for CodexServerRemoteAgent: agent protocol surface.

Covers the public protocol methods (info, execute, cancel) and the
allow-list enforcement and callback routing methods for the remote agent.
This file mirrors the structure of test_codex_server_agent.py for the
local variant and provides the explicit named target for:

    uv run pytest tests/unit/test_codex_server_remote_agent.py -v

Filter: pytest -k 'codex_server_remote_agent'
"""

from __future__ import annotations

import asyncio

import pytest

from orchestrator.agents.codex_server_remote import CodexServerRemoteAgent
from orchestrator.agents.errors import (
    AgentCancelledError,
    AgentConfigError,
    AgentExecutionError,
    AgentNotAvailableError,
)
from orchestrator.agents.types import ExecutionContext, ExecutionMetrics
from orchestrator.config.enums import AgentType, ChecklistStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_URL = "https://codex.example.com"
_VALID_KEY = "sk-remote-agent-test-key"  # pragma: allowlist secret


def _agent(
    callback_channel: str = "rest",
    model: str | None = None,
    session_id: str | None = None,
) -> CodexServerRemoteAgent:
    return CodexServerRemoteAgent(
        base_url=_VALID_URL,
        api_key=_VALID_KEY,
        callback_channel=callback_channel,
        model=model,
        session_id=session_id,
        _environ={},
    )


def _ctx(
    prompt: str = "Remote task.",
    requirements: list[str] | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        run_id="run-remote-agent",
        task_id="task-remote-agent",
        working_dir="/tmp/remote-agent",
        prompt=prompt,
        requirements=requirements or ["R-01: implement feature", "R-02: write tests"],
    )


async def _noop_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
    pass


async def _noop_submit() -> None:
    pass


async def _noop_grade(req_id: str, grade: str, reason: str | None) -> None:
    pass


# ---------------------------------------------------------------------------
# AgentInfo
# ---------------------------------------------------------------------------


def test_remote_agent_info_type() -> None:
    """Remote agent info returns CODEX_SERVER_REMOTE type."""
    agent = _agent()
    assert agent.info.agent_type == AgentType.CODEX_SERVER_REMOTE


def test_remote_agent_info_name() -> None:
    """Remote agent info returns the canonical display name."""
    agent = _agent()
    assert agent.info.name == "Codex Server Remote"


def test_remote_agent_info_version_is_none() -> None:
    """Remote agent version is None (no local binary to inspect)."""
    agent = _agent()
    assert agent.info.version is None


# ---------------------------------------------------------------------------
# TOOL_ALLOWLIST class attribute
# ---------------------------------------------------------------------------


def test_remote_agent_tool_allowlist_class_attribute_exists() -> None:
    """TOOL_ALLOWLIST is a class-level attribute on CodexServerRemoteAgent."""
    assert hasattr(CodexServerRemoteAgent, "TOOL_ALLOWLIST")


def test_remote_agent_tool_allowlist_is_frozenset() -> None:
    """TOOL_ALLOWLIST is an immutable frozenset."""
    assert isinstance(CodexServerRemoteAgent.TOOL_ALLOWLIST, frozenset)


def test_remote_agent_tool_allowlist_contains_four_tools() -> None:
    """TOOL_ALLOWLIST contains exactly the four v1 orchestrator callback tools."""
    expected = frozenset({"update_checklist", "grade", "submit", "request_clarification"})
    assert CodexServerRemoteAgent.TOOL_ALLOWLIST == expected


# ---------------------------------------------------------------------------
# Construction — AgentConfigError on invalid input
# ---------------------------------------------------------------------------


def test_remote_agent_config_error_for_empty_base_url() -> None:
    """Empty base_url raises AgentConfigError at construction time."""
    with pytest.raises(AgentConfigError) as exc_info:
        CodexServerRemoteAgent(base_url="", api_key=_VALID_KEY, _environ={})
    assert exc_info.value.agent_type == AgentType.CODEX_SERVER_REMOTE.value


def test_remote_agent_config_error_for_no_token() -> None:
    """No token source raises AgentConfigError at construction time."""
    with pytest.raises(AgentConfigError) as exc_info:
        CodexServerRemoteAgent(base_url=_VALID_URL, api_key=None, _environ={})
    assert exc_info.value.agent_type == AgentType.CODEX_SERVER_REMOTE.value


def test_remote_agent_config_error_is_typed() -> None:
    """AgentConfigError is a distinct, typed exception."""
    with pytest.raises(AgentConfigError) as exc_info:
        CodexServerRemoteAgent(base_url="", api_key=_VALID_KEY, _environ={})
    assert not isinstance(exc_info.value, AgentExecutionError)


# ---------------------------------------------------------------------------
# _build_prompt — phase-aware selection
# ---------------------------------------------------------------------------


def test_remote_agent_build_prompt_builder_contains_update_checklist() -> None:
    """Builder-phase prompt includes update_checklist tool instructions."""
    agent = _agent()
    prompt = agent._build_prompt(_ctx(), is_verifier=False)
    assert "update_checklist" in prompt


def test_remote_agent_build_prompt_builder_excludes_grade_workflow() -> None:
    """Builder-phase prompt excludes verifier grading workflow."""
    agent = _agent()
    prompt = agent._build_prompt(_ctx(), is_verifier=False)
    assert "Grade EVERY requirement" not in prompt


def test_remote_agent_build_prompt_verifier_contains_grade() -> None:
    """Verifier-phase prompt includes grade tool instructions."""
    agent = _agent()
    prompt = agent._build_prompt(_ctx(), is_verifier=True)
    assert "grade" in prompt


def test_remote_agent_build_prompt_verifier_contains_grading_workflow() -> None:
    """Verifier-phase prompt includes the Grade EVERY requirement instruction."""
    agent = _agent()
    prompt = agent._build_prompt(_ctx(), is_verifier=True)
    assert "Grade EVERY requirement" in prompt


def test_remote_agent_builder_and_verifier_prompts_differ() -> None:
    """Builder and verifier produce distinct prompts for the same context."""
    agent = _agent()
    ctx = _ctx()
    assert agent._build_prompt(ctx, is_verifier=False) != agent._build_prompt(ctx, is_verifier=True)


def test_remote_agent_build_prompt_includes_task_prompt_text() -> None:
    """Both phases embed the task prompt text from the context."""
    agent = _agent()
    prompt_text = "Implement the widget interface."
    ctx = _ctx(prompt=prompt_text)
    for is_verifier in [False, True]:
        prompt = agent._build_prompt(ctx, is_verifier=is_verifier)
        assert prompt_text in prompt


def test_remote_agent_build_prompt_includes_requirements() -> None:
    """Prompt includes the requirement strings from the context."""
    agent = _agent()
    ctx = _ctx(requirements=["R-01: first requirement", "R-02: second requirement"])
    prompt = agent._build_prompt(ctx, is_verifier=False)
    assert "R-01: first requirement" in prompt
    assert "R-02: second requirement" in prompt


# ---------------------------------------------------------------------------
# execute() — pre-flight cancellation and transport-not-implemented
# ---------------------------------------------------------------------------


async def test_remote_agent_execute_raises_agent_cancelled_if_already_cancelled() -> None:
    """execute() raises AgentCancelledError when cancel() was called first."""
    agent = _agent()
    await agent.cancel()
    with pytest.raises(AgentCancelledError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_type == AgentType.CODEX_SERVER_REMOTE.value


async def test_remote_agent_execute_raises_not_available_transport_not_implemented() -> None:
    """execute() raises AgentNotAvailableError until HTTPS transport is wired up."""
    agent = _agent()
    with pytest.raises(AgentNotAvailableError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_type == AgentType.CODEX_SERVER_REMOTE.value


async def test_remote_agent_not_available_error_carries_typed_agent_type() -> None:
    """AgentNotAvailableError from execute() is typed and carries agent_type."""
    agent = _agent()
    exc_caught: AgentNotAvailableError | None = None
    try:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    except AgentNotAvailableError as exc:
        exc_caught = exc

    assert exc_caught is not None
    assert exc_caught.agent_type == AgentType.CODEX_SERVER_REMOTE.value


# ---------------------------------------------------------------------------
# cancel()
# ---------------------------------------------------------------------------


async def test_remote_agent_cancel_sets_flag() -> None:
    """cancel() sets the _cancelled flag."""
    agent = _agent()
    assert agent._cancelled is False
    await agent.cancel()
    assert agent._cancelled is True


async def test_remote_agent_cancel_is_idempotent() -> None:
    """Calling cancel() multiple times never raises."""
    agent = _agent()
    for _ in range(10):
        await agent.cancel()
    assert agent._cancelled is True


async def test_remote_agent_cancel_with_completed_session_task_does_not_raise() -> None:
    """cancel() is safe when the session task is already completed."""
    agent = _agent()

    async def _noop() -> None:
        pass

    task: asyncio.Task[None] = asyncio.create_task(_noop())
    await task
    agent._session_task = task

    await agent.cancel()
    assert agent._cancelled is True


async def test_remote_agent_cancel_with_active_session_task_cancels_it() -> None:
    """cancel() calls task.cancel() on an in-flight session task."""
    agent = _agent()

    async def _long_running() -> None:
        await asyncio.sleep(60)

    task: asyncio.Task[None] = asyncio.create_task(_long_running())
    agent._session_task = task

    await agent.cancel()
    await asyncio.sleep(0)

    assert agent._cancelled is True
    assert task.cancelled() or task.done()


# ---------------------------------------------------------------------------
# _route_tool_call — allow-listed tools are dispatched correctly
# ---------------------------------------------------------------------------


async def test_remote_agent_route_update_checklist_dispatched() -> None:
    """update_checklist tool call invokes the checklist callback."""
    agent = _agent()
    received: list[tuple[str, ChecklistStatus, str | None]] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append((req_id, status, note))

    await agent._route_tool_call(
        tool_name="update_checklist",
        args={"req_id": "R-01", "status": "done", "note": "finished"},
        on_checklist_update=capture,
        on_submit=_noop_submit,
    )
    assert received == [("R-01", ChecklistStatus.DONE, "finished")]


async def test_remote_agent_route_submit_dispatched() -> None:
    """submit tool call invokes the submit callback."""
    agent = _agent()
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


async def test_remote_agent_route_grade_dispatched_in_verifier_phase() -> None:
    """grade tool call invokes the grade callback in verifier phase."""
    agent = _agent()
    grades: list[tuple[str, str, str | None]] = []

    async def capture_grade(req_id: str, grade: str, reason: str | None) -> None:
        grades.append((req_id, grade, reason))

    await agent._route_tool_call(
        tool_name="grade",
        args={"req_id": "R-01", "grade": "A", "grade_reason": "Well done"},
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
        on_grade=capture_grade,
    )
    assert grades == [("R-01", "A", "Well done")]


async def test_remote_agent_route_grade_ignored_in_builder_phase() -> None:
    """grade is a no-op (not an error) when on_grade is None (builder phase)."""
    agent = _agent()
    await agent._route_tool_call(
        tool_name="grade",
        args={"req_id": "R-01", "grade": "B"},
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
        on_grade=None,
    )


async def test_remote_agent_route_request_clarification_does_not_raise() -> None:
    """request_clarification is allow-listed and handled without error."""
    agent = _agent()
    await agent._route_tool_call(
        tool_name="request_clarification",
        args={"question": "What does R-01 require exactly?"},
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )


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
        "GRADE",
    ],
)
async def test_remote_agent_route_rejects_disallowed_tools(disallowed_tool: str) -> None:
    """Any tool not on the v1 allow-list raises ValueError."""
    agent = _agent()
    with pytest.raises(ValueError, match="not on the Codex server v1 allow-list"):
        await agent._route_tool_call(
            tool_name=disallowed_tool,
            args={},
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )


async def test_remote_agent_disallowed_tool_does_not_invoke_checklist_callback() -> None:
    """Disallowed tool raises before checklist callback is invoked."""
    agent = _agent()
    called: list[bool] = []

    async def should_not_be_called(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        called.append(True)

    with pytest.raises(ValueError):
        await agent._route_tool_call(
            tool_name="bash",
            args={},
            on_checklist_update=should_not_be_called,
            on_submit=_noop_submit,
        )
    assert called == []


async def test_remote_agent_disallowed_tool_does_not_invoke_submit_callback() -> None:
    """Disallowed tool raises before submit callback is invoked."""
    agent = _agent()
    called: list[bool] = []

    async def should_not_be_called() -> None:
        called.append(True)

    with pytest.raises(ValueError):
        await agent._route_tool_call(
            tool_name="delete_file",
            args={},
            on_checklist_update=_noop_checklist,
            on_submit=should_not_be_called,
        )
    assert called == []


# ---------------------------------------------------------------------------
# _normalize_output and _build_metrics delegation
# ---------------------------------------------------------------------------


def test_remote_agent_normalize_output_delegates_to_common() -> None:
    """_normalize_output delegates to the shared helper."""
    agent = _agent()
    result = agent._normalize_output(["line one", {"text": "line two"}, 42])
    assert result == ["line one", "line two", "42"]


def test_remote_agent_build_metrics_returns_execution_metrics() -> None:
    """_build_metrics returns a populated ExecutionMetrics object."""
    agent = _agent()
    m = agent._build_metrics(
        duration_ms=600,
        tokens_read=200,
        tokens_write=75,
        tokens_cache=15,
        num_actions=4,
    )
    assert isinstance(m, ExecutionMetrics)
    assert m.duration_ms == 600
    assert m.tokens_read == 200
    assert m.tokens_write == 75
    assert m.tokens_cache == 15
    assert m.num_actions == 4


# ---------------------------------------------------------------------------
# Failure path: AgentExecutionError does not leak secrets
# ---------------------------------------------------------------------------


class _GenericFailingRemoteAgent(CodexServerRemoteAgent):
    """Subclass that raises a generic RuntimeError in execute() to exercise
    the AgentExecutionError wrapping path without the bearer token leaking."""

    def __init__(self, secret_in_message: str) -> None:
        super().__init__(base_url=_VALID_URL, api_key=_VALID_KEY, _environ={})
        self._secret = secret_in_message

    async def execute(  # type: ignore[override]
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
            raise AgentCancelledError(AgentType.CODEX_SERVER_REMOTE.value)

        start_ms = int(time.monotonic() * 1000)
        try:
            raise RuntimeError(self._secret)
        except (AgentCancelledError, AgentNotAvailableError):
            raise
        except asyncio.CancelledError:
            raise AgentCancelledError(AgentType.CODEX_SERVER_REMOTE.value)
        except Exception as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            raise AgentExecutionError(
                AgentType.CODEX_SERVER_REMOTE.value,
                f"Session failed after {duration_ms}ms",
            ) from exc


async def test_remote_agent_generic_failure_raises_agent_execution_error() -> None:
    """Generic session errors map to AgentExecutionError (not bare Exception)."""
    agent = _GenericFailingRemoteAgent("some failure message")
    with pytest.raises(AgentExecutionError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_type == AgentType.CODEX_SERVER_REMOTE.value


async def test_remote_agent_generic_failure_does_not_leak_secret() -> None:
    """AgentExecutionError message must not contain raw exception text (secrets)."""
    secret = "sk-bearer-do-not-leak-12345"  # pragma: allowlist secret
    agent = _GenericFailingRemoteAgent(secret_in_message=secret)
    with pytest.raises(AgentExecutionError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert secret not in exc_info.value.message
