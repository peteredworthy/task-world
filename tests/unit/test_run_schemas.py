"""Unit tests for run API schema validation."""

import pytest
from pydantic import ValidationError

from orchestrator.api.schemas.runs import (
    CreateRunRequest,
    get_agent_display_name,
    get_agent_icon,
)
from orchestrator.config.enums import AgentType


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
    req = CreateRunRequest(routine_id="my-routine", project_id="proj-1")
    assert req.routine_id == "my-routine"
    assert req.routine_embedded is None


def test_create_run_request_with_routine_embedded_only() -> None:
    """CreateRunRequest with only routine_embedded is valid."""
    req = CreateRunRequest(
        project_id="proj-1",
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
            project_id="proj-1",
            routine_embedded=VALID_EMBEDDED_ROUTINE,
        )


def test_create_run_request_with_neither_raises() -> None:
    """CreateRunRequest with neither routine_id nor routine_embedded raises ValueError."""
    with pytest.raises(
        ValidationError, match="routine_id.*routine_embedded|routine_embedded.*routine_id"
    ):
        CreateRunRequest(project_id="proj-1")


def test_create_run_request_preserves_config() -> None:
    """Config, agent_type, and agent_config pass through correctly."""
    req = CreateRunRequest(
        routine_id="my-routine",
        project_id="proj-1",
        config={"key": "value"},
        agent_type="cli_subprocess",
        agent_config={"model": "test"},
    )
    assert req.config == {"key": "value"}
    assert req.agent_type == "cli_subprocess"
    assert req.agent_config == {"model": "test"}


def test_get_agent_display_name_openhands_local() -> None:
    """OpenHands local agent returns correct display name."""
    assert get_agent_display_name(AgentType.OPENHANDS_LOCAL) == "OpenHands"


def test_get_agent_display_name_openhands_docker() -> None:
    """OpenHands docker agent returns correct display name."""
    assert get_agent_display_name(AgentType.OPENHANDS_DOCKER) == "OpenHands Docker"


def test_get_agent_display_name_cli_subprocess() -> None:
    """CLI subprocess agent returns correct display name."""
    assert get_agent_display_name(AgentType.CLI_SUBPROCESS) == "Claude CLI"


def test_get_agent_display_name_user_managed() -> None:
    """User managed agent returns correct display name."""
    assert get_agent_display_name(AgentType.USER_MANAGED) == "External Agent"


def test_get_agent_display_name_none() -> None:
    """None agent type returns 'No Agent'."""
    assert get_agent_display_name(None) == "No Agent"


def test_get_agent_icon_openhands_local() -> None:
    """OpenHands local agent returns correct icon."""
    assert get_agent_icon(AgentType.OPENHANDS_LOCAL) == "openhands"


def test_get_agent_icon_openhands_docker() -> None:
    """OpenHands docker agent returns correct icon."""
    assert get_agent_icon(AgentType.OPENHANDS_DOCKER) == "docker"


def test_get_agent_icon_cli_subprocess() -> None:
    """CLI subprocess agent returns correct icon."""
    assert get_agent_icon(AgentType.CLI_SUBPROCESS) == "cli"


def test_get_agent_icon_user_managed() -> None:
    """User managed agent returns correct icon."""
    assert get_agent_icon(AgentType.USER_MANAGED) == "external"


def test_get_agent_icon_none() -> None:
    """None agent type returns 'none' icon."""
    assert get_agent_icon(None) == "none"
