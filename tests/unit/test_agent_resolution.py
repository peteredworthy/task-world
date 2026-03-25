"""Unit tests for agent name resolution and system prompt lookup."""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from orchestrator.runners.profiles.models import AgentConfigModel
from orchestrator.runners.profiles.resolution import get_agent_system_prompt, resolve_agent_name
from orchestrator.db import Base


# ---------------------------------------------------------------------------
# resolve_agent_name — pure function, no DB needed
# ---------------------------------------------------------------------------


class TestResolveAgentName:
    def test_task_agent_wins_over_all(self) -> None:
        assert (
            resolve_agent_name("builder", "TaskAgent", "StepAgent", "RoutineAgent") == "TaskAgent"
        )

    def test_step_agent_wins_over_routine_and_default(self) -> None:
        assert resolve_agent_name("builder", None, "StepAgent", "RoutineAgent") == "StepAgent"

    def test_routine_agent_wins_over_default(self) -> None:
        assert resolve_agent_name("builder", None, None, "RoutineAgent") == "RoutineAgent"

    def test_system_default_builder_when_all_none(self) -> None:
        assert resolve_agent_name("builder", None, None, None) == "Builder"

    def test_system_default_verifier_when_all_none(self) -> None:
        assert resolve_agent_name("verifier", None, None, None) == "Verifier"

    def test_system_default_planner_when_all_none(self) -> None:
        assert resolve_agent_name("planner", None, None, None) == "Planner"

    def test_task_none_step_none_routine_set(self) -> None:
        assert resolve_agent_name("verifier", None, None, "CustomVerifier") == "CustomVerifier"

    def test_task_set_step_none_routine_none(self) -> None:
        assert resolve_agent_name("planner", "MyPlanner", None, None) == "MyPlanner"

    def test_step_set_routine_none(self) -> None:
        assert resolve_agent_name("planner", None, "StepPlanner", None) == "StepPlanner"

    def test_task_overrides_step(self) -> None:
        assert resolve_agent_name("verifier", "TaskV", "StepV", None) == "TaskV"

    def test_task_overrides_routine(self) -> None:
        assert resolve_agent_name("verifier", "TaskV", None, "RoutineV") == "TaskV"


# ---------------------------------------------------------------------------
# get_agent_system_prompt — requires DB
# ---------------------------------------------------------------------------


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        yield sess

    await engine.dispose()


class TestGetAgentSystemPrompt:
    async def test_returns_system_prompt_for_existing_agent(self, session: AsyncSession) -> None:
        from datetime import datetime, timezone

        import uuid

        model = AgentConfigModel(
            id=str(uuid.uuid4()),
            name="TestBuilder",
            system_prompt="You are a skilled builder.",
            default_prompt="You are a skilled builder.",
            model_profile="coder",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(model)
        await session.commit()

        result = await get_agent_system_prompt(session, "TestBuilder")
        assert result == "You are a skilled builder."

    async def test_returns_none_for_unknown_agent(self, session: AsyncSession) -> None:
        result = await get_agent_system_prompt(session, "NonExistentAgent")
        assert result is None

    async def test_returns_none_when_db_empty(self, session: AsyncSession) -> None:
        result = await get_agent_system_prompt(session, "Builder")
        assert result is None

    async def test_returns_correct_agent_among_multiple(self, session: AsyncSession) -> None:
        from datetime import datetime, timezone

        import uuid

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
