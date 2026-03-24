"""Detection sub-package: agent discovery and configuration."""

from orchestrator.runners.detection.config_utils import coerce_llm_config
from orchestrator.runners.detection.detector import AGENT_CONFIG_FIELDS, ToolDetector
from orchestrator.runners.detection.profile_resolution import resolve_model_for_profile

__all__ = [
    "AGENT_CONFIG_FIELDS",
    "ToolDetector",
    "coerce_llm_config",
    "resolve_model_for_profile",
]
