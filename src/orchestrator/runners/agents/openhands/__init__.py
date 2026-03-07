"""OpenHands agent sub-package — registers OPENHANDS_LOCAL and OPENHANDS_DOCKER.

Uses try/except ImportError since openhands is an optional dependency.
"""

from orchestrator.runners.agents.openhands.factory import create_local, create_docker  # noqa: F401
from orchestrator.runners.agents.openhands.config import (  # noqa: F401
    OPENHANDS_LOCAL_CONFIG,
    OPENHANDS_DOCKER_CONFIG,
)

# Re-export agent classes with graceful fallback for missing openhands SDK
try:
    from orchestrator.runners.agents.openhands.agent import OpenHandsAgent  # noqa: F401
except ImportError:
    pass

try:
    from orchestrator.runners.agents.openhands.docker_agent import DockerOpenHandsAgent  # noqa: F401
except ImportError:
    pass

# Register factory functions — wrapped in try/except since openhands is optional
try:
    from orchestrator.config.enums import AgentRunnerType
    from orchestrator.runners.agent_factory import register

    register(AgentRunnerType.OPENHANDS_LOCAL, create_local)
    register(AgentRunnerType.OPENHANDS_DOCKER, create_docker)
except ImportError:
    pass

__all__ = [
    "create_local",
    "create_docker",
    "OPENHANDS_LOCAL_CONFIG",
    "OPENHANDS_DOCKER_CONFIG",
    "OpenHandsAgent",
    "DockerOpenHandsAgent",
]
