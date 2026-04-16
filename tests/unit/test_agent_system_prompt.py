"""Integration tests for get_agent_system_prompt — requires DB."""

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from orchestrator.runners import AgentConfigModel, get_agent_system_prompt
from orchestrator.db import Base


@pytest_asyncio.fixture(scope="module")
async def session(tmp_path_factory) -> AsyncGenerator[AsyncSession, None]:
    db_path = tmp_path_factory.mktemp("agent_resolution") / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as s:
        yield s
    await engine.dispose()


class TestGetAgentSystemPrompt:
    async def test_returns_system_prompt_for_existing_agent(self, session: AsyncSession) -> None:
        now = datetime.now(timezone.utc)
        model = AgentConfigModel(
            id=str(uuid.uuid4()),
            name="TestBuilder",
            system_prompt="You are a skilled builder.",
            default_prompt="You are a skilled builder.",
            model_profile="coder",
            created_at=now,
            updated_at=now,
        )
        session.add(model)
        await session.commit()

        result = await get_agent_system_prompt(session, "TestBuilder")
        assert result == "You are a skilled builder."

    async def test_returns_none_for_unknown_agent(self, session: AsyncSession) -> None:
        result = await get_agent_system_prompt(session, "NonExistentAgent")
        assert result is None

    async def test_returns_none_when_db_empty(self, session: AsyncSession) -> None:
        # Uses a fresh name that was never inserted
        result = await get_agent_system_prompt(session, "NeverInserted")
        assert result is None

    async def test_returns_correct_agent_among_multiple(self, session: AsyncSession) -> None:
        now = datetime.now(timezone.utc)
        for name, prompt in [("Alpha", "Alpha prompt"), ("Beta", "Beta prompt")]:
            session.add(
                AgentConfigModel(
                    id=str(uuid.uuid4()),
                    name=name,
                    system_prompt=prompt,
                    default_prompt=prompt,
                    model_profile="coder",
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.commit()

        assert await get_agent_system_prompt(session, "Alpha") == "Alpha prompt"
        assert await get_agent_system_prompt(session, "Beta") == "Beta prompt"
