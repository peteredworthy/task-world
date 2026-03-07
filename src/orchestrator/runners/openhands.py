"""Backward-compat shim — real code at runners.agents.openhands.agent."""

from orchestrator.runners.agents.openhands.agent import *  # noqa: F401,F403
from orchestrator.runners.agents.openhands.agent import OpenHandsAgent as OpenHandsAgent  # noqa: F401

# Re-export private names used by tests
try:
    from orchestrator.runners.agents.openhands.agent import (  # noqa: F401
        _SDK_AVAILABLE as _SDK_AVAILABLE,  # pyright: ignore[reportPrivateUsage]
        _build_openhands_mcp_config as _build_openhands_mcp_config,  # pyright: ignore[reportPrivateUsage]
        _obs_get_req as _obs_get_req,  # pyright: ignore[reportPrivateUsage]
    )
except ImportError:
    pass
