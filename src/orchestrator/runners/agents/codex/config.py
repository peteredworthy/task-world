"""Config schema and session recovery for CODEX_SERVER agents.

Extracted from ``detector.py`` and ``executor._prepare_codex_config``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from orchestrator.config.enums import AgentRunnerType
from orchestrator.runners.agents.codex.common import select_preferred_codex_model
from orchestrator.runners.types import AgentConfigField

logger = logging.getLogger(__name__)

LMSTUDIO_QWEN_27B_MODELS: list[str] = [
    "qwen3.8-27b-mlx@4bit",
    "qwen3.8-27b-mlx@8bit",
]

CODEX_LOCAL_PROVIDER_FIELD = AgentConfigField(
    name="local_provider",
    field_type="select",
    default="openai",
    description=(
        "Codex inference provider. Select LM Studio to use a locally loaded "
        "model while retaining Codex Server's native orchestration tools."
    ),
    options=["openai", "lmstudio"],
)

CODEX_SERVER_CONFIG: list[AgentConfigField] = [
    AgentConfigField(
        name="model",
        field_type="string",
        description="Model to use for Codex agent sessions",
        allow_custom=True,
    ),
    AgentConfigField(
        name="callback_channel",
        field_type="select",
        default="rest",
        description="How the Codex server calls back to the orchestrator",
        options=["rest", "mcp"],
    ),
    AgentConfigField(
        name="restrictions",
        field_type="select",
        default="managed",
        description=(
            "How strictly to sandbox Codex. "
            "'none' runs with workspace-write and network enabled. "
            "'managed' uses orchestrator-managed writable roots; network is currently enabled "
            "so package-manager caches and hook environments can refresh. "
            "'use-local' hands control to your local Codex config.toml (may be read-only)."
        ),
        options=["none", "managed", "use-local"],
    ),
    AgentConfigField(
        name="reasoning_effort",
        field_type="select",
        default="high",
        description="Reasoning effort for Codex model turns",
        options=["low", "medium", "high"],
    ),
    CODEX_LOCAL_PROVIDER_FIELD,
]


def codex_server_config_with_models(models: list[str]) -> list[AgentConfigField]:
    """Return the Codex Server config schema with discovered and local models."""
    config: list[AgentConfigField] = []
    for cfg_field in CODEX_SERVER_CONFIG:
        if cfg_field.name == "model":
            options = list(dict.fromkeys([*models, *LMSTUDIO_QWEN_27B_MODELS]))
            config.append(
                cfg_field.model_copy(
                    update={
                        "field_type": "combobox",
                        "allow_custom": True,
                        "options": options,
                        "default": select_preferred_codex_model(models),
                    }
                )
            )
        else:
            config.append(cfg_field.model_copy())
    return config


def _is_codex_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def prepare_codex_config(
    agent_runner_type: AgentRunnerType,
    agent_runner_config: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    """Apply the deterministic recovery rule for Codex agent sessions."""
    if agent_runner_type == AgentRunnerType.CODEX_SERVER:
        pid_raw = agent_runner_config.get("pid")
        if pid_raw is None:
            return agent_runner_config, None
        pid = int(pid_raw)
        if _is_codex_process_alive(pid):
            return agent_runner_config, None
        stale_reason = f"local_codex_process_not_alive (pid={pid})"
        cleaned = {key: value for key, value in agent_runner_config.items() if key != "pid"}
        logger.info("Codex config: session stale — %s; starting fresh", stale_reason)
        return cleaned, stale_reason

    return agent_runner_config, None
