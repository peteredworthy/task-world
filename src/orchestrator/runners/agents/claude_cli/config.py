"""Config schema for CLI_SUBPROCESS agents.

Extracted from ``detector.py``.
"""

from __future__ import annotations

from orchestrator.runners.types import AgentConfigField

CLI_SUBPROCESS_CONFIG: list[AgentConfigField] = [
    AgentConfigField(
        name="command",
        field_type="string",
        description="CLI command to run (read-only, set by detection)",
    ),
    AgentConfigField(
        name="model",
        field_type="string",
        description="Model to pass as --model flag",
    ),
    AgentConfigField(
        name="callback_channel",
        field_type="select",
        default="rest",
        description="How the subprocess calls back to the orchestrator",
        options=["rest", "mcp"],
    ),
    AgentConfigField(
        name="stdin_mode",
        field_type="select",
        default="close",
        description="Whether to close stdin after sending the prompt",
        options=["close", "open"],
    ),
]


def cli_config_for_command(command: str) -> list[AgentConfigField]:
    """Return CLI config schema with command default pinned to the selected tool."""
    config: list[AgentConfigField] = []
    for cfg_field in CLI_SUBPROCESS_CONFIG:
        if cfg_field.name == "command":
            config.append(cfg_field.model_copy(update={"default": command}))
        else:
            config.append(cfg_field.model_copy())
    return config


def cli_config_for_codex(command: str, models: list[str]) -> list[AgentConfigField]:
    """Return the CLI config schema for ``codex`` with model options populated.

    When *models* is non-empty the ``model`` field is upgraded to a
    ``"select"`` with the discovered IDs as options and the first entry
    as the default.  When empty the field stays as a plain
    ``"string"`` -- identical to the baseline ``cli_config_for_command``
    output.

    Args:
        command: The CLI command name (e.g. ``"codex"``).
        models: Ordered list of model ID strings returned by
            ``fetch_codex_models()``.

    Returns:
        A config schema list with the ``command`` default pinned and the
        ``model`` field updated when models are available.
    """
    config: list[AgentConfigField] = []
    for cfg_field in CLI_SUBPROCESS_CONFIG:
        if cfg_field.name == "command":
            config.append(cfg_field.model_copy(update={"default": command}))
        elif cfg_field.name == "model" and models:
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
