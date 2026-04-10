"""Tests for global config to agent config conversion."""

from datetime import timedelta

from orchestrator.config.global_config import NudgerConfig


def test_nudger_config_to_agent_config() -> None:
    """NudgerConfig.to_agent_config() converts to agent format."""
    config = NudgerConfig(
        check_interval_seconds=60,
        nudge_after_seconds=300,
        kill_after_seconds=900,
    )

    agent_config = config.to_agent_config()

    assert agent_config.output_timeout == timedelta(seconds=300)
    assert agent_config.nudge_interval == timedelta(seconds=60)
    assert agent_config.max_nudges == 3  # 900 / 300
    assert agent_config.nudge_message == "Please continue or call orchestrator tools to submit."


def test_nudger_config_to_agent_config_defaults() -> None:
    """Default NudgerConfig values convert correctly."""
    config = NudgerConfig()

    agent_config = config.to_agent_config()

    assert agent_config.output_timeout == timedelta(seconds=300)
    assert agent_config.nudge_interval == timedelta(seconds=60)
    assert agent_config.max_nudges == 2  # 600 / 300
