"""Unit tests for OpenHands custom tool executors.

These tests exercise the executor classes defined in openhands.py.
The async bridge tests verify the run_coroutine_threadsafe pattern works
correctly from a worker thread back to the event loop.
"""

import asyncio
from dataclasses import dataclass

import pytest

from orchestrator.agents.openhands import _SDK_AVAILABLE
from orchestrator.agents.openhands_common import (
    GetRequirementsExecutor,
    SubmitExecutor,
    UpdateChecklistExecutor,
)
from orchestrator.config.enums import ChecklistStatus


# Simple observation stand-in for tests that don't need real SDK types.
@dataclass
class _FakeObservation:
    text: str


def _fake_observation_factory(text: str) -> _FakeObservation:
    return _FakeObservation(text=text)


# --- GetRequirementsExecutor ---


def test_get_requirements_executor_text() -> None:
    """get_requirements_text() returns formatted requirements without SDK."""
    executor = GetRequirementsExecutor(["R1", "R2", "R3"])
    text = executor.get_requirements_text()
    assert text == "- R1\n- R2\n- R3"


def test_get_requirements_executor_empty() -> None:
    executor = GetRequirementsExecutor([])
    assert executor.get_requirements_text() == ""


def test_get_requirements_executor_call_with_factory() -> None:
    """Calling the executor with a factory returns the observation."""
    executor = GetRequirementsExecutor(["R1", "R2"], observation_factory=_fake_observation_factory)
    result = executor(action=None)
    assert isinstance(result, _FakeObservation)
    assert "R1" in result.text
    assert "R2" in result.text


@pytest.mark.skipif(not _SDK_AVAILABLE, reason="openhands-ai not installed")
def test_get_requirements_executor_call_returns_sdk_observation() -> None:
    """Calling the executor with the SDK factory returns a real SDK Observation."""
    from orchestrator.agents.openhands import _obs_get_req

    executor = GetRequirementsExecutor(["R1", "R2"], observation_factory=_obs_get_req)
    result = executor(action=None)
    # Verify it's an Observation with content
    assert hasattr(result, "content")
    assert len(result.content) == 1
    assert "R1" in result.content[0].text
    assert "R2" in result.content[0].text


# --- UpdateChecklistExecutor ---


async def test_update_checklist_executor_invokes_callback() -> None:
    """UpdateChecklistExecutor bridges to async callback via run_coroutine_threadsafe."""
    updates: list[tuple[str, ChecklistStatus, str | None]] = []

    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        updates.append((req_id, status, note))

    loop = asyncio.get_running_loop()
    executor = UpdateChecklistExecutor(
        on_update, loop, observation_factory=_fake_observation_factory
    )

    class FakeAction:
        req_id = "R1"
        status = "done"
        note = "completed the work"

    def run_executor() -> object:
        return executor(FakeAction())

    result = await asyncio.to_thread(run_executor)

    assert len(updates) == 1
    assert updates[0] == ("R1", ChecklistStatus.DONE, "completed the work")
    assert isinstance(result, _FakeObservation)
    assert "R1" in result.text


async def test_update_checklist_executor_without_note() -> None:
    """Note defaults to None when not present on the action."""
    updates: list[tuple[str, ChecklistStatus, str | None]] = []

    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        updates.append((req_id, status, note))

    loop = asyncio.get_running_loop()
    executor = UpdateChecklistExecutor(
        on_update, loop, observation_factory=_fake_observation_factory
    )

    class FakeAction:
        req_id = "R2"
        status = "blocked"

    def run_executor() -> object:
        return executor(FakeAction())

    await asyncio.to_thread(run_executor)

    assert updates[0] == ("R2", ChecklistStatus.BLOCKED, None)


async def test_update_checklist_executor_not_applicable() -> None:
    """not_applicable status is handled correctly."""
    updates: list[tuple[str, ChecklistStatus, str | None]] = []

    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        updates.append((req_id, status, note))

    loop = asyncio.get_running_loop()
    executor = UpdateChecklistExecutor(
        on_update, loop, observation_factory=_fake_observation_factory
    )

    class FakeAction:
        req_id = "R3"
        status = "not_applicable"
        note = None

    await asyncio.to_thread(lambda: executor(FakeAction()))
    assert updates[0][1] == ChecklistStatus.NOT_APPLICABLE


async def test_update_checklist_executor_invalid_status() -> None:
    """Invalid status raises ValueError."""

    async def on_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        pass

    loop = asyncio.get_running_loop()
    executor = UpdateChecklistExecutor(
        on_update, loop, observation_factory=_fake_observation_factory
    )

    class FakeAction:
        req_id = "R1"
        status = "invalid_status"
        note = None

    with pytest.raises(ValueError, match="Invalid checklist status"):
        await asyncio.to_thread(lambda: executor(FakeAction()))


# --- SubmitExecutor ---


async def test_submit_executor_invokes_callback() -> None:
    """SubmitExecutor bridges to async submit callback."""
    submitted = False

    async def on_submit() -> None:
        nonlocal submitted
        submitted = True

    loop = asyncio.get_running_loop()
    executor = SubmitExecutor(on_submit, loop, observation_factory=_fake_observation_factory)

    def run_executor() -> object:
        return executor(action=None)

    result = await asyncio.to_thread(run_executor)

    assert submitted is True
    assert isinstance(result, _FakeObservation)
    assert "submitted" in result.text.lower()
