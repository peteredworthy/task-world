"""Agent discovery API endpoints."""

import logging
import uuid
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.deps import get_session
from orchestrator.api.schemas.model_profiles import RunnerProfileDefaultsSchema
from orchestrator.config.enums import ModelProfile
from orchestrator.db.models import RunnerProfileDefaultModel
from orchestrator.runners.detector import ToolDetector
from orchestrator.runners.types import AgentRunnerOption

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent-runners", tags=["agent-runners"])


@router.get("", response_model=list[AgentRunnerOption])
async def list_agent_runners(request: Request) -> list[AgentRunnerOption]:
    """List available agent runner backends."""
    detector: ToolDetector = request.app.state.tool_detector
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


@router.get("/{runner_type}/profiles", response_model=RunnerProfileDefaultsSchema)
async def get_runner_profiles(
    runner_type: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunnerProfileDefaultsSchema:
    """Get per-profile model defaults for a runner type."""
    result = await session.execute(
        select(RunnerProfileDefaultModel).where(
            RunnerProfileDefaultModel.runner_type == runner_type
        )
    )
    rows = result.scalars().all()
    profiles: dict[ModelProfile, str] = {}
    for row in rows:
        try:
            profiles[ModelProfile(row.profile)] = row.model
        except ValueError:
            pass
    return RunnerProfileDefaultsSchema(runner_type=runner_type, profiles=profiles)


@router.put("/{runner_type}/profiles", response_model=RunnerProfileDefaultsSchema)
async def set_runner_profiles(
    runner_type: str,
    body: RunnerProfileDefaultsSchema,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunnerProfileDefaultsSchema:
    """Set per-profile model defaults for a runner type."""
    await session.execute(
        delete(RunnerProfileDefaultModel).where(
            RunnerProfileDefaultModel.runner_type == runner_type
        )
    )
    for profile, model in body.profiles.items():
        session.add(
            RunnerProfileDefaultModel(
                id=str(uuid.uuid4()),
                runner_type=runner_type,
                profile=profile.value,
                model=model,
            )
        )
    await session.commit()
    return RunnerProfileDefaultsSchema(runner_type=runner_type, profiles=body.profiles)
