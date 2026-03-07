"""Backward-compat shim — real code at runners.agents.openhands.docker_agent."""

from orchestrator.runners.agents.openhands.docker_agent import *  # noqa: F401,F403
from orchestrator.runners.agents.openhands.docker_agent import (
    DockerOpenHandsAgent as DockerOpenHandsAgent,
)  # noqa: F401

# Re-export private names used by tests
try:
    from orchestrator.runners.agents.openhands.docker_agent import (  # noqa: F401
        _SDK_AVAILABLE as _SDK_AVAILABLE,  # pyright: ignore[reportPrivateUsage]
        _DOCKER_WORKSPACE_AVAILABLE as _DOCKER_WORKSPACE_AVAILABLE,  # pyright: ignore[reportPrivateUsage]
        _detect_platform as _detect_platform,  # pyright: ignore[reportPrivateUsage]
    )
except ImportError:
    pass
