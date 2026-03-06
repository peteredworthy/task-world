"""Tests for MockAgent."""

import pytest

from orchestrator.agents.errors import AgentExecutionError
from orchestrator.agents.interface import Agent
from orchestrator.agents.mock import MockAgent, MockBehavior
from orchestrator.agents.types import ExecutionContext
from orchestrator.config.enums import AgentRunnerType, ChecklistStatus


def _make_context() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp/work",
        prompt="Do the thing",
        requirements=["R1", "R2"],
    )


async def test_mock_agent_satisfies_protocol() -> None:
    agent = MockAgent()
    assert isinstance(agent, Agent)


async def test_mock_agent_info() -> None:
    agent = MockAgent()
    assert agent.info.agent_type == AgentRunnerType.CLI_SUBPROCESS
    assert agent.info.name == "mock"


async def test_mock_agent_complete_requirements() -> None:
    updates: list[tuple[str, ChecklistStatus, str | None]] = []

    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        updates.append((req_id, status, note))

    submitted = False

    async def on_submit() -> None:
        nonlocal submitted
        submitted = True

    behavior = MockBehavior(
        complete_requirements=["R1", "R2"],
        should_submit=True,
    )
    agent = MockAgent(behavior)
    result = await agent.execute(_make_context(), on_update, on_submit)

    assert result.success is True
    assert len(updates) == 2
    assert updates[0] == ("R1", ChecklistStatus.DONE, None)
    assert updates[1] == ("R2", ChecklistStatus.DONE, None)
    assert submitted is True


async def test_mock_agent_fail_requirements() -> None:
    updates: list[tuple[str, ChecklistStatus, str | None]] = []

    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        updates.append((req_id, status, note))

    async def on_submit() -> None:
        pass

    behavior = MockBehavior(
        fail_requirements=["R1"],
        should_submit=False,
    )
    agent = MockAgent(behavior)
    result = await agent.execute(_make_context(), on_update, on_submit)

    assert result.success is True
    assert len(updates) == 1
    assert updates[0][0] == "R1"
    assert updates[0][1] == ChecklistStatus.BLOCKED


async def test_mock_agent_no_submit() -> None:
    submitted = False

    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        pass

    async def on_submit() -> None:
        nonlocal submitted
        submitted = True

    behavior = MockBehavior(should_submit=False)
    agent = MockAgent(behavior)
    await agent.execute(_make_context(), on_update, on_submit)

    assert submitted is False


async def test_mock_agent_should_fail() -> None:
    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        pass

    async def on_submit() -> None:
        pass

    behavior = MockBehavior(should_fail=True)
    agent = MockAgent(behavior)

    with pytest.raises(AgentExecutionError, match="Simulated failure"):
        await agent.execute(_make_context(), on_update, on_submit)


async def test_mock_agent_metrics() -> None:
    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        pass

    async def on_submit() -> None:
        pass

    behavior = MockBehavior(
        tokens_read=500,
        tokens_write=200,
        tokens_cache=50,
        duration_ms=3000,
        should_submit=False,
    )
    agent = MockAgent(behavior)
    result = await agent.execute(_make_context(), on_update, on_submit)

    assert result.metrics.tokens_read == 500
    assert result.metrics.tokens_write == 200
    assert result.metrics.tokens_cache == 50
    assert result.metrics.duration_ms == 3000


async def test_mock_agent_default_behavior() -> None:
    """Default behavior: no requirements, submit, default metrics."""

    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        pass

    submitted = False

    async def on_submit() -> None:
        nonlocal submitted
        submitted = True

    agent = MockAgent()
    result = await agent.execute(_make_context(), on_update, on_submit)

    assert result.success is True
    assert submitted is True
    assert result.metrics.tokens_read == 100  # defaults
