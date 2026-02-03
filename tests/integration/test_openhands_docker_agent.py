"""Integration tests for DockerOpenHandsAgent.

These tests require Docker daemon and/or OPENAI_API_KEY.
Tests are skipped when prerequisites are not met.
"""

import os
import subprocess
from collections.abc import Generator

import httpx
import pytest

from orchestrator.agents.errors import AgentNotAvailableError
from orchestrator.agents.openhands_docker import (
    DockerOpenHandsAgent,
    _DOCKER_WORKSPACE_AVAILABLE,
)
from orchestrator.agents.types import ExecutionContext


def _docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _kill_orphan_agent_containers() -> None:
    """Stop and remove any leftover agent-server-* containers.

    DockerWorkspace names containers ``agent-server-<uuid>`` and creates them
    with ``--rm``, so stopping is sufficient to remove them.  We also attempt
    ``docker rm -f`` as a safety net in case ``--rm`` was somehow absent.
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
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)
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
def _cleanup_containers() -> Generator[None, None, None]:
    """Remove orphan agent-server containers before and after every test.

    Runs before (to handle leftovers from a previously crashed run) and after
    (to guarantee cleanup even if the test itself raises).
    """
    _kill_orphan_agent_containers()
    yield
    _kill_orphan_agent_containers()


@_needs_docker
@_needs_workspace_pkg
def test_docker_workspace_lifecycle() -> None:
    """DockerWorkspace starts a container, serves health, and cleans up."""
    from openhands.workspace import DockerWorkspace  # pyright: ignore[reportMissingImports]

    from orchestrator.agents.openhands_docker import _detect_platform

    platform = _detect_platform()
    kwargs: dict[str, str] = {}
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

    # After context manager exit, container is cleaned up
    running_after = _running_agent_container_names()
    assert len(running_after) == 0


@_needs_docker
@_needs_workspace_pkg
def test_docker_workspace_cleanup_on_exception() -> None:
    """Container is cleaned up even when an exception occurs inside the block."""
    from openhands.workspace import DockerWorkspace  # pyright: ignore[reportMissingImports]

    from orchestrator.agents.openhands_docker import _detect_platform

    platform = _detect_platform()
    kwargs: dict[str, str] = {}
    if platform is not None:
        kwargs["platform"] = platform

    with pytest.raises(RuntimeError, match="deliberate"):
        with DockerWorkspace(server_image="ghcr.io/openhands/agent-server:latest-python", **kwargs):
            raise RuntimeError("deliberate")

    # Container should be gone despite the exception
    running = _running_agent_container_names()
    assert len(running) == 0


@_needs_docker
async def test_docker_openhands_health_check() -> None:
    """check_health() returns True when Docker daemon is running."""
    agent = DockerOpenHandsAgent()
    assert await agent.check_health() is True


async def test_docker_openhands_health_check_no_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    """check_health() returns False when docker is not in PATH."""
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _name: None)
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


async def test_docker_openhands_sdk_not_available() -> None:
    """execute() raises AgentNotAvailableError when SDK is not installed."""
    import orchestrator.agents.openhands_docker as mod

    original = mod._SDK_AVAILABLE
    try:
        mod._SDK_AVAILABLE = False  # pyright: ignore[reportConstantRedefinition]
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
    finally:
        mod._SDK_AVAILABLE = original  # pyright: ignore[reportConstantRedefinition]


async def test_docker_openhands_workspace_not_available() -> None:
    """execute() raises AgentNotAvailableError when workspace package is missing."""
    import orchestrator.agents.openhands_docker as mod

    original_sdk = mod._SDK_AVAILABLE
    original_ws = mod._DOCKER_WORKSPACE_AVAILABLE
    try:
        mod._SDK_AVAILABLE = True  # pyright: ignore[reportConstantRedefinition]
        mod._DOCKER_WORKSPACE_AVAILABLE = False  # pyright: ignore[reportConstantRedefinition]
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
    finally:
        mod._SDK_AVAILABLE = original_sdk  # pyright: ignore[reportConstantRedefinition]
        mod._DOCKER_WORKSPACE_AVAILABLE = original_ws  # pyright: ignore[reportConstantRedefinition]
