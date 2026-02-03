"""Unit tests for DockerOpenHandsAgent.

These tests verify agent metadata, prompt construction, and platform detection
without requiring Docker, the SDK, or any network access.
"""

from orchestrator.agents.openhands_common import build_openhands_prompt
from orchestrator.agents.openhands_docker import (
    DockerOpenHandsAgent,
    _detect_platform,  # pyright: ignore[reportPrivateUsage]
)
from orchestrator.agents.types import ExecutionContext
from orchestrator.config.enums import AgentType


def test_docker_agent_info() -> None:
    agent = DockerOpenHandsAgent()
    assert agent.info.agent_type == AgentType.OPENHANDS_DOCKER
    assert agent.info.name == "OpenHands (Docker)"


def test_docker_build_prompt_contains_requirements() -> None:
    context = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp/work",
        prompt="Do the thing",
        requirements=["req-A", "req-B"],
    )
    prompt = build_openhands_prompt(context)

    assert "Do the thing" in prompt
    assert "req-A" in prompt
    assert "req-B" in prompt
    assert "Requirements" in prompt
    assert "update_checklist" in prompt
    assert "submit" in prompt


def test_docker_platform_detection() -> None:
    """_detect_platform returns a valid platform string or None."""
    result = _detect_platform()  # pyright: ignore[reportPrivateUsage]
    if result is not None:
        assert result.startswith("linux/")
        assert result in ("linux/amd64", "linux/arm64")
