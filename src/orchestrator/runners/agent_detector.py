"""Registry-based agent detection.

Replaces the hardcoded detector.py by delegating to each agent package's
``config.py`` module for detection and config schema information.

During the transition period, this module coexists with the old detector.py.
It will fully replace it once all agent packages provide detect() and config_schema().
"""

from __future__ import annotations

import logging
from typing import Protocol

from orchestrator.config.enums import AgentRunnerType
from orchestrator.runners.types import AgentConfigField, AgentRunnerOption

logger = logging.getLogger(__name__)


class AgentDetector(Protocol):
    """Protocol that agent config modules must satisfy for detection."""

    def detect(self) -> AgentRunnerOption | list[AgentRunnerOption]: ...

    def config_schema(self) -> list[AgentConfigField]: ...


# Registry: AgentRunnerType -> detector instance or callable
_DETECTORS: dict[AgentRunnerType, AgentDetector] = {}


def register_detector(agent_type: AgentRunnerType, detector: AgentDetector) -> None:
    """Register a detector for an agent type."""
    _DETECTORS[agent_type] = detector
    logger.debug("Registered detector for %s", agent_type.value)


def detect_all() -> list[AgentRunnerOption]:
    """Run detection for all registered agent types."""
    results: list[AgentRunnerOption] = []
    for agent_type, detector in _DETECTORS.items():
        try:
            result = detector.detect()
            if isinstance(result, list):
                results.extend(result)
            else:
                results.append(result)
        except Exception:
            logger.debug("Detection failed for %s", agent_type.value, exc_info=True)
    return results


def get_config_schema(agent_type: AgentRunnerType) -> list[AgentConfigField]:
    """Get the config schema for a specific agent type."""
    detector = _DETECTORS.get(agent_type)
    if detector is None:
        return []
    return detector.config_schema()


def get_detector_registry() -> dict[AgentRunnerType, AgentDetector]:
    """Return a copy of the detector registry (for inspection/testing)."""
    return dict(_DETECTORS)
