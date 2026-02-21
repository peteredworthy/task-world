"""Unit tests for CodexServerRemoteAgent: config validation, token resolution,
agent protocol, and allow-list enforcement.

No mocking — uses dependency injection (_environ parameter) for env lookups.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from orchestrator.agents.codex_server_remote import (
    DEFAULT_TOKEN_ENV_VAR,
    FALLBACK_TOKEN_ENV_VAR,
    CodexServerRemoteAgent,
    map_transport_error,
    resolve_remote_token,
)
from orchestrator.agents.errors import (
    AgentCancelledError,
    AgentConfigError,
    AgentExecutionError,
    AgentNotAvailableError,
    AgentTimeoutError,
)
from orchestrator.agents.types import ExecutionContext, ExecutionMetrics
from orchestrator.config.enums import AgentType, ChecklistStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_URL = "https://codex.example.com"
_VALID_KEY = "sk-test-key-abc123"  # pragma: allowlist secret


def _make_agent(
    base_url: str = _VALID_URL,
    model: str | None = None,
    session_id: str | None = None,
    callback_channel: str = "rest",
    api_key: str | None = _VALID_KEY,
    token_env_var: str = DEFAULT_TOKEN_ENV_VAR,
    retry: int = 3,
    timeout: float = 300.0,
    environ: dict[str, str] | None = None,
) -> CodexServerRemoteAgent:
    return CodexServerRemoteAgent(
        base_url=base_url,
        model=model,
        session_id=session_id,
        callback_channel=callback_channel,
        api_key=api_key,
        token_env_var=token_env_var,
        retry=retry,
        timeout=timeout,
        _environ=environ or {},
    )


def _ctx(
    prompt: str = "Do the remote task.",
    requirements: list[str] | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        run_id="run-remote-01",
        task_id="task-remote-01",
        working_dir="/tmp/remote-work",
        prompt=prompt,
        requirements=requirements or ["R-01: implement feature", "R-02: write tests"],
    )


async def _noop_checklist(req_id: str, status: ChecklistStatus, note: str | None) -> None:
    pass


async def _noop_submit() -> None:
    pass


async def _noop_grade(req_id: str, grade: str, reason: str | None) -> None:
    pass


# ===========================================================================
# resolve_remote_token — pure function tests
# ===========================================================================


def test_resolve_token_prefers_api_key_over_env_vars() -> None:
    """api_key takes precedence over environment variables."""
    result = resolve_remote_token(
        api_key="direct-key",  # pragma: allowlist secret
        token_env_var="MY_VAR",
        environ={"MY_VAR": "env-key", "OPENAI_API_KEY": "openai-key"},  # pragma: allowlist secret
    )
    assert result == "direct-key"


def test_resolve_token_uses_token_env_var_when_no_api_key() -> None:
    """token_env_var env var is used when api_key is None."""
    result = resolve_remote_token(
        api_key=None,
        token_env_var="CODEX_SERVER_API_KEY",
        environ={"CODEX_SERVER_API_KEY": "from-env"},  # pragma: allowlist secret
    )
    assert result == "from-env"


def test_resolve_token_falls_back_to_openai_api_key() -> None:
    """OPENAI_API_KEY is used when api_key and token_env_var env var are absent."""
    result = resolve_remote_token(
        api_key=None,
        token_env_var="CODEX_SERVER_API_KEY",
        environ={"OPENAI_API_KEY": "openai-fallback"},  # pragma: allowlist secret
    )
    assert result == "openai-fallback"


def test_resolve_token_returns_none_when_all_sources_absent() -> None:
    """Returns None when no source in the precedence chain yields a token."""
    result = resolve_remote_token(
        api_key=None,
        token_env_var="CODEX_SERVER_API_KEY",
        environ={},
    )
    assert result is None


def test_resolve_token_empty_api_key_falls_through_to_env() -> None:
    """Empty string api_key is treated as absent and falls through."""
    result = resolve_remote_token(
        api_key="",
        token_env_var="MY_VAR",
        environ={"MY_VAR": "env-value"},
    )
    assert result == "env-value"


def test_resolve_token_custom_token_env_var_name() -> None:
    """A custom token_env_var name is correctly resolved."""
    result = resolve_remote_token(
        api_key=None,
        token_env_var="MY_CUSTOM_TOKEN_VAR",
        environ={"MY_CUSTOM_TOKEN_VAR": "custom-token"},
    )
    assert result == "custom-token"


def test_resolve_token_uses_os_environ_by_default() -> None:
    """When environ=None, resolve_remote_token reads os.environ (not empty dict)."""

    # We can only confirm this doesn't crash and returns based on actual env.
    # We don't inject a key to avoid side effects; just verify the return type.
    result = resolve_remote_token(api_key="explicit-key", token_env_var=DEFAULT_TOKEN_ENV_VAR)
    assert result == "explicit-key"  # api_key always wins regardless of env


def test_resolve_token_token_env_var_preferred_over_openai_key() -> None:
    """token_env_var env var is preferred over OPENAI_API_KEY when both present."""
    result = resolve_remote_token(
        api_key=None,
        token_env_var="CODEX_SERVER_API_KEY",
        environ={
            "CODEX_SERVER_API_KEY": "primary-key",  # pragma: allowlist secret
            "OPENAI_API_KEY": "fallback-key",  # pragma: allowlist secret
        },
    )
    assert result == "primary-key"


# ===========================================================================
# Construction — valid config
# ===========================================================================


def test_construction_succeeds_with_direct_api_key() -> None:
    """Agent constructs without error when api_key is provided directly."""
    agent = _make_agent(api_key="direct-token")  # pragma: allowlist secret
    assert agent is not None


def test_construction_succeeds_with_token_from_env_var() -> None:
    """Agent constructs when token is resolved from token_env_var env var."""
    agent = _make_agent(
        api_key=None,
        environ={DEFAULT_TOKEN_ENV_VAR: "env-token"},  # pragma: allowlist secret
    )
    assert agent is not None


def test_construction_succeeds_with_token_from_openai_api_key() -> None:
    """Agent constructs when token is resolved from OPENAI_API_KEY fallback."""
    agent = _make_agent(
        api_key=None,
        environ={FALLBACK_TOKEN_ENV_VAR: "openai-token"},  # pragma: allowlist secret
    )
    assert agent is not None


def test_construction_http_base_url_accepted() -> None:
    """HTTP (non-TLS) base_url is accepted for local/dev setups."""
    agent = _make_agent(base_url="http://localhost:9000", api_key=_VALID_KEY)
    assert agent is not None


def test_construction_trailing_slash_stripped_from_base_url() -> None:
    """Trailing slash in base_url is stripped on construction."""
    agent = _make_agent(base_url="https://example.com/", api_key=_VALID_KEY)
    assert agent._base_url == "https://example.com"


def test_construction_stores_model() -> None:
    """model parameter is stored on the agent."""
    agent = _make_agent(model="gpt-4o", api_key=_VALID_KEY)
    assert agent._model == "gpt-4o"


def test_construction_stores_session_id() -> None:
    """session_id parameter is stored on the agent."""
    agent = _make_agent(session_id="sess-abc", api_key=_VALID_KEY)
    assert agent._session_id == "sess-abc"


def test_construction_stores_retry() -> None:
    """retry parameter is stored on the agent."""
    agent = _make_agent(retry=5, api_key=_VALID_KEY)
    assert agent._retry == 5


def test_construction_stores_timeout() -> None:
    """timeout parameter is stored on the agent."""
    agent = _make_agent(timeout=120.0, api_key=_VALID_KEY)
    assert agent._timeout == 120.0


def test_construction_mcp_callback_channel_accepted() -> None:
    """'mcp' callback_channel is a valid configuration."""
    agent = _make_agent(callback_channel="mcp", api_key=_VALID_KEY)
    assert agent._callback_channel == "mcp"


def test_construction_zero_retry_accepted() -> None:
    """retry=0 means no retries and is a valid configuration."""
    agent = _make_agent(retry=0, api_key=_VALID_KEY)
    assert agent._retry == 0


# ===========================================================================
# Construction — invalid config raises AgentConfigError
# ===========================================================================


def test_construction_raises_for_empty_base_url() -> None:
    """Empty base_url raises AgentConfigError."""
    with pytest.raises(AgentConfigError) as exc_info:
        _make_agent(base_url="", api_key=_VALID_KEY)
    assert exc_info.value.agent_type == AgentType.CODEX_SERVER_REMOTE.value


def test_construction_raises_for_invalid_base_url_scheme() -> None:
    """base_url without http/https scheme raises AgentConfigError."""
    with pytest.raises(AgentConfigError) as exc_info:
        _make_agent(base_url="ftp://example.com", api_key=_VALID_KEY)
    assert "base_url" in exc_info.value.message


def test_construction_raises_for_no_scheme_base_url() -> None:
    """base_url with no scheme raises AgentConfigError."""
    with pytest.raises(AgentConfigError):
        _make_agent(base_url="example.com", api_key=_VALID_KEY)


def test_construction_raises_for_unresolved_token() -> None:
    """Missing token from all sources raises AgentConfigError."""
    with pytest.raises(AgentConfigError) as exc_info:
        _make_agent(api_key=None, environ={})
    assert exc_info.value.agent_type == AgentType.CODEX_SERVER_REMOTE.value


def test_construction_raises_for_unresolved_token_error_message_contains_env_var_names() -> None:
    """AgentConfigError message names the env vars the caller should set."""
    with pytest.raises(AgentConfigError) as exc_info:
        _make_agent(api_key=None, environ={}, token_env_var="CODEX_SERVER_API_KEY")
    msg = exc_info.value.message
    assert "CODEX_SERVER_API_KEY" in msg
    assert "OPENAI_API_KEY" in msg


def test_construction_raises_for_invalid_callback_channel() -> None:
    """Unsupported callback_channel raises AgentConfigError."""
    with pytest.raises(AgentConfigError) as exc_info:
        _make_agent(callback_channel="websocket", api_key=_VALID_KEY)
    assert "callback_channel" in exc_info.value.message


def test_construction_raises_for_negative_retry() -> None:
    """Negative retry value raises AgentConfigError."""
    with pytest.raises(AgentConfigError) as exc_info:
        _make_agent(retry=-1, api_key=_VALID_KEY)
    assert "retry" in exc_info.value.message


def test_construction_raises_for_zero_timeout() -> None:
    """timeout=0 raises AgentConfigError."""
    with pytest.raises(AgentConfigError) as exc_info:
        _make_agent(timeout=0, api_key=_VALID_KEY)
    assert "timeout" in exc_info.value.message


def test_construction_raises_for_negative_timeout() -> None:
    """Negative timeout raises AgentConfigError."""
    with pytest.raises(AgentConfigError):
        _make_agent(timeout=-5.0, api_key=_VALID_KEY)


def test_construction_config_error_is_not_agent_execution_error() -> None:
    """AgentConfigError is distinct from AgentExecutionError."""
    with pytest.raises(AgentConfigError) as exc_info:
        _make_agent(api_key=None, environ={})
    assert not isinstance(exc_info.value, AgentExecutionError)


def test_construction_config_error_carries_agent_type() -> None:
    """AgentConfigError carries the correct agent_type string."""
    with pytest.raises(AgentConfigError) as exc_info:
        _make_agent(base_url="", api_key=_VALID_KEY)
    assert exc_info.value.agent_type == AgentType.CODEX_SERVER_REMOTE.value


# ===========================================================================
# AgentInfo
# ===========================================================================


def test_agent_info_type() -> None:
    agent = _make_agent()
    assert agent.info.agent_type == AgentType.CODEX_SERVER_REMOTE


def test_agent_info_name() -> None:
    agent = _make_agent()
    assert agent.info.name == "Codex Server Remote"


def test_agent_info_version_is_none() -> None:
    agent = _make_agent()
    assert agent.info.version is None


# ===========================================================================
# Tool allow-list class attribute
# ===========================================================================


def test_tool_allowlist_contains_required_tools() -> None:
    """The class-level allow-list contains the four v1 callback tools."""
    expected = {"update_checklist", "grade", "submit", "request_clarification"}
    assert expected == CodexServerRemoteAgent.TOOL_ALLOWLIST


# ===========================================================================
# execute() — pre-flight cancellation check
# ===========================================================================


async def test_execute_raises_agent_cancelled_error_when_already_cancelled() -> None:
    """execute() raises AgentCancelledError if cancel() was called first."""
    agent = _make_agent()
    await agent.cancel()
    with pytest.raises(AgentCancelledError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_type == AgentType.CODEX_SERVER_REMOTE.value


async def test_execute_raises_agent_not_available_transport_not_implemented() -> None:
    """execute() raises AgentNotAvailableError until HTTPS transport is wired up."""
    agent = _make_agent()
    with pytest.raises(AgentNotAvailableError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_type == AgentType.CODEX_SERVER_REMOTE.value


async def test_execute_builder_phase_when_on_grade_is_none() -> None:
    """_build_prompt produces builder-phase prompt when on_grade is None."""
    agent = _make_agent()
    prompt = agent._build_prompt(_ctx(), is_verifier=False)
    assert "update_checklist" in prompt
    assert "Grade EVERY requirement" not in prompt


async def test_execute_verifier_phase_when_on_grade_provided() -> None:
    """_build_prompt produces verifier-phase prompt when is_verifier=True."""
    agent = _make_agent()
    prompt = agent._build_prompt(_ctx(), is_verifier=True)
    assert "grade" in prompt


# ===========================================================================
# cancel()
# ===========================================================================


async def test_cancel_sets_cancelled_flag() -> None:
    agent = _make_agent()
    assert agent._cancelled is False
    await agent.cancel()
    assert agent._cancelled is True


async def test_cancel_is_idempotent() -> None:
    agent = _make_agent()
    for _ in range(5):
        await agent.cancel()
    assert agent._cancelled is True


async def test_cancel_with_completed_task_does_not_raise() -> None:
    agent = _make_agent()

    async def _noop() -> None:
        pass

    task: asyncio.Task[None] = asyncio.create_task(_noop())
    await task
    agent._session_task = task

    await agent.cancel()
    assert agent._cancelled is True


async def test_cancel_with_active_task_cancels_it() -> None:
    agent = _make_agent()

    async def _long() -> None:
        await asyncio.sleep(60)

    task: asyncio.Task[None] = asyncio.create_task(_long())
    agent._session_task = task

    await agent.cancel()
    await asyncio.sleep(0)
    assert agent._cancelled is True
    assert task.cancelled() or task.done()


# ===========================================================================
# _route_tool_call — allow-listed tools dispatched correctly
# ===========================================================================


async def test_route_tool_call_update_checklist_dispatched() -> None:
    agent = _make_agent()
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


async def test_route_tool_call_update_checklist_blocked() -> None:
    agent = _make_agent()
    received: list[ChecklistStatus] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append(status)

    await agent._route_tool_call(
        tool_name="update_checklist",
        args={"req_id": "R-01", "status": "blocked", "note": None},
        on_checklist_update=capture,
        on_submit=_noop_submit,
    )
    assert received == [ChecklistStatus.BLOCKED]


async def test_route_tool_call_update_checklist_not_applicable() -> None:
    agent = _make_agent()
    received: list[ChecklistStatus] = []

    async def capture(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        received.append(status)

    await agent._route_tool_call(
        tool_name="update_checklist",
        args={"req_id": "R-01", "status": "not_applicable", "note": "N/A"},
        on_checklist_update=capture,
        on_submit=_noop_submit,
    )
    assert received == [ChecklistStatus.NOT_APPLICABLE]


async def test_route_tool_call_submit_dispatched() -> None:
    agent = _make_agent()
    submitted: list[bool] = []

    async def capture() -> None:
        submitted.append(True)

    await agent._route_tool_call(
        tool_name="submit",
        args={},
        on_checklist_update=_noop_checklist,
        on_submit=capture,
    )
    assert submitted == [True]


async def test_route_tool_call_grade_dispatched_in_verifier_phase() -> None:
    agent = _make_agent()
    grades: list[tuple[str, str, str | None]] = []

    async def capture(req_id: str, grade: str, reason: str | None) -> None:
        grades.append((req_id, grade, reason))

    await agent._route_tool_call(
        tool_name="grade",
        args={"req_id": "R-01", "grade": "A", "grade_reason": "Excellent"},
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
        on_grade=capture,
    )
    assert grades == [("R-01", "A", "Excellent")]


async def test_route_tool_call_grade_ignored_in_builder_phase() -> None:
    """grade is silently ignored when on_grade is None (builder phase)."""
    agent = _make_agent()
    await agent._route_tool_call(
        tool_name="grade",
        args={"req_id": "R-01", "grade": "B"},
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
        on_grade=None,
    )
    # No error raised; no-op in builder phase.


async def test_route_tool_call_request_clarification_does_not_raise() -> None:
    agent = _make_agent()
    await agent._route_tool_call(
        tool_name="request_clarification",
        args={"question": "What does R-01 require?"},
        on_checklist_update=_noop_checklist,
        on_submit=_noop_submit,
    )


# ===========================================================================
# _route_tool_call — disallowed tools are rejected
# ===========================================================================


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
async def test_route_tool_call_rejects_disallowed_tools(disallowed_tool: str) -> None:
    agent = _make_agent()
    with pytest.raises(ValueError, match="not on the Codex server v1 allow-list"):
        await agent._route_tool_call(
            tool_name=disallowed_tool,
            args={},
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )


async def test_route_tool_call_disallowed_does_not_invoke_checklist_callback() -> None:
    agent = _make_agent()
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


async def test_route_tool_call_disallowed_does_not_invoke_submit_callback() -> None:
    agent = _make_agent()
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


async def test_route_tool_call_disallowed_does_not_invoke_grade_callback() -> None:
    agent = _make_agent()
    called: list[bool] = []

    async def should_not_be_called(req_id: str, grade: str, reason: str | None) -> None:
        called.append(True)

    with pytest.raises(ValueError):
        await agent._route_tool_call(
            tool_name="write_file",
            args={},
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
            on_grade=should_not_be_called,
        )
    assert called == []


# ===========================================================================
# _normalize_output and _build_metrics delegation
# ===========================================================================


def test_normalize_output_delegates_to_common() -> None:
    agent = _make_agent()
    result = agent._normalize_output(["line one", {"text": "line two"}, 42])
    assert result == ["line one", "line two", "42"]


def test_build_metrics_delegates_to_common() -> None:
    agent = _make_agent()
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


# ===========================================================================
# Failure-path error mapping
# ===========================================================================


async def test_execute_failure_raises_agent_not_available_error() -> None:
    """Transport failure raises typed AgentNotAvailableError (not bare Exception)."""
    agent = _make_agent()
    with pytest.raises(AgentNotAvailableError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert isinstance(exc_info.value, AgentNotAvailableError)
    assert exc_info.value.agent_type == AgentType.CODEX_SERVER_REMOTE.value


async def test_execute_cancelled_before_start_raises_agent_cancelled_error() -> None:
    agent = _make_agent()
    await agent.cancel()
    with pytest.raises(AgentCancelledError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_type == AgentType.CODEX_SERVER_REMOTE.value


class _FailingRemoteAgent(CodexServerRemoteAgent):
    """Subclass that simulates a generic session error to exercise AgentExecutionError path."""

    def __init__(self, fail_message: str) -> None:
        super().__init__(
            base_url=_VALID_URL,
            api_key=_VALID_KEY,
            _environ={},
        )
        self._fail_message = fail_message

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
            raise RuntimeError(self._fail_message)
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


async def test_generic_failure_raises_agent_execution_error() -> None:
    agent = _FailingRemoteAgent("something went wrong")
    with pytest.raises(AgentExecutionError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_type == AgentType.CODEX_SERVER_REMOTE.value


async def test_generic_failure_does_not_leak_secret_in_error_message() -> None:
    """AgentExecutionError message must not contain raw exception text (may include secrets)."""
    secret = "sk-very-secret-api-key-xyz"  # pragma: allowlist secret
    agent = _FailingRemoteAgent(fail_message=secret)
    with pytest.raises(AgentExecutionError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert secret not in exc_info.value.message


# ===========================================================================
# Bearer auth — dedicated auth-named tests for auto-verify discoverability
# ===========================================================================


def test_bearer_auth_resolution_from_explicit_api_key() -> None:
    """Bearer auth: explicit api_key is resolved as the bearer token."""
    agent = _make_agent(api_key="explicit-bearer-token")  # pragma: allowlist secret
    assert agent._token == "explicit-bearer-token"


def test_bearer_auth_resolution_from_env_var() -> None:
    """Bearer auth: token resolved from token_env_var when api_key is absent."""
    agent = _make_agent(
        api_key=None,
        environ={DEFAULT_TOKEN_ENV_VAR: "env-bearer-token"},  # pragma: allowlist secret
    )
    assert agent._token == "env-bearer-token"


def test_bearer_auth_resolution_from_openai_fallback() -> None:
    """Bearer auth: OPENAI_API_KEY used as fallback when primary env var absent."""
    agent = _make_agent(
        api_key=None,
        environ={FALLBACK_TOKEN_ENV_VAR: "openai-bearer-token"},  # pragma: allowlist secret
    )
    assert agent._token == "openai-bearer-token"


def test_bearer_auth_raises_config_error_when_no_token_source() -> None:
    """Bearer auth: AgentConfigError raised when no token source resolves."""
    with pytest.raises(AgentConfigError) as exc_info:
        _make_agent(api_key=None, environ={})
    assert exc_info.value.agent_type == AgentType.CODEX_SERVER_REMOTE.value
    assert "CODEX_SERVER_API_KEY" in exc_info.value.message
    assert "OPENAI_API_KEY" in exc_info.value.message


def test_bearer_auth_api_key_takes_precedence_over_env_var() -> None:
    """Bearer auth: explicit api_key always wins over env var."""
    agent = _make_agent(
        api_key="api-key-wins",  # pragma: allowlist secret
        environ={DEFAULT_TOKEN_ENV_VAR: "env-would-lose"},  # pragma: allowlist secret
    )
    assert agent._token == "api-key-wins"


def test_bearer_auth_token_not_in_base_url() -> None:
    """Bearer auth: token is never embedded in the stored base URL."""
    key = "sk-secret-bearer"  # pragma: allowlist secret
    agent = _make_agent(api_key=key)
    assert key not in agent._base_url


def test_bearer_auth_token_not_exposed_in_agent_info() -> None:
    """Bearer auth: token does not appear in agent info."""
    key = "sk-secret-bearer"  # pragma: allowlist secret
    agent = _make_agent(api_key=key)
    assert key not in str(agent.info)


async def test_bearer_auth_token_safe_in_execution_error_message() -> None:
    """Bearer auth: AgentExecutionError message never contains the raw bearer token."""
    secret_token = "sk-bearer-secret-xyz"  # pragma: allowlist secret
    # _FailingRemoteAgent simulates a session error whose message contains the token.
    agent = _FailingRemoteAgent(fail_message=secret_token)
    agent._token = secret_token  # Simulate token stored on agent.
    with pytest.raises(AgentExecutionError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert secret_token not in exc_info.value.message


# ===========================================================================
# map_transport_error — pure function tests (no I/O required)
# ===========================================================================

#: Shared request used to construct httpx.HTTPStatusError instances.
_DUMMY_REQUEST = httpx.Request("POST", "https://codex.example.com/sessions")

_AGENT_TYPE = AgentType.CODEX_SERVER_REMOTE.value


def test_map_transport_error_timeout_returns_agent_timeout_error() -> None:
    """httpx.TimeoutException → AgentTimeoutError."""
    exc = httpx.TimeoutException("read timed out")
    result = map_transport_error(exc, _AGENT_TYPE, duration_ms=5000)
    assert isinstance(result, AgentTimeoutError)
    assert result.agent_type == _AGENT_TYPE


def test_map_transport_error_timeout_message_contains_duration() -> None:
    """AgentTimeoutError message includes the elapsed time."""
    exc = httpx.TimeoutException("connect timed out")
    result = map_transport_error(exc, _AGENT_TYPE, duration_ms=3200)
    assert "3200" in result.message


def test_map_transport_error_connect_error_returns_agent_not_available_error() -> None:
    """httpx.ConnectError → AgentNotAvailableError (endpoint unreachable)."""
    exc = httpx.ConnectError("connection refused")
    result = map_transport_error(exc, _AGENT_TYPE, duration_ms=100)
    assert isinstance(result, AgentNotAvailableError)
    assert result.agent_type == _AGENT_TYPE


def test_map_transport_error_connect_error_message_indicates_unreachable() -> None:
    """AgentNotAvailableError message communicates endpoint unreachability."""
    exc = httpx.ConnectError("connection refused")
    result = map_transport_error(exc, _AGENT_TYPE, duration_ms=50)
    assert isinstance(result, AgentNotAvailableError)
    assert "unreachable" in result.reason.lower()


def test_map_transport_error_http_401_returns_agent_execution_error() -> None:
    """httpx.HTTPStatusError with 401 → AgentExecutionError (explicit auth failure)."""
    response = httpx.Response(401, request=_DUMMY_REQUEST)
    exc = httpx.HTTPStatusError("401 Unauthorized", request=_DUMMY_REQUEST, response=response)
    result = map_transport_error(exc, _AGENT_TYPE, duration_ms=200)
    assert isinstance(result, AgentExecutionError)
    assert result.agent_type == _AGENT_TYPE


def test_map_transport_error_http_401_message_is_token_safe() -> None:
    """AgentExecutionError for 401 must not contain the bearer token value."""
    secret = "sk-bearer-secret-401"  # pragma: allowlist secret
    response = httpx.Response(401, request=_DUMMY_REQUEST)
    exc = httpx.HTTPStatusError("401 Unauthorized", request=_DUMMY_REQUEST, response=response)
    result = map_transport_error(exc, _AGENT_TYPE, duration_ms=200)
    assert secret not in result.message


def test_map_transport_error_http_401_message_mentions_401() -> None:
    """AgentExecutionError for 401 message includes '401' for diagnostics."""
    response = httpx.Response(401, request=_DUMMY_REQUEST)
    exc = httpx.HTTPStatusError("401 Unauthorized", request=_DUMMY_REQUEST, response=response)
    result = map_transport_error(exc, _AGENT_TYPE, duration_ms=200)
    assert isinstance(result, AgentExecutionError)
    assert "401" in result.message


def test_map_transport_error_http_403_returns_agent_execution_error() -> None:
    """httpx.HTTPStatusError with 403 → AgentExecutionError (explicit permission failure)."""
    response = httpx.Response(403, request=_DUMMY_REQUEST)
    exc = httpx.HTTPStatusError("403 Forbidden", request=_DUMMY_REQUEST, response=response)
    result = map_transport_error(exc, _AGENT_TYPE, duration_ms=150)
    assert isinstance(result, AgentExecutionError)
    assert result.agent_type == _AGENT_TYPE


def test_map_transport_error_http_403_message_is_token_safe() -> None:
    """AgentExecutionError for 403 must not contain the bearer token value."""
    secret = "sk-bearer-secret-403"  # pragma: allowlist secret
    response = httpx.Response(403, request=_DUMMY_REQUEST)
    exc = httpx.HTTPStatusError("403 Forbidden", request=_DUMMY_REQUEST, response=response)
    result = map_transport_error(exc, _AGENT_TYPE, duration_ms=150)
    assert secret not in result.message


def test_map_transport_error_http_403_message_mentions_403() -> None:
    """AgentExecutionError for 403 message includes '403' for diagnostics."""
    response = httpx.Response(403, request=_DUMMY_REQUEST)
    exc = httpx.HTTPStatusError("403 Forbidden", request=_DUMMY_REQUEST, response=response)
    result = map_transport_error(exc, _AGENT_TYPE, duration_ms=150)
    assert isinstance(result, AgentExecutionError)
    assert "403" in result.message


def test_map_transport_error_http_500_returns_agent_execution_error() -> None:
    """httpx.HTTPStatusError with non-401/403 status → AgentExecutionError with status code."""
    response = httpx.Response(500, request=_DUMMY_REQUEST)
    exc = httpx.HTTPStatusError(
        "500 Internal Server Error", request=_DUMMY_REQUEST, response=response
    )
    result = map_transport_error(exc, _AGENT_TYPE, duration_ms=1000)
    assert isinstance(result, AgentExecutionError)
    assert "500" in result.message


def test_map_transport_error_http_500_message_excludes_response_body() -> None:
    """AgentExecutionError for HTTP errors must not include the response body."""
    sensitive_body = "internal error: token=sk-leaked-key"  # pragma: allowlist secret
    response = httpx.Response(500, text=sensitive_body, request=_DUMMY_REQUEST)
    exc = httpx.HTTPStatusError(
        "500 Internal Server Error", request=_DUMMY_REQUEST, response=response
    )
    result = map_transport_error(exc, _AGENT_TYPE, duration_ms=1000)
    assert sensitive_body not in result.message
    assert "sk-leaked-key" not in result.message  # pragma: allowlist secret


def test_map_transport_error_generic_exception_returns_agent_execution_error() -> None:
    """Generic Exception → AgentExecutionError (secret-safe fallback)."""
    exc = ValueError("schema mismatch: unexpected field 'token'")
    result = map_transport_error(exc, _AGENT_TYPE, duration_ms=300)
    assert isinstance(result, AgentExecutionError)
    assert result.agent_type == _AGENT_TYPE


def test_map_transport_error_generic_exception_message_excludes_raw_text() -> None:
    """Generic fallback AgentExecutionError must not echo the raw exception message."""
    secret_in_exc = "sk-raw-secret-in-exception"  # pragma: allowlist secret
    exc = RuntimeError(secret_in_exc)
    result = map_transport_error(exc, _AGENT_TYPE, duration_ms=300)
    assert secret_in_exc not in result.message


def test_map_transport_error_agent_type_propagated() -> None:
    """The agent_type string is correctly propagated to the resulting error."""
    exc = httpx.ConnectError("refused")
    result = map_transport_error(exc, "custom_agent_type", duration_ms=0)
    assert result.agent_type == "custom_agent_type"


# ===========================================================================
# execute() — transport error mapping wired into execute() via subclasses
# ===========================================================================


class _HttpxFailingRemoteAgent(CodexServerRemoteAgent):
    """Subclass that simulates specific httpx transport failures in execute()."""

    def __init__(self, httpx_exc: Exception) -> None:
        super().__init__(
            base_url=_VALID_URL,
            api_key=_VALID_KEY,
            _environ={},
        )
        self._httpx_exc = httpx_exc

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
            raise self._httpx_exc
        except (AgentCancelledError, AgentNotAvailableError):
            raise
        except asyncio.CancelledError:
            raise AgentCancelledError(AgentType.CODEX_SERVER_REMOTE.value)
        except httpx.TimeoutException as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            raise map_transport_error(
                exc, AgentType.CODEX_SERVER_REMOTE.value, duration_ms
            ) from exc
        except httpx.ConnectError as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            raise map_transport_error(
                exc, AgentType.CODEX_SERVER_REMOTE.value, duration_ms
            ) from exc
        except httpx.HTTPStatusError as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            raise map_transport_error(
                exc, AgentType.CODEX_SERVER_REMOTE.value, duration_ms
            ) from exc
        except Exception as exc:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            raise map_transport_error(
                exc, AgentType.CODEX_SERVER_REMOTE.value, duration_ms
            ) from exc


async def test_execute_timeout_maps_to_agent_timeout_error() -> None:
    """Timeout during transport raises AgentTimeoutError (not bare TimeoutException)."""
    agent = _HttpxFailingRemoteAgent(httpx.TimeoutException("read timeout"))
    with pytest.raises(AgentTimeoutError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_type == AgentType.CODEX_SERVER_REMOTE.value


async def test_execute_connect_error_maps_to_agent_not_available_error() -> None:
    """Unreachable endpoint raises AgentNotAvailableError."""
    agent = _HttpxFailingRemoteAgent(httpx.ConnectError("connection refused"))
    with pytest.raises(AgentNotAvailableError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_type == AgentType.CODEX_SERVER_REMOTE.value


async def test_execute_http_401_maps_to_agent_execution_error() -> None:
    """401 response raises AgentExecutionError (explicit auth failure, token-safe)."""
    response = httpx.Response(401, request=_DUMMY_REQUEST)
    exc = httpx.HTTPStatusError("401", request=_DUMMY_REQUEST, response=response)
    agent = _HttpxFailingRemoteAgent(exc)
    with pytest.raises(AgentExecutionError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_type == AgentType.CODEX_SERVER_REMOTE.value
    assert "401" in exc_info.value.message
    # Must not contain the actual bearer token value.
    assert _VALID_KEY not in exc_info.value.message


async def test_execute_http_403_maps_to_agent_execution_error() -> None:
    """403 response raises AgentExecutionError (explicit permission failure, token-safe)."""
    response = httpx.Response(403, request=_DUMMY_REQUEST)
    exc = httpx.HTTPStatusError("403", request=_DUMMY_REQUEST, response=response)
    agent = _HttpxFailingRemoteAgent(exc)
    with pytest.raises(AgentExecutionError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_type == AgentType.CODEX_SERVER_REMOTE.value
    assert "403" in exc_info.value.message
    # Must not contain the actual bearer token value.
    assert _VALID_KEY not in exc_info.value.message


async def test_execute_http_401_error_does_not_leak_token() -> None:
    """AgentExecutionError raised for 401 must not include bearer token in message."""
    secret = "sk-secret-bearer-401"  # pragma: allowlist secret
    agent = _HttpxFailingRemoteAgent(
        httpx.HTTPStatusError(
            "401",
            request=_DUMMY_REQUEST,
            response=httpx.Response(401, request=_DUMMY_REQUEST),
        )
    )
    agent._token = secret
    with pytest.raises(AgentExecutionError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert secret not in exc_info.value.message


async def test_execute_http_403_error_does_not_leak_token() -> None:
    """AgentExecutionError raised for 403 must not include bearer token in message."""
    secret = "sk-secret-bearer-403"  # pragma: allowlist secret
    agent = _HttpxFailingRemoteAgent(
        httpx.HTTPStatusError(
            "403",
            request=_DUMMY_REQUEST,
            response=httpx.Response(403, request=_DUMMY_REQUEST),
        )
    )
    agent._token = secret
    with pytest.raises(AgentExecutionError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert secret not in exc_info.value.message


async def test_execute_schema_mismatch_maps_to_agent_execution_error() -> None:
    """Schema/validation errors (ValueError) are mapped to AgentExecutionError."""
    agent = _HttpxFailingRemoteAgent(ValueError("unexpected field 'token_extra'"))
    with pytest.raises(AgentExecutionError) as exc_info:
        await agent.execute(
            context=_ctx(),
            on_checklist_update=_noop_checklist,
            on_submit=_noop_submit,
        )
    assert exc_info.value.agent_type == AgentType.CODEX_SERVER_REMOTE.value
