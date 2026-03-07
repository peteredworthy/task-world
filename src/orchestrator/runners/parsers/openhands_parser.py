"""Backward-compat shim — real code at runners.agents.openhands.parser."""

from orchestrator.runners.agents.openhands.parser import *  # noqa: F401,F403
from orchestrator.runners.agents.openhands.parser import (
    OpenHandsEventParser as OpenHandsEventParser,
)  # noqa: F401
