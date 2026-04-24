"""Config schema and session recovery for CODEX_SERVER agents.

Extracted from ``detector.py`` and ``executor._prepare_codex_config``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from orchestrator.runners.types import AgentConfigField
from orchestrator.config.enums import AgentRunnerType

logger = logging.getLogger(__name__)

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
]


def codex_server_config_with_models(models: list[str]) -> list[AgentConfigField]:
    """Return the Codex Server config schema with the model field populated.

    When *models* is non-empty the model field is upgraded to a ``"select"``
    with the discovered model IDs as options and the first entry as the
    default.  When empty the field stays as a plain ``"string"`` with no
    options, preserving the existing behaviour.

    Args:
        models: Ordered list of model ID strings returned by
            ``fetch_codex_models()``.

    Returns:
        A new config schema list with the model field updated.
    """
    config: list[AgentConfigField] = []
    for cfg_field in CODEX_SERVER_CONFIG:
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


def _is_codex_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def prepare_codex_config(
    agent_type: AgentRunnerType,
    agent_config: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    """Apply the deterministic recovery rule for Codex agents.

    Inspects the stored session state (PID for local) and decides whether
    to resume the persisted session or discard it and start a fresh attempt.

    Rule:
    - Healthy persisted session  -> return config unchanged so the agent
      can resume (PID passed through).
    - Stale / missing session    -> return a cleaned config (session keys
      removed) and a non-None ``stale_reason`` string describing why the
      session was discarded.

    Only CODEX_SERVER is handled; all other agent types are returned
    unchanged with ``stale_reason=None``.

    Args:
        agent_type: The agent type of the run.
        agent_config: The current agent_config dict from the run.

    Returns:
        ``(effective_config, stale_reason)`` where ``effective_config``
        is the agent_config to use for agent creation (may have session
        keys stripped) and ``stale_reason`` is ``None`` when the session
        is healthy or the agent type is not Codex.
    """
    if agent_type == AgentRunnerType.CODEX_SERVER:
        pid_raw = agent_config.get("pid")
        if pid_raw is None:
            return agent_config, None
        pid = int(pid_raw)
        if _is_codex_process_alive(pid):
            return agent_config, None
        stale_reason = f"local_codex_process_not_alive (pid={pid})"
        cleaned = {k: v for k, v in agent_config.items() if k != "pid"}
        logger.info("Codex config: session stale — %s; starting fresh", stale_reason)
        return cleaned, stale_reason

    return agent_config, None
