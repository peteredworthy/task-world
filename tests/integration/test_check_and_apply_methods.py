"""Integration tests for the check_submission / apply_submission /
check_verification / apply_verification service methods.

These methods implement the synchronous-check + async-signal pattern:

  1. HTTP endpoint calls check_submission / check_verification synchronously.
  2. On success the endpoint enqueues an ACTIVITY_COMPLETED / ACTIVITY_VERIFIED
     signal and returns 200.
  3. The signal handler calls apply_submission / apply_verification to apply
     the state transition.

Each method is tested independently so the contract is explicit and regression
is immediately visible.
"""

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config import ChecklistStatus, Priority, RoutineSource, RunStatus, TaskStatus
from orchestrator.db import SqliteEventStore, create_engine, create_session_factory, init_db
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.state.errors import TaskNotFoundError
from orchestrator.workflow import LocalAutoVerifyRunner
from orchestrator.workflow import GateBlockedError, InvalidTransitionError
from orchestrator.workflow.service import WorkflowService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


def _now() -> datetime:
    return datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_run(
    run_id: str = "run-1",
    task_id: str = "task-1",
    worktree_path: str | None = None,
    auto_verify_cmd: str | None = None,
    max_attempts: int = 3,
) -> Run:
    """Create a minimal Run suitable for service-level tests."""
    task_cfg: dict[str, Any] = {
        "id": "T-01",
        "title": "Test task",
        "task_context": "Do the work",
        "requirements": [{"id": "R1", "desc": "It works"}],
    }
    if auto_verify_cmd is not None:
        task_cfg["auto_verify"] = {
            "items": [{"id": "av-1", "cmd": auto_verify_cmd, "must": True}],
            "tail_lines": 10,
        }

    now = _now()
    return Run(
        id=run_id,
        repo_name="test-repo",
        worktree_path=worktree_path,
        status=RunStatus.DRAFT,
        routine_id="test-routine",
        routine_source=RoutineSource.EMBEDDED,
        routine_embedded={
            "id": "test-routine",
            "name": "Test Routine",
            "steps": [{"id": "S-01", "title": "Step 1", "tasks": [task_cfg]}],
        },
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id=task_id,
                        config_id="T-01",
                        status=TaskStatus.PENDING,
                        checklist=[
                            ChecklistItem(
                                req_id="R1",
                                desc="It works",
                                priority=Priority.CRITICAL,
                            )
                        ],
                        max_attempts=max_attempts,
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )


async def _setup_building(
    session: AsyncSession,
    run_id: str = "run-1",
    task_id: str = "task-1",
    worktree_path: str | None = None,
    auto_verify_cmd: str | None = None,
    max_attempts: int = 3,
) -> WorkflowService:
    """Create, start, and begin a task; return the service with task in BUILDING."""
    runner = LocalAutoVerifyRunner()
    service = WorkflowService(session, auto_verify_runner=runner)
    run = _make_run(
        run_id=run_id,
        task_id=task_id,
        worktree_path=worktree_path,
        auto_verify_cmd=auto_verify_cmd,
        max_attempts=max_attempts,
    )
    await service.create_run(run)
    await service.apply_start_run(run_id)
    await service.start_task(run_id, task_id)
    return service


async def _setup_verifying(
    session: AsyncSession,
    run_id: str = "run-1",
    task_id: str = "task-1",
    max_attempts: int = 3,
) -> WorkflowService:
    """Set up a task in VERIFYING state (checklist done, apply_submission called)."""
    service = await _setup_building(
        session, run_id=run_id, task_id=task_id, max_attempts=max_attempts
    )
    await service.update_checklist_item(run_id, task_id, "R1", ChecklistStatus.DONE)
    await service.apply_submission(run_id, task_id)
    return service


# ===========================================================================
# check_submission
# ===========================================================================


class TestCheckSubmission:
    """check_submission validates gate + auto-verify without changing state."""

    @pytest.mark.asyncio
    async def test_gate_blocked_raises_when_checklist_open(self, session: AsyncSession) -> None:
        """OPEN critical item raises GateBlockedError — task stays BUILDING."""
        service = await _setup_building(session)

        with pytest.raises(GateBlockedError):
            await service.check_submission("run-1", "task-1")

        task = await service.get_task("run-1", "task-1")
        assert task.status == TaskStatus.BUILDING

    @pytest.mark.asyncio
    async def test_passes_when_checklist_done(self, session: AsyncSession) -> None:
        """All checklist done → returns success=True, new_status=BUILDING (signal pending)."""
        service = await _setup_building(session)
        await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)

        result = await service.check_submission("run-1", "task-1")

        assert result.success is True
        assert result.new_status == TaskStatus.BUILDING
        # Task is still BUILDING — state transition happens via apply_submission
        task = await service.get_task("run-1", "task-1")
        assert task.status == TaskStatus.BUILDING

    @pytest.mark.asyncio
    async def test_idempotent_when_already_verifying(self, session: AsyncSession) -> None:
        """If task is already VERIFYING, check_submission returns idempotent success."""
        service = await _setup_building(session)
        await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
        await service.apply_submission("run-1", "task-1")  # advance to VERIFYING

        result = await service.check_submission("run-1", "task-1")

        assert result.success is True
        assert result.new_status == TaskStatus.VERIFYING

    @pytest.mark.asyncio
    async def test_raises_invalid_transition_when_run_not_active(
        self, session: AsyncSession
    ) -> None:
        """Run must be ACTIVE or STOPPING; raises InvalidTransitionError otherwise."""
        service = await _setup_building(session)
        await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
        await service.apply_submission("run-1", "task-1")  # → VERIFYING
        # Now pause the run so it is no longer ACTIVE
        await service.apply_pause_run("run-1", reason="test_pause")

        with pytest.raises(InvalidTransitionError):
            await service.check_submission("run-1", "task-1")

    @pytest.mark.asyncio
    async def test_failing_auto_verify_returns_failure(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        """Failing must:true auto-verify returns success=False, task stays BUILDING."""
        service = await _setup_building(
            session,
            worktree_path=str(tmp_path),
            auto_verify_cmd="false",
        )
        await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)

        result = await service.check_submission("run-1", "task-1")

        assert result.success is False
        assert result.new_status == TaskStatus.BUILDING
        task = await service.get_task("run-1", "task-1")
        assert task.status == TaskStatus.BUILDING

    @pytest.mark.asyncio
    async def test_passing_auto_verify_auto_marks_and_passes_gate(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        """Passing auto-verify auto-marks OPEN items and passes the gate."""
        service = await _setup_building(
            session,
            worktree_path=str(tmp_path),
            auto_verify_cmd="echo ok",
        )
        # Checklist is still OPEN — auto-verify should mark it done

        result = await service.check_submission("run-1", "task-1")

        assert result.success is True
        assert result.new_status == TaskStatus.BUILDING
        # Checklist item should have been auto-marked DONE
        task = await service.get_task("run-1", "task-1")
        assert all(item.status == ChecklistStatus.DONE for item in task.checklist)

        events = await SqliteEventStore(session).get_stream("run-1")
        task_status_events = [
            event for event in events if event.event_type == "task_status_changed"
        ]
        assert len(task_status_events) == 1
        auto_verify_event = next(
            event for event in events if event.event_type == "auto_verify_completed"
        )
        payload = json.loads(auto_verify_event.payload)
        assert payload["checklist"][0]["status"] == "done"
        assert payload["latest_attempt_snapshot"]["auto_verify_results"][0]["passed"] is True

    @pytest.mark.asyncio
    async def test_failing_auto_verify_blocks_even_with_done_checklist(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        """Failing auto-verify blocks even if builder pre-marked all items done.

        This is the core timing-fix invariant: auto-verify runs BEFORE the gate,
        so a builder cannot bypass it by self-reporting everything done.
        """
        service = await _setup_building(
            session,
            worktree_path=str(tmp_path),
            auto_verify_cmd="false",
        )
        await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)

        result = await service.check_submission("run-1", "task-1")

        assert result.success is False
        assert result.new_status == TaskStatus.BUILDING


# ===========================================================================
# apply_submission
# ===========================================================================


class TestApplySubmission:
    """apply_submission applies BUILDING → VERIFYING (called by signal handler)."""

    @pytest.mark.asyncio
    async def test_transitions_building_to_verifying(self, session: AsyncSession) -> None:
        """After a passed check_submission, apply_submission advances to VERIFYING."""
        service = await _setup_building(session)
        await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
        await service.check_submission("run-1", "task-1")

        result = await service.apply_submission("run-1", "task-1")

        assert result.success is True
        assert result.new_status == TaskStatus.VERIFYING
        task = await service.get_task("run-1", "task-1")
        assert task.status == TaskStatus.VERIFYING

    @pytest.mark.asyncio
    async def test_idempotent_when_already_verifying(self, session: AsyncSession) -> None:
        """Calling apply_submission on an already-VERIFYING task is idempotent."""
        service = await _setup_building(session)
        await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
        await service.apply_submission("run-1", "task-1")

        result = await service.apply_submission("run-1", "task-1")

        assert result.success is True
        assert result.new_status == TaskStatus.VERIFYING

    @pytest.mark.asyncio
    async def test_raises_when_run_not_active(self, session: AsyncSession) -> None:
        """apply_submission requires an ACTIVE or STOPPING run."""
        service = await _setup_building(session)
        await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
        await service.apply_submission("run-1", "task-1")  # → VERIFYING
        await service.apply_pause_run("run-1", reason="test_pause")

        with pytest.raises(InvalidTransitionError):
            await service.apply_submission("run-1", "task-1")

    @pytest.mark.asyncio
    async def test_gate_still_enforced_if_checklist_reverted(self, session: AsyncSession) -> None:
        """apply_submission re-checks the gate; raises GateBlockedError if not met.

        This tests the edge case where a checklist item is somehow OPEN when the
        signal is processed (e.g. a race or manual revert).  The gate is still
        enforced at apply time.
        """
        service = await _setup_building(session)
        # Do NOT mark checklist done — gate will block at apply time

        with pytest.raises(GateBlockedError):
            await service.apply_submission("run-1", "task-1")

        task = await service.get_task("run-1", "task-1")
        assert task.status == TaskStatus.BUILDING


# ===========================================================================
# check_verification
# ===========================================================================


class TestCheckVerification:
    """check_verification validates that verification can proceed; no state change."""

    @pytest.mark.asyncio
    async def test_returns_success_when_task_verifying(self, session: AsyncSession) -> None:
        """Task in VERIFYING state → returns success=True, new_status=VERIFYING."""
        service = await _setup_verifying(session)

        result = await service.check_verification("run-1", "task-1")

        assert result.success is True
        assert result.new_status == TaskStatus.VERIFYING
        # No state change
        task = await service.get_task("run-1", "task-1")
        assert task.status == TaskStatus.VERIFYING

    @pytest.mark.asyncio
    async def test_raises_when_task_still_building(self, session: AsyncSession) -> None:
        """Task in BUILDING state → raises InvalidTransitionError."""
        service = await _setup_building(session)

        with pytest.raises(InvalidTransitionError):
            await service.check_verification("run-1", "task-1")

    @pytest.mark.asyncio
    async def test_raises_when_task_pending(self, session: AsyncSession) -> None:
        """Task in PENDING state → raises InvalidTransitionError."""
        runner = LocalAutoVerifyRunner()
        service = WorkflowService(session, auto_verify_runner=runner)
        run = _make_run()
        await service.create_run(run)
        await service.apply_start_run("run-1")
        # task is PENDING, not started

        with pytest.raises(InvalidTransitionError):
            await service.check_verification("run-1", "task-1")

    @pytest.mark.asyncio
    async def test_idempotent_when_already_completed(self, session: AsyncSession) -> None:
        """Task already COMPLETED → returns success=True, new_status=COMPLETED."""
        service = await _setup_verifying(session)
        await service.set_grade("run-1", "task-1", "R1", "A", "Looks good")
        await service.apply_verification("run-1", "task-1")

        result = await service.check_verification("run-1", "task-1")

        assert result.success is True
        assert result.new_status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_idempotent_when_already_failed(self, session: AsyncSession) -> None:
        """Task already FAILED → returns success=True, new_status=FAILED.

        Uses max_attempts=1 so a failing grade exhausts retries → FAILED (not BUILDING).
        """
        service = await _setup_verifying(session, max_attempts=1)
        await service.set_grade("run-1", "task-1", "R1", "F", "Did not work")
        await service.apply_verification("run-1", "task-1")

        result = await service.check_verification("run-1", "task-1")

        assert result.success is True
        assert result.new_status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_raises_when_run_cancelled(self, session: AsyncSession) -> None:
        """Run in CANCELLED state → raises InvalidTransitionError."""
        service = await _setup_building(session)
        await service.apply_cancel_run("run-1")

        with pytest.raises(InvalidTransitionError):
            await service.check_verification("run-1", "task-1")

    @pytest.mark.asyncio
    async def test_raises_for_unknown_task(self, session: AsyncSession) -> None:
        """Unknown task_id → raises TaskNotFoundError."""
        service = await _setup_verifying(session)

        with pytest.raises(TaskNotFoundError):
            await service.check_verification("run-1", "no-such-task")


# ===========================================================================
# apply_verification
# ===========================================================================


class TestApplyVerification:
    """apply_verification delegates to complete_verification (signal handler path)."""

    @pytest.mark.asyncio
    async def test_completes_task_with_passing_grade(self, session: AsyncSession) -> None:
        """Passing grade → task moves to COMPLETED."""
        service = await _setup_verifying(session)
        await service.set_grade("run-1", "task-1", "R1", "A", "Perfect")

        result = await service.apply_verification("run-1", "task-1")

        assert result.success is True
        assert result.new_status == TaskStatus.COMPLETED
        task = await service.get_task("run-1", "task-1")
        assert task.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_fails_task_with_failing_grade(self, session: AsyncSession) -> None:
        """Failing grade with max_attempts=1 → task moves to FAILED (no more retries)."""
        service = await _setup_verifying(session, max_attempts=1)
        await service.set_grade("run-1", "task-1", "R1", "F", "Incomplete")

        result = await service.apply_verification("run-1", "task-1")

        assert result.success is True
        assert result.new_status == TaskStatus.FAILED
        task = await service.get_task("run-1", "task-1")
        assert task.status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_produces_same_result_as_complete_verification(
        self, session: AsyncSession
    ) -> None:
        """apply_verification is a thin wrapper; result matches complete_verification contract."""
        service = await _setup_verifying(session)
        await service.set_grade("run-1", "task-1", "R1", "A", "Good")

        result = await service.apply_verification("run-1", "task-1")

        # The task should have moved to a terminal state
        task = await service.get_task("run-1", "task-1")
        assert task.status == result.new_status
        assert task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)


# ===========================================================================
# check → apply round-trip
# ===========================================================================


class TestCheckApplyRoundTrip:
    """End-to-end round-trips validating the two-phase pattern."""

    @pytest.mark.asyncio
    async def test_submission_round_trip(self, session: AsyncSession) -> None:
        """check_submission (pass) → apply_submission → task in VERIFYING."""
        service = await _setup_building(session)
        await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)

        check = await service.check_submission("run-1", "task-1")
        assert check.success is True
        assert check.new_status == TaskStatus.BUILDING  # still BUILDING after check

        apply = await service.apply_submission("run-1", "task-1")
        assert apply.success is True
        assert apply.new_status == TaskStatus.VERIFYING

        task = await service.get_task("run-1", "task-1")
        assert task.status == TaskStatus.VERIFYING

    @pytest.mark.asyncio
    async def test_verification_round_trip(self, session: AsyncSession) -> None:
        """check_verification (pass) → apply_verification → task in terminal state."""
        service = await _setup_verifying(session)
        await service.set_grade("run-1", "task-1", "R1", "A", "Great")

        check = await service.check_verification("run-1", "task-1")
        assert check.success is True
        assert check.new_status == TaskStatus.VERIFYING  # still VERIFYING after check

        apply = await service.apply_verification("run-1", "task-1")
        assert apply.success is True

        task = await service.get_task("run-1", "task-1")
        assert task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)

    @pytest.mark.asyncio
    async def test_gate_failure_never_enqueues_apply(self, session: AsyncSession) -> None:
        """When check_submission raises GateBlockedError, apply is never called.

        This simulates the HTTP endpoint pattern: exception → no signal enqueued
        → apply never runs → task stays BUILDING.
        """
        service = await _setup_building(session)
        # checklist is OPEN — gate will block

        enqueued = False
        try:
            await service.check_submission("run-1", "task-1")
            enqueued = True  # only set if check_submission succeeded
        except GateBlockedError:
            pass

        assert enqueued is False
        task = await service.get_task("run-1", "task-1")
        assert task.status == TaskStatus.BUILDING

    @pytest.mark.asyncio
    async def test_full_task_lifecycle_via_check_and_apply(self, session: AsyncSession) -> None:
        """Complete lifecycle using only the new check/apply methods."""
        service = await _setup_building(session)

        # Builder marks checklist done and submits
        await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
        check_sub = await service.check_submission("run-1", "task-1")
        assert check_sub.success is True

        apply_sub = await service.apply_submission("run-1", "task-1")
        assert apply_sub.new_status == TaskStatus.VERIFYING

        # Verifier grades and completes
        await service.set_grade("run-1", "task-1", "R1", "A", "All good")
        check_ver = await service.check_verification("run-1", "task-1")
        assert check_ver.success is True

        apply_ver = await service.apply_verification("run-1", "task-1")
        assert apply_ver.new_status == TaskStatus.COMPLETED

        task = await service.get_task("run-1", "task-1")
        assert task.status == TaskStatus.COMPLETED
