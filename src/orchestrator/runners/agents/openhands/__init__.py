"""OpenHands agent sub-package — registers OPENHANDS_LOCAL and OPENHANDS_DOCKER.

Uses try/except ImportError since openhands is an optional dependency.
OpenHandsAgent and DockerOpenHandsAgent are loaded lazily via __getattr__ to
avoid eagerly importing openhands.sdk (~1.5s) when the package is first imported.
"""

from orchestrator.runners.agents.openhands.factory import create_local, create_docker  # noqa: F401
from orchestrator.runners.agents.openhands.config import (  # noqa: F401
    OPENHANDS_LOCAL_CONFIG,
    OPENHANDS_DOCKER_CONFIG,
)

# Register factory functions — wrapped in try/except since openhands is optional
try:
    from orchestrator.config.enums import AgentRunnerType
    from orchestrator.runners.agent_factory import register

    register(AgentRunnerType.OPENHANDS_LOCAL, create_local)
    register(AgentRunnerType.OPENHANDS_DOCKER, create_docker)
except ImportError:
    pass


def __getattr__(name: str):  # type: ignore[misc]
    if name == "OpenHandsAgent":
        from orchestrator.runners.agents.openhands.agent import OpenHandsAgent  # noqa: PLC0415

        return OpenHandsAgent
    if name == "DockerOpenHandsAgent":
        from orchestrator.runners.agents.openhands.docker_agent import DockerOpenHandsAgent  # noqa: PLC0415

        return DockerOpenHandsAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "create_local",
    "create_docker",
    "OPENHANDS_LOCAL_CONFIG",
    "OPENHANDS_DOCKER_CONFIG",
    # OpenHandsAgent and DockerOpenHandsAgent are accessible via __getattr__ (lazy import)
]
