"""Unit tests for RunLifecycleProjector."""

import pytest

from orchestrator.config.enums import RunStatus
from orchestrator.db import RunLifecycleProjector
from orchestrator.workflow import RunStatusChanged


def _status_event(run_id: str, new_status: RunStatus) -> RunStatusChanged:
    return RunStatusChanged(
        run_id=run_id,
        event_type="run_status_changed",
        old_status=RunStatus.DRAFT,
        new_status=new_status,
    )


# ---------------------------------------------------------------------------
# is_active for each RunStatus value
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_status_is_active() -> None:
    projector = RunLifecycleProjector()
    await projector.handle(_status_event("run-1", RunStatus.ACTIVE), session=None)  # type: ignore[arg-type]
    assert projector.is_active("run-1") is True


@pytest.mark.asyncio
async def test_paused_status_is_active() -> None:
    projector = RunLifecycleProjector()
    await projector.handle(_status_event("run-1", RunStatus.PAUSED), session=None)  # type: ignore[arg-type]
    assert projector.is_active("run-1") is True


@pytest.mark.asyncio
async def test_draft_status_is_inactive() -> None:
    projector = RunLifecycleProjector()
    await projector.handle(_status_event("run-1", RunStatus.DRAFT), session=None)  # type: ignore[arg-type]
    assert projector.is_active("run-1") is False


@pytest.mark.asyncio
async def test_stopping_status_is_inactive() -> None:
    projector = RunLifecycleProjector()
    await projector.handle(_status_event("run-1", RunStatus.STOPPING), session=None)  # type: ignore[arg-type]
    assert projector.is_active("run-1") is False


@pytest.mark.asyncio
async def test_completed_status_is_inactive() -> None:
    projector = RunLifecycleProjector()
    await projector.handle(_status_event("run-1", RunStatus.COMPLETED), session=None)  # type: ignore[arg-type]
    assert projector.is_active("run-1") is False


@pytest.mark.asyncio
async def test_failed_status_is_inactive() -> None:
    projector = RunLifecycleProjector()
    await projector.handle(_status_event("run-1", RunStatus.FAILED), session=None)  # type: ignore[arg-type]
    assert projector.is_active("run-1") is False


# ---------------------------------------------------------------------------
# Transitions between statuses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_then_paused_remains_active() -> None:
    projector = RunLifecycleProjector()
    await projector.handle(_status_event("run-1", RunStatus.ACTIVE), session=None)  # type: ignore[arg-type]
    await projector.handle(_status_event("run-1", RunStatus.PAUSED), session=None)  # type: ignore[arg-type]
    assert projector.is_active("run-1") is True


@pytest.mark.asyncio
async def test_active_then_completed_becomes_inactive() -> None:
    projector = RunLifecycleProjector()
    await projector.handle(_status_event("run-1", RunStatus.ACTIVE), session=None)  # type: ignore[arg-type]
    assert projector.is_active("run-1") is True
    await projector.handle(_status_event("run-1", RunStatus.COMPLETED), session=None)  # type: ignore[arg-type]
    assert projector.is_active("run-1") is False


@pytest.mark.asyncio
async def test_active_then_failed_becomes_inactive() -> None:
    projector = RunLifecycleProjector()
    await projector.handle(_status_event("run-1", RunStatus.ACTIVE), session=None)  # type: ignore[arg-type]
    await projector.handle(_status_event("run-1", RunStatus.FAILED), session=None)  # type: ignore[arg-type]
    assert projector.is_active("run-1") is False


@pytest.mark.asyncio
async def test_paused_then_stopping_becomes_inactive() -> None:
    projector = RunLifecycleProjector()
    await projector.handle(_status_event("run-1", RunStatus.PAUSED), session=None)  # type: ignore[arg-type]
    await projector.handle(_status_event("run-1", RunStatus.STOPPING), session=None)  # type: ignore[arg-type]
    assert projector.is_active("run-1") is False


@pytest.mark.asyncio
async def test_unknown_run_is_inactive() -> None:
    projector = RunLifecycleProjector()
    assert projector.is_active("run-unknown") is False


# ---------------------------------------------------------------------------
# Multiple runs tracked independently
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_runs_tracked_independently() -> None:
    projector = RunLifecycleProjector()
    await projector.handle(_status_event("run-1", RunStatus.ACTIVE), session=None)  # type: ignore[arg-type]
    await projector.handle(_status_event("run-2", RunStatus.COMPLETED), session=None)  # type: ignore[arg-type]
    await projector.handle(_status_event("run-3", RunStatus.PAUSED), session=None)  # type: ignore[arg-type]
    assert projector.is_active("run-1") is True
    assert projector.is_active("run-2") is False
    assert projector.is_active("run-3") is True


# ---------------------------------------------------------------------------
# String status values (deserialized from JSON)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_string_status_active() -> None:
    projector = RunLifecycleProjector()
    event = RunStatusChanged(
        run_id="run-1",
        event_type="run_status_changed",
        old_status="draft",
        new_status="active",
    )
    await projector.handle(event, session=None)  # type: ignore[arg-type]
    assert projector.is_active("run-1") is True


@pytest.mark.asyncio
async def test_string_status_completed_is_inactive() -> None:
    projector = RunLifecycleProjector()
    event = RunStatusChanged(
        run_id="run-1",
        event_type="run_status_changed",
        old_status="active",
        new_status="completed",
    )
    await projector.handle(event, session=None)  # type: ignore[arg-type]
    assert projector.is_active("run-1") is False


# ---------------------------------------------------------------------------
# rebuild restores state from event stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rebuild_restores_active_run() -> None:
    projector = RunLifecycleProjector()
    events = [
        _status_event("run-1", RunStatus.ACTIVE),
        _status_event("run-2", RunStatus.ACTIVE),
        _status_event("run-2", RunStatus.COMPLETED),
    ]
    await projector.rebuild(events, session=None)  # type: ignore[arg-type]
    assert projector.is_active("run-1") is True
    assert projector.is_active("run-2") is False


@pytest.mark.asyncio
async def test_rebuild_clears_previous_state() -> None:
    projector = RunLifecycleProjector()
    await projector.handle(_status_event("run-1", RunStatus.ACTIVE), session=None)  # type: ignore[arg-type]
    assert projector.is_active("run-1") is True

    # Rebuild with empty stream should clear state
    await projector.rebuild([], session=None)  # type: ignore[arg-type]
    assert projector.is_active("run-1") is False


@pytest.mark.asyncio
async def test_rebuild_final_status_wins() -> None:
    projector = RunLifecycleProjector()
    events = [
        _status_event("run-1", RunStatus.ACTIVE),
        _status_event("run-1", RunStatus.PAUSED),
        _status_event("run-1", RunStatus.ACTIVE),
        _status_event("run-1", RunStatus.FAILED),
    ]
    await projector.rebuild(events, session=None)  # type: ignore[arg-type]
    assert projector.is_active("run-1") is False


@pytest.mark.asyncio
async def test_rebuild_ignores_non_run_status_events() -> None:
    from orchestrator.workflow import StepCompleted

    projector = RunLifecycleProjector()
    events = [
        _status_event("run-1", RunStatus.ACTIVE),
        StepCompleted(run_id="run-1", event_type="step_completed", step_index=0, step_id="step-1"),
    ]
    await projector.rebuild(events, session=None)  # type: ignore[arg-type]
    assert projector.is_active("run-1") is True


# ---------------------------------------------------------------------------
# Stale signal scenario: run completed before signal delivery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_signal_rejected_for_completed_run() -> None:
    """A signal for a completed run should be detected as inactive."""
    projector = RunLifecycleProjector()
    await projector.handle(_status_event("run-1", RunStatus.ACTIVE), session=None)  # type: ignore[arg-type]
    await projector.handle(_status_event("run-1", RunStatus.COMPLETED), session=None)  # type: ignore[arg-type]

    # A signal consumer would check is_active before delivering
    assert projector.is_active("run-1") is False


@pytest.mark.asyncio
async def test_stale_signal_rejected_for_failed_run() -> None:
    projector = RunLifecycleProjector()
    await projector.handle(_status_event("run-1", RunStatus.ACTIVE), session=None)  # type: ignore[arg-type]
    await projector.handle(_status_event("run-1", RunStatus.FAILED), session=None)  # type: ignore[arg-type]

    assert projector.is_active("run-1") is False
