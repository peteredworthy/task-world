"""Unit tests for run API schema validation."""

import pytest
from pydantic import ValidationError

from orchestrator.api import (
    CreateRunRequest,
    get_agent_runner_display_name,
    get_agent_runner_icon,
)
from orchestrator.config import AgentRunnerType

VALID_EMBEDDED_ROUTINE = {
    "id": "embedded-test",
    "name": "Embedded Test Routine",
    "steps": [
        {
            "id": "S-01",
            "title": "Step One",
            "tasks": [
                {
                    "id": "T-01",
                    "title": "Task One",
                    "task_context": "Do something",
                    "requirements": [{"id": "R1", "desc": "Complete it"}],
                }
            ],
        }
    ],
}


def test_create_run_request_with_routine_id_only() -> None:
    """CreateRunRequest with only routine_id is valid."""
    req = CreateRunRequest(routine_id="my-routine", repo_name="proj-1", branch="main")
    assert req.routine_id == "my-routine"
    assert req.routine_embedded is None


def test_create_run_request_with_routine_embedded_only() -> None:
    """CreateRunRequest with only routine_embedded is valid."""
    req = CreateRunRequest(
        repo_name="proj-1",
        branch="main",
        routine_embedded=VALID_EMBEDDED_ROUTINE,
    )
    assert req.routine_id is None
    assert req.routine_embedded == VALID_EMBEDDED_ROUTINE


def test_create_run_request_with_both_raises() -> None:
    """CreateRunRequest with both routine_id and routine_embedded raises ValueError."""
    with pytest.raises(
        ValidationError, match="routine_id.*routine_embedded|routine_embedded.*routine_id"
    ):
        CreateRunRequest(
            routine_id="my-routine",
            repo_name="proj-1",
            branch="main",
            routine_embedded=VALID_EMBEDDED_ROUTINE,
        )


def test_create_run_request_with_neither_raises() -> None:
    """CreateRunRequest with neither routine_id nor routine_embedded raises ValueError."""
    with pytest.raises(
        ValidationError, match="routine_id.*routine_embedded|routine_embedded.*routine_id"
    ):
        CreateRunRequest(repo_name="proj-1", branch="main")


def test_create_run_request_preserves_config() -> None:
    """Config, agent_runner_type, and agent_runner_config pass through correctly."""
    req = CreateRunRequest(
        routine_id="my-routine",
        repo_name="proj-1",
        branch="main",
        config={"key": "value"},
        agent_runner_type="cli_subprocess",
        agent_runner_config={"model": "test"},
    )
    assert req.config == {"key": "value"}
    assert req.agent_runner_type == "cli_subprocess"
    assert req.agent_runner_config == {"model": "test"}


def test_get_agent_runner_display_name_openhands_local() -> None:
    """OpenHands local agent returns correct display name."""
    assert get_agent_runner_display_name(AgentRunnerType.OPENHANDS_LOCAL) == "OpenHands"


def test_get_agent_runner_display_name_openhands_docker() -> None:
    """OpenHands docker agent returns correct display name."""
    assert get_agent_runner_display_name(AgentRunnerType.OPENHANDS_DOCKER) == "OpenHands Docker"


def test_get_agent_runner_display_name_cli_subprocess() -> None:
    """CLI subprocess agent returns correct display name."""
    assert get_agent_runner_display_name(AgentRunnerType.CLI_SUBPROCESS) == "Claude CLI"


def test_get_agent_runner_display_name_cli_subprocess_uses_command_when_present() -> None:
    """CLI subprocess display uses selected command when available."""
    assert (
        get_agent_runner_display_name(AgentRunnerType.CLI_SUBPROCESS, {"command": "codex"})
        == "codex CLI"
    )


def test_get_agent_runner_display_name_user_managed() -> None:
    """User-managed agent runner returns correct display name."""
    assert get_agent_runner_display_name(AgentRunnerType.USER_MANAGED) == "User Managed"


def test_get_agent_runner_display_name_none() -> None:
    """None agent runner type returns 'No Agent Runner'."""
    assert get_agent_runner_display_name(None) == "No Agent Runner"


def test_get_agent_runner_icon_openhands_local() -> None:
    """OpenHands local agent returns correct icon."""
    assert get_agent_runner_icon(AgentRunnerType.OPENHANDS_LOCAL) == "openhands"


def test_get_agent_runner_icon_openhands_docker() -> None:
    """OpenHands docker agent returns correct icon."""
    assert get_agent_runner_icon(AgentRunnerType.OPENHANDS_DOCKER) == "docker"


def test_get_agent_runner_icon_cli_subprocess() -> None:
    """CLI subprocess agent returns correct icon."""
    assert get_agent_runner_icon(AgentRunnerType.CLI_SUBPROCESS) == "cli"


def test_get_agent_runner_icon_user_managed() -> None:
    """User managed agent returns correct icon."""
    assert get_agent_runner_icon(AgentRunnerType.USER_MANAGED) == "external"


def test_get_agent_runner_icon_none() -> None:
    """None agent runner type returns 'none' icon."""
    assert get_agent_runner_icon(None) == "none"
