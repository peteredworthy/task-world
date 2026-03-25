"""CRUD service for Agent configs."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.runners.profiles.errors import (
    AgentNameConflictError,
    AgentNoDefaultPromptError,
    AgentNotFoundError,
)
from orchestrator.runners.profiles.models import AgentConfigModel
from orchestrator.runners.profiles.schemas import (
    AgentSchema,
    CreateAgentRequest,
    UpdateAgentRequest,
)
from orchestrator.config.enums import ModelProfile

_PLANNER_PROMPT = (
    "You are a Planner agent. Your role is to break down high-level goals into "
    "clear, actionable steps. Analyse the requirements, identify dependencies, "
    "and produce a structured plan that builders can execute sequentially. "
    "Favour clarity and completeness over brevity."
)

_BUILDER_PROMPT = (
    "You are a Builder agent. Your role is to implement the requirements listed "
    "in the task checklist. Write clean, idiomatic code that satisfies every "
    "requirement. Mark each requirement done as you complete it, then submit "
    "for verification when all are addressed."
)

_VERIFIER_PROMPT = (
    "You are a Verifier agent. Your role is to review the builder's work and "
    "grade each requirement objectively. Assign a letter grade (A–F) with a "
    "brief reason. Be precise: pass only work that genuinely meets the bar. "
    "If critical requirements fail, mark the task for revision."
)

_DEFAULT_AGENTS: list[tuple[str, ModelProfile, str]] = [
    ("Planner", ModelProfile.ARCHITECT, _PLANNER_PROMPT),
    ("Builder", ModelProfile.CODER, _BUILDER_PROMPT),
    ("Verifier", ModelProfile.CODER, _VERIFIER_PROMPT),
]


async def seed_default_agents(session: AsyncSession) -> None:
    """Insert the three factory-default agents if they do not already exist."""
    now = datetime.now(timezone.utc)
    for name, profile, prompt in _DEFAULT_AGENTS:
        existing = await session.execute(
            select(AgentConfigModel).where(AgentConfigModel.name == name)
        )
        if existing.scalar_one_or_none() is not None:
            continue
        model = AgentConfigModel(
            id=str(uuid.uuid4()),
            name=name,
            system_prompt=prompt,
            default_prompt=prompt,
            model_profile=profile.value,
            created_at=now,
            updated_at=now,
        )
        session.add(model)
    await session.commit()


async def list_agents(session: AsyncSession) -> list[AgentSchema]:
    return await AgentService(session).list_agents()


async def get_agent(session: AsyncSession, agent_id: str) -> AgentSchema:
    return await AgentService(session).get_agent(agent_id)


async def create_agent(session: AsyncSession, req: CreateAgentRequest) -> AgentSchema:
    return await AgentService(session).create_agent(req)


async def update_agent(
    session: AsyncSession, agent_id: str, req: UpdateAgentRequest
) -> AgentSchema:
    return await AgentService(session).update_agent(agent_id, req)


async def delete_agent(session: AsyncSession, agent_id: str) -> None:
    return await AgentService(session).delete_agent(agent_id)


def _to_schema(model: AgentConfigModel) -> AgentSchema:
    return AgentSchema(
        id=model.id,
        name=model.name,
        system_prompt=model.system_prompt,
        default_prompt=model.default_prompt,
        model_profile=ModelProfile(model.model_profile),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class AgentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_agents(self) -> list[AgentSchema]:
        result = await self._session.execute(
            select(AgentConfigModel).order_by(AgentConfigModel.name)
        )
        return [_to_schema(m) for m in result.scalars().all()]

    async def get_agent(self, agent_id: str) -> AgentSchema:
        model = await self._session.get(AgentConfigModel, agent_id)
        if model is None:
            raise AgentNotFoundError(agent_id)
        return _to_schema(model)

    async def create_agent(self, req: CreateAgentRequest) -> AgentSchema:
        now = datetime.now(timezone.utc)
        model = AgentConfigModel(
            id=str(uuid.uuid4()),
            name=req.name,
            system_prompt=req.system_prompt,
            default_prompt=req.default_prompt,
            model_profile=req.model_profile.value,
            created_at=now,
            updated_at=now,
        )
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            raise AgentNameConflictError(req.name)
        await self._session.commit()
        await self._session.refresh(model)
        return _to_schema(model)

    async def update_agent(self, agent_id: str, req: UpdateAgentRequest) -> AgentSchema:
        model = await self._session.get(AgentConfigModel, agent_id)
        if model is None:
            raise AgentNotFoundError(agent_id)
        if req.name is not None:
            model.name = req.name
        if req.system_prompt is not None:
            model.system_prompt = req.system_prompt
        if req.default_prompt is not None:
            model.default_prompt = req.default_prompt
        if req.model_profile is not None:
            model.model_profile = req.model_profile.value
        model.updated_at = datetime.now(timezone.utc)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            raise AgentNameConflictError(req.name or "")
        await self._session.commit()
        await self._session.refresh(model)
        return _to_schema(model)

    async def delete_agent(self, agent_id: str) -> None:
        model = await self._session.get(AgentConfigModel, agent_id)
        if model is None:
            raise AgentNotFoundError(agent_id)
        await self._session.delete(model)
        await self._session.commit()

    async def reset_prompt(self, agent_id: str) -> AgentSchema:
        model = await self._session.get(AgentConfigModel, agent_id)
        if model is None:
            raise AgentNotFoundError(agent_id)
        if not model.default_prompt:
            raise AgentNoDefaultPromptError(agent_id)
        model.system_prompt = model.default_prompt
        model.updated_at = datetime.now(timezone.utc)
        await self._session.commit()
        await self._session.refresh(model)
        return _to_schema(model)
