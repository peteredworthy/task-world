"""Claude Agent SDK activity adapter."""

from orchestrator.workflow.activity import BaseActivityAdapter


class ClaudeSdkActivityAdapter(BaseActivityAdapter):
    """ActivityAdapter wrapping ClaudeSdkAgent (in-process SDK runner).

    The SDK agent uses an in-process MCP server for orchestrator callbacks.
    Future override of start() may wire real in-process callbacks rather
    than relying on REST API calls.  For now, BaseActivityAdapter handles
    everything via no-op callbacks (agent uses api_base_url for callbacks).
    """
