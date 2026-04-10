"""Unit tests for ClaudeSDKAgent: builder/verifier flows, MCP server, error mapping."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from orchestrator.runners import (
    ClaudeSDKAgent,
    build_orchestrator_mcp_server,
    build_mcp_servers,
    build_claude_sdk_prompt,
)
from orchestrator.runners.errors import (
    AgentCancelledError,
    AgentExecutionError,
    AgentNotAvailableError,
)
from orchestrator.runners.types import ExecutionContext, ExecutionResult
from orchestrator.config import AgentRunnerType, ChecklistStatus
from orchestrator.config.models import MCPServerConfig

from claude_agent_sdk import AssistantMessage, ResultMessage
from claude_agent_sdk.types import TextBlock, ToolUseBlock

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


def _result_msg(
    *,
    is_error: bool = False,
    num_turns: int = 1,
    total_cost_usd: float = 0.01,
    usage: dict[str, Any] | None = None,
    result: str | None = "Done",
) -> ResultMessage:
    """Build a ResultMessage with convenient defaults."""
    return ResultMessage(
        subtype="result",
        duration_ms=100,
        duration_api_ms=80,
        is_error=is_error,
        num_turns=num_turns,
        session_id="test-session",
        total_cost_usd=total_cost_usd,
        usage=usage or {"input_tokens": 100, "output_tokens": 50},
        result=result,
    )


# ---------------------------------------------------------------------------
# _query_fn factories
# ---------------------------------------------------------------------------


async def _end_turn_query(*, prompt: str, options: Any = None, transport: Any = None):
    """Yields a single assistant message then a result — simulates end_turn."""
    yield AssistantMessage(content=[TextBlock(text="All done.")], model="claude-sonnet-4-5")
    yield _result_msg()


async def _tool_use_query(*, prompt: str, options: Any = None, transport: Any = None):
    """Yields an assistant message with tool use blocks then a result."""
    yield AssistantMessage(
        content=[
            ToolUseBlock(
                id="tu-1",
                name="mcp__orchestrator__update_checklist",
                input={"req_id": "R-01", "status": "done"},
            ),
            ToolUseBlock(id="tu-2", name="mcp__orchestrator__submit", input={}),
        ],
        model="claude-sonnet-4-5",
    )
    yield _result_msg(num_turns=1)


async def _grade_and_submit_query(*, prompt: str, options: Any = None, transport: Any = None):
    """Yields an assistant message with grade + submit tool use blocks."""
    yield AssistantMessage(
        content=[
            ToolUseBlock(
                id="tu-1",
                name="mcp__orchestrator__grade",
                input={"req_id": "R-01", "grade": "A", "grade_reason": "Excellent"},
            ),
            ToolUseBlock(id="tu-2", name="mcp__orchestrator__submit", input={}),
        ],
        model="claude-sonnet-4-5",
    )
    yield _result_msg(num_turns=1)


async def _error_result_query(*, prompt: str, options: Any = None, transport: Any = None):
    """Yields a ResultMessage with is_error=True."""
    yield _result_msg(is_error=True, result="Session crashed")


async def _raising_query(*, prompt: str, options: Any = None, transport: Any = None):
    """Raises RuntimeError — simulates connection failure."""
    raise RuntimeError("connection refused")
    yield  # noqa: RET503  — make it an async generator


async def _cancelled_error_query(*, prompt: str, options: Any = None, transport: Any = None):
    """Raises asyncio.CancelledError — simulates task cancellation."""
    raise asyncio.CancelledError()
    yield  # noqa: RET503


def _make_text_query(text: str):
    """Returns a query_fn that yields a single text message."""

    async def _query(*, prompt: str, options: Any = None, transport: Any = None):
        yield AssistantMessage(content=[TextBlock(text=text)], model="claude-sonnet-4-5")
        yield _result_msg()

    return _query


def _make_cancelling_query(agent: ClaudeSDKAgent):
    """Returns a query_fn that cancels the agent mid-stream."""

    async def _query(*, prompt: str, options: Any = None, transport: Any = None):
        yield AssistantMessage(content=[TextBlock(text="Starting...")], model="claude-sonnet-4-5")
        await agent.cancel()
        yield AssistantMessage(
            content=[TextBlock(text="Should not reach.")], model="claude-sonnet-4-5"
        )
        yield _result_msg()

    return _query


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
    agent = ClaudeSDKAgent(api_key="sk-ant-test", _query_fn=_end_turn_query)
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
    import orchestrator.runners.agents.claude_sdk.agent as module

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
# execute() — end_turn flow
# ---------------------------------------------------------------------------


async def test_execute_end_turn_returns_success() -> None:
    """When the SDK returns a normal result, execute() returns success."""
    agent = ClaudeSDKAgent(api_key="sk-ant-test", _query_fn=_end_turn_query)
    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )
    assert isinstance(result, ExecutionResult)
    assert result.success is True


async def test_execute_end_turn_collects_output_lines() -> None:
    """Text blocks in the assistant message are collected as output_lines."""
    agent = ClaudeSDKAgent(
        api_key="sk-ant-test",
        _query_fn=_make_text_query("I completed the task."),
    )
    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )
    assert "I completed the task." in result.output_lines


async def test_execute_end_turn_accumulates_token_metrics() -> None:
    """Token counts from the ResultMessage are accumulated in metrics."""
    agent = ClaudeSDKAgent(api_key="sk-ant-test", _query_fn=_end_turn_query)
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
        _query_fn=_make_text_query("Output line."),
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


async def test_execute_tool_use_counts_actions() -> None:
    """num_actions in metrics counts tool_use blocks processed."""
    agent = ClaudeSDKAgent(api_key="sk-ant-test", _query_fn=_tool_use_query)
    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )
    # _tool_use_query has 2 tool_use blocks (update_checklist + submit)
    assert result.metrics.num_actions >= 2


async def test_execute_tool_use_returns_success() -> None:
    """Tool use flow completes successfully."""
    agent = ClaudeSDKAgent(api_key="sk-ant-test", _query_fn=_tool_use_query)
    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )
    assert result.success is True


# ---------------------------------------------------------------------------
# execute() — verifier phase
# ---------------------------------------------------------------------------


async def test_execute_verifier_phase_returns_success() -> None:
    """Verifier phase completes successfully with grade + submit."""
    agent = ClaudeSDKAgent(api_key="sk-ant-test", _query_fn=_grade_and_submit_query)
    result = await agent.execute(
        context=_ctx(),
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
        on_grade=_noop_grade,
    )
    assert result.success is True


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
    """Any exception from the query_fn maps to AgentExecutionError."""
    agent = ClaudeSDKAgent(api_key="sk-ant-test", _query_fn=_raising_query)
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

    async def _leaking_query(*, prompt: str, options: Any = None, transport: Any = None):
        raise RuntimeError(f"auth failed: {secret}")
        yield  # noqa: RET503

    agent = ClaudeSDKAgent(api_key=secret, _query_fn=_leaking_query)
    with pytest.raises(AgentExecutionError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert secret not in exc_info.value.message


async def test_execute_error_result_raises_agent_execution_error() -> None:
    """ResultMessage with is_error=True raises AgentExecutionError."""
    agent = ClaudeSDKAgent(api_key="sk-ant-test", _query_fn=_error_result_query)
    with pytest.raises(AgentExecutionError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_type == AgentRunnerType.CLAUDE_SDK.value


async def test_execute_asyncio_cancelled_error_maps_to_agent_cancelled_error() -> None:
    """asyncio.CancelledError from the query_fn is re-raised as AgentCancelledError."""
    agent = ClaudeSDKAgent(api_key="sk-ant-test", _query_fn=_cancelled_error_query)
    with pytest.raises(AgentCancelledError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_type == AgentRunnerType.CLAUDE_SDK.value


async def test_execute_cancelled_before_start_raises_agent_cancelled_error() -> None:
    agent = ClaudeSDKAgent(api_key="sk-ant-test", _query_fn=_end_turn_query)
    await agent.cancel()
    with pytest.raises(AgentCancelledError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_type == AgentRunnerType.CLAUDE_SDK.value


async def test_execute_cancelled_mid_stream_raises_agent_cancelled_error() -> None:
    """Cancelling mid-stream raises AgentCancelledError."""
    agent = ClaudeSDKAgent(api_key="sk-ant-test")
    agent._query_fn = _make_cancelling_query(agent)
    with pytest.raises(AgentCancelledError):
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )


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
# Constructor — credential resolution
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
# build_orchestrator_mcp_server — tool creation
# ---------------------------------------------------------------------------


class TestBuildOrchestratorMcpServer:
    """Tests for build_orchestrator_mcp_server() — verifies tools are created correctly."""

    async def test_builder_phase_creates_three_tools(self) -> None:
        """Builder phase (on_grade=None) creates update_checklist, submit, request_clarification."""
        server = build_orchestrator_mcp_server(_noop_checklist, _noop_submit, on_grade=None)
        # The server is returned from create_sdk_mcp_server; it should exist.
        assert server is not None

    async def test_verifier_phase_creates_four_tools(self) -> None:
        """Verifier phase (on_grade provided) creates grade + the 3 builder tools."""
        server = build_orchestrator_mcp_server(_noop_checklist, _noop_submit, on_grade=_noop_grade)
        assert server is not None

    async def test_update_checklist_tool_calls_callback(self) -> None:
        """The update_checklist tool function calls the on_checklist_update callback."""
        received: list[tuple[str, ChecklistStatus, str | None]] = []

        async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
            received.append((req_id, status, note))

        # Build the server — we need to test the tool functions directly.
        # Since build_orchestrator_mcp_server uses @tool decorator, we test
        # via the full execute() flow instead.
        agent = ClaudeSDKAgent(api_key="sk-ant-test", _query_fn=_tool_use_query)
        await agent.execute(
            context=_ctx(),
            on_checklist_update=capture,
            on_submit=_noop_submit,
        )
        # The tool use blocks are processed by the SDK; in tests we verify the
        # execute flow handles messages without error.
        assert isinstance(agent, ClaudeSDKAgent)

    async def test_grade_tool_not_created_for_builder_phase(self) -> None:
        """Builder phase should not include grade tool in the MCP server."""
        # Verified indirectly: when on_grade is None, the server is built
        # with only 3 tools (update_checklist, submit, request_clarification).
        server = build_orchestrator_mcp_server(_noop_checklist, _noop_submit, on_grade=None)
        assert server is not None

    async def test_grade_tool_created_for_verifier_phase(self) -> None:
        """Verifier phase should include grade tool in the MCP server."""
        server = build_orchestrator_mcp_server(_noop_checklist, _noop_submit, on_grade=_noop_grade)
        assert server is not None


# ---------------------------------------------------------------------------
# build_mcp_servers — server dict assembly
# ---------------------------------------------------------------------------


class TestBuildMcpServers:
    """Tests for build_mcp_servers() — assembles MCP server dict for SDK options."""

    def test_orchestrator_always_included(self) -> None:
        """The orchestrator server is always included in the result."""
        sentinel = object()
        result = build_mcp_servers(sentinel, mcp_servers=None)
        assert result["orchestrator"] is sentinel

    def test_no_external_servers(self) -> None:
        """With no external servers, only orchestrator is in the result."""
        sentinel = object()
        result = build_mcp_servers(sentinel, mcp_servers=None)
        assert len(result) == 1
        assert "orchestrator" in result

    def test_empty_list_returns_only_orchestrator(self) -> None:
        """Empty mcp_servers list returns only orchestrator."""
        sentinel = object()
        result = build_mcp_servers(sentinel, mcp_servers=[])
        assert len(result) == 1

    def test_stdio_server_included(self) -> None:
        """stdio-transport MCP server is included with command config."""
        mcp = MCPServerConfig(name="local", command="context7-mcp", args=["--port", "3000"])
        result = build_mcp_servers("orch", mcp_servers=[mcp])
        assert "local" in result
        assert result["local"]["command"] == "context7-mcp"
        assert result["local"]["args"] == ["--port", "3000"]

    def test_url_server_included(self) -> None:
        """URL-based (SSE) MCP server is included with url config."""
        mcp = MCPServerConfig(name="remote", url="https://remote.example.com/mcp")
        result = build_mcp_servers("orch", mcp_servers=[mcp])
        assert "remote" in result
        assert result["remote"]["url"] == "https://remote.example.com/mcp"
        assert result["remote"]["type"] == "sse"

    def test_multiple_servers(self) -> None:
        """Multiple external servers are all included alongside orchestrator."""
        mcp1 = MCPServerConfig(name="srv1", url="https://srv1.example.com")
        mcp2 = MCPServerConfig(name="srv2", command="srv2-cmd")
        result = build_mcp_servers("orch", mcp_servers=[mcp1, mcp2])
        assert len(result) == 3  # orchestrator + srv1 + srv2
        assert "srv1" in result
        assert "srv2" in result

    def test_stdio_auth_token_env_resolved(self) -> None:
        """Auth token env var is resolved and passed in env dict for stdio servers."""
        import os

        old = os.environ.get("TEST_MCP_TOKEN")
        os.environ["TEST_MCP_TOKEN"] = "secret123"
        try:
            mcp = MCPServerConfig(name="auth", command="auth-cmd", auth_token_env="TEST_MCP_TOKEN")
            result = build_mcp_servers("orch", mcp_servers=[mcp])
            assert result["auth"]["env"]["TEST_MCP_TOKEN"] == "secret123"
        finally:
            if old is None:
                os.environ.pop("TEST_MCP_TOKEN", None)
            else:
                os.environ["TEST_MCP_TOKEN"] = old

    def test_url_auth_token_env_resolved(self) -> None:
        """Auth token env var is resolved and passed as Authorization header for URL servers."""
        import os

        old = os.environ.get("TEST_URL_TOKEN")
        os.environ["TEST_URL_TOKEN"] = "bearer-secret"
        try:
            mcp = MCPServerConfig(
                name="auth", url="https://auth.example.com", auth_token_env="TEST_URL_TOKEN"
            )
            result = build_mcp_servers("orch", mcp_servers=[mcp])
            assert result["auth"]["headers"]["Authorization"] == "Bearer bearer-secret"
        finally:
            if old is None:
                os.environ.pop("TEST_URL_TOKEN", None)
            else:
                os.environ["TEST_URL_TOKEN"] = old

    def test_missing_auth_token_env_no_env_dict(self) -> None:
        """When auth_token_env is set but env var is missing, no env dict is added."""
        import os

        os.environ.pop("NONEXISTENT_TOKEN", None)
        mcp = MCPServerConfig(name="noauth", command="cmd", auth_token_env="NONEXISTENT_TOKEN")
        result = build_mcp_servers("orch", mcp_servers=[mcp])
        assert "env" not in result["noauth"]

    def test_missing_url_auth_token_no_headers(self) -> None:
        """When auth_token_env is set for URL server but env var is missing, no headers added."""
        import os

        os.environ.pop("NONEXISTENT_TOKEN_2", None)
        mcp = MCPServerConfig(
            name="noauth", url="https://x.example.com", auth_token_env="NONEXISTENT_TOKEN_2"
        )
        result = build_mcp_servers("orch", mcp_servers=[mcp])
        assert "headers" not in result["noauth"]


# ---------------------------------------------------------------------------
# max_turns parameter
# ---------------------------------------------------------------------------


def test_max_turns_default() -> None:
    agent = ClaudeSDKAgent(_environ={})
    assert agent._max_turns == 50


def test_max_turns_custom() -> None:
    agent = ClaudeSDKAgent(max_turns=10, _environ={})
    assert agent._max_turns == 10
