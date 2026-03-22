"""CLI subprocess activity adapter."""

from orchestrator.workflow.activity import BaseActivityAdapter


class CLIActivityAdapter(BaseActivityAdapter):
    """ActivityAdapter wrapping CLIAgent (subprocess-based runner).

    The CLI agent enriches its own prompt with REST callback instructions
    when ``api_base_url`` is set on the context, so no-op callbacks from
    BaseActivityAdapter.start() are sufficient.  No runner-specific
    divergence exists — BaseActivityAdapter handles everything.
    """
