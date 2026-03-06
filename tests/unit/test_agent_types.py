"""Tests for agent types and protocol."""

from orchestrator.agents.errors import (
    AgentCancelledError,
    AgentError,
    AgentExecutionError,
    AgentNotAvailableError,
)
from orchestrator.agents.interface import Agent
from orchestrator.agents.types import (
    AgentConfigField,
    AgentRunnerInfo,
    AgentOption,
    ExecutionContext,
    ExecutionMetrics,
    ExecutionResult,
)
from orchestrator.config.enums import AgentRunnerType


def test_execution_context_validation() -> None:
    ctx = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp/work",
        prompt="Do the thing",
        requirements=["R1", "R2"],
    )
    assert ctx.run_id == "run-1"
    assert ctx.requirements == ["R1", "R2"]


def test_execution_context_with_api_base_url() -> None:
    ctx = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp/work",
        prompt="Do the thing",
        requirements=["R1"],
        api_base_url="http://localhost:8000",
    )
    assert ctx.api_base_url == "http://localhost:8000"


def test_execution_context_api_base_url_defaults_to_none() -> None:
    ctx = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp/work",
        prompt="Do the thing",
        requirements=["R1"],
    )
    assert ctx.api_base_url is None


def test_execution_metrics_defaults() -> None:
    metrics = ExecutionMetrics()
    assert metrics.tokens_read == 0
    assert metrics.tokens_write == 0
    assert metrics.tokens_cache == 0
    assert metrics.duration_ms == 0


def test_execution_result_success() -> None:
    result = ExecutionResult(success=True)
    assert result.success is True
    assert result.error is None
    assert result.metrics.tokens_read == 0


def test_execution_result_failure() -> None:
    result = ExecutionResult(
        success=False,
        error="Something went wrong",
        metrics=ExecutionMetrics(tokens_read=100, tokens_write=50, duration_ms=5000),
    )
    assert result.success is False
    assert result.error == "Something went wrong"
    assert result.metrics.tokens_read == 100


def test_agent_info() -> None:
    info = AgentRunnerInfo(
        agent_type=AgentRunnerType.CLI_SUBPROCESS, name="claude", version="1.0.0"
    )
    assert info.agent_type == AgentRunnerType.CLI_SUBPROCESS
    assert info.name == "claude"
    assert info.version == "1.0.0"


def test_agent_info_no_version() -> None:
    info = AgentRunnerInfo(agent_type=AgentRunnerType.OPENHANDS_LOCAL, name="openhands_local")
    assert info.version is None


def test_agent_type_claude_sdk_in_enum() -> None:
    assert AgentRunnerType.CLAUDE_SDK == "claude_sdk"
    assert AgentRunnerType.CLAUDE_SDK in AgentRunnerType


def test_agent_option() -> None:
    opt = AgentOption(
        agent_type=AgentRunnerType.CLI_SUBPROCESS,
        name="Claude CLI",
        available=True,
        detail="Found at /usr/local/bin/claude",
    )
    assert opt.available is True
    assert opt.install_hint == ""


def test_agent_option_unavailable() -> None:
    opt = AgentOption(
        agent_type=AgentRunnerType.OPENHANDS_LOCAL,
        name="OpenHands",
        available=False,
        detail="Server not reachable",
        install_hint="docker run -d -p 3000:3000 ghcr.io/all-hands-ai/openhands:latest",
    )
    assert opt.available is False
    assert "docker" in opt.install_hint


class _FakeAgent:
    """Minimal concrete agent for protocol check."""

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_type=AgentRunnerType.CLI_SUBPROCESS, name="fake")

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: object,
        on_submit: object,
    ) -> ExecutionResult:
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        pass

    def get_quota(self, fetcher: object = None) -> None:
        return None


def test_agent_protocol_runtime_check() -> None:
    agent = _FakeAgent()
    assert isinstance(agent, Agent)


def test_agent_error_hierarchy() -> None:
    assert issubclass(AgentExecutionError, AgentError)
    assert issubclass(AgentNotAvailableError, AgentError)
    assert issubclass(AgentCancelledError, AgentError)


def test_agent_execution_error() -> None:
    err = AgentExecutionError("openhands_local", "connection refused")
    assert err.agent_type == "openhands_local"
    assert err.message == "connection refused"
    assert "openhands_local" in str(err)


def test_agent_not_available_error() -> None:
    err = AgentNotAvailableError("cli_subprocess", "claude not found in PATH")
    assert err.agent_type == "cli_subprocess"
    assert err.reason == "claude not found in PATH"


def test_agent_not_available_error_no_reason() -> None:
    err = AgentNotAvailableError("openhands_local")
    assert err.reason == ""
    assert "not available" in str(err)


def test_agent_cancelled_error() -> None:
    err = AgentCancelledError("cli_subprocess")
    assert err.agent_type == "cli_subprocess"
    assert "cancelled" in str(err)


def test_callback_type_aliases_exist() -> None:
    """Verify callback type aliases are importable."""
    from orchestrator.agents.types import ChecklistUpdateCallback, SubmitCallback

    # They're type aliases, so just verify they exist
    assert ChecklistUpdateCallback is not None
    assert SubmitCallback is not None


# --- AgentConfigField ---


def test_agent_config_field_string() -> None:
    field = AgentConfigField(
        name="model",
        field_type="string",
        default="gpt-5-mini",
        description="LLM model to use",
    )
    assert field.name == "model"
    assert field.field_type == "string"
    assert field.default == "gpt-5-mini"
    assert field.required is False
    assert field.options is None


def test_agent_config_field_select() -> None:
    field = AgentConfigField(
        name="callback_channel",
        field_type="select",
        required=True,
        options=["rest", "mcp"],
        description="Callback channel",
    )
    assert field.field_type == "select"
    assert field.required is True
    assert field.options == ["rest", "mcp"]


def test_agent_config_field_number() -> None:
    field = AgentConfigField(
        name="timeout_minutes",
        field_type="number",
        default=60,
    )
    assert field.default == 60
    assert field.description == ""


def test_agent_option_with_config_schema() -> None:
    schema = [
        AgentConfigField(name="model", field_type="string", default="gpt-5-mini"),
        AgentConfigField(name="max_iterations", field_type="number", default=100),
    ]
    opt = AgentOption(
        agent_type=AgentRunnerType.OPENHANDS_LOCAL,
        name="OpenHands",
        available=True,
        config_schema=schema,
    )
    assert len(opt.config_schema) == 2
    assert opt.config_schema[0].name == "model"
    assert opt.config_schema[1].name == "max_iterations"


def test_agent_option_config_schema_defaults_to_empty() -> None:
    opt = AgentOption(
        agent_type=AgentRunnerType.CLI_SUBPROCESS,
        name="claude",
        available=True,
    )
    assert opt.config_schema == []
