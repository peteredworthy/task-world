"""Pydantic schemas for model profiles and runner profile defaults."""

from orchestrator.api.schemas.base import ApiModel
from orchestrator.config.enums import ModelProfile


class ModelProfileSchema(ApiModel):
    name: ModelProfile
    description: str


class RunnerProfileDefaultsSchema(ApiModel):
    runner_type: str
    profiles: dict[ModelProfile, str]
