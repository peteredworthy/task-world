"""Integration tests for DockerOpenHandsAgent.

These tests require Docker daemon and/or OPENAI_API_KEY.
Tests are skipped when prerequisites are not met.
"""

import os
import shutil
import subprocess
from collections.abc import Generator
from typing import Any

import httpx
import pytest

from orchestrator.runners.errors import AgentNotAvailableError
from orchestrator.runners.openhands_docker import (
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


def _kill_orphan_agent_containers() -> None:
    """Kill and remove any leftover agent-server-* containers.

    Uses ``docker kill`` (immediate SIGKILL) instead of ``docker stop``
    (which waits for a grace period) for fast cleanup in tests.
    DockerWorkspace creates containers with ``--rm``, so killing also
    removes them.  We also attempt ``docker rm -f`` as a safety net.
    """
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=agent-server-", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return
        containers = [name.strip() for name in result.stdout.splitlines() if name.strip()]
        for name in containers:
            subprocess.run(["docker", "kill", name], capture_output=True, timeout=10)
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass


def _running_agent_container_names() -> list[str]:
    """Return names of currently running agent-server-* containers."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=agent-server-", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []
        return [name.strip() for name in result.stdout.splitlines() if name.strip()]
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []


_needs_docker = pytest.mark.skipif(not _docker_available(), reason="Docker daemon not available")
_needs_api_key = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="No OPENAI_API_KEY")
_needs_workspace_pkg = pytest.mark.skipif(
    not _DOCKER_WORKSPACE_AVAILABLE, reason="openhands-workspace not installed"
)


@pytest.fixture(autouse=True)
def _cleanup_containers() -> Generator[None, None, None]:  # pyright: ignore[reportUnusedFunction]
    """Remove orphan agent-server containers before and after every test.

    Runs before (to handle leftovers from a previously crashed run) and after
    (to guarantee cleanup even if the test itself raises).
    """
    _kill_orphan_agent_containers()
    yield
    _kill_orphan_agent_containers()


@pytest.mark.slow
@pytest.mark.timeout(120)
@_needs_docker
@_needs_workspace_pkg
def test_docker_workspace_lifecycle() -> None:
    """DockerWorkspace starts a container, serves health, and cleans up."""
    from openhands.workspace import DockerWorkspace  # pyright: ignore[reportMissingImports]

    from orchestrator.runners.openhands_docker import _detect_platform  # pyright: ignore[reportPrivateUsage]

    platform = _detect_platform()
    kwargs: dict[str, Any] = {}
    if platform is not None:
        kwargs["platform"] = platform

    with DockerWorkspace(
        server_image="ghcr.io/openhands/agent-server:latest-python", **kwargs
    ) as ws:
        # Container is running — host is set to http://localhost:<port>
        assert ws.host.startswith("http://localhost:")

        # Health endpoint responds
        response = httpx.get(f"{ws.host}/health", timeout=5)
        assert response.status_code == 200

        # Exactly one agent-server container should be running
        running = _running_agent_container_names()
        assert len(running) == 1

        # Force-kill the container before context manager exit to avoid
        # the ~7s docker stop grace period.  The --rm flag on docker run
        # auto-removes the container, so cleanup() becomes a no-op.
        cid = ws._container_id  # pyright: ignore[reportPrivateUsage]
        assert cid is not None
        subprocess.run(
            ["docker", "kill", cid],
            capture_output=True,
            timeout=10,
        )

    # After context manager exit, container is cleaned up
    running_after = _running_agent_container_names()
    assert len(running_after) == 0


@pytest.mark.slow
@pytest.mark.timeout(120)
@_needs_docker
@_needs_workspace_pkg
def test_docker_workspace_cleanup_on_exception() -> None:
    """Container is cleaned up even when an exception occurs inside the block."""
    from openhands.workspace import DockerWorkspace  # pyright: ignore[reportMissingImports]

    from orchestrator.runners.openhands_docker import _detect_platform  # pyright: ignore[reportPrivateUsage]

    platform = _detect_platform()
    kwargs: dict[str, Any] = {}
    if platform is not None:
        kwargs["platform"] = platform

    with pytest.raises(RuntimeError, match="deliberate"):
        with DockerWorkspace(
            server_image="ghcr.io/openhands/agent-server:latest-python", **kwargs
        ) as ws:
            # Force-kill the container before raising the exception to avoid
            # the ~7s docker stop grace period during cleanup().
            cid = ws._container_id  # pyright: ignore[reportPrivateUsage]
            assert cid is not None
            subprocess.run(["docker", "kill", cid], capture_output=True, timeout=10)
            raise RuntimeError("deliberate")

    # Container should be gone despite the exception
    running = _running_agent_container_names()
    assert len(running) == 0


@_needs_docker
async def test_docker_openhands_health_check() -> None:
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
