"""Pydantic schemas for model profiles and agent runner model defaults."""

from typing import Annotated

from pydantic import BeforeValidator

from orchestrator.api.schemas.base import ApiModel
from orchestrator.config import SELECTABLE_AGENT_RUNNER_VALUES
from orchestrator.config.enums import ModelProfile


_SELECTABLE_AGENT_RUNNER_VALUES = sorted(SELECTABLE_AGENT_RUNNER_VALUES)


def validate_selectable_agent_runner_type(value: str) -> str:
    """Normalize and validate a runner selected for new execution."""
    lowered = value.lower()
    if lowered not in SELECTABLE_AGENT_RUNNER_VALUES:
        raise ValueError(
            f"Invalid agent_runner_type '{value}'. Valid options: "
            f"{', '.join(_SELECTABLE_AGENT_RUNNER_VALUES)}"
        )
    return lowered


SelectableAgentRunnerType = Annotated[str, BeforeValidator(validate_selectable_agent_runner_type)]


class ModelProfileSchema(ApiModel):
    name: ModelProfile
    description: str


class AgentRunnerModelProfileDefaultsSchema(ApiModel):
    agent_runner_type: SelectableAgentRunnerType
    model_profile_defaults: dict[ModelProfile, str]
