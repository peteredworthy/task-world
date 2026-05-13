"""Slow DockerWorkspace lifecycle checks.

These are external Docker integration tests, not orchestrator E2E tests.
"""

import subprocess
from collections.abc import Generator
from typing import Any

import httpx
import pytest

from orchestrator.runners import (  # pyright: ignore[reportPrivateUsage]
    _DOCKER_WORKSPACE_AVAILABLE,
    _detect_platform,
)


def _docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _kill_orphan_agent_containers() -> None:
    """Kill and remove leftover agent-server containers."""
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
_needs_workspace_pkg = pytest.mark.skipif(
    not _DOCKER_WORKSPACE_AVAILABLE, reason="openhands-workspace not installed"
)


@pytest.fixture(autouse=True)
def _cleanup_containers() -> Generator[None, None, None]:  # pyright: ignore[reportUnusedFunction]
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

    platform = _detect_platform()
    kwargs: dict[str, Any] = {}
    if platform is not None:
        kwargs["platform"] = platform

    with DockerWorkspace(
        server_image="ghcr.io/openhands/agent-server:latest-python", **kwargs
    ) as ws:
        assert ws.host.startswith("http://localhost:")

        response = httpx.get(f"{ws.host}/health", timeout=5)
        assert response.status_code == 200

        running = _running_agent_container_names()
        assert len(running) == 1

        cid = ws._container_id  # pyright: ignore[reportPrivateUsage]
        assert cid is not None
        subprocess.run(["docker", "kill", cid], capture_output=True, timeout=10)

    running_after = _running_agent_container_names()
    assert len(running_after) == 0


@pytest.mark.slow
@pytest.mark.timeout(120)
@_needs_docker
@_needs_workspace_pkg
def test_docker_workspace_cleanup_on_exception() -> None:
    """Container is cleaned up even when an exception occurs inside the block."""
    from openhands.workspace import DockerWorkspace  # pyright: ignore[reportMissingImports]

    platform = _detect_platform()
    kwargs: dict[str, Any] = {}
    if platform is not None:
        kwargs["platform"] = platform

    with pytest.raises(RuntimeError, match="deliberate"):
        with DockerWorkspace(
            server_image="ghcr.io/openhands/agent-server:latest-python", **kwargs
        ) as ws:
            cid = ws._container_id  # pyright: ignore[reportPrivateUsage]
            assert cid is not None
            subprocess.run(["docker", "kill", cid], capture_output=True, timeout=10)
            raise RuntimeError("deliberate")

    running = _running_agent_container_names()
    assert len(running) == 0
