"""Config schema and detection for the Claude SDK agent."""

from __future__ import annotations

from orchestrator.runners.types import AgentConfigField, AgentOption
from orchestrator.config.enums import AgentRunnerType


_CLAUDE_SDK_CONFIG: list[AgentConfigField] = [
    AgentConfigField(
        name="model",
        field_type="string",
        default="claude-sonnet-4-5",
        description="Claude model to use (e.g. claude-sonnet-4-5, claude-opus-4-5)",
    ),
    AgentConfigField(
        name="api_key",
        field_type="secret",
        description=(
            "Anthropic API key (optional). Falls back to ANTHROPIC_API_KEY env var, "
            "then the Claude CLI OAuth token from the macOS keychain (`claude auth login`)."
        ),
    ),
    AgentConfigField(
        name="auth_token",
        field_type="secret",
        description=(
            "Anthropic OAuth bearer token (optional). Falls back to ANTHROPIC_AUTH_TOKEN env var, "
            "then the Claude CLI OAuth token from the macOS keychain."
        ),
    ),
    AgentConfigField(
        name="max_turns",
        field_type="number",
        default=50,
        description="Maximum agentic turns per run",
    ),
]


def _claude_sdk_config_with_models(models: list[str]) -> list[AgentConfigField]:
    """Return the Claude SDK config schema with the model field populated.

    When *models* is non-empty the model field is upgraded to a ``"select"``
    with the discovered model IDs as options and the first entry as the
    default.  When empty the field stays as a plain ``"string"`` with the
    existing default, preserving the existing behaviour.

    Args:
        models: Ordered list of model ID strings returned by
            ``fetch_claude_models()``.

    Returns:
        A new config schema list with the model field updated.
    """
    config: list[AgentConfigField] = []
    for cfg_field in _CLAUDE_SDK_CONFIG:
        if cfg_field.name == "model" and models:
            config.append(
                cfg_field.model_copy(
                    update={
                        "field_type": "select",
                        "options": models,
                        "default": models[0],
                    }
                )
            )
        else:
            config.append(cfg_field.model_copy())
    return config


def detect() -> AgentOption:
    """Check if the Claude Agent SDK is importable for in-process execution.

    When available, ``fetch_claude_models()`` is called to discover the
    models exposed by the Anthropic API.  If successful, the ``model``
    config field is upgraded to a ``"select"`` with the available model IDs
    and the first model set as the default value.  When model discovery
    fails the field stays as a plain ``"string"``.
    """
    try:
        import claude_agent_sdk  # noqa: F401  # pyright: ignore[reportUnusedImport]

        from orchestrator.runners.agents.claude_sdk.agent import fetch_claude_models

        models = fetch_claude_models()
        config_schema = _claude_sdk_config_with_models(models)
        return AgentOption(
            agent_type=AgentRunnerType.CLAUDE_SDK,
            name="Claude SDK",
            title="Claude SDK Agent",
            description=(
                "In-process Claude agent using the Claude Agent SDK. "
                "Runs locally with built-in tools (Read, Write, Edit, Bash, etc.) "
                "and orchestrator callbacks exposed via an in-process MCP server."
            ),
            available=True,
            detail="claude-agent-sdk installed",
            config_schema=config_schema,
        )
    except ImportError:
        return AgentOption(
            agent_type=AgentRunnerType.CLAUDE_SDK,
            name="Claude SDK",
            title="Claude SDK Agent",
            description=(
                "In-process Claude agent using the Claude Agent SDK. "
                "Runs locally with built-in tools (Read, Write, Edit, Bash, etc.) "
                "and orchestrator callbacks exposed via an in-process MCP server."
            ),
            available=False,
            detail="claude-agent-sdk not installed",
            install_hint="Install with: uv add claude-agent-sdk",
            config_schema=_CLAUDE_SDK_CONFIG,
        )
