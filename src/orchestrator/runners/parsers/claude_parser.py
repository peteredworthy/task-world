"""Backward-compat shim — real code at runners.agents.claude_cli.parser."""

from orchestrator.runners.agents.claude_cli.parser import *  # noqa: F401,F403
from orchestrator.runners.agents.claude_cli.parser import ClaudeStreamParser as ClaudeStreamParser  # noqa: F401
