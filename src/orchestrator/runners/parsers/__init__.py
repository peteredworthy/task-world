"""Per-agent stream parsers for structured action log capture."""
# pyright: reportUnsupportedDunderAll=false

from orchestrator.runners.parsers.base import BatchParser, StreamParser

# Lazy imports to avoid circular dependency with agent sub-packages.
# The parser files in agent sub-packages import from parsers.base,
# which triggers this __init__.py, creating a cycle if we eagerly
# import from the agent sub-packages here.


def __getattr__(name: str) -> object:
    if name == "ClaudeStreamParser":
        from orchestrator.runners.agents.claude_cli.parser import ClaudeStreamParser

        return ClaudeStreamParser
    if name == "CodexStreamParser":
        from orchestrator.runners.agents.codex.parser import CodexStreamParser

        return CodexStreamParser
    if name == "OpenHandsEventParser":
        from orchestrator.runners.agents.openhands.parser import OpenHandsEventParser

        return OpenHandsEventParser
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BatchParser",
    "ClaudeStreamParser",
    "CodexStreamParser",
    "OpenHandsEventParser",
    "StreamParser",
]
