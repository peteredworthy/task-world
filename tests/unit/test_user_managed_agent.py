"""Unit tests for UserManagedAgent."""

import asyncio

import pytest

from orchestrator.runners.errors import AgentCancelledError, AgentTimeoutError
from orchestrator.runners.types import (
    ChecklistUpdateCallback,
    ExecutionContext,
    SubmitCallback,
)
from orchestrator.runners import UserManagedAgent
from orchestrator.config import AgentRunnerType, ChecklistStatus
from orchestrator.workflow.service import SubmitEventRegistry


def _make_context(task_id: str = "task-1") -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        task_id=task_id,
        working_dir="/tmp",
        prompt="Complete the work",
        requirements=["R1"],
    )


def _noop_callbacks() -> tuple[ChecklistUpdateCallback, SubmitCallback]:
    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        pass

    async def on_submit() -> None:
        pass

    return on_update, on_submit


def test_user_managed_agent_info() -> None:
    """Agent info has correct type and name."""
    # Create a minimal mock service with the needed interface
    service = _FakeService()
    agent = UserManagedAgent(service=service)  # type: ignore[arg-type]
    assert agent.info.agent_type == AgentRunnerType.USER_MANAGED
    assert agent.info.name == "User Managed"


def test_user_managed_default_params() -> None:
    """Default callback_channel is 'mcp' and timeout is 60 minutes."""
    service = _FakeService()
    agent = UserManagedAgent(service=service)  # type: ignore[arg-type]
    assert agent._callback_channel == "mcp"  # pyright: ignore[reportPrivateUsage]
    assert agent._timeout_minutes == 60  # pyright: ignore[reportPrivateUsage]


def test_user_managed_custom_params() -> None:
    """Custom callback_channel and timeout are stored."""
    service = _FakeService()
    agent = UserManagedAgent(
        service=service,  # type: ignore[arg-type]
        callback_channel="rest",
        timeout_minutes=30,
    )
    assert agent._callback_channel == "rest"  # pyright: ignore[reportPrivateUsage]
    assert agent._timeout_minutes == 30  # pyright: ignore[reportPrivateUsage]


async def test_user_managed_submit_event_fires() -> None:
    """When the submit event is set, execute returns success."""
    service = _FakeService()
    agent = UserManagedAgent(service=service, timeout_minutes=1)  # type: ignore[arg-type]
    on_update, on_submit = _noop_callbacks()
    ctx = _make_context()

    # Fire the event after a short delay
    async def fire_event() -> None:
        await asyncio.sleep(0.1)
        event = service.registered_events.get("task-1")
        assert event is not None
        event.set()

    task = asyncio.create_task(fire_event())
    result = await agent.execute(ctx, on_update, on_submit)
    await task

    assert result.success is True


async def test_user_managed_timeout() -> None:
    """When timeout expires, AgentTimeoutError is raised."""
    service = _FakeService()
    # Very short timeout for testing
    agent = UserManagedAgent(service=service, timeout_minutes=0)  # type: ignore[arg-type]
    on_update, on_submit = _noop_callbacks()

    # timeout_minutes=0 means 0 seconds timeout
    with pytest.raises(AgentTimeoutError, match="No submission received"):
        await agent.execute(_make_context(), on_update, on_submit)


async def test_user_managed_cancel() -> None:
    """Cancellation raises AgentCancelledError."""
    service = _FakeService()
    agent = UserManagedAgent(service=service, timeout_minutes=1, poll_interval=0.05)  # type: ignore[arg-type]
    on_update, on_submit = _noop_callbacks()

    async def cancel_soon() -> None:
        await asyncio.sleep(0.1)
        await agent.cancel()

    task = asyncio.create_task(cancel_soon())
    with pytest.raises(AgentCancelledError):
        await agent.execute(_make_context(), on_update, on_submit)
    await task


async def test_user_managed_cancel_before_execute() -> None:
    """If cancelled before execute, raises immediately."""
    service = _FakeService()
    agent = UserManagedAgent(service=service)  # type: ignore[arg-type]
    on_update, on_submit = _noop_callbacks()

    await agent.cancel()
    with pytest.raises(AgentCancelledError):
        await agent.execute(_make_context(), on_update, on_submit)


async def test_user_managed_unregisters_on_success() -> None:
    """Submit event is unregistered after successful execution."""
    service = _FakeService()
    agent = UserManagedAgent(service=service, timeout_minutes=1)  # type: ignore[arg-type]
    on_update, on_submit = _noop_callbacks()

    async def fire_event() -> None:
        await asyncio.sleep(0.1)
        event = service.registered_events.get("task-1")
        assert event is not None
        event.set()

    task = asyncio.create_task(fire_event())
    await agent.execute(_make_context(), on_update, on_submit)
    await task

    assert "task-1" not in service.registered_events


async def test_user_managed_unregisters_on_timeout() -> None:
    """Submit event is unregistered after timeout."""
    service = _FakeService()
    agent = UserManagedAgent(service=service, timeout_minutes=0)  # type: ignore[arg-type]
    on_update, on_submit = _noop_callbacks()

    with pytest.raises(AgentTimeoutError):
        await agent.execute(_make_context(), on_update, on_submit)

    assert "task-1" not in service.registered_events


# --- Fake service with submit event support ---


class _FakeService:
    """Minimal fake that implements the submit event interface used by UserManagedAgent.

    Delegates to a real SubmitEventRegistry so tests use the same notification
    logic as production code.
    """

    def __init__(self) -> None:
        self._registry = SubmitEventRegistry()

    @property
    def registered_events(self) -> dict[str, asyncio.Event]:
        """Expose internal events for test assertions."""
        return self._registry._events  # pyright: ignore[reportPrivateUsage]

    def register_submit_event(self, task_id: str) -> asyncio.Event:
        return self._registry.register(task_id)

    def unregister_submit_event(self, task_id: str) -> None:
        self._registry.unregister(task_id)
