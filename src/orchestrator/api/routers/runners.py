"""Agent discovery API endpoints."""

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request

from orchestrator.runners.detector import ToolDetector
from orchestrator.runners.types import AgentRunnerOption

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent-runners", tags=["agent-runners"])


@router.get("", response_model=list[AgentRunnerOption])
async def list_agents(request: Request) -> list[AgentRunnerOption]:
    """List available agent backends."""
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
