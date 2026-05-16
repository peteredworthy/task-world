"""Tests for global config to agent runner config conversion."""

from datetime import timedelta

from orchestrator.config.global_config import NudgerConfig


def test_nudger_config_to_agent_runner_config() -> None:
    """NudgerConfig.to_agent_runner_config() converts to agent format."""
    config = NudgerConfig(
        check_interval_seconds=60,
        nudge_after_seconds=300,
        kill_after_seconds=900,
    )

    agent_runner_config = config.to_agent_runner_config()

    assert agent_runner_config.output_timeout == timedelta(seconds=300)
    assert agent_runner_config.nudge_interval == timedelta(seconds=60)
    assert agent_runner_config.max_nudges == 3  # 900 / 300
    assert (
        agent_runner_config.nudge_message == "Please continue or call orchestrator tools to submit."
    )


def test_nudger_config_to_agent_runner_config_defaults() -> None:
    """Default NudgerConfig values convert correctly."""
    config = NudgerConfig()

    agent_runner_config = config.to_agent_runner_config()

    # Defaults bumped to leave headroom for 600s orchestrator_wait_for_run
    # MCP calls during oversight tasks (parent waiting on child terminal state).
    assert agent_runner_config.output_timeout == timedelta(seconds=660)
    assert agent_runner_config.nudge_interval == timedelta(seconds=60)
    assert agent_runner_config.max_nudges == 2  # 1320 / 660
