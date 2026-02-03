"""Tests for ToolDetector."""

from orchestrator.agents.detector import ToolDetector
from orchestrator.config.enums import AgentType


async def test_detect_openhands_local_present() -> None:
    """Local detection returns an OPENHANDS_LOCAL entry (available depends on SDK install)."""
    detector = ToolDetector()
    options = await detector.detect_all()

    oh_local = [o for o in options if o.agent_type == AgentType.OPENHANDS_LOCAL][0]
    # SDK may or may not be installed -- just verify it returns an option
    assert oh_local.name == "OpenHands (local)"
    assert isinstance(oh_local.available, bool)


async def test_detect_openhands_docker_present() -> None:
    """Docker detection returns an OPENHANDS_DOCKER entry."""
    detector = ToolDetector()
    options = await detector.detect_all()

    oh_docker = [o for o in options if o.agent_type == AgentType.OPENHANDS_DOCKER][0]
    assert oh_docker.name == "OpenHands (Docker)"
    assert isinstance(oh_docker.available, bool)
    # Available depends on whether DockerWorkspace is importable + Docker running
    if oh_docker.available:
        assert "Docker" in oh_docker.detail


async def test_detect_cli_tools_real() -> None:
    """Verify CLI detection runs without error and returns expected entries."""
    detector = ToolDetector()
    options = await detector.detect_all()

    cli_options = [o for o in options if o.agent_type == AgentType.CLI_SUBPROCESS]
    names = {o.name for o in cli_options}
    assert "claude" in names
    assert "codex" in names


async def test_user_managed_always_available() -> None:
    detector = ToolDetector()
    options = await detector.detect_all()

    um = [o for o in options if o.agent_type == AgentType.USER_MANAGED][0]
    assert um.available is True
    assert um.name == "User Managed"


async def test_detect_all_returns_both_openhands_types() -> None:
    """detect_all returns both OPENHANDS_LOCAL and OPENHANDS_DOCKER entries."""
    detector = ToolDetector()
    options = await detector.detect_all()

    agent_types = [o.agent_type for o in options]
    assert AgentType.OPENHANDS_LOCAL in agent_types
    assert AgentType.OPENHANDS_DOCKER in agent_types


async def test_config_schema_populated() -> None:
    """All agent options have config_schema populated."""
    detector = ToolDetector()
    options = await detector.detect_all()

    for option in options:
        assert isinstance(option.config_schema, list)
        assert len(option.config_schema) > 0, (
            f"{option.name} ({option.agent_type}) has empty config_schema"
        )

    # Verify specific fields exist for known types
    oh_local = [o for o in options if o.agent_type == AgentType.OPENHANDS_LOCAL][0]
    field_names = [f.name for f in oh_local.config_schema]
    assert "model" in field_names
    assert "tools" in field_names
    assert "max_iterations" in field_names

    um = [o for o in options if o.agent_type == AgentType.USER_MANAGED][0]
    um_field_names = [f.name for f in um.config_schema]
    assert "callback_channel" in um_field_names
    assert "timeout_minutes" in um_field_names
