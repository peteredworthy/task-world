"""Agent discovery API endpoints."""

import logging
import uuid
from typing import Annotated, Any, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from orchestrator.api.deps import get_session, get_tool_detector
from orchestrator.api.schemas.model_profiles import (
    AgentRunnerModelProfileDefaultsSchema,
    SelectableAgentRunnerType,
)
from orchestrator.config.enums import ModelProfile
from orchestrator.db import AgentRunnerModelProfileDefaultModel
from orchestrator.runners.agent_detector import ToolDetector
from orchestrator.runners.types import AgentRunnerOption

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent-runners", tags=["agent-runners"])

_LM_STUDIO_BASE_URL = "http://127.0.0.1:1234"


def _is_loaded_lmstudio_model(models_payload: dict[str, Any], model: str) -> bool:
    """Return whether LM Studio already has *model* loaded in an instance."""
    raw_models = models_payload.get("models")
    if not isinstance(raw_models, list):
        return False
    models = cast(list[object], raw_models)
    for raw_entry in models:
        if not isinstance(raw_entry, dict):
            continue
        entry = cast(dict[str, Any], raw_entry)
        if entry.get("key") != model:
            continue
        instances = entry.get("loaded_instances")
        if isinstance(instances, list):
            for raw_instance in cast(list[object], instances):
                if (
                    isinstance(raw_instance, dict)
                    and cast(dict[str, Any], raw_instance).get("id") == model
                ):
                    return True
    return False


def _lmstudio_models_compat_payload(openai_payload: dict[str, Any]) -> dict[str, Any]:
    """Satisfy Codex's catalog reader while preserving LM Studio's model list."""
    return {**openai_payload, "models": []}


async def _close_lmstudio_stream(response: httpx.Response, client: httpx.AsyncClient) -> None:
    await response.aclose()
    await client.aclose()


@router.api_route(
    "/lmstudio-codex/{path:path}",
    methods=["GET", "POST"],
    include_in_schema=False,
    response_model=None,
)
async def lmstudio_codex_compat_proxy(
    path: str, request: Request
) -> JSONResponse | StreamingResponse:
    """Bridge Codex OSS model loading to an already-loaded LM Studio model.

    Codex 0.144 requests a fresh native LM Studio model load for every session.
    On constrained local machines that can fail even when the target instance
    is already loaded.  The bridge reports that existing instance as loaded,
    supplies a tolerant model-catalog payload, and transparently forwards the
    OpenAI-compatible Responses stream used for inference.
    """
    target = path.strip("/")
    if target in {"models", "v1/models"}:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                upstream = await client.get(f"{_LM_STUDIO_BASE_URL}/v1/models")
                upstream.raise_for_status()
                raw_payload: object = upstream.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(
                status_code=502, detail=f"LM Studio model discovery failed: {exc}"
            ) from exc
        if not isinstance(raw_payload, dict):
            raise HTTPException(status_code=502, detail="LM Studio returned an invalid model list")
        payload = cast(dict[str, Any], raw_payload)
        return JSONResponse(_lmstudio_models_compat_payload(payload))

    if target == "api/v1/models/load":
        try:
            raw_body: object = await request.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="LM Studio model load requires JSON"
            ) from exc
        body = cast(dict[str, Any], raw_body) if isinstance(raw_body, dict) else None
        model = body.get("model") if body is not None else None
        if not isinstance(model, str) or not model:
            raise HTTPException(
                status_code=422, detail="LM Studio model load requires a model string"
            )
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                models_response = await client.get(f"{_LM_STUDIO_BASE_URL}/api/v1/models")
                models_response.raise_for_status()
                raw_models_payload: object = models_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(
                status_code=502, detail=f"LM Studio model status failed: {exc}"
            ) from exc
        models_payload = (
            cast(dict[str, Any], raw_models_payload)
            if isinstance(raw_models_payload, dict)
            else None
        )
        if models_payload is not None and _is_loaded_lmstudio_model(models_payload, model):
            return JSONResponse(
                {
                    "type": "llm",
                    "instance_id": model,
                    "load_time_seconds": 0,
                    "status": "loaded",
                }
            )
        raise HTTPException(
            status_code=409,
            detail=f"LM Studio model '{model}' is not already loaded",
        )

    if target in {"responses", "v1/responses"}:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=None, write=30.0, pool=5.0)
        )
        try:
            upstream_request = client.build_request(
                request.method,
                f"{_LM_STUDIO_BASE_URL}/v1/responses",
                content=await request.body(),
                headers={
                    key: value
                    for key, value in request.headers.items()
                    if key.lower() in {"accept", "authorization", "content-type"}
                },
            )
            upstream = await client.send(upstream_request, stream=True)
        except httpx.HTTPError as exc:
            await client.aclose()
            raise HTTPException(
                status_code=502, detail=f"LM Studio inference request failed: {exc}"
            ) from exc
        headers = {
            key: value
            for key, value in upstream.headers.items()
            if key.lower() in {"cache-control", "content-type"}
        }
        return StreamingResponse(
            upstream.aiter_raw(),
            status_code=upstream.status_code,
            headers=headers,
            background=BackgroundTask(_close_lmstudio_stream, upstream, client),
        )

    raise HTTPException(
        status_code=404, detail="Unsupported LM Studio Codex compatibility endpoint"
    )


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
    runner_type: SelectableAgentRunnerType,
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
    runner_type: SelectableAgentRunnerType,
    body: AgentRunnerModelProfileDefaultsSchema,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgentRunnerModelProfileDefaultsSchema:
    """Set model defaults for each profile on an agent runner type."""
    if body.agent_runner_type != runner_type:
        raise HTTPException(
            status_code=422,
            detail="agent_runner_type in the request body must match the path runner_type",
        )
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
