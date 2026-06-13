"""Configuration API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from orchestrator.api.deps import get_global_config
from orchestrator.config.global_config import GlobalConfig

router = APIRouter(prefix="/api/config", tags=["config"])


class ConfigResponse(BaseModel):
    """Global configuration exposed to the frontend."""

    dashboard_refresh_interval_seconds: int
    dashboard_max_recent_runs: int
    default_execution_mode: str
    agents_openhands_url: str | None
    agents_default_type: str | None


@router.get("", response_model=ConfigResponse)
async def get_config(
    config: Annotated[GlobalConfig, Depends(get_global_config)],
) -> ConfigResponse:
    """Get global configuration settings."""
    return ConfigResponse(
        dashboard_refresh_interval_seconds=config.dashboard.refresh_interval_seconds,
        dashboard_max_recent_runs=config.dashboard.max_recent_runs,
        default_execution_mode=config.execution.default_execution_mode,
        agents_openhands_url=config.agents.openhands_url,
        agents_default_type=config.agents.default_type,
    )
