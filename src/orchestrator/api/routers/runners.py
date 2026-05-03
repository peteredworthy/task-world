"""Agent discovery API endpoints."""

import logging
import uuid
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.deps import get_session, get_tool_detector
from orchestrator.api.schemas.model_profiles import AgentRunnerModelProfileDefaultsSchema
from orchestrator.config.enums import ModelProfile
from orchestrator.db import AgentRunnerModelProfileDefaultModel
from orchestrator.runners.agent_detector import ToolDetector
from orchestrator.runners.types import AgentRunnerOption

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent-runners", tags=["agent-runners"])


@router.get("", response_model=list[AgentRunnerOption])
async def list_agent_runners(
    detector: Annotated[ToolDetector, Depends(get_tool_detector)],
) -> list[AgentRunnerOption]:
    """List available agent runner backends."""
    return await detector.detect_all()


@router.get("/local-models")
async def discover_local_models(
    base_url: str = Query(..., description="Base URL of the local OpenAI-compatible server"),
) -> dict[str, Any]:
    """Discover models from a local OpenAI-compatible LLM server.

    Calls ``{base_url}/models`` and returns the list of model IDs.
    On connection failure returns an empty list with an error message
    rather than a 4xx/5xx status code so the UI can surface the error
    without throwing an exception.
    """
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=422,
            detail="base_url must start with http:// or https://",
        )
    models_url = base_url.rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(models_url)
            response.raise_for_status()
            data = response.json()
            model_ids = [entry["id"] for entry in data.get("data", []) if "id" in entry]
            return {"models": model_ids}
    except Exception as exc:
        logger.debug("Failed to discover local models from %s: %s", models_url, exc)
        return {"models": [], "error": str(exc)}


@router.get(
    "/{runner_type}/model-profile-defaults",
    response_model=AgentRunnerModelProfileDefaultsSchema,
)
async def get_agent_runner_model_profile_defaults(
    runner_type: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentRunnerModelProfileDefaultsSchema:
    """Get model defaults for each profile on an agent runner type."""
    result = await session.execute(
        select(AgentRunnerModelProfileDefaultModel).where(
            AgentRunnerModelProfileDefaultModel.runner_type == runner_type
        )
    )
    rows = result.scalars().all()
    model_defaults: dict[ModelProfile, str] = {}
    for row in rows:
        try:
            model_defaults[ModelProfile(row.profile)] = row.model
        except ValueError:
            pass
    return AgentRunnerModelProfileDefaultsSchema(
        agent_runner_type=runner_type,
        model_profile_defaults=model_defaults,
    )


@router.put(
    "/{runner_type}/model-profile-defaults",
    response_model=AgentRunnerModelProfileDefaultsSchema,
)
async def set_agent_runner_model_profile_defaults(
    runner_type: str,
    body: AgentRunnerModelProfileDefaultsSchema,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentRunnerModelProfileDefaultsSchema:
    """Set model defaults for each profile on an agent runner type."""
    await session.execute(
        delete(AgentRunnerModelProfileDefaultModel).where(
            AgentRunnerModelProfileDefaultModel.runner_type == runner_type
        )
    )
    for profile, model in body.model_profile_defaults.items():
        session.add(
            AgentRunnerModelProfileDefaultModel(
                id=str(uuid.uuid4()),
                runner_type=runner_type,
                profile=profile.value,
                model=model,
            )
        )
    await session.commit()
    return AgentRunnerModelProfileDefaultsSchema(
        agent_runner_type=runner_type,
        model_profile_defaults=body.model_profile_defaults,
    )
