"""Unit tests for ClaudeSDKAgent: builder/verifier flows, tool dispatch, error mapping."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from orchestrator.agents.claude_sdk import (
    ClaudeSDKAgent,
    _BUILDER_TOOLS,
    _VERIFIER_TOOLS,
    _build_tool_list,
    _dispatch_tool,
    build_claude_sdk_prompt,
)
from orchestrator.agents.errors import (
    AgentCancelledError,
    AgentExecutionError,
    AgentNotAvailableError,
)
from orchestrator.agents.types import ExecutionContext, ExecutionResult
from orchestrator.config.enums import AgentRunnerType, ChecklistStatus


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


# ---------------------------------------------------------------------------
# Fake Anthropic client helpers (no MagicMock — plain inline stubs)
# ---------------------------------------------------------------------------


class _FakeUsage:
    def __init__(self, input_tokens: int = 100, output_tokens: int = 50) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeToolUseBlock:
    def __init__(
        self,
        id: str,
        name: str,
        input: dict[str, Any],  # noqa: A002
    ) -> None:
        self.type = "tool_use"
        self.id = id
        self.name = name
        self.input = input


class _FakeResponse:
    """Fake Anthropic Messages API response."""

    def __init__(
        self,
        content: list[Any],
        stop_reason: str = "end_turn",
        input_tokens: int = 100,
        output_tokens: int = 50,
    ) -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _FakeUsage(input_tokens, output_tokens)


class _SingleEndTurnClient:
    """Returns a single end_turn response with a text block, then stops."""

    def __init__(self, text: str = "Task complete.") -> None:
        self._text = text
        self.calls: list[dict[str, Any]] = []

        class _Messages:
            def __init__(self_, client: _SingleEndTurnClient) -> None:
                self_._client = client

            def create(self_, **kwargs: Any) -> _FakeResponse:
                self_._client.calls.append(kwargs)
                return _FakeResponse(
                    content=[_FakeTextBlock(self_._client._text)],
                    stop_reason="end_turn",
                )

        self.messages = _Messages(self)


class _ToolUseClient:
    """Returns one tool_use response (update_checklist then submit), then end_turn."""

    def __init__(self) -> None:
        self._call_count = 0

        class _Messages:
            def __init__(self_, client: _ToolUseClient) -> None:
                self_._client = client

            def create(self_, **kwargs: Any) -> _FakeResponse:
                count = self_._client._call_count
                self_._client._call_count += 1
                if count == 0:
                    # First call: Claude calls update_checklist then submit.
                    return _FakeResponse(
                        content=[
                            _FakeToolUseBlock(
                                id="tu-1",
                                name="update_checklist",
                                input={"req_id": "R-01", "status": "done", "note": "done"},
                            ),
                            _FakeToolUseBlock(
                                id="tu-2",
                                name="submit",
                                input={},
                            ),
                        ],
                        stop_reason="tool_use",
                    )
                # Should not be reached since submit ends the loop.
                return _FakeResponse(content=[], stop_reason="end_turn")

        self.messages = _Messages(self)


class _GradeAndSubmitClient:
    """Returns grade + submit tool use for verifier phase testing."""

    def __init__(self) -> None:
        self._call_count = 0

        class _Messages:
            def __init__(self_, client: _GradeAndSubmitClient) -> None:
                self_._client = client

            def create(self_, **kwargs: Any) -> _FakeResponse:
                count = self_._client._call_count
                self_._client._call_count += 1
                if count == 0:
                    return _FakeResponse(
                        content=[
                            _FakeToolUseBlock(
                                id="tu-1",
                                name="grade",
                                input={
                                    "req_id": "R-01",
                                    "grade": "A",
                                    "grade_reason": "Excellent",
                                },
                            ),
                            _FakeToolUseBlock(
                                id="tu-2",
                                name="submit",
                                input={},
                            ),
                        ],
                        stop_reason="tool_use",
                    )
                return _FakeResponse(content=[], stop_reason="end_turn")

        self.messages = _Messages(self)


class _RaisingClient:
    """Raises an exception on the first API call."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

        class _Messages:
            def __init__(self_, client: _RaisingClient) -> None:
                self_._client = client

            def create(self_, **kwargs: Any) -> _FakeResponse:
                raise self_._client._exc

        self.messages = _Messages(self)


# ---------------------------------------------------------------------------
# AgentRunnerInfo
# ---------------------------------------------------------------------------


def test_agent_info_type() -> None:
    agent = ClaudeSDKAgent()
    assert agent.info.agent_type == AgentRunnerType.CLAUDE_SDK


def test_agent_info_name() -> None:
    agent = ClaudeSDKAgent()
    assert agent.info.name == "Claude SDK"


def test_agent_class_name_attribute() -> None:
    assert ClaudeSDKAgent.name == "Claude SDK"


# ---------------------------------------------------------------------------
# Tool schema definitions
# ---------------------------------------------------------------------------


def test_builder_tools_contains_update_checklist() -> None:
    names = {t["name"] for t in _BUILDER_TOOLS}
    assert "update_checklist" in names


def test_builder_tools_contains_submit() -> None:
    names = {t["name"] for t in _BUILDER_TOOLS}
    assert "submit" in names


def test_builder_tools_does_not_contain_grade() -> None:
    names = {t["name"] for t in _BUILDER_TOOLS}
    assert "grade" not in names


def test_verifier_tools_contains_grade() -> None:
    names = {t["name"] for t in _VERIFIER_TOOLS}
    assert "grade" in names


def test_verifier_tools_contains_submit() -> None:
    names = {t["name"] for t in _VERIFIER_TOOLS}
    assert "submit" in names


# ---------------------------------------------------------------------------
# build_claude_sdk_prompt
# ---------------------------------------------------------------------------


def test_build_prompt_builder_contains_update_checklist() -> None:
    prompt = build_claude_sdk_prompt(_ctx(), is_verifier=False)
    assert "update_checklist" in prompt


def test_build_prompt_builder_contains_task_prompt() -> None:
    prompt = build_claude_sdk_prompt(_ctx(prompt="Special task desc."), is_verifier=False)
    assert "Special task desc." in prompt


def test_build_prompt_builder_contains_requirements() -> None:
    ctx = _ctx(requirements=["R-01: first req", "R-02: second req"])
    prompt = build_claude_sdk_prompt(ctx, is_verifier=False)
    assert "R-01: first req" in prompt
    assert "R-02: second req" in prompt


def test_build_prompt_verifier_contains_grade() -> None:
    prompt = build_claude_sdk_prompt(_ctx(), is_verifier=True)
    assert "grade" in prompt


def test_build_prompt_verifier_contains_task_prompt() -> None:
    prompt = build_claude_sdk_prompt(_ctx(prompt="Verifier text."), is_verifier=True)
    assert "Verifier text." in prompt


def test_build_prompt_builder_and_verifier_differ() -> None:
    ctx = _ctx()
    assert build_claude_sdk_prompt(ctx, is_verifier=False) != build_claude_sdk_prompt(
        ctx, is_verifier=True
    )


# ---------------------------------------------------------------------------
# _dispatch_tool — tool routing
# ---------------------------------------------------------------------------


async def test_dispatch_update_checklist_invokes_callback() -> None:
    received: list[tuple[str, ChecklistStatus, str | None]] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append((req_id, status, note))

    result = await _dispatch_tool(
        "update_checklist",
        {"req_id": "R-01", "status": "done", "note": "done it"},
        on_checklist_update=capture,
        on_submit=_noop_submit,
        on_grade=None,
    )
    assert received == [("R-01", ChecklistStatus.DONE, "done it")]
    assert "R-01" in result


async def test_dispatch_update_checklist_blocked_status() -> None:
    received: list[ChecklistStatus] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append(status)

    await _dispatch_tool(
        "update_checklist",
        {"req_id": "R-02", "status": "blocked"},
        on_checklist_update=capture,
        on_submit=_noop_submit,
        on_grade=None,
    )
    assert received == [ChecklistStatus.BLOCKED]


async def test_dispatch_submit_invokes_callback() -> None:
    submitted: list[bool] = []

    async def capture_submit() -> None:
        submitted.append(True)

    result = await _dispatch_tool(
        "submit",
        {},
        on_checklist_update=_noop_checklist,
        on_submit=capture_submit,
        on_grade=None,
    )
    assert submitted == [True]
    assert "submitted" in result.lower()


async def test_dispatch_grade_invokes_on_grade_callback() -> None:
    grades: list[tuple[str, str, str | None]] = []

    async def capture_grade(req_id: str, grade: str, reason: str | None) -> None:
        grades.append((req_id, grade, reason))

    result = await _dispatch_tool(
        "grade",
        {"req_id": "R-01", "grade": "A", "grade_reason": "Perfect"},
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
        on_grade=capture_grade,
    )
    assert grades == [("R-01", "A", "Perfect")]
    assert "A" in result


async def test_dispatch_grade_ignored_in_builder_phase() -> None:
    """grade tool returns a message when on_grade is None (builder phase)."""
    result = await _dispatch_tool(
        "grade",
        {"req_id": "R-01", "grade": "A"},
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
        on_grade=None,
    )
    # No error raised; returns informational message.
    assert isinstance(result, str)


async def test_dispatch_request_clarification_does_not_raise() -> None:
    result = await _dispatch_tool(
        "request_clarification",
        {"question": "What does R-01 mean?"},
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
        on_grade=None,
    )
    assert isinstance(result, str)


async def test_dispatch_unknown_tool_does_not_raise() -> None:
    result = await _dispatch_tool(
        "some_unknown_tool",
        {},
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
        on_grade=None,
    )
    assert "Unknown tool" in result


# ---------------------------------------------------------------------------
# cancel()
# ---------------------------------------------------------------------------


async def test_cancel_sets_cancelled_flag() -> None:
    agent = ClaudeSDKAgent()
    assert agent._cancelled is False
    await agent.cancel()
    assert agent._cancelled is True


async def test_cancel_is_idempotent() -> None:
    agent = ClaudeSDKAgent()
    await agent.cancel()
    await agent.cancel()  # second call must not raise
    assert agent._cancelled is True


async def test_cancel_many_times_is_idempotent() -> None:
    agent = ClaudeSDKAgent()
    for _ in range(10):
        await agent.cancel()
    assert agent._cancelled is True


# ---------------------------------------------------------------------------
# execute() — cancelled before start
# ---------------------------------------------------------------------------


async def test_execute_raises_agent_cancelled_error_if_already_cancelled() -> None:
    agent = ClaudeSDKAgent(api_key="sk-ant-test", _client=_SingleEndTurnClient())
    await agent.cancel()
    with pytest.raises(AgentCancelledError):
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )


# ---------------------------------------------------------------------------
# execute() — no SDK available
# ---------------------------------------------------------------------------


async def test_execute_raises_agent_not_available_when_sdk_not_installed() -> None:
    """When _SDK_AVAILABLE is False the agent raises AgentNotAvailableError."""
    import orchestrator.agents.claude_sdk as module

    original = module._SDK_AVAILABLE
    try:
        module._SDK_AVAILABLE = False
        agent = ClaudeSDKAgent(api_key="sk-ant-test")
        with pytest.raises(AgentNotAvailableError) as exc_info:
            await agent.execute(
                context=_ctx(),
                on_checklist_update=_noop_checklist,
                on_submit=_noop_submit,
            )
        assert exc_info.value.agent_type == AgentRunnerType.CLAUDE_SDK.value
    finally:
        module._SDK_AVAILABLE = original


# ---------------------------------------------------------------------------
# execute() — no credentials
# ---------------------------------------------------------------------------


async def test_execute_raises_agent_not_available_when_no_credentials() -> None:
    # _environ={} triggers test mode: no env-var or keychain fallback.
    agent = ClaudeSDKAgent(api_key=None, auth_token=None, _environ={})
    with pytest.raises(AgentNotAvailableError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_type == AgentRunnerType.CLAUDE_SDK.value


# ---------------------------------------------------------------------------
# execute() — end_turn flow (auto-submit)
# ---------------------------------------------------------------------------


async def test_execute_end_turn_auto_submits() -> None:
    """When Claude returns end_turn, execute() calls on_submit automatically."""
    submitted: list[bool] = []

    async def capture_submit() -> None:
        submitted.append(True)

    agent = ClaudeSDKAgent(
        api_key="sk-ant-test",
        _client=_SingleEndTurnClient(text="All done."),
    )
    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=capture_submit,
    )
    assert isinstance(result, ExecutionResult)
    assert result.success is True
    assert submitted == [True]


async def test_execute_end_turn_collects_output_lines() -> None:
    """Text blocks in the response are collected as output_lines."""
    agent = ClaudeSDKAgent(
        api_key="sk-ant-test",
        _client=_SingleEndTurnClient(text="I completed the task."),
    )
    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )
    assert "I completed the task." in result.output_lines


async def test_execute_end_turn_accumulates_token_metrics() -> None:
    """Token counts from the API response are accumulated in metrics."""
    agent = ClaudeSDKAgent(
        api_key="sk-ant-test",
        _client=_SingleEndTurnClient(),
    )
    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )
    assert result.metrics.tokens_read > 0
    assert result.metrics.tokens_write > 0


async def test_execute_end_turn_calls_on_output_callback() -> None:
    """on_output callback receives text lines as they are collected."""
    received_lines: list[str] = []

    async def capture_output(lines: list[str]) -> None:
        received_lines.extend(lines)

    agent = ClaudeSDKAgent(
        api_key="sk-ant-test",
        _client=_SingleEndTurnClient(text="Output line."),
    )
    await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
        on_output=capture_output,
    )
    assert "Output line." in received_lines


# ---------------------------------------------------------------------------
# execute() — tool_use flow (builder phase)
# ---------------------------------------------------------------------------


async def test_execute_tool_use_dispatches_update_checklist_and_submit() -> None:
    """Builder phase: Claude calls update_checklist then submit via tool_use."""
    updates: list[tuple[str, ChecklistStatus, str | None]] = []
    submits: list[bool] = []

    async def capture_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        updates.append((req_id, status, note))

    async def capture_submit() -> None:
        submits.append(True)

    agent = ClaudeSDKAgent(api_key="sk-ant-test", _client=_ToolUseClient())
    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=capture_update,
        on_submit=capture_submit,
    )
    assert result.success is True
    assert len(updates) == 1
    assert updates[0] == ("R-01", ChecklistStatus.DONE, "done")
    assert submits == [True]


async def test_execute_tool_use_counts_actions() -> None:
    """num_actions in metrics counts tool_use blocks processed."""
    agent = ClaudeSDKAgent(api_key="sk-ant-test", _client=_ToolUseClient())
    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )
    # _ToolUseClient has 2 tool_use blocks (update_checklist + submit)
    assert result.metrics.num_actions == 2


# ---------------------------------------------------------------------------
# execute() — verifier phase
# ---------------------------------------------------------------------------


async def test_execute_verifier_phase_dispatches_grade() -> None:
    """Verifier phase: Claude calls grade then submit."""
    grades: list[tuple[str, str, str | None]] = []
    submits: list[bool] = []

    async def capture_grade(req_id: str, grade: str, reason: str | None) -> None:
        grades.append((req_id, grade, reason))

    async def capture_submit() -> None:
        submits.append(True)

    agent = ClaudeSDKAgent(api_key="sk-ant-test", _client=_GradeAndSubmitClient())
    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=capture_submit,
        on_grade=capture_grade,
    )
    assert result.success is True
    assert grades == [("R-01", "A", "Excellent")]
    assert submits == [True]


async def test_execute_builder_phase_detected_when_on_grade_is_none() -> None:
    """Builder phase: prompt contains update_checklist instructions."""
    ctx = _ctx()
    prompt = build_claude_sdk_prompt(ctx, is_verifier=False)
    assert "update_checklist" in prompt
    assert "Grade EVERY requirement" not in prompt


async def test_execute_verifier_phase_detected_when_on_grade_is_provided() -> None:
    """Verifier phase: prompt contains grade instructions."""
    ctx = _ctx()
    prompt = build_claude_sdk_prompt(ctx, is_verifier=True)
    assert "Grade EVERY requirement" in prompt


# ---------------------------------------------------------------------------
# execute() — error mapping
# ---------------------------------------------------------------------------


async def test_execute_api_error_raises_agent_execution_error() -> None:
    """Any API exception maps to AgentExecutionError (not bare Exception)."""
    agent = ClaudeSDKAgent(
        api_key="sk-ant-test",
        _client=_RaisingClient(RuntimeError("connection refused")),
    )
    with pytest.raises(AgentExecutionError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_type == AgentRunnerType.CLAUDE_SDK.value


async def test_execute_api_error_does_not_leak_secret_in_message() -> None:
    """AgentExecutionError message must not contain the raw API key."""
    secret = "sk-ant-supersecret-key"  # pragma: allowlist secret
    agent = ClaudeSDKAgent(
        api_key=secret,
        _client=_RaisingClient(RuntimeError(f"auth failed: {secret}")),
    )
    with pytest.raises(AgentExecutionError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    # The error message must not expose the raw exception text (which contains the secret).
    assert secret not in exc_info.value.message


async def test_execute_asyncio_cancelled_error_maps_to_agent_cancelled_error() -> None:
    """asyncio.CancelledError from a thread is re-raised as AgentCancelledError."""
    agent = ClaudeSDKAgent(
        api_key="sk-ant-test",
        _client=_RaisingClient(asyncio.CancelledError()),
    )
    with pytest.raises(AgentCancelledError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_type == AgentRunnerType.CLAUDE_SDK.value


async def test_execute_cancelled_before_start_raises_agent_cancelled_error() -> None:
    agent = ClaudeSDKAgent(api_key="sk-ant-test", _client=_SingleEndTurnClient())
    await agent.cancel()
    with pytest.raises(AgentCancelledError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_type == AgentRunnerType.CLAUDE_SDK.value


# ---------------------------------------------------------------------------
# execute() — max_iterations exhausted
# ---------------------------------------------------------------------------


async def test_execute_max_iterations_auto_submits() -> None:
    """When max_iterations is reached without submit, on_submit is called."""
    submitted: list[bool] = []

    async def capture_submit() -> None:
        submitted.append(True)

    # Client always returns end_turn but we limit to 1 iteration.
    # end_turn will auto-submit on the first call.
    agent = ClaudeSDKAgent(
        api_key="sk-ant-test",
        _client=_SingleEndTurnClient(),
        max_iterations=1,
    )
    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=capture_submit,
    )
    assert result.success is True
    assert submitted == [True]


# ---------------------------------------------------------------------------
# get_quota
# ---------------------------------------------------------------------------


def test_get_quota_returns_none() -> None:
    """ClaudeSDKAgent does not support quota — always returns None."""
    agent = ClaudeSDKAgent()
    assert agent.get_quota() is None


def test_get_quota_with_fetcher_returns_none() -> None:
    """Fetcher argument is accepted but result is still None."""
    agent = ClaudeSDKAgent()

    class _AnyFetcher:
        def fetch_openai_credits(self, api_key: str) -> dict[str, Any]:
            return {"total_granted": 100.0, "total_used": 10.0}

    assert agent.get_quota(fetcher=_AnyFetcher()) is None


# ---------------------------------------------------------------------------
# Constructor — API key resolution
# ---------------------------------------------------------------------------


def test_api_key_from_explicit_arg() -> None:
    agent = ClaudeSDKAgent(api_key="sk-ant-explicit", _environ={})
    assert agent._api_key == "sk-ant-explicit"


def test_api_key_from_environ() -> None:
    agent = ClaudeSDKAgent(api_key=None, _environ={"ANTHROPIC_API_KEY": "sk-ant-env"})
    assert agent._api_key == "sk-ant-env"


def test_explicit_api_key_overrides_environ() -> None:
    agent = ClaudeSDKAgent(
        api_key="sk-ant-explicit",
        _environ={"ANTHROPIC_API_KEY": "sk-ant-env"},
    )
    assert agent._api_key == "sk-ant-explicit"


def test_no_api_key_results_in_none_when_no_env() -> None:
    agent = ClaudeSDKAgent(api_key=None, _environ={})
    # _environ={} (test mode) skips os.environ and keychain lookups.
    assert agent._api_key is None
    assert agent._auth_token is None


def test_auth_token_from_explicit_arg() -> None:
    agent = ClaudeSDKAgent(auth_token="sk-ant-oat01-test", _environ={})
    assert agent._auth_token == "sk-ant-oat01-test"
    assert agent._api_key is None


def test_auth_token_from_environ() -> None:
    agent = ClaudeSDKAgent(api_key=None, _environ={"ANTHROPIC_AUTH_TOKEN": "sk-ant-oat01-env"})
    assert agent._auth_token == "sk-ant-oat01-env"
    assert agent._api_key is None


def test_api_key_takes_priority_over_auth_token() -> None:
    agent = ClaudeSDKAgent(
        api_key="sk-ant-key",
        auth_token="sk-ant-oat01-token",
        _environ={},
    )
    assert agent._api_key == "sk-ant-key"
    assert agent._auth_token == "sk-ant-oat01-token"


# ---------------------------------------------------------------------------
# AgentRunnerType enum registration
# ---------------------------------------------------------------------------


def test_claude_sdk_agent_type_in_enum() -> None:
    assert AgentRunnerType.CLAUDE_SDK == "claude_sdk"
    assert AgentRunnerType.CLAUDE_SDK in AgentRunnerType


def test_claude_sdk_is_distinct_from_other_types() -> None:
    other_types = {
        AgentRunnerType.OPENHANDS_LOCAL,
        AgentRunnerType.OPENHANDS_DOCKER,
        AgentRunnerType.CLI_SUBPROCESS,
        AgentRunnerType.USER_MANAGED,
        AgentRunnerType.CODEX_SERVER,
    }
    assert AgentRunnerType.CLAUDE_SDK not in other_types


# ---------------------------------------------------------------------------
# Tool filtering: step-level tools are additive to phase tools
# ---------------------------------------------------------------------------


class TestBuildToolList:
    """Tests for _build_tool_list() — additive step-level tool filtering."""

    def test_builder_without_available_tools(self) -> None:
        """Builder phase returns standard builder tools when available_tools is None."""
        tools = _build_tool_list(is_verifier=False, available_tools=None)
        tool_names = {t["name"] for t in tools}

        # Should have all builder phase tools
        assert "update_checklist" in tool_names
        assert "submit" in tool_names
        assert "request_clarification" in tool_names
        # Builder should NOT have grade
        assert "grade" not in tool_names

    def test_verifier_without_available_tools(self) -> None:
        """Verifier phase returns standard verifier tools when available_tools is None."""
        tools = _build_tool_list(is_verifier=True, available_tools=None)
        tool_names = {t["name"] for t in tools}

        # Should have all verifier phase tools
        assert "grade" in tool_names
        assert "update_checklist" in tool_names
        assert "submit" in tool_names
        assert "request_clarification" in tool_names

    def test_phase_tools_always_included(self) -> None:
        """Phase tools are always included regardless of available_tools."""
        tools = _build_tool_list(is_verifier=False, available_tools=["terminal"])
        tool_names = {t["name"] for t in tools}

        # Phase tools must always be present
        assert "update_checklist" in tool_names
        assert "submit" in tool_names
        assert "request_clarification" in tool_names

    def test_verifier_phase_tools_always_included(self) -> None:
        """Verifier phase tools are always included even when available_tools is provided."""
        tools = _build_tool_list(is_verifier=True, available_tools=["terminal"])
        tool_names = {t["name"] for t in tools}

        # Verifier phase tools must always be present
        assert "grade" in tool_names
        assert "update_checklist" in tool_names
        assert "submit" in tool_names

    def test_unknown_tool_produces_warning(self, caplog) -> None:
        """Unknown tool names produce a warning and are skipped."""
        import logging

        with caplog.at_level(logging.WARNING):
            tools = _build_tool_list(is_verifier=False, available_tools=["nonexistent_tool"])

        # Should log a warning about the unknown tool
        assert "nonexistent_tool" in caplog.text
        assert "Unknown tool" in caplog.text

        # But should still return the phase tools
        tool_names = {t["name"] for t in tools}
        assert "submit" in tool_names

    def test_multiple_unknown_tools_produce_warnings(self, caplog) -> None:
        """Multiple unknown tools each produce a warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            tools = _build_tool_list(
                is_verifier=False,
                available_tools=["fake1", "fake2", "fake3"],
            )

        # All three unknown tools should be mentioned in warnings
        assert "fake1" in caplog.text
        assert "fake2" in caplog.text
        assert "fake3" in caplog.text

        # But should still return the phase tools
        tool_names = {t["name"] for t in tools}
        assert "submit" in tool_names

    def test_duplicate_phase_tool_not_added(self) -> None:
        """If available_tools contains a tool already in phase tools, it's not duplicated."""
        tools = _build_tool_list(is_verifier=False, available_tools=["submit"])
        tool_names = [t["name"] for t in tools]

        # Count how many times "submit" appears
        submit_count = tool_names.count("submit")
        assert submit_count == 1  # Should appear exactly once, not twice

    def test_empty_available_tools_list(self) -> None:
        """Empty available_tools list returns only phase tools."""
        tools = _build_tool_list(is_verifier=False, available_tools=[])
        tool_names = {t["name"] for t in tools}

        # Should have phase tools
        assert "update_checklist" in tool_names
        assert "submit" in tool_names

    def test_builder_tools_count_baseline(self) -> None:
        """Builder tools have the expected baseline count."""
        tools = _build_tool_list(is_verifier=False, available_tools=None)
        # Builder phase should have: update_checklist, submit, request_clarification (3 tools)
        assert len(tools) == 3

    def test_verifier_tools_count_baseline(self) -> None:
        """Verifier tools have the expected baseline count."""
        tools = _build_tool_list(is_verifier=True, available_tools=None)
        # Verifier phase should have: grade, update_checklist, submit, request_clarification (4 tools)
        assert len(tools) == 4
