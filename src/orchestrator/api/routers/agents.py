"""Agent CRUD API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.runners import (
    AgentNameConflictError,
    AgentNoDefaultPromptError,
    AgentNotFoundError,
    AgentSchema,
    AgentService,
    CreateAgentRequest,
    UpdateAgentRequest,
)
from orchestrator.api.deps import get_session

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _get_service(session: Annotated[AsyncSession, Depends(get_session)]) -> AgentService:
    return AgentService(session)


@router.get("", response_model=list[AgentSchema])
async def list_agents(
    service: Annotated[AgentService, Depends(_get_service)],
) -> list[AgentSchema]:
    """List all agent configs."""
    return await service.list_agents()


@router.post("", response_model=AgentSchema, status_code=201)
async def create_agent(
    req: CreateAgentRequest,
    service: Annotated[AgentService, Depends(_get_service)],
) -> AgentSchema:
    """Create a new agent config. Returns 409 if name already exists."""
    try:
        return await service.create_agent(req)
    except AgentNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{agent_id}", response_model=AgentSchema)
async def get_agent(
    agent_id: str,
    service: Annotated[AgentService, Depends(_get_service)],
) -> AgentSchema:
    """Get an agent config by ID."""
    try:
        return await service.get_agent(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{agent_id}", response_model=AgentSchema)
async def update_agent(
    agent_id: str,
    req: UpdateAgentRequest,
    service: Annotated[AgentService, Depends(_get_service)],
) -> AgentSchema:
    """Update an agent config. Returns 404 if not found, 409 if name conflicts."""
    try:
        return await service.update_agent(agent_id, req)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: str,
    service: Annotated[AgentService, Depends(_get_service)],
) -> None:
    """Delete an agent config. Returns 404 if not found."""
    try:
        await service.delete_agent(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{agent_id}/reset-prompt", response_model=AgentSchema)
async def reset_prompt(
    agent_id: str,
    service: Annotated[AgentService, Depends(_get_service)],
) -> AgentSchema:
    """Reset system_prompt to default_prompt. Returns 404 if not found, 400 if no default."""
    try:
        return await service.reset_prompt(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentNoDefaultPromptError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
