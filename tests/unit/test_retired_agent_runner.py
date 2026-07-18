"""Contract tests for readable but non-selectable retired runners."""

import pytest

from orchestrator.api import get_agent_runner_display_name
from orchestrator.config import (
    AgentRunnerType,
    SELECTABLE_AGENT_RUNNER_TYPES,
    SELECTABLE_AGENT_RUNNER_VALUES,
    is_selectable_agent_runner_type,
    normalize_persisted_agent_runner_type,
)
from orchestrator.runners import AgentNotAvailableError, create_agent_runner


def test_claude_sdk_is_represented_as_retired_for_readback() -> None:
    assert "claude_sdk" not in {runner_type.value for runner_type in AgentRunnerType}
    assert AgentRunnerType.RETIRED.value == "retired"
    assert normalize_persisted_agent_runner_type("claude_sdk") is AgentRunnerType.RETIRED
    assert normalize_persisted_agent_runner_type("retired") is AgentRunnerType.RETIRED


def test_retired_runner_is_not_selectable() -> None:
    assert SELECTABLE_AGENT_RUNNER_TYPES == frozenset(
        {
            AgentRunnerType.OPENHANDS_LOCAL,
            AgentRunnerType.OPENHANDS_DOCKER,
            AgentRunnerType.CLI_SUBPROCESS,
            AgentRunnerType.CODEX_SERVER,
        }
    )
    assert SELECTABLE_AGENT_RUNNER_VALUES == frozenset(
        {
            "openhands_local",
            "openhands_docker",
            "cli_subprocess",
            "codex_server",
        }
    )
    assert is_selectable_agent_runner_type(AgentRunnerType.CODEX_SERVER)
    assert not is_selectable_agent_runner_type(AgentRunnerType.RETIRED)


def test_retired_runner_has_readback_display_name() -> None:
    assert get_agent_runner_display_name(AgentRunnerType.RETIRED) == "Retired runner"


def test_factory_rejects_retired_runner() -> None:
    with pytest.raises(AgentNotAvailableError, match="retired"):
        create_agent_runner(AgentRunnerType.RETIRED, {})
