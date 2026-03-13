"""Pydantic schemas for Agent CRUD API."""

from datetime import datetime

from pydantic import Field, field_validator

from orchestrator.api.schemas.base import ApiModel
from orchestrator.config.enums import ModelProfile


class AgentSchema(ApiModel):
    id: str
    name: str
    system_prompt: str
    default_prompt: str
    model_profile: ModelProfile
    created_at: datetime
    updated_at: datetime


class CreateAgentRequest(ApiModel):
    name: str = Field(..., min_length=1)
    system_prompt: str = Field(..., min_length=1)
    default_prompt: str = Field(default="")
    model_profile: ModelProfile = ModelProfile.coder

    @field_validator("model_profile", mode="before")
    @classmethod
    def normalize_model_profile(cls, v: object) -> object:
        if isinstance(v, str):
            return v.lower()
        return v


class UpdateAgentRequest(ApiModel):
    name: str | None = Field(default=None, min_length=1)
    system_prompt: str | None = Field(default=None, min_length=1)
    default_prompt: str | None = None
    model_profile: ModelProfile | None = None

    @field_validator("model_profile", mode="before")
    @classmethod
    def normalize_model_profile(cls, v: object) -> object:
        if isinstance(v, str):
            return v.lower()
        return v
