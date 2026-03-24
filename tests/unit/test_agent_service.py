"""Unit tests for AgentService CRUD operations and error cases."""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from orchestrator.runners.profiles.errors import (
    AgentNameConflictError,
    AgentNoDefaultPromptError,
    AgentNotFoundError,
)
from orchestrator.runners.profiles.schemas import CreateAgentRequest, UpdateAgentRequest
from orchestrator.runners.profiles.service import AgentService, seed_default_agents
from orchestrator.config.enums import ModelProfile
from orchestrator.db.base import Base


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an in-memory SQLite session with the agent_configs table."""
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


@pytest.fixture
async def service(session: AsyncSession) -> AgentService:
    return AgentService(session)


@pytest.fixture
def create_req() -> CreateAgentRequest:
    return CreateAgentRequest(
        name="TestAgent",
        system_prompt="You are a test agent.",
        default_prompt="You are a test agent.",
        model_profile=ModelProfile.CODER,
    )


# ---------------------------------------------------------------------------
# list_agents
# ---------------------------------------------------------------------------


class TestListAgents:
    async def test_empty_returns_empty_list(self, service: AgentService) -> None:
        result = await service.list_agents()
        assert result == []

    async def test_returns_all_agents_ordered_by_name(self, service: AgentService) -> None:
        await service.create_agent(
            CreateAgentRequest(name="Zebra", system_prompt="z", model_profile=ModelProfile.CODER)
        )
        await service.create_agent(
            CreateAgentRequest(
                name="Alpha", system_prompt="a", model_profile=ModelProfile.ARCHITECT
            )
        )
        result = await service.list_agents()
        assert len(result) == 2
        assert result[0].name == "Alpha"
        assert result[1].name == "Zebra"

    async def test_schema_fields_present(
        self, service: AgentService, create_req: CreateAgentRequest
    ) -> None:
        await service.create_agent(create_req)
        agents = await service.list_agents()
        agent = agents[0]
        assert agent.id
        assert agent.name == "TestAgent"
        assert agent.system_prompt == "You are a test agent."
        assert agent.default_prompt == "You are a test agent."
        assert agent.model_profile == ModelProfile.CODER
        assert agent.created_at is not None
        assert agent.updated_at is not None


# ---------------------------------------------------------------------------
# get_agent
# ---------------------------------------------------------------------------


class TestGetAgent:
    async def test_returns_agent_by_id(
        self, service: AgentService, create_req: CreateAgentRequest
    ) -> None:
        created = await service.create_agent(create_req)
        fetched = await service.get_agent(created.id)
        assert fetched.id == created.id
        assert fetched.name == created.name

    async def test_not_found_raises(self, service: AgentService) -> None:
        with pytest.raises(AgentNotFoundError) as exc_info:
            await service.get_agent("nonexistent-id")
        assert "nonexistent-id" in str(exc_info.value)


# ---------------------------------------------------------------------------
# create_agent
# ---------------------------------------------------------------------------


class TestCreateAgent:
    async def test_creates_and_returns_schema(
        self, service: AgentService, create_req: CreateAgentRequest
    ) -> None:
        result = await service.create_agent(create_req)
        assert result.id
        assert result.name == "TestAgent"
        assert result.system_prompt == "You are a test agent."
        assert result.model_profile == ModelProfile.CODER

    async def test_default_prompt_defaults_to_empty_string(self, service: AgentService) -> None:
        req = CreateAgentRequest(name="NoDefault", system_prompt="prompt")
        result = await service.create_agent(req)
        assert result.default_prompt == ""

    async def test_duplicate_name_raises_conflict(
        self, service: AgentService, create_req: CreateAgentRequest
    ) -> None:
        await service.create_agent(create_req)
        with pytest.raises(AgentNameConflictError) as exc_info:
            await service.create_agent(create_req)
        assert "TestAgent" in str(exc_info.value)

    async def test_model_profile_stored_correctly(self, service: AgentService) -> None:
        req = CreateAgentRequest(
            name="Arch", system_prompt="plan", model_profile=ModelProfile.ARCHITECT
        )
        result = await service.create_agent(req)
        assert result.model_profile == ModelProfile.ARCHITECT

    async def test_accepts_case_insensitive_model_profile(self, service: AgentService) -> None:
        req = CreateAgentRequest(name="MyAgent", system_prompt="hi", model_profile="CODER")  # type: ignore[arg-type]
        result = await service.create_agent(req)
        assert result.model_profile == ModelProfile.CODER


# ---------------------------------------------------------------------------
# update_agent
# ---------------------------------------------------------------------------


class TestUpdateAgent:
    async def test_update_name(self, service: AgentService, create_req: CreateAgentRequest) -> None:
        created = await service.create_agent(create_req)
        updated = await service.update_agent(created.id, UpdateAgentRequest(name="Renamed"))
        assert updated.name == "Renamed"
        assert updated.system_prompt == created.system_prompt  # unchanged

    async def test_update_system_prompt(
        self, service: AgentService, create_req: CreateAgentRequest
    ) -> None:
        created = await service.create_agent(create_req)
        updated = await service.update_agent(
            created.id, UpdateAgentRequest(system_prompt="Updated prompt.")
        )
        assert updated.system_prompt == "Updated prompt."
        assert updated.name == created.name  # unchanged

    async def test_update_model_profile(
        self, service: AgentService, create_req: CreateAgentRequest
    ) -> None:
        created = await service.create_agent(create_req)
        updated = await service.update_agent(
            created.id, UpdateAgentRequest(model_profile=ModelProfile.ARCHITECT)
        )
        assert updated.model_profile == ModelProfile.ARCHITECT

    async def test_update_default_prompt(
        self, service: AgentService, create_req: CreateAgentRequest
    ) -> None:
        created = await service.create_agent(create_req)
        updated = await service.update_agent(
            created.id, UpdateAgentRequest(default_prompt="New default.")
        )
        assert updated.default_prompt == "New default."

    async def test_partial_update_leaves_other_fields_unchanged(
        self, service: AgentService, create_req: CreateAgentRequest
    ) -> None:
        created = await service.create_agent(create_req)
        updated = await service.update_agent(created.id, UpdateAgentRequest(name="OnlyName"))
        assert updated.name == "OnlyName"
        assert updated.system_prompt == created.system_prompt
        assert updated.model_profile == created.model_profile

    async def test_not_found_raises(self, service: AgentService) -> None:
        with pytest.raises(AgentNotFoundError):
            await service.update_agent("bad-id", UpdateAgentRequest(name="X"))

    async def test_duplicate_name_raises_conflict(self, service: AgentService) -> None:
        a = await service.create_agent(CreateAgentRequest(name="AgentA", system_prompt="a"))
        await service.create_agent(CreateAgentRequest(name="AgentB", system_prompt="b"))
        with pytest.raises(AgentNameConflictError):
            await service.update_agent(a.id, UpdateAgentRequest(name="AgentB"))

    async def test_updated_at_changes(
        self, service: AgentService, create_req: CreateAgentRequest
    ) -> None:
        created = await service.create_agent(create_req)
        updated = await service.update_agent(created.id, UpdateAgentRequest(name="New"))
        assert updated.updated_at >= created.updated_at


# ---------------------------------------------------------------------------
# delete_agent
# ---------------------------------------------------------------------------


class TestDeleteAgent:
    async def test_delete_removes_agent(
        self, service: AgentService, create_req: CreateAgentRequest
    ) -> None:
        created = await service.create_agent(create_req)
        await service.delete_agent(created.id)
        with pytest.raises(AgentNotFoundError):
            await service.get_agent(created.id)

    async def test_delete_reduces_list_count(
        self, service: AgentService, create_req: CreateAgentRequest
    ) -> None:
        created = await service.create_agent(create_req)
        await service.create_agent(CreateAgentRequest(name="Other", system_prompt="other"))
        await service.delete_agent(created.id)
        agents = await service.list_agents()
        assert len(agents) == 1
        assert agents[0].name == "Other"

    async def test_delete_not_found_raises(self, service: AgentService) -> None:
        with pytest.raises(AgentNotFoundError):
            await service.delete_agent("ghost-id")


# ---------------------------------------------------------------------------
# reset_prompt
# ---------------------------------------------------------------------------


class TestResetPrompt:
    async def test_reset_restores_default_prompt(self, service: AgentService) -> None:
        created = await service.create_agent(
            CreateAgentRequest(
                name="Resettable",
                system_prompt="Original prompt.",
                default_prompt="Factory prompt.",
            )
        )
        # Modify the system_prompt
        await service.update_agent(created.id, UpdateAgentRequest(system_prompt="Modified."))
        # Reset should restore the default
        result = await service.reset_prompt(created.id)
        assert result.system_prompt == "Factory prompt."

    async def test_reset_not_found_raises(self, service: AgentService) -> None:
        with pytest.raises(AgentNotFoundError):
            await service.reset_prompt("missing-id")

    async def test_reset_without_default_raises(self, service: AgentService) -> None:
        created = await service.create_agent(
            CreateAgentRequest(
                name="NoDefault",
                system_prompt="prompt",
                default_prompt="",  # empty = no default
            )
        )
        with pytest.raises(AgentNoDefaultPromptError) as exc_info:
            await service.reset_prompt(created.id)
        assert created.id in str(exc_info.value)

    async def test_reset_does_not_change_default_prompt(self, service: AgentService) -> None:
        created = await service.create_agent(
            CreateAgentRequest(
                name="Stable",
                system_prompt="custom",
                default_prompt="factory",
            )
        )
        result = await service.reset_prompt(created.id)
        assert result.default_prompt == "factory"


# ---------------------------------------------------------------------------
# seed_default_agents
# ---------------------------------------------------------------------------


class TestSeedDefaultAgents:
    async def test_seeds_three_agents(self, session: AsyncSession) -> None:
        await seed_default_agents(session)
        svc = AgentService(session)
        agents = await svc.list_agents()
        names = {a.name for a in agents}
        assert names == {"Planner", "Builder", "Verifier"}

    async def test_seeded_agents_have_correct_profiles(self, session: AsyncSession) -> None:
        await seed_default_agents(session)
        svc = AgentService(session)
        agents = await svc.list_agents()
        by_name = {a.name: a for a in agents}
        assert by_name["Planner"].model_profile == ModelProfile.ARCHITECT
        assert by_name["Builder"].model_profile == ModelProfile.CODER
        assert by_name["Verifier"].model_profile == ModelProfile.CODER

    async def test_seed_is_idempotent(self, session: AsyncSession) -> None:
        await seed_default_agents(session)
        await seed_default_agents(session)
        svc = AgentService(session)
        agents = await svc.list_agents()
        assert len(agents) == 3

    async def test_seeded_agents_have_default_prompts(self, session: AsyncSession) -> None:
        await seed_default_agents(session)
        svc = AgentService(session)
        agents = await svc.list_agents()
        for agent in agents:
            assert agent.default_prompt, f"{agent.name} should have a non-empty default_prompt"
            assert agent.system_prompt == agent.default_prompt
