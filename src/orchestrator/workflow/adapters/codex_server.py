"""Codex server activity adapter."""

from orchestrator.workflow.activity import BaseActivityAdapter


class CodexServerActivityAdapter(BaseActivityAdapter):
    """ActivityAdapter wrapping CodexServerAgent (managed subprocess runner).

    The Codex server communicates via JSON-RPC 2.0 over stdio and handles
    dynamic tool specs internally.  No runner-specific divergence exists
    from the adapter perspective — BaseActivityAdapter handles everything.
    """
