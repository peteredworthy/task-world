"""Tests for ToolDetector."""

from orchestrator.runners.detector import ToolDetector
from orchestrator.config.enums import AgentRunnerType


async def test_detect_openhands_local_present() -> None:
    """Local detection returns an OPENHANDS_LOCAL entry (available depends on SDK install)."""
    detector = ToolDetector()
    options = await detector.detect_all()

    oh_local = [o for o in options if o.agent_type == AgentRunnerType.OPENHANDS_LOCAL][0]
    # SDK may or may not be installed -- just verify it returns an option
    assert oh_local.name == "OpenHands (local)"
    assert isinstance(oh_local.available, bool)


async def test_detect_openhands_docker_present() -> None:
    """Docker detection returns an OPENHANDS_DOCKER entry."""
    detector = ToolDetector()
    options = await detector.detect_all()

    oh_docker = [o for o in options if o.agent_type == AgentRunnerType.OPENHANDS_DOCKER][0]
    assert oh_docker.name == "OpenHands (Docker)"
    assert isinstance(oh_docker.available, bool)
    # Available depends on whether DockerWorkspace is importable + Docker running
    if oh_docker.available:
        assert "Docker" in oh_docker.detail


async def test_detect_cli_tools_real() -> None:
    """Verify CLI detection runs without error and returns expected entries."""
    detector = ToolDetector()
    options = await detector.detect_all()

    cli_options = [o for o in options if o.agent_type == AgentRunnerType.CLI_SUBPROCESS]
    names = {o.name for o in cli_options}
    assert "claude" in names
    assert "codex" in names
    for option in cli_options:
        command_field = next((f for f in option.config_schema if f.name == "command"), None)
        assert command_field is not None
        assert command_field.default == option.name


async def test_user_managed_always_available() -> None:
    detector = ToolDetector()
    options = await detector.detect_all()

    um = [o for o in options if o.agent_type == AgentRunnerType.USER_MANAGED][0]
    assert um.available is True
    assert um.name == "User Managed"


async def test_detect_all_returns_both_openhands_types() -> None:
    """detect_all returns both OPENHANDS_LOCAL and OPENHANDS_DOCKER entries."""
    detector = ToolDetector()
    options = await detector.detect_all()

    agent_types = [o.agent_type for o in options]
    assert AgentRunnerType.OPENHANDS_LOCAL in agent_types
    assert AgentRunnerType.OPENHANDS_DOCKER in agent_types


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
    oh_local = [o for o in options if o.agent_type == AgentRunnerType.OPENHANDS_LOCAL][0]
    field_names = [f.name for f in oh_local.config_schema]
    assert "model" in field_names
    assert "max_iterations" in field_names

    um = [o for o in options if o.agent_type == AgentRunnerType.USER_MANAGED][0]
    um_field_names = [f.name for f in um.config_schema]
    assert "callback_channel" in um_field_names
    assert "timeout_minutes" in um_field_names


async def test_detect_codex_server_present() -> None:
    """detect_all always returns a CODEX_SERVER entry."""
    detector = ToolDetector()
    options = await detector.detect_all()

    cs = [o for o in options if o.agent_type == AgentRunnerType.CODEX_SERVER]
    assert len(cs) == 1
    entry = cs[0]
    assert entry.name == "Codex Server"
    assert isinstance(entry.available, bool)
    if entry.available:
        assert "codex" in entry.detail.lower()
    else:
        assert entry.install_hint != ""


async def test_detect_codex_server_config_fields() -> None:
    """CODEX_SERVER option has required config fields."""
    detector = ToolDetector()
    options = await detector.detect_all()

    cs = [o for o in options if o.agent_type == AgentRunnerType.CODEX_SERVER][0]
    field_names = [f.name for f in cs.config_schema]
    assert "model" in field_names
    assert "callback_channel" in field_names
    assert "restrictions" in field_names

    cb_field = next(f for f in cs.config_schema if f.name == "callback_channel")
    assert cb_field.options is not None
    assert "rest" in cb_field.options
    assert "mcp" in cb_field.options


async def test_detect_all_includes_codex_server_type() -> None:
    """detect_all returns a CODEX_SERVER entry."""
    detector = ToolDetector()
    options = await detector.detect_all()

    agent_types = [o.agent_type for o in options]
    assert AgentRunnerType.CODEX_SERVER in agent_types


async def test_detect_codex_server_model_field_present() -> None:
    """CODEX_SERVER config schema includes a 'model' field for session model selection."""
    detector = ToolDetector()
    options = await detector.detect_all()

    cs = [o for o in options if o.agent_type == AgentRunnerType.CODEX_SERVER][0]
    field_names = [f.name for f in cs.config_schema]
    assert "model" in field_names

    model_field = next(f for f in cs.config_schema if f.name == "model")
    # When codex is installed and models are discoverable the field is 'select';
    # otherwise it falls back to 'string'. Both are valid.
    assert model_field.field_type in ("string", "select")
    if model_field.field_type == "select":
        assert model_field.options is not None
        assert len(model_field.options) > 0
        assert model_field.default == model_field.options[0]


async def test_detect_codex_server_title() -> None:
    """CODEX_SERVER entry has the expected title describing local operation."""
    detector = ToolDetector()
    options = await detector.detect_all()

    cs = [o for o in options if o.agent_type == AgentRunnerType.CODEX_SERVER][0]
    assert cs.title == "Codex Server (local)"


async def test_detect_codex_server_description_mentions_local_process() -> None:
    """CODEX_SERVER description mentions it launches a local process."""
    detector = ToolDetector()
    options = await detector.detect_all()

    cs = [o for o in options if o.agent_type == AgentRunnerType.CODEX_SERVER][0]
    assert "local" in cs.description.lower() or "stdio" in cs.description.lower()


async def test_detect_codex_server_install_hint_content() -> None:
    """CODEX_SERVER install_hint mentions npm or the Codex CLI when unavailable."""
    detector = ToolDetector()
    options = await detector.detect_all()

    cs = [o for o in options if o.agent_type == AgentRunnerType.CODEX_SERVER][0]
    if not cs.available:
        assert cs.install_hint is not None
        hint_lower = cs.install_hint.lower()
        assert "codex" in hint_lower or "npm" in hint_lower


async def test_detect_codex_server_restrictions_field_has_default() -> None:
    """CODEX_SERVER restrictions config field has a default value."""
    detector = ToolDetector()
    options = await detector.detect_all()

    cs = [o for o in options if o.agent_type == AgentRunnerType.CODEX_SERVER][0]
    restrictions_field = next(f for f in cs.config_schema if f.name == "restrictions")
    assert restrictions_field.default is not None
    assert restrictions_field.default == "no-network"
