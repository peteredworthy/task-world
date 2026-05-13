"""Integration tests for DockerOpenHandsAgent.

These tests avoid starting agent-server containers. Container lifecycle checks
live in tests/slow because they require Docker I/O and are expensive to collect
and run in the default suite.
"""

import shutil
import subprocess

import pytest

from orchestrator.runners.errors import AgentNotAvailableError
from orchestrator.runners import (
    DockerOpenHandsAgent,
    _DOCKER_WORKSPACE_AVAILABLE,  # pyright: ignore[reportPrivateUsage]
    _SDK_AVAILABLE,  # pyright: ignore[reportPrivateUsage]
)
from orchestrator.runners.types import ExecutionContext


def _docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


@pytest.fixture
def require_docker() -> None:
    if not _docker_available():
        pytest.skip("Docker daemon not available")


async def test_docker_openhands_health_check(require_docker: None) -> None:
    """check_health() returns True when Docker daemon is running."""
    agent = DockerOpenHandsAgent()
    assert await agent.check_health() is True


@pytest.mark.skipif(
    shutil.which("docker") is not None,
    reason="docker is available in PATH; cannot test missing-docker path",
)
async def test_docker_openhands_health_check_no_docker() -> None:
    """check_health() returns False when docker is not in PATH."""
    agent = DockerOpenHandsAgent()
    assert await agent.check_health() is False


async def test_docker_openhands_missing_api_key() -> None:
    """execute() raises AgentNotAvailableError when API key is missing."""
    agent = DockerOpenHandsAgent(api_key="placeholder")
    agent._api_key = ""  # pyright: ignore[reportPrivateUsage]
    context = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp",
        prompt="test",
        requirements=["test"],
    )

    async def noop_checklist(req_id: str, status: object, note: str | None) -> None:
        pass

    async def noop_submit() -> None:
        pass

    with pytest.raises(AgentNotAvailableError, match="OPENAI_API_KEY"):
        await agent.execute(context, noop_checklist, noop_submit)


@pytest.mark.skipif(_SDK_AVAILABLE, reason="SDK is installed; cannot test missing-SDK path")
async def test_docker_openhands_sdk_not_available() -> None:
    """execute() raises AgentNotAvailableError when SDK is not installed."""
    agent = DockerOpenHandsAgent(api_key="test-key")
    context = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp",
        prompt="test",
        requirements=["test"],
    )

    async def noop_checklist(req_id: str, status: object, note: str | None) -> None:
        pass

    async def noop_submit() -> None:
        pass

    with pytest.raises(AgentNotAvailableError, match="SDK not installed"):
        await agent.execute(context, noop_checklist, noop_submit)


@pytest.mark.skipif(
    _DOCKER_WORKSPACE_AVAILABLE,
    reason="openhands-workspace is installed; cannot test missing-workspace path",
)
@pytest.mark.skipif(not _SDK_AVAILABLE, reason="SDK not installed")
async def test_docker_openhands_workspace_not_available() -> None:
    """execute() raises AgentNotAvailableError when workspace package is missing."""
    agent = DockerOpenHandsAgent(api_key="test-key")
    context = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp",
        prompt="test",
        requirements=["test"],
    )

    async def noop_checklist(req_id: str, status: object, note: str | None) -> None:
        pass

    async def noop_submit() -> None:
        pass

    with pytest.raises(AgentNotAvailableError, match="openhands-workspace"):
        await agent.execute(context, noop_checklist, noop_submit)
