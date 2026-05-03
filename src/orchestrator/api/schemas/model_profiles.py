"""Pydantic schemas for model profiles and agent runner model defaults."""

from orchestrator.api.schemas.base import ApiModel
from orchestrator.config.enums import ModelProfile


class ModelProfileSchema(ApiModel):
    name: ModelProfile
    description: str


class AgentRunnerModelProfileDefaultsSchema(ApiModel):
    agent_runner_type: str
    model_profile_defaults: dict[ModelProfile, str]
