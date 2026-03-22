"""OpenHands activity adapter."""

from orchestrator.workflow.activity import BaseActivityAdapter


class OpenHandsActivityAdapter(BaseActivityAdapter):
    """ActivityAdapter wrapping OpenHandsAgent (in-process openhands-ai runner).

    The OpenHands agent uses custom tool executors for checklist/submit
    callbacks.  Future override of start() may wire real in-process
    callbacks rather than REST calls.  For now, BaseActivityAdapter handles
    everything via no-op callbacks (agent uses api_base_url for callbacks).
    """
