"""Re-export bridge for backward compatibility.

agent/prompts.py moved; this module re-exports from the new location.
"""

from orchestrator.workflow.agent.prompts import *  # noqa: F401, F403
